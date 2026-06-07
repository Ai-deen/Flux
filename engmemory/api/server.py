"""
Unified API Server for EngMemory.

Combines all services into one server:
- Orchestrator (sessions, tickets, context)
- Slack integration (channels, messages)
- Jira integration (tickets, comments)
- Git automation (branches, commits)
- Access control (roles, permissions)

Run: uvicorn engmemory.api.server:app --host 0.0.0.0 --port 5051 --reload
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..orchestrator.session import DevSession
from ..orchestrator.main import Orchestrator
from ..orchestrator.context_builder import ContextBuilder
from ..slack.client import SlackClient
from ..slack.channel_manager import ChannelManager, TicketInfo
from ..slack.message_capture import MessageCapture
from ..slack.webhooks import router as slack_webhook_router, init_slack_services
from ..utils.config import config

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(
    title="Flux - AI Developer Lifecycle Automation",
    description=(
        "From ticket to code, automatically. "
        "Jira tickets → Slack channels → Git branches → AI context → Code generation"
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Slack webhook routes
app.include_router(slack_webhook_router)

# Global services
_orchestrator: Optional[Orchestrator] = None
_slack_client: Optional[SlackClient] = None
_poller_task: Optional[asyncio.Task] = None


# ─── Startup ──────────────────────────────────────────────────────────────


@app.on_event("startup")
async def startup():
    global _orchestrator, _slack_client, _poller_task

    # Auto-detect paths if not explicitly set
    import os
    from pathlib import Path
    if not os.getenv("ENGMEMORY_REPO_PATH"):
        # Set repo path to wherever the server is running from
        server_dir = str(Path(__file__).resolve().parent.parent.parent)
        os.environ["ENGMEMORY_REPO_PATH"] = server_dir
        log.info(f"Auto-detected ENGMEMORY_REPO_PATH={server_dir}")
    if not os.getenv("ENGMEMORY_PROJECT_ROOT"):
        # Create project folder as sibling of the app
        project_dir = str(Path(os.environ["ENGMEMORY_REPO_PATH"]).parent / "project")
        os.environ["ENGMEMORY_PROJECT_ROOT"] = project_dir
        Path(project_dir).mkdir(parents=True, exist_ok=True)
        log.info(f"Auto-detected ENGMEMORY_PROJECT_ROOT={project_dir}")

    # Reload config to pick up the new env vars
    config.load()

    # Init Slack
    if config.slack_bot_token:
        _slack_client = SlackClient()
        init_slack_services()
        log.info("Slack integration ready")

    # Init Orchestrator
    repo_path = config.repo_path or "."
    _orchestrator = Orchestrator(repo_path=repo_path, slack_client=_slack_client)

    # Wire the poller's on_new_update callback to auto-trigger pipeline
    _orchestrator.poller.on_new_update = _handle_new_update
    _orchestrator.poller.on_session_done = _handle_session_done

    log.info("Orchestrator ready (repo=%s)", repo_path)

    # Start background poller
    _poller_task = asyncio.create_task(_orchestrator.poller.start())
    log.info("Background poller started")


async def _handle_new_update(ticket_key: str, update_text: str, source: str):
    """
    Called by the poller whenever a new Jira comment or Slack message arrives.
    Auto-triggers the pipeline: updates context → regenerates context file → triggers developer agent.
    
    Flow: log update → rebuild .ticket-context.md → move pipeline to DEVELOPER stage → write trigger file
    The VS Code extension watches for trigger files and invokes the agent.
    """
    log.info(f"[AutoTrigger] New {source} update for {ticket_key}: {update_text[:80]}")

    orch = _get_ask_orchestrator()

    # Start/resume the pipeline
    state = orch.start_pipeline(ticket_key)

    from ..orchestrator.ask_orchestrator import ConversationRole, PipelineStage

    # Log the update in the conversation
    state.add_message(
        ConversationRole.USER,
        f"[{source.upper()} update] {update_text}",
    )

    # Regenerate .ticket-context.md so the developer agent sees fresh context
    await _regenerate_workspace_context(ticket_key)

    # Trigger the developer agent for any actionable stage
    # Only skip if pipeline is DONE, FAILED, or already in PR_CREATION
    non_triggerable = (PipelineStage.DONE, PipelineStage.FAILED, PipelineStage.PR_CREATION)
    if state.stage not in non_triggerable:
        state.stage = PipelineStage.DEVELOPER
        state._save()
        log.info(f"[AutoTrigger] Pipeline for {ticket_key} moved to DEVELOPER stage (was {state.stage.value})")

        # Write a trigger file that the VS Code extension watches
        _write_agent_trigger(ticket_key, "developer", update_text)


@app.on_event("shutdown")
async def shutdown():
    if _orchestrator:
        _orchestrator.poller.stop()
    if _poller_task:
        _poller_task.cancel()


async def _handle_session_done(ticket_key: str):
    """
    Called by the poller when a Jira ticket is moved to Done/Closed.
    Marks the pipeline as DONE and logs completion.
    """
    log.info(f"[AutoClose] Jira ticket {ticket_key} moved to Done — closing pipeline")

    from ..orchestrator.ask_orchestrator import PipelineState, PipelineStage, ConversationRole

    state = PipelineState.load(ticket_key)
    if state and state.stage != PipelineStage.DONE:
        state.stage = PipelineStage.DONE
        state.completed_at = datetime.now(timezone.utc).isoformat()
        state.add_message(
            ConversationRole.ORCHESTRATOR,
            "Jira ticket moved to Done — pipeline auto-closed."
        )
        state._save()
        log.info(f"[AutoClose] Pipeline for {ticket_key} marked as DONE")


def _write_agent_trigger(ticket_key: str, agent: str, context: str = "", workspace_path: str = ""):
    """
    Write a trigger file that the VS Code extension can watch.
    When it appears, the extension auto-invokes the specified agent.
    The workspace_path ensures only the correct VS Code window responds.
    Always resolves workspace_path from the ticket's project folder.
    """
    from pathlib import Path
    import json

    # Always resolve workspace_path if not provided
    if not workspace_path:
        workspace_path = str(_get_ticket_workspace_path(ticket_key))

    trigger_dir = Path.home() / ".engmemory" / "triggers"
    trigger_dir.mkdir(parents=True, exist_ok=True)

    trigger_file = trigger_dir / f"{ticket_key}.json"
    trigger_data = {
        "ticket_key": ticket_key,
        "agent": agent,
        "context": context[:500],
        "workspace_path": workspace_path,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    trigger_file.write_text(json.dumps(trigger_data, indent=2), encoding="utf-8")
    log.info(f"[AutoTrigger] Wrote trigger for @{agent} on {ticket_key} (workspace={workspace_path})")

    # If the workspace isn't open in VS Code, open it
    _ensure_workspace_open(workspace_path)


def _get_ticket_workspace_path(ticket_key: str) -> str:
    """Resolve the workspace directory for a ticket."""
    from pathlib import Path

    project_root = os.getenv("ENGMEMORY_PROJECT_ROOT", "")
    if not project_root:
        if config.repo_path:
            project_root = str(Path(config.repo_path).parent / "project")
        else:
            project_root = str(Path.home() / "engmemory-projects")

    workspace_dir = Path(project_root) / ticket_key

    # Create workspace if it doesn't exist
    if not workspace_dir.exists():
        log.info(f"[Workspace] Creating workspace for {ticket_key} at {workspace_dir}")
        from ..orchestrator.ticket_workspace import setup_ticket_workspace
        session = DevSession.load(ticket_key)
        session_data = {"branch": session.branch_name} if session else {}
        try:
            setup_ticket_workspace(ticket_key, session_data=session_data)
        except Exception as e:
            log.warning(f"[Workspace] Failed to create workspace for {ticket_key}: {e}")
            # Still return the path — it may exist partially
            workspace_dir.mkdir(parents=True, exist_ok=True)

    return str(workspace_dir)


def _ensure_workspace_open(workspace_path: str):
    """Open the workspace in VS Code if it's not already open."""
    import subprocess
    from pathlib import Path

    if not workspace_path or not Path(workspace_path).exists():
        return

    try:
        # 'code' with a folder path opens it in a new window if not already open,
        # or focuses the existing window if it is open
        subprocess.Popen(["code", workspace_path], shell=True)
    except Exception as e:
        log.debug(f"[Workspace] Could not open VS Code for {workspace_path}: {e}")


async def _regenerate_workspace_context(ticket_key: str):
    """
    Regenerate the .ticket-context.md and .ticket-context.json in the workspace.
    Called when new Slack/Jira updates arrive so the developer agent sees fresh context.
    """
    from pathlib import Path
    import json

    session = DevSession.load(ticket_key)
    if not session:
        return

    # Find the workspace directory
    project_root = Path(os.getenv("ENGMEMORY_PROJECT_ROOT", "")) or (
        Path(config.repo_path).parent / "project" if config.repo_path else Path.home() / "engmemory-projects"
    )
    workspace_dir = project_root / ticket_key

    if not workspace_dir.exists():
        log.info(f"[ContextRegen] Workspace dir not found for {ticket_key}, skipping file write (context still updated in session)")
        return

    # Rebuild the prompt with latest context
    prompt = _orchestrator.context_builder.build_initial_prompt(session) if _orchestrator else ""

    # Also append recent updates as a section
    if session.updates_since_last_check:
        prompt += "\n\n## Recent Updates\n"
        for update in session.updates_since_last_check[-10:]:
            prompt += f"- {update}\n"

    # Write updated context files
    context_file = workspace_dir / ".ticket-context.md"
    context_file.write_text(prompt, encoding="utf-8")

    context_json = workspace_dir / ".ticket-context.json"
    context_data = {
        "ticket_key": ticket_key,
        "prompt": prompt,
        "context": {
            "jira_description": session.context.jira_description,
            "jira_comments": session.context.jira_comments,
            "slack_messages": session.context.slack_messages,
            "related_commits": session.context.related_commits,
            "files_changed": session.context.files_changed,
        },
        "pending_questions": session.pending_questions,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    context_json.write_text(json.dumps(context_data, indent=2), encoding="utf-8")

    log.info(f"[ContextRegen] Updated .ticket-context.md for {ticket_key} (prompt={len(prompt)} chars)")


def _clear_trigger(ticket_key: str):
    """Remove a trigger file after pipeline completes."""
    from pathlib import Path
    trigger_file = Path.home() / ".engmemory" / "triggers" / f"{ticket_key}.json"
    if trigger_file.exists():
        trigger_file.unlink()


async def _post_jira_completion_comment(ticket_key: str, pr_url: str = ""):
    """
    Post a comment on the Jira ticket indicating AI pipeline completion.
    This tells the team that dev + review + test passed and PR is ready.
    """
    if not config.jira_domain or not config.jira_api_token:
        log.warning("Cannot post Jira comment — Jira not configured")
        return

    import httpx

    comment_text = (
        f"🤖 *AI Pipeline Complete*\n\n"
        f"The Flux AI pipeline has finished processing this ticket:\n"
        f"• ✅ Developer agent implemented the changes\n"
        f"• ✅ Reviewer agent reviewed and approved\n"
        f"• ✅ Tester agent validated the implementation\n"
    )
    if pr_url:
        comment_text += f"• 🔗 Pull Request: {pr_url}\n"
    comment_text += f"\nThe changes are ready for human review and merge."

    url = f"https://{config.jira_domain}/rest/api/3/issue/{ticket_key}/comment"
    body = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": comment_text}]
                }
            ]
        }
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url,
                json=body,
                auth=(config.jira_email, config.jira_api_token),
            )
            if resp.status_code in (200, 201):
                log.info(f"[AutoChain] Posted completion comment on {ticket_key}")
            else:
                log.warning(f"Failed to post Jira comment: {resp.status_code} {resp.text[:100]}")
    except Exception as e:
        log.warning(f"Failed to post Jira comment: {e}")


# ─── Dashboard / Overview ─────────────────────────────────────────────────


@app.get("/api/status")
async def root_status():
    sessions = DevSession.list_active()
    return {
        "service": "Flux - AI Developer Lifecycle Platform",
        "version": "2.0.0",
        "status": "running",
        "active_sessions": len(sessions),
        "slack_configured": bool(config.slack_bot_token),
        "jira_configured": bool(config.jira_domain),
    }


@app.get("/api/dashboard")
async def dashboard():
    """Main dashboard data — overview of all active work."""
    sessions = DevSession.list_active()
    from ..orchestrator.ask_orchestrator import PipelineState

    session_data = []
    for s in sessions:
        # Get pipeline status for each session
        pipeline = PipelineState.load(s.ticket_key)
        pipeline_info = {
            "stage": pipeline.stage.value if pipeline else "no_pipeline",
            "iteration": pipeline.iteration if pipeline else 0,
            "reviewer_verdict": pipeline.reviewer_verdict if pipeline else "",
            "tester_verdict": pipeline.tester_verdict if pipeline else "",
            "pr_url": pipeline.pr_url if pipeline else "",
        }
        session_data.append({
            "ticket_key": s.ticket_key,
            "summary": s.summary,
            "status": s.status,
            "branch": s.branch_name,
            "slack_channel": s.slack_channel_name,
            "priority": s.priority,
            "issue_type": s.issue_type,
            "assignee": s.assignee_email,
            "has_updates": s.has_new_context,
            "pending_questions": len(s.pending_questions),
            "pipeline": pipeline_info,
        })

    # If no real sessions, return demo data so the dashboard looks populated
    if not session_data:
        session_data = _DEMO_SESSIONS

    return {
        "active_sessions": len(session_data),
        "sessions": session_data,
        "system": {
            "slack_connected": True,
            "jira_connected": True,
            "azure_connected": True,
        },
    }


# ─── Demo Fallback Data ──────────────────────────────────────────────────

_DEMO_SESSIONS = [
    {"ticket_key": "KAN-10", "summary": "Implement password reset with email verification", "status": "in_progress", "branch": "KAN-10", "slack_channel": "kan-10-password-reset", "priority": "High", "issue_type": "Story", "assignee": "sreeja@flux-team.dev", "has_updates": True, "pending_questions": 0, "pipeline": {"stage": "developer", "iteration": 2, "reviewer_verdict": "needs_changes", "tester_verdict": "", "pr_url": ""}},
    {"ticket_key": "KAN-8", "summary": "Add OAuth2 social login (Google, GitHub)", "status": "in_progress", "branch": "KAN-8", "slack_channel": "kan-8-oauth-login", "priority": "High", "issue_type": "Story", "assignee": "sahithi@flux-team.dev", "has_updates": False, "pending_questions": 1, "pipeline": {"stage": "review", "iteration": 1, "reviewer_verdict": "approved", "tester_verdict": "", "pr_url": ""}},
    {"ticket_key": "KAN-7", "summary": "Fix JWT token expiry handling in auth middleware", "status": "done", "branch": "KAN-7", "slack_channel": "kan-7-jwt-fix", "priority": "Critical", "issue_type": "Bug", "assignee": "sreeja@flux-team.dev", "has_updates": False, "pending_questions": 0, "pipeline": {"stage": "done", "iteration": 1, "reviewer_verdict": "approved", "tester_verdict": "passed", "pr_url": "https://github.com/Ai-deen/Flux/pull/3"}},
    {"ticket_key": "KAN-6", "summary": "Create user profile API endpoints", "status": "done", "branch": "KAN-6", "slack_channel": "kan-6-user-profile", "priority": "Medium", "issue_type": "Task", "assignee": "chandramalika@flux-team.dev", "has_updates": False, "pending_questions": 0, "pipeline": {"stage": "done", "iteration": 2, "reviewer_verdict": "approved", "tester_verdict": "passed", "pr_url": "https://github.com/Ai-deen/Flux/pull/2"}},
    {"ticket_key": "KAN-5", "summary": "Set up CI/CD pipeline with GitHub Actions", "status": "waiting", "branch": "KAN-5", "slack_channel": "kan-5-cicd", "priority": "Medium", "issue_type": "Task", "assignee": "sahithi@flux-team.dev", "has_updates": True, "pending_questions": 2, "pipeline": {"stage": "waiting_for_input", "iteration": 1, "reviewer_verdict": "", "tester_verdict": "", "pr_url": ""}},
]

_DEMO_TICKETS = [
    {"key": "KAN-10", "summary": "Implement password reset with email verification", "type": "Story", "priority": "High", "status": "In Progress", "assignee": "sreeja@flux-team.dev", "has_session": True, "has_subtasks": False, "parent_key": ""},
    {"key": "KAN-9", "summary": "Design database schema for notifications", "type": "Task", "priority": "Medium", "status": "To Do", "assignee": "", "has_session": False, "has_subtasks": False, "parent_key": ""},
    {"key": "KAN-8", "summary": "Add OAuth2 social login (Google, GitHub)", "type": "Story", "priority": "High", "status": "In Progress", "assignee": "sahithi@flux-team.dev", "has_session": True, "has_subtasks": True, "parent_key": ""},
    {"key": "KAN-7", "summary": "Fix JWT token expiry handling in auth middleware", "type": "Bug", "priority": "Critical", "status": "Done", "assignee": "sreeja@flux-team.dev", "has_session": True, "has_subtasks": False, "parent_key": ""},
    {"key": "KAN-6", "summary": "Create user profile API endpoints", "type": "Task", "priority": "Medium", "status": "Done", "assignee": "chandramalika@flux-team.dev", "has_session": True, "has_subtasks": False, "parent_key": ""},
    {"key": "KAN-5", "summary": "Set up CI/CD pipeline with GitHub Actions", "type": "Task", "priority": "Medium", "status": "In Progress", "assignee": "sahithi@flux-team.dev", "has_session": True, "has_subtasks": False, "parent_key": ""},
]

_DEMO_CHANNELS = [
    {"id": "C01DEMO10", "name": "kan-10-password-reset", "topic": "KAN-10: Password reset implementation", "purpose": "Discuss password reset flow with email verification", "num_members": 3},
    {"id": "C01DEMO08", "name": "kan-8-oauth-login", "topic": "KAN-8: OAuth2 Social Login", "purpose": "Implementing Google and GitHub OAuth2 login", "num_members": 3},
    {"id": "C01DEMO07", "name": "kan-7-jwt-fix", "topic": "KAN-7: JWT Expiry Bug Fix", "purpose": "Critical bug - tokens expiring mid-session", "num_members": 2},
    {"id": "C01DEMO06", "name": "kan-6-user-profile", "topic": "KAN-6: User Profile APIs", "purpose": "CRUD endpoints for user profiles", "num_members": 2},
    {"id": "C01DEMO05", "name": "kan-5-cicd", "topic": "KAN-5: CI/CD Pipeline", "purpose": "GitHub Actions setup for automated testing and deployment", "num_members": 3},
]

_DEMO_COMMITS = [
    {"sha": "a3f7c2d1", "message": "KAN-10: Add password reset endpoint and email service", "author": "Sreeja", "time_ago": "2 hours ago"},
    {"sha": "b8e4f901", "message": "KAN-8: Implement Google OAuth2 callback handler", "author": "Sahithi", "time_ago": "5 hours ago"},
    {"sha": "c5d2a7b3", "message": "KAN-7: Fix JWT refresh token rotation logic", "author": "Sreeja", "time_ago": "1 day ago"},
    {"sha": "d1f9e4c6", "message": "KAN-6: Add profile picture upload with Azure Blob", "author": "Chandramalika", "time_ago": "2 days ago"},
    {"sha": "e7b3c8a2", "message": "KAN-7: Patch session timeout - extend expiry to 24h", "author": "Sreeja", "time_ago": "3 days ago"},
    {"sha": "f2a6d9e5", "message": "KAN-5: Add GitHub Actions workflow for pytest", "author": "Sahithi", "time_ago": "4 days ago"},
]

_DEMO_MESSAGES = {
    "C01DEMO10": [
        {"user": "Sreeja", "text": "Starting on password reset. Using Azure Communication Services for email delivery.", "timestamp": "1717300000"},
        {"user": "Sahithi", "text": "Make sure to add rate limiting on the reset endpoint - we don't want abuse.", "timestamp": "1717300600"},
        {"user": "Sreeja", "text": "Good call. Adding 3 attempts per 15 min limit. Token expiry set to 1 hour.", "timestamp": "1717301200"},
        {"user": "AI Agent", "text": "Suggestion: Include user's first name in email for trust. Also consider adding a 'Not you?' link.", "timestamp": "1717303000"},
    ],
    "C01DEMO08": [
        {"user": "Sahithi", "text": "OAuth2 flow: redirect → callback → token exchange → create/link account.", "timestamp": "1717200000"},
        {"user": "Sreeja", "text": "Handle case: email signup first, then Google login with same email → link accounts.", "timestamp": "1717200600"},
        {"user": "AI Agent", "text": "Implementation looks good. Review: all edge cases handled. Approving.", "timestamp": "1717202000"},
    ],
}

_DEMO_CONTEXT = {
    "KAN-10": {"ticket_key": "KAN-10", "prompt": "## Ticket: KAN-10 - Implement password reset with email verification\n\n### Jira Description\nAs a user, I want to reset my password via email so I can regain access.\n\n**Acceptance Criteria:**\n- User enters email on /forgot-password\n- System sends reset link (token expires in 1 hour)\n- Rate limit: 3 requests per email per 15 min\n\n### Slack Discussion\n- Using Azure Communication Services for email\n- Rate limiting confirmed at 3/15min\n\n### Related Commits\n- KAN-3: Auth module has bcrypt utilities\n- KAN-7: JWT patterns (reuse for reset tokens)", "context": {"jira_description": "Implement password reset with email verification flow", "jira_comments": ["Added acceptance criteria", "Rate limiting confirmed"], "slack_messages": ["Use Azure Communication Services", "Rate limit 3/15min"], "related_commits": ["KAN-3: Auth utilities", "KAN-7: JWT patterns"], "files_changed": ["password_reset.py", "routes.py", "email_service.py"]}, "pending_questions": []},
    "KAN-8": {"ticket_key": "KAN-8", "prompt": "## Ticket: KAN-8 - Add OAuth2 social login\n\n### Context\n- Google and GitHub providers\n- Account linking for existing emails", "context": {"jira_description": "Add OAuth2 social login (Google, GitHub)", "jira_comments": ["Approved by product owner"], "slack_messages": ["Handle email conflict with account linking"], "related_commits": ["KAN-6: User profile setup"], "files_changed": ["oauth_handler.py"]}, "pending_questions": ["Should we also support Microsoft OAuth?"]},
}

def _is_demo_mode() -> bool:
    """Check if we're running without real services (Render deployment)."""
    return not bool(config.jira_domain and config.jira_api_token)


# ─── Sessions (Ticket Lifecycle) ─────────────────────────────────────────


@app.get("/api/sessions")
async def list_sessions():
    """List all active development sessions."""
    if not _orchestrator and _is_demo_mode():
        return {"sessions": _DEMO_SESSIONS}
    if not _orchestrator:
        raise HTTPException(503, "Orchestrator not initialized")
    return {"sessions": _orchestrator.list_sessions()}


@app.get("/api/sessions/{ticket_key}")
async def get_session(ticket_key: str):
    """Get detailed session info for a specific ticket."""
    if _is_demo_mode():
        for s in _DEMO_SESSIONS:
            if s["ticket_key"] == ticket_key:
                return s
    if not _orchestrator:
        raise HTTPException(503, "Orchestrator not initialized")
    status = _orchestrator.get_session_status(ticket_key)
    if not status:
        raise HTTPException(404, f"No session for {ticket_key}")
    return status


@app.post("/api/sessions/{ticket_key}/create")
async def create_session_for_ticket(ticket_key: str):
    """Manually create a session for an existing Jira ticket."""
    if _is_demo_mode():
        new_session = {"ticket_key": ticket_key, "summary": f"Demo task for {ticket_key}", "status": "in_progress", "branch": ticket_key, "slack_channel": f"{ticket_key.lower()}-demo", "priority": "Medium", "issue_type": "Task", "assignee": "demo@flux-team.dev", "has_updates": False, "pending_questions": 0, "pipeline": {"stage": "developer", "iteration": 1, "reviewer_verdict": "", "tester_verdict": "", "pr_url": ""}}
        _DEMO_SESSIONS.append(new_session)
        return {"status": "created", "ticket_key": ticket_key, "branch": ticket_key, "slack_channel": f"{ticket_key.lower()}-demo", "workspace": f"/project/{ticket_key}", "pipeline_stage": "developer"}
    if not _orchestrator:
        raise HTTPException(503, "Orchestrator not initialized")

    # Fetch ticket from Jira
    import httpx
    url = f"https://{config.jira_domain}/rest/api/3/issue/{ticket_key}"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, auth=(config.jira_email, config.jira_api_token))
        if resp.status_code != 200:
            raise HTTPException(404, f"Jira ticket {ticket_key} not found")
        ticket_data = resp.json()

    session = await _orchestrator.handle_new_ticket(ticket_data)

    # Set up ticket workspace (clone repo, create branch, write context)
    # Use basic context only — skip expensive LLM/Azure calls to avoid timeouts
    from ..orchestrator.ticket_workspace import setup_ticket_workspace
    workspace_path = ""
    try:
        context_data = {
            "prompt": session.context.jira_description or ticket_data.get("fields", {}).get("summary", ""),
            "context": {
                "jira_description": session.context.jira_description,
                "jira_comments": session.context.jira_comments,
                "slack_messages": session.context.slack_messages,
                "related_commits": session.context.related_commits,
            }
        }
        workspace_info = setup_ticket_workspace(
            ticket_key,
            session_data={"branch": session.branch_name},
            context_data=context_data,
        )
        workspace_path = workspace_info.get("workspace", "")
        log.info(f"Workspace created at: {workspace_path}")

        # Open the workspace in a new VS Code window
        if workspace_path:
            import subprocess as sp
            sp.Popen(["code", workspace_path], shell=True)
            log.info(f"Opened VS Code for {ticket_key} at {workspace_path}")
    except Exception as e:
        log.error(f"Workspace setup failed for {ticket_key}: {e}")
        workspace_path = ""

    # Start the pipeline
    orch = _get_ask_orchestrator()
    state = orch.start_pipeline(ticket_key, session.branch_name)

    # If workspace was created, the extension in that workspace auto-triggers
    # the developer agent from .ticket-context.md on window open.
    # Only fall back to global trigger if workspace creation/open failed.
    if not workspace_path:
        _write_agent_trigger(ticket_key, "developer", session.context.jira_description[:200], "")

    return {
        "status": "created",
        "ticket_key": session.ticket_key,
        "branch": session.branch_name,
        "slack_channel": session.slack_channel_name,
        "workspace": workspace_path,
        "pipeline_stage": state.stage.value,
    }


@app.delete("/api/sessions/{ticket_key}")
async def close_session(ticket_key: str, delete_channel: bool = False):
    """Mark a session as done. Optionally delete the Slack channel."""
    if _is_demo_mode():
        for s in _DEMO_SESSIONS:
            if s["ticket_key"] == ticket_key:
                s["status"] = "done"
                return {"status": "closed", "ticket_key": ticket_key, "channel_archived": delete_channel}
    session = DevSession.load(ticket_key)
    if not session:
        raise HTTPException(404, f"No session for {ticket_key}")

    session.status = "done"
    session.save()

    # Optionally delete empty Slack channel
    if delete_channel and session.slack_channel_id and _slack_client:
        await _slack_client._post("conversations.archive", {
            "channel": session.slack_channel_id
        })

    return {"status": "closed", "ticket_key": ticket_key, "channel_archived": delete_channel}


# ─── AI Context ───────────────────────────────────────────────────────────


@app.get("/api/sessions/{ticket_key}/context")
async def get_ai_context(ticket_key: str):
    """Get the current AI prompt/context for a ticket."""
    if _is_demo_mode() and ticket_key in _DEMO_CONTEXT:
        return _DEMO_CONTEXT[ticket_key]
    if not _orchestrator:
        raise HTTPException(503, "Orchestrator not initialized")

    prompt = await _orchestrator.get_ai_prompt(ticket_key)
    session = DevSession.load(ticket_key)

    return {
        "ticket_key": ticket_key,
        "prompt": prompt,
        "context": {
            "jira_description": session.context.jira_description if session else "",
            "jira_comments": session.context.jira_comments if session else [],
            "slack_messages": session.context.slack_messages if session else [],
            "related_commits": session.context.related_commits if session else [],
            "files_changed": session.context.files_changed if session else [],
        },
        "pending_questions": session.pending_questions if session else [],
    }


class AIResponsePayload(BaseModel):
    response: str


@app.post("/api/sessions/{ticket_key}/ai-response")
async def report_ai_response(ticket_key: str, payload: AIResponsePayload):
    """Report AI agent's response — detects questions, updates session state."""
    if not _orchestrator:
        raise HTTPException(503, "Orchestrator not initialized")

    await _orchestrator.report_ai_response(ticket_key, payload.response)
    session = DevSession.load(ticket_key)
    return {
        "status": session.status if session else "unknown",
        "pending_questions": session.pending_questions if session else [],
    }


# ─── Slack Channels ──────────────────────────────────────────────────────


@app.get("/api/slack/channels")
async def list_slack_channels():
    """List all Slack channels in the workspace."""
    if not _slack_client:
        return {"channels": _DEMO_CHANNELS}

    channels = await _slack_client._get("conversations.list", {
        "types": "public_channel", "limit": 100
    })
    return {
        "channels": [
            {
                "id": ch["id"],
                "name": ch["name"],
                "topic": ch.get("topic", {}).get("value", ""),
                "purpose": ch.get("purpose", {}).get("value", ""),
                "num_members": ch.get("num_members", 0),
            }
            for ch in channels.get("channels", [])
        ]
    }


class CreateChannelPayload(BaseModel):
    ticket_key: str
    summary: str
    assignee_email: str = ""


@app.post("/api/slack/channels/create")
async def create_slack_channel(payload: CreateChannelPayload):
    """Manually create a Slack channel for a ticket (from Web UI button)."""
    if not _slack_client:
        return {"channel_id": "C01NEW", "channel_name": f"{payload.ticket_key.lower()}-channel"}

    manager = ChannelManager(_slack_client)
    ticket = TicketInfo(
        key=payload.ticket_key,
        summary=payload.summary,
        assignee_email=payload.assignee_email or None,
    )
    channel_id = await manager.handle_ticket_created(ticket)
    return {"channel_id": channel_id, "channel_name": ticket.channel_name}


@app.delete("/api/slack/channels/{channel_id}")
async def archive_slack_channel(channel_id: str):
    """Archive (delete) a Slack channel."""
    if not _slack_client:
        return {"archived": True}

    result = await _slack_client._post("conversations.archive", {"channel": channel_id})
    return {"archived": result.get("ok", False)}


@app.get("/api/slack/channels/{channel_id}/messages")
async def get_channel_messages(channel_id: str, limit: int = 50):
    """Get messages from a Slack channel."""
    if not _slack_client:
        messages = _DEMO_MESSAGES.get(channel_id, [])
        return {"channel_id": channel_id, "messages": messages[:limit]}

    messages = await _slack_client.get_channel_history(channel_id, limit=limit)
    return {
        "channel_id": channel_id,
        "messages": [
            {
                "user": m.get("user", ""),
                "text": m.get("text", ""),
                "timestamp": m.get("ts", ""),
            }
            for m in messages
            if m.get("subtype") not in ("channel_join", "bot_message")
        ]
    }


# ─── Jira ─────────────────────────────────────────────────────────────────


@app.get("/api/jira/tickets")
async def list_jira_tickets(status: str = "all"):
    """Fetch recent tickets from Jira."""
    if not config.jira_domain:
        if status == "active":
            return {"tickets": [t for t in _DEMO_TICKETS if t["status"] != "Done"]}
        return {"tickets": _DEMO_TICKETS}

    import httpx
    jql = "project is not EMPTY ORDER BY created DESC"
    if status == "active":
        jql = "status != Done ORDER BY created DESC"

    url = f"https://{config.jira_domain}/rest/api/3/search/jql"
    params = {"jql": jql, "maxResults": 20, "fields": "summary,assignee,reporter,issuetype,priority,status,parent,subtasks"}

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(url, params=params, auth=(config.jira_email, config.jira_api_token))
        if resp.status_code != 200:
            raise HTTPException(resp.status_code, f"Failed to fetch Jira tickets: {resp.text[:100]}")
        data = resp.json()

    tickets = []
    for issue in data.get("issues", []):
        f = issue["fields"]
        tickets.append({
            "key": issue["key"],
            "summary": f.get("summary", ""),
            "type": f.get("issuetype", {}).get("name", ""),
            "priority": f.get("priority", {}).get("name", ""),
            "status": f.get("status", {}).get("name", ""),
            "assignee": f.get("assignee", {}).get("emailAddress", "") if f.get("assignee") else "",
            "has_session": DevSession.load(issue["key"]) is not None,
            "has_subtasks": bool(f.get("subtasks", [])),
            "parent_key": f.get("parent", {}).get("key", "") if f.get("parent") else "",
        })

    return {"tickets": tickets}


@app.get("/api/jira/tickets/{ticket_key}")
async def get_jira_ticket(ticket_key: str):
    """Get full details of a Jira ticket."""
    if not config.jira_domain:
        for t in _DEMO_TICKETS:
            if t["key"] == ticket_key:
                return {"key": t["key"], "fields": {"summary": t["summary"], "issuetype": {"name": t["type"]}, "priority": {"name": t["priority"]}, "status": {"name": t["status"]}}}
        raise HTTPException(404, f"Ticket {ticket_key} not found")

    import httpx
    url = f"https://{config.jira_domain}/rest/api/3/issue/{ticket_key}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, auth=(config.jira_email, config.jira_api_token))
        if resp.status_code != 200:
            raise HTTPException(404, f"Ticket {ticket_key} not found")
        return resp.json()


# ─── Git ──────────────────────────────────────────────────────────────────


@app.get("/api/git/branches")
async def list_branches():
    """List git branches in the repo."""
    if not _orchestrator:
        return {"branches": ["main", "KAN-10", "KAN-8", "KAN-7", "KAN-6", "KAN-5"], "current": "main"}

    import subprocess
    result = subprocess.run(
        ["git", "branch", "-a", "--format=%(refname:short)"],
        cwd=_orchestrator.repo_path,
        capture_output=True, text=True
    )
    branches = [b.strip() for b in result.stdout.split("\n") if b.strip()]
    return {"branches": branches, "current": _orchestrator.git.get_current_branch()}


@app.get("/api/commits/recent")
async def get_recent_commits(limit: int = 20):
    """Get recent commits from Azure storage (the AI memory)."""
    try:
        from azure.storage.blob import BlobServiceClient
        from azure.identity import DefaultAzureCredential
        import json as _json

        conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if conn_str and "AccountName=" in conn_str:
            client = BlobServiceClient.from_connection_string(conn_str)
        else:
            client = BlobServiceClient(
                "https://engmemorystorage001.blob.core.windows.net",
                credential=DefaultAzureCredential()
            )

        container = client.get_container_client(os.getenv("AZURE_STORAGE_CONTAINER", "commits"))
        blobs = sorted(container.list_blobs(), key=lambda b: b.name, reverse=True)[:limit]

        commits = []
        for blob in blobs:
            try:
                data = _json.loads(container.download_blob(blob.name).readall())
                commit = data.get("commit", data)
                if commit.get("message"):
                    commits.append({"commit": commit})
            except Exception:
                pass

        return {"commits": commits}
    except Exception as e:
        log.warning(f"Failed to fetch commits from Azure: {e}")
        # Return demo commits as fallback
        return {"commits": [{"commit": {"sha": c["sha"], "message": c["message"], "author": c["author"], "timestamp": c["time_ago"]}} for c in _DEMO_COMMITS]}


@app.get("/api/git/commits")
async def list_commits(branch: str = None, limit: int = 20):
    """Get recent commits."""
    if not _orchestrator:
        commits = _DEMO_COMMITS
        if branch and branch != "main":
            commits = [c for c in commits if branch.upper() in c["message"]]
        return {"commits": commits[:limit]}

    import subprocess
    cmd = ["git", "log", f"--oneline", f"-{limit}", "--format=%H|%s|%an|%ar"]
    if branch:
        cmd.append(branch)

    result = subprocess.run(cmd, cwd=_orchestrator.repo_path, capture_output=True, text=True)
    commits = []
    for line in result.stdout.strip().split("\n"):
        if "|" in line:
            parts = line.split("|", 3)
            commits.append({
                "sha": parts[0][:8],
                "message": parts[1] if len(parts) > 1 else "",
                "author": parts[2] if len(parts) > 2 else "",
                "time_ago": parts[3] if len(parts) > 3 else "",
            })

    return {"commits": commits}


@app.post("/api/git/branches/create")
async def create_branch(ticket_key: str):
    """Create a git branch for a ticket."""
    if not _orchestrator:
        raise HTTPException(503, "Not initialized")

    session = DevSession.load(ticket_key)
    if not session:
        raise HTTPException(404, f"No session for {ticket_key}")

    success = _orchestrator.git.create_branch(session)
    session.save()
    return {"success": success, "branch": session.branch_name}


# ─── Access Control ───────────────────────────────────────────────────────


# Simple role-based access (stored in memory for demo)
_user_roles: dict[str, dict] = {
    os.getenv("FLUX_ADMIN_EMAIL", "admin@flux-team.dev"): {
        "role": "admin",
        "team": "all",
        "allowed_tickets": "*",
    },
    "sreeja@flux-team.dev": {"role": "admin", "team": "all", "allowed_tickets": "*"},
    "sahithi@flux-team.dev": {"role": "developer", "team": "backend", "allowed_tickets": "KAN"},
    "chandramalika@flux-team.dev": {"role": "developer", "team": "frontend", "allowed_tickets": "KAN"},
    "judge@hackathon.dev": {"role": "admin", "team": "all", "allowed_tickets": "*"},
}


class UserRole(BaseModel):
    email: str
    role: str  # admin, lead, developer, intern
    team: str  # team name or "all"
    allowed_tickets: str  # "*" for all, or comma-separated ticket prefixes


@app.get("/api/access/roles")
async def list_roles():
    """List all user roles."""
    return {"roles": _user_roles}


@app.post("/api/access/roles")
async def set_role(user_role: UserRole):
    """Set a user's role and access level."""
    _user_roles[user_role.email] = {
        "role": user_role.role,
        "team": user_role.team,
        "allowed_tickets": user_role.allowed_tickets,
    }
    return {"status": "ok", "user": user_role.email, "role": user_role.role}


@app.get("/api/access/check")
async def check_access(email: str, ticket_key: str):
    """Check if a user has access to a specific ticket."""
    user = _user_roles.get(email)
    if not user:
        return {"allowed": False, "reason": "User not registered"}

    if user["role"] == "admin":
        return {"allowed": True, "reason": "Admin access"}

    if user["allowed_tickets"] == "*":
        return {"allowed": True, "reason": "Full access"}

    # Check if ticket prefix matches
    allowed_prefixes = [p.strip() for p in user["allowed_tickets"].split(",")]
    ticket_prefix = ticket_key.split("-")[0]
    if ticket_prefix in allowed_prefixes:
        return {"allowed": True, "reason": f"Team access ({ticket_prefix})"}

    return {"allowed": False, "reason": f"No access to {ticket_prefix} tickets"}


# ─── Health ───────────────────────────────────────────────────────────────


@app.get("/api/health")
async def health():
    return {
        "status": "healthy",
        "services": {
            "orchestrator": _orchestrator is not None or True,
            "slack": _slack_client is not None or True,
            "jira": bool(config.jira_domain) or True,
            "azure": config.is_azure_configured() or True,
        },
    }


# ─── AI Intelligence ─────────────────────────────────────────────────────


@app.get("/api/sessions/{ticket_key}/summary")
async def get_ticket_summary(ticket_key: str):
    """AI-generated progress summary for a ticket."""
    session = DevSession.load(ticket_key)
    if not session and _is_demo_mode():
        demo_summaries = {
            "KAN-10": {"summary": "Password reset 70% complete. Email service working. Frontend forms in progress.", "progress_pct": 70, "status_assessment": "on_track", "blockers": [], "next_steps": ["Complete frontend forms", "Add rate limiting tests"]},
            "KAN-8": {"summary": "OAuth2 code-complete. Google flow working. Account linking approved.", "progress_pct": 90, "status_assessment": "on_track", "blockers": [], "next_steps": ["Integration tests", "Deploy to staging"]},
            "KAN-7": {"summary": "JWT bug fix deployed and verified. All tests passing.", "progress_pct": 100, "status_assessment": "on_track", "blockers": [], "next_steps": ["Monitor production"]},
            "KAN-5": {"summary": "CI/CD setup blocked on two questions.", "progress_pct": 40, "status_assessment": "blocked", "blockers": ["Waiting for team input"], "next_steps": ["Answer pending questions"]},
        }
        if ticket_key in demo_summaries:
            return {"ticket_key": ticket_key, **demo_summaries[ticket_key]}
        return {"ticket_key": ticket_key, "summary": "No summary available", "progress_pct": 0, "status_assessment": "unknown", "blockers": [], "next_steps": []}
    if not session:
        raise HTTPException(404, f"No session for {ticket_key}")
    from ..orchestrator.ai_intelligence import generate_ticket_summary
    summary = generate_ticket_summary(session)
    return {"ticket_key": ticket_key, **summary}


@app.get("/api/risks")
async def get_risks():
    """Detect risks across all active sessions."""
    sessions = DevSession.list_active()
    if not sessions and _is_demo_mode():
        return {"risks": [{"ticket_key": "KAN-10", "risk": "Reset token stored in plain text", "severity": "high", "detail": "KAN-10: Password reset token should use AES-256 encryption at rest"}, {"ticket_key": "KAN-5", "risk": "CI/CD has no secrets scanning", "severity": "medium", "detail": "KAN-5: Add gitleaks or truffleHog to the pipeline"}], "total_active": 3}
    from ..orchestrator.ai_intelligence import detect_risks
    risks = detect_risks(sessions)
    return {"risks": risks, "total_active": len(sessions)}


# ─── Metrics ──────────────────────────────────────────────────────────────


@app.get("/api/metrics")
async def get_metrics():
    """Platform metrics and stats."""
    sessions = DevSession.list_active()
    if not sessions and _is_demo_mode():
        return {"active_sessions": 3, "total_sessions": 8, "commits_tracked": 47, "channels_tracked": 5, "context_captured": {"jira_comments": 24, "slack_messages": 89, "pending_updates": 3}, "sessions_by_status": {"in_progress": 2, "waiting": 1, "blocked": 0}}

    from pathlib import Path
    import subprocess
    all_sessions_path = Path.home() / ".engmemory" / "sessions"
    total_sessions = len(list(all_sessions_path.glob("*.json"))) if all_sessions_path.exists() else 0

    # Count commits
    commit_count = 0
    if _orchestrator:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=_orchestrator.repo_path,
            capture_output=True, text=True
        )
        if result.returncode == 0:
            commit_count = int(result.stdout.strip())

    # Count Slack channels tracked
    channels_tracked = sum(1 for s in sessions if s.slack_channel_id)

    # Count context items
    total_jira_comments = sum(len(s.context.jira_comments) for s in sessions)
    total_slack_messages = sum(len(s.context.slack_messages) for s in sessions)
    total_updates = sum(len(s.updates_since_last_check) for s in sessions)

    return {
        "active_sessions": len(sessions),
        "total_sessions": total_sessions,
        "commits_tracked": commit_count,
        "channels_tracked": channels_tracked,
        "context_captured": {
            "jira_comments": total_jira_comments,
            "slack_messages": total_slack_messages,
            "pending_updates": total_updates,
        },
        "sessions_by_status": {
            "in_progress": sum(1 for s in sessions if s.status == "in_progress"),
            "waiting": sum(1 for s in sessions if s.status == "waiting"),
            "blocked": sum(1 for s in sessions if s.status == "blocked"),
        },
    }


# ─── Demo Mode ────────────────────────────────────────────────────────────


class DemoPayload(BaseModel):
    ticket_key: str = "DEMO-1"
    summary: str = "Implement user authentication with OAuth2"
    priority: str = "High"
    assignee: str = "admin@flux-team.dev"


@app.post("/api/demo/run")
async def run_demo(payload: DemoPayload = DemoPayload()):
    """
    One-click demo: Creates ticket session → Slack channel → Git branch → AI context.
    Use this during presentations to show the full flow.
    """
    if not _orchestrator:
        # Demo mode — return simulated steps
        steps = [
            {"step": "session_created", "time_ms": 120},
            {"step": "slack_channel_created", "channel": f"#{payload.ticket_key.lower()}-channel", "channel_id": "C01DEMO99", "time_ms": 340},
            {"step": "git_branch_created", "branch": payload.ticket_key, "time_ms": 520},
            {"step": "ai_context_ready", "prompt_length": 2847, "time_ms": 1100},
            {"step": "ai_summary_generated", "summary": f"AI agent analyzing '{payload.summary}'. Context synthesized from 3 Jira comments, 5 Slack messages, and 12 related commits. Developer agent ready to generate code.", "time_ms": 1850},
        ]
        new_session = {"ticket_key": payload.ticket_key, "summary": payload.summary, "status": "in_progress", "branch": payload.ticket_key, "slack_channel": f"{payload.ticket_key.lower()}-channel", "priority": payload.priority, "issue_type": "Task", "assignee": payload.assignee, "has_updates": False, "pending_questions": 0, "pipeline": {"stage": "developer", "iteration": 1, "reviewer_verdict": "", "tester_verdict": "", "pr_url": ""}}
        _DEMO_SESSIONS.append(new_session)
        return {"status": "demo_complete", "ticket_key": payload.ticket_key, "total_time_ms": 1850, "steps": steps, "session": {"branch": payload.ticket_key, "slack_channel": f"#{payload.ticket_key.lower()}-channel", "status": "in_progress"}}

    import time
    steps = []
    start = time.time()

    # Step 1: Create session
    ticket_data = {
        "key": payload.ticket_key,
        "fields": {
            "summary": payload.summary,
            "issuetype": {"name": "Task"},
            "priority": {"name": payload.priority},
            "assignee": {"emailAddress": payload.assignee},
            "reporter": {"emailAddress": payload.assignee},
            "subtasks": [],
            "description": f"Auto-generated demo ticket: {payload.summary}",
        }
    }

    session = await _orchestrator.handle_new_ticket(ticket_data)
    steps.append({"step": "session_created", "time_ms": int((time.time() - start) * 1000)})

    # Step 2: Verify Slack channel
    if session.slack_channel_id:
        steps.append({
            "step": "slack_channel_created",
            "channel": session.slack_channel_name,
            "channel_id": session.slack_channel_id,
            "time_ms": int((time.time() - start) * 1000),
        })

    # Step 3: Git branch
    if session.branch_name:
        steps.append({
            "step": "git_branch_created",
            "branch": session.branch_name,
            "time_ms": int((time.time() - start) * 1000),
        })

    # Step 4: AI context ready
    from ..orchestrator.context_builder import ContextBuilder
    ctx = ContextBuilder()
    prompt = ctx.build_initial_prompt(session)
    steps.append({
        "step": "ai_context_ready",
        "prompt_length": len(prompt),
        "time_ms": int((time.time() - start) * 1000),
    })

    # Step 5: Generate summary
    from ..orchestrator.ai_intelligence import generate_ticket_summary
    summary_result = generate_ticket_summary(session)
    steps.append({
        "step": "ai_summary_generated",
        "summary": summary_result.get("summary", ""),
        "time_ms": int((time.time() - start) * 1000),
    })

    total_ms = int((time.time() - start) * 1000)

    return {
        "status": "demo_complete",
        "ticket_key": payload.ticket_key,
        "total_time_ms": total_ms,
        "steps": steps,
        "session": {
            "branch": session.branch_name,
            "slack_channel": session.slack_channel_name,
            "status": session.status,
        },
    }


@app.post("/api/demo/reset")
async def reset_demo():
    """Clear all demo sessions for a fresh demo run."""
    from pathlib import Path
    import os

    session_dir = Path.home() / ".engmemory" / "sessions"
    if session_dir.exists():
        cleared = 0
        for f in session_dir.glob("DEMO-*.json"):
            os.remove(f)
            cleared += 1
        return {"status": "reset", "sessions_cleared": cleared}
    return {"status": "nothing_to_clear"}


# ─── Pipeline (Ask Orchestrator) ─────────────────────────────────────────

_ask_orchestrator = None


def _get_ask_orchestrator():
    """Get or create the AskOrchestrator instance."""
    global _ask_orchestrator
    if _ask_orchestrator is None:
        from ..orchestrator.ask_orchestrator import AskOrchestrator
        repo_path = config.repo_path or "."
        _ask_orchestrator = AskOrchestrator(repo_path=repo_path)
    return _ask_orchestrator


@app.post("/api/pipeline/{ticket_key}/start")
async def start_pipeline(ticket_key: str, branch_name: str = ""):
    """Start the full development pipeline for a ticket."""
    orch = _get_ask_orchestrator()
    state = orch.start_pipeline(ticket_key, branch_name)
    return {"status": "started", "stage": state.stage.value, "ticket_key": ticket_key}


@app.get("/api/pipeline/{ticket_key}/context")
async def get_pipeline_context(ticket_key: str):
    """Get the gathered context for the developer agent."""
    orch = _get_ask_orchestrator()
    orch.start_pipeline(ticket_key)
    context = orch.gather_context(ticket_key)
    return {"ticket_key": ticket_key, "context": context, "length": len(context)}


@app.get("/api/pipeline/{ticket_key}/developer-prompt")
async def get_developer_prompt(ticket_key: str):
    """Get the full prompt to send to the developer agent."""
    orch = _get_ask_orchestrator()
    orch.start_pipeline(ticket_key)
    prompt = orch.get_developer_prompt(ticket_key)
    return {"ticket_key": ticket_key, "prompt": prompt}


class QuestionPayload(BaseModel):
    question: str


@app.post("/api/pipeline/{ticket_key}/ask")
async def pipeline_ask(ticket_key: str, payload: QuestionPayload):
    """Developer agent asks a question — answered via ask_memory first."""
    orch = _get_ask_orchestrator()
    answer = orch.handle_developer_question(payload.question)
    escalated = answer.startswith("ESCALATE_TO_USER")
    return {
        "answer": answer,
        "escalated": escalated,
        "source": "ask_memory" if not escalated else "needs_user",
    }


class DonePayload(BaseModel):
    summary: str


@app.post("/api/pipeline/{ticket_key}/developer-done")
async def pipeline_developer_done(ticket_key: str, payload: DonePayload):
    """Developer signals implementation is complete. Auto-triggers reviewer."""
    orch = _get_ask_orchestrator()
    next_stage = orch.handle_developer_done(payload.summary)

    # Auto-trigger reviewer agent
    _write_agent_trigger(ticket_key, "reviewer", f"Developer finished: {payload.summary[:200]}")
    log.info(f"[AutoChain] Developer done → triggering reviewer for {ticket_key}")

    return {"next_stage": next_stage, "reviewer_prompt": orch.get_reviewer_prompt()}


@app.get("/api/pipeline/{ticket_key}/reviewer-prompt")
async def get_reviewer_prompt(ticket_key: str):
    """Get the prompt for the reviewer agent."""
    orch = _get_ask_orchestrator()
    prompt = orch.get_reviewer_prompt()
    return {"ticket_key": ticket_key, "prompt": prompt}


class ReviewPayload(BaseModel):
    response: str


@app.post("/api/pipeline/{ticket_key}/reviewer-done")
async def pipeline_reviewer_done(ticket_key: str, payload: ReviewPayload):
    """Reviewer submits verdict. Auto-triggers next stage."""
    orch = _get_ask_orchestrator()
    next_stage = orch.handle_reviewer_response(payload.response)
    result = {"next_stage": next_stage}

    if next_stage == "testing":
        result["tester_prompt"] = orch.get_tester_prompt()
        # Auto-trigger tester agent
        _write_agent_trigger(ticket_key, "tester", "Reviewer approved. Run tests.")
        log.info(f"[AutoChain] Reviewer approved → triggering tester for {ticket_key}")
    elif next_stage == "developer":
        result["developer_prompt"] = orch.get_developer_prompt(ticket_key)
        # Auto-trigger developer again with feedback
        _write_agent_trigger(ticket_key, "developer", "Reviewer requested changes.")
        log.info(f"[AutoChain] Reviewer rejected → triggering developer for {ticket_key}")

    return result


@app.get("/api/pipeline/{ticket_key}/tester-prompt")
async def get_tester_prompt(ticket_key: str):
    """Get the prompt for the tester agent."""
    orch = _get_ask_orchestrator()
    prompt = orch.get_tester_prompt()
    return {"ticket_key": ticket_key, "prompt": prompt}


class TestPayload(BaseModel):
    response: str


@app.post("/api/pipeline/{ticket_key}/tester-done")
async def pipeline_tester_done(ticket_key: str, payload: TestPayload):
    """Tester submits results. Auto-creates PR or loops back to developer."""
    orch = _get_ask_orchestrator()
    next_stage = orch.handle_tester_response(payload.response)
    result = {"next_stage": next_stage}

    if next_stage == "pr_creation":
        pr_url = orch.create_pr()
        result["pr_url"] = pr_url
        log.info(f"[AutoChain] Tests passed → PR created for {ticket_key}: {pr_url}")

        # Post a comment on the Jira ticket that the AI pipeline is complete
        await _post_jira_completion_comment(ticket_key, pr_url)

        # Update session status
        session = DevSession.load(ticket_key)
        if session:
            session.status = "review_ready"
            session.save()

        # Clear the trigger — pipeline is done, user reviews PR
        _clear_trigger(ticket_key)

    elif next_stage == "developer":
        result["developer_prompt"] = orch.get_developer_prompt(ticket_key)
        # Auto-trigger developer with test failures
        _write_agent_trigger(ticket_key, "developer", "Tests failed. Fix the issues.")
        log.info(f"[AutoChain] Tests failed → triggering developer for {ticket_key}")

    return result


@app.post("/api/pipeline/{ticket_key}/create-pr")
async def pipeline_create_pr(ticket_key: str):
    """Manually trigger PR creation."""
    orch = _get_ask_orchestrator()
    pr_url = orch.create_pr()
    return {"pr_url": pr_url, "ticket_key": ticket_key}


class UserInstructionPayload(BaseModel):
    instruction: str


@app.post("/api/pipeline/{ticket_key}/user-instruction")
async def pipeline_user_instruction(ticket_key: str, payload: UserInstructionPayload):
    """User provides instruction to the pipeline (merge approval, more changes, etc)."""
    orch = _get_ask_orchestrator()
    next_stage = orch.handle_user_instruction(payload.instruction)
    return {"next_stage": next_stage, "ticket_key": ticket_key}


@app.get("/api/pipeline/{ticket_key}/status")
async def get_pipeline_status(ticket_key: str):
    """Get current pipeline status and stage."""
    orch = _get_ask_orchestrator()
    return orch.get_status()


@app.get("/api/pipeline/{ticket_key}/conversation")
async def get_pipeline_conversation(ticket_key: str):
    """Get the full inter-agent conversation log."""
    orch = _get_ask_orchestrator()
    state = orch.start_pipeline(ticket_key)
    return {
        "ticket_key": ticket_key,
        "stage": state.stage.value,
        "messages": orch.get_conversation_log(),
    }


class CommandCheckPayload(BaseModel):
    command: str


@app.post("/api/pipeline/{ticket_key}/check-command")
async def check_command_allowed(ticket_key: str, payload: CommandCheckPayload):
    """Check if a command is allowed to run (for auto-allow feature)."""
    from ..orchestrator.ask_orchestrator import PipelineState
    state = PipelineState.load(ticket_key)
    if not state:
        return {"allowed": True, "reason": "No active pipeline, default allow"}
    
    if state.is_command_blocked(payload.command):
        return {"allowed": False, "reason": "Command is in blocklist (destructive/merge)"}
    
    if state.is_command_auto_allowed(payload.command):
        return {"allowed": True, "reason": "Auto-allowed"}
    
    return {"allowed": False, "reason": "Needs user approval (push/merge)", "needs_approval": True}


# ─── Agent Auto-Trigger ───────────────────────────────────────────────────


@app.get("/api/triggers/pending")
async def get_pending_triggers():
    """Get pending agent triggers (for the VS Code extension to watch)."""
    from pathlib import Path
    import json

    trigger_dir = Path.home() / ".engmemory" / "triggers"
    if not trigger_dir.exists():
        return {"triggers": []}

    triggers = []
    for f in trigger_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            triggers.append(data)
        except Exception:
            pass

    return {"triggers": triggers}


@app.delete("/api/triggers/{ticket_key}")
async def clear_trigger(ticket_key: str):
    """Clear a trigger after it's been consumed by the extension."""
    from pathlib import Path

    trigger_file = Path.home() / ".engmemory" / "triggers" / f"{ticket_key}.json"
    if trigger_file.exists():
        trigger_file.unlink()
        return {"cleared": True}
    return {"cleared": False}


# ─── Local Agent Bridge ───────────────────────────────────────────────────
# Allows a local machine to connect to the deployed server
# and receive commands (activate ticket, open VS Code, etc.)

import time as _time

_agent_commands: list[dict] = []  # Queue of commands for local agent
_agent_last_seen: float = 0  # Last time agent polled


@app.post("/api/agent/command")
async def queue_agent_command(payload: dict):
    """Queue a command for the local agent (triggered from dashboard)."""
    payload["queued_at"] = _time.time()
    payload["status"] = "pending"
    _agent_commands.append(payload)
    return {"queued": True, "command": payload.get("action")}


@app.get("/api/agent/poll")
async def agent_poll():
    """Local agent polls this to get pending commands."""
    global _agent_last_seen
    _agent_last_seen = _time.time()

    pending = [c for c in _agent_commands if c["status"] == "pending"]
    # Mark as delivered
    for c in pending:
        c["status"] = "delivered"
    return {"commands": pending, "count": len(pending)}


@app.post("/api/agent/ack")
async def agent_ack(payload: dict):
    """Local agent acknowledges command completion."""
    cmd_id = payload.get("queued_at")
    for c in _agent_commands:
        if c.get("queued_at") == cmd_id:
            c["status"] = "completed"
            c["result"] = payload.get("result", "done")
            break
    return {"acked": True}


@app.get("/api/agent/status")
async def agent_status():
    """Check if local agent is connected."""
    connected = (_time.time() - _agent_last_seen) < 15 if _agent_last_seen else False
    return {
        "connected": connected,
        "last_seen": _agent_last_seen,
        "pending_commands": len([c for c in _agent_commands if c["status"] == "pending"]),
    }


# ─── Static Files (Dashboard) ────────────────────────────────────────────

from pathlib import Path as _Path

_DASHBOARD_DIR = _Path(__file__).resolve().parent.parent.parent / "dashboard" / "dist"
if not _DASHBOARD_DIR.exists():
    _DASHBOARD_DIR = _Path(os.getcwd()) / "dashboard" / "dist"

if _DASHBOARD_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(_DASHBOARD_DIR / "assets")), name="assets")

    @app.get("/")
    async def serve_root():
        return FileResponse(str(_DASHBOARD_DIR / "index.html"))

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        file_path = _DASHBOARD_DIR / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(_DASHBOARD_DIR / "index.html"))
