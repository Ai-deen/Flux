"""
Flux Demo Server — Full deployment with static dashboard.

This server:
1. Serves the Flux API with sample data (no credentials needed)
2. Serves the built React dashboard as static files
3. Deploys as a single service to Render/Railway/Azure

Run locally:
  pip install -r requirements.txt
  uvicorn demo_server:app --host 0.0.0.0 --port 5051

Deploy to Render:
  - Build Command: pip install -r requirements.txt && cd dashboard && npm install && npm run build
  - Start Command: uvicorn demo_server:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(
    title="Flux - AI Developer Lifecycle Automation",
    description="From ticket to code, automatically. Demo instance with sample data.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Demo Data ────────────────────────────────────────────────────────────

DEMO_SESSIONS = [
    {
        "ticket_key": "KAN-10",
        "summary": "Implement password reset with email verification",
        "status": "in_progress",
        "branch": "KAN-10",
        "slack_channel": "kan-10-password-reset",
        "priority": "High",
        "issue_type": "Story",
        "assignee": "sreeja@flux-team.dev",
        "has_updates": True,
        "pending_questions": 0,
        "pipeline": {"stage": "developer", "iteration": 2, "reviewer_verdict": "needs_changes", "tester_verdict": "", "pr_url": ""},
    },
    {
        "ticket_key": "KAN-8",
        "summary": "Add OAuth2 social login (Google, GitHub)",
        "status": "in_progress",
        "branch": "KAN-8",
        "slack_channel": "kan-8-oauth-login",
        "priority": "High",
        "issue_type": "Story",
        "assignee": "sahithi@flux-team.dev",
        "has_updates": False,
        "pending_questions": 1,
        "pipeline": {"stage": "review", "iteration": 1, "reviewer_verdict": "approved", "tester_verdict": "", "pr_url": ""},
    },
    {
        "ticket_key": "KAN-7",
        "summary": "Fix JWT token expiry handling in auth middleware",
        "status": "done",
        "branch": "KAN-7",
        "slack_channel": "kan-7-jwt-fix",
        "priority": "Critical",
        "issue_type": "Bug",
        "assignee": "sreeja@flux-team.dev",
        "has_updates": False,
        "pending_questions": 0,
        "pipeline": {"stage": "done", "iteration": 1, "reviewer_verdict": "approved", "tester_verdict": "passed", "pr_url": "https://github.com/Ai-deen/AI-DOCS/pull/3"},
    },
    {
        "ticket_key": "KAN-6",
        "summary": "Create user profile API endpoints",
        "status": "done",
        "branch": "KAN-6",
        "slack_channel": "kan-6-user-profile",
        "priority": "Medium",
        "issue_type": "Task",
        "assignee": "chandramalika@flux-team.dev",
        "has_updates": False,
        "pending_questions": 0,
        "pipeline": {"stage": "done", "iteration": 2, "reviewer_verdict": "approved", "tester_verdict": "passed", "pr_url": "https://github.com/Ai-deen/AI-DOCS/pull/2"},
    },
    {
        "ticket_key": "KAN-5",
        "summary": "Set up CI/CD pipeline with GitHub Actions",
        "status": "waiting",
        "branch": "KAN-5",
        "slack_channel": "kan-5-cicd",
        "priority": "Medium",
        "issue_type": "Task",
        "assignee": "sahithi@flux-team.dev",
        "has_updates": True,
        "pending_questions": 2,
        "pipeline": {"stage": "waiting_for_input", "iteration": 1, "reviewer_verdict": "", "tester_verdict": "", "pr_url": ""},
    },
]

DEMO_TICKETS = [
    {"key": "KAN-10", "summary": "Implement password reset with email verification", "type": "Story", "priority": "High", "status": "In Progress", "assignee": "sreeja@flux-team.dev", "has_session": True, "has_subtasks": False, "parent_key": ""},
    {"key": "KAN-9", "summary": "Design database schema for notifications", "type": "Task", "priority": "Medium", "status": "To Do", "assignee": "", "has_session": False, "has_subtasks": False, "parent_key": ""},
    {"key": "KAN-8", "summary": "Add OAuth2 social login (Google, GitHub)", "type": "Story", "priority": "High", "status": "In Progress", "assignee": "sahithi@flux-team.dev", "has_session": True, "has_subtasks": True, "parent_key": ""},
    {"key": "KAN-7", "summary": "Fix JWT token expiry handling in auth middleware", "type": "Bug", "priority": "Critical", "status": "Done", "assignee": "sreeja@flux-team.dev", "has_session": True, "has_subtasks": False, "parent_key": ""},
    {"key": "KAN-6", "summary": "Create user profile API endpoints", "type": "Task", "priority": "Medium", "status": "Done", "assignee": "chandramalika@flux-team.dev", "has_session": True, "has_subtasks": False, "parent_key": ""},
    {"key": "KAN-5", "summary": "Set up CI/CD pipeline with GitHub Actions", "type": "Task", "priority": "Medium", "status": "In Progress", "assignee": "sahithi@flux-team.dev", "has_session": True, "has_subtasks": False, "parent_key": ""},
    {"key": "KAN-4", "summary": "Implement rate limiting for API endpoints", "type": "Task", "priority": "Low", "status": "To Do", "assignee": "", "has_session": False, "has_subtasks": False, "parent_key": ""},
    {"key": "KAN-3", "summary": "Add unit tests for auth module", "type": "Task", "priority": "Medium", "status": "Done", "assignee": "sreeja@flux-team.dev", "has_session": False, "has_subtasks": False, "parent_key": ""},
]

DEMO_SLACK_CHANNELS = [
    {"id": "C01DEMO10", "name": "kan-10-password-reset", "topic": "KAN-10: Password reset implementation", "purpose": "Discuss password reset flow with email verification", "num_members": 3},
    {"id": "C01DEMO08", "name": "kan-8-oauth-login", "topic": "KAN-8: OAuth2 Social Login", "purpose": "Implementing Google and GitHub OAuth2 login", "num_members": 3},
    {"id": "C01DEMO07", "name": "kan-7-jwt-fix", "topic": "KAN-7: JWT Expiry Bug Fix", "purpose": "Critical bug - tokens expiring mid-session", "num_members": 2},
    {"id": "C01DEMO06", "name": "kan-6-user-profile", "topic": "KAN-6: User Profile APIs", "purpose": "CRUD endpoints for user profiles", "num_members": 2},
    {"id": "C01DEMO05", "name": "kan-5-cicd", "topic": "KAN-5: CI/CD Pipeline", "purpose": "GitHub Actions setup for automated testing and deployment", "num_members": 3},
]

DEMO_COMMITS = [
    {"sha": "a3f7c2d1", "message": "KAN-10: Add password reset endpoint and email service", "author": "Sreeja", "time_ago": "2 hours ago"},
    {"sha": "b8e4f901", "message": "KAN-8: Implement Google OAuth2 callback handler", "author": "Sahithi", "time_ago": "5 hours ago"},
    {"sha": "c5d2a7b3", "message": "KAN-7: Fix JWT refresh token rotation logic", "author": "Sreeja", "time_ago": "1 day ago"},
    {"sha": "d1f9e4c6", "message": "KAN-6: Add profile picture upload with Azure Blob", "author": "Chandramalika", "time_ago": "2 days ago"},
    {"sha": "e7b3c8a2", "message": "KAN-7: Patch session timeout - extend expiry to 24h", "author": "Sreeja", "time_ago": "3 days ago"},
    {"sha": "f2a6d9e5", "message": "KAN-5: Add GitHub Actions workflow for pytest", "author": "Sahithi", "time_ago": "4 days ago"},
    {"sha": "g4c1b7f8", "message": "KAN-6: Create /api/profile CRUD endpoints", "author": "Chandramalika", "time_ago": "5 days ago"},
    {"sha": "h9e5a2d3", "message": "KAN-3: Add auth module unit tests (95% coverage)", "author": "Sreeja", "time_ago": "6 days ago"},
]

DEMO_MESSAGES = {
    "C01DEMO10": [
        {"user": "Sreeja", "text": "Starting on password reset. Using Azure Communication Services for email delivery.", "timestamp": "1717300000"},
        {"user": "Sahithi", "text": "Make sure to add rate limiting on the reset endpoint - we don't want abuse.", "timestamp": "1717300600"},
        {"user": "Sreeja", "text": "Good call. Adding 3 attempts per 15 min limit. Token expiry set to 1 hour.", "timestamp": "1717301200"},
        {"user": "Chandramalika", "text": "Designed the reset email template - clean and mobile-friendly. Pushing HTML now.", "timestamp": "1717302000"},
        {"user": "AI Agent", "text": "💡 Suggestion: Include user's first name in email for trust. Also consider adding a 'Not you?' link.", "timestamp": "1717303000"},
    ],
    "C01DEMO08": [
        {"user": "Sahithi", "text": "OAuth2 flow: redirect → callback → token exchange → create/link account.", "timestamp": "1717200000"},
        {"user": "Sreeja", "text": "Handle case: email signup first, then Google login with same email → link accounts.", "timestamp": "1717200600"},
        {"user": "Sahithi", "text": "Account linking: if email exists → link OAuth to existing, don't create duplicate.", "timestamp": "1717201200"},
        {"user": "AI Agent", "text": "✅ Implementation looks good. Review: all edge cases handled. Approving.", "timestamp": "1717202000"},
    ],
    "C01DEMO07": [
        {"user": "Sreeja", "text": "Found the bug - JWT middleware checking exp but not accounting for clock skew. Adding 30s buffer.", "timestamp": "1717100000"},
        {"user": "Sahithi", "text": "Also noticed refresh token rotation wasn't atomic. Two simultaneous requests would fail.", "timestamp": "1717100600"},
        {"user": "Sreeja", "text": "Fixed with Redis lock on refresh. AI reviewer approved - pushing now.", "timestamp": "1717101200"},
    ],
    "C01DEMO06": [
        {"user": "Chandramalika", "text": "Profile API done. Endpoints: GET/PUT /api/profile, POST /api/profile/avatar", "timestamp": "1717000000"},
        {"user": "AI Agent", "text": "Review complete. Code quality: Good. One suggestion: add input validation for bio field (max 500 chars).", "timestamp": "1717000600"},
    ],
    "C01DEMO05": [
        {"user": "Sahithi", "text": "Setting up GitHub Actions. Workflow: lint → test → build → deploy to staging.", "timestamp": "1716900000"},
        {"user": "AI Agent", "text": "❓ Question: Should we add secrets scanning (gitleaks) to the pipeline? Also, what's the target coverage threshold?", "timestamp": "1716900600"},
    ],
}

DEMO_CONTEXT = {
    "KAN-10": {
        "ticket_key": "KAN-10",
        "prompt": "## Ticket: KAN-10 - Implement password reset with email verification\n\n### Jira Description\nAs a user, I want to reset my password via email so I can regain access.\n\n**Acceptance Criteria:**\n- User enters email on /forgot-password\n- System sends reset link (token expires in 1 hour)\n- New password: min 8 chars, 1 uppercase, 1 number\n- All existing sessions invalidated on reset\n- Rate limit: 3 requests per email per 15 min\n\n### Slack Discussion\n- Using Azure Communication Services for email\n- Rate limiting confirmed at 3/15min\n- Include user's first name in email\n\n### Related Commits\n- KAN-3: Auth module has bcrypt utilities\n- KAN-7: JWT patterns (reuse for reset tokens)",
        "context": {
            "jira_description": "Implement password reset with email verification flow",
            "jira_comments": ["Added acceptance criteria", "Rate limiting confirmed", "Design approved"],
            "slack_messages": ["Use Azure Communication Services", "Rate limit 3/15min", "Include user name in email"],
            "related_commits": ["KAN-3: Auth utilities", "KAN-7: JWT patterns"],
            "files_changed": ["password_reset.py", "routes.py", "email_service.py"],
        },
        "pending_questions": [],
    },
    "KAN-8": {
        "ticket_key": "KAN-8",
        "prompt": "## Ticket: KAN-8 - Add OAuth2 social login\n\n### Context\n- Google and GitHub providers\n- Strategy pattern for extensibility\n- Account linking for existing emails\n- Store OAuth tokens encrypted",
        "context": {
            "jira_description": "Add OAuth2 social login (Google, GitHub)",
            "jira_comments": ["Approved by product owner", "GitHub OAuth app created"],
            "slack_messages": ["Handle email conflict with account linking", "Use strategy pattern"],
            "related_commits": ["KAN-6: User profile setup"],
            "files_changed": ["oauth_handler.py", "google_strategy.py", "github_strategy.py"],
        },
        "pending_questions": ["Should we also support Microsoft OAuth?"],
    },
}


# ─── API Routes ───────────────────────────────────────────────────────────


@app.get("/api/dashboard")
async def dashboard():
    active = [s for s in DEMO_SESSIONS if s["status"] != "done"]
    return {
        "active_sessions": len(active),
        "sessions": DEMO_SESSIONS,
        "system": {"slack_connected": True, "jira_connected": True, "azure_connected": True},
    }


@app.get("/api/sessions")
async def list_sessions():
    return {"sessions": DEMO_SESSIONS}


@app.get("/api/sessions/{ticket_key}")
async def get_session(ticket_key: str):
    for s in DEMO_SESSIONS:
        if s["ticket_key"] == ticket_key:
            return s
    raise HTTPException(404, f"No session for {ticket_key}")


@app.post("/api/sessions/{ticket_key}/create")
async def create_session(ticket_key: str):
    new_session = {
        "ticket_key": ticket_key,
        "summary": f"Demo task for {ticket_key}",
        "status": "in_progress",
        "branch": ticket_key,
        "slack_channel": f"{ticket_key.lower()}-demo",
        "priority": "Medium",
        "issue_type": "Task",
        "assignee": "demo@flux-team.dev",
        "has_updates": False,
        "pending_questions": 0,
        "pipeline": {"stage": "developer", "iteration": 1, "reviewer_verdict": "", "tester_verdict": "", "pr_url": ""},
    }
    DEMO_SESSIONS.append(new_session)
    return {"status": "created", "ticket_key": ticket_key, "branch": ticket_key, "slack_channel": f"{ticket_key.lower()}-demo", "workspace": f"/project/{ticket_key}", "pipeline_stage": "developer"}


@app.delete("/api/sessions/{ticket_key}")
async def close_session(ticket_key: str, delete_channel: bool = False):
    for s in DEMO_SESSIONS:
        if s["ticket_key"] == ticket_key:
            s["status"] = "done"
            return {"status": "closed", "ticket_key": ticket_key, "channel_archived": delete_channel}
    raise HTTPException(404, f"No session for {ticket_key}")


@app.get("/api/sessions/{ticket_key}/context")
async def get_context(ticket_key: str):
    if ticket_key in DEMO_CONTEXT:
        return DEMO_CONTEXT[ticket_key]
    return {"ticket_key": ticket_key, "prompt": f"Gathering context for {ticket_key}...", "context": {"jira_description": "", "jira_comments": [], "slack_messages": [], "related_commits": [], "files_changed": []}, "pending_questions": []}


@app.get("/api/sessions/{ticket_key}/summary")
async def get_summary(ticket_key: str):
    summaries = {
        "KAN-10": {"summary": "Password reset 70% complete. Email service working. Frontend forms in progress. Reviewer requested rate limiting improvement.", "progress_pct": 70, "status_assessment": "on_track", "blockers": [], "next_steps": ["Complete frontend forms", "Add rate limiting tests"]},
        "KAN-8": {"summary": "OAuth2 code-complete. Google flow working. GitHub callback passing review. Account linking approved.", "progress_pct": 90, "status_assessment": "on_track", "blockers": [], "next_steps": ["Integration tests", "Deploy to staging"]},
        "KAN-7": {"summary": "JWT bug fix deployed and verified. Clock skew buffer added. All tests passing.", "progress_pct": 100, "status_assessment": "on_track", "blockers": [], "next_steps": ["Monitor production"]},
        "KAN-5": {"summary": "CI/CD setup blocked on two questions: secrets scanning tool choice and coverage threshold.", "progress_pct": 40, "status_assessment": "blocked", "blockers": ["Waiting for team input on secrets scanning", "Coverage threshold undefined"], "next_steps": ["Answer pending questions", "Configure gitleaks"]},
    }
    if ticket_key in summaries:
        return {"ticket_key": ticket_key, **summaries[ticket_key]}
    return {"ticket_key": ticket_key, "summary": "No summary available", "progress_pct": 0, "status_assessment": "unknown", "blockers": [], "next_steps": []}


@app.get("/api/jira/tickets")
async def list_tickets(status: str = "all"):
    if status == "active":
        return {"tickets": [t for t in DEMO_TICKETS if t["status"] != "Done"]}
    return {"tickets": DEMO_TICKETS}


@app.get("/api/jira/tickets/{ticket_key}")
async def get_ticket(ticket_key: str):
    for t in DEMO_TICKETS:
        if t["key"] == ticket_key:
            return {"key": t["key"], "fields": {"summary": t["summary"], "issuetype": {"name": t["type"]}, "priority": {"name": t["priority"]}, "status": {"name": t["status"]}}}
    raise HTTPException(404, f"Ticket {ticket_key} not found")


@app.get("/api/slack/channels")
async def list_channels():
    return {"channels": DEMO_SLACK_CHANNELS}


@app.get("/api/slack/channels/{channel_id}/messages")
async def get_messages(channel_id: str, limit: int = 50):
    messages = DEMO_MESSAGES.get(channel_id, [])
    return {"channel_id": channel_id, "messages": messages[:limit]}


@app.post("/api/slack/channels/create")
async def create_channel(payload: dict = {}):
    return {"channel_id": "C01NEW", "channel_name": f"{payload.get('ticket_key', 'new').lower()}-channel"}


@app.delete("/api/slack/channels/{channel_id}")
async def archive_channel(channel_id: str):
    return {"archived": True}


@app.get("/api/git/branches")
async def list_branches():
    return {"branches": ["main", "KAN-10", "KAN-8", "KAN-7", "KAN-6", "KAN-5"], "current": "main"}


@app.get("/api/git/commits")
async def list_commits(branch: str = None, limit: int = 20):
    commits = DEMO_COMMITS
    if branch and branch != "main":
        commits = [c for c in DEMO_COMMITS if branch.upper() in c["message"]]
    return {"commits": commits[:limit]}


@app.post("/api/git/branches/create")
async def create_branch(ticket_key: str):
    return {"success": True, "branch": ticket_key}


@app.get("/api/access/roles")
async def list_roles():
    return {"roles": {
        "sreeja@flux-team.dev": {"role": "admin", "team": "all", "allowed_tickets": "*"},
        "sahithi@flux-team.dev": {"role": "developer", "team": "backend", "allowed_tickets": "KAN"},
        "chandramalika@flux-team.dev": {"role": "developer", "team": "frontend", "allowed_tickets": "KAN"},
        "judge@hackathon.dev": {"role": "admin", "team": "all", "allowed_tickets": "*"},
    }}


@app.post("/api/access/roles")
async def set_role(payload: dict = {}):
    return {"status": "ok", "user": payload.get("email", ""), "role": payload.get("role", "developer")}


@app.get("/api/access/check")
async def check_access(email: str, ticket_key: str):
    return {"allowed": True, "reason": "Demo mode - full access"}


@app.get("/api/health")
async def health():
    return {"status": "healthy", "mode": "demo", "services": {"orchestrator": True, "slack": True, "jira": True, "azure": True}}


@app.get("/api/risks")
async def get_risks():
    return {
        "risks": [
            {"ticket_key": "KAN-10", "risk": "Reset token stored in plain text — needs encryption", "severity": "high", "detail": "KAN-10: Password reset token should use AES-256 encryption at rest"},
            {"ticket_key": "KAN-5", "risk": "CI/CD has no secrets scanning", "severity": "medium", "detail": "KAN-5: Add gitleaks or truffleHog to the pipeline"},
        ],
        "total_active": 3,
    }


@app.get("/api/metrics")
async def get_metrics():
    return {
        "active_sessions": 3,
        "total_sessions": 8,
        "commits_tracked": 47,
        "channels_tracked": 5,
        "context_captured": {"jira_comments": 24, "slack_messages": 89, "pending_updates": 3},
        "sessions_by_status": {"in_progress": 2, "waiting": 1, "blocked": 0},
    }


@app.post("/api/demo/run")
async def run_demo(payload: dict = None):
    ticket_key = (payload or {}).get("ticket_key", "DEMO-1")
    summary = (payload or {}).get("summary", "Implement user authentication with OAuth2")
    steps = [
        {"step": "session_created", "time_ms": 120},
        {"step": "slack_channel_created", "channel": f"#{ticket_key.lower()}-auth", "channel_id": "C01DEMO99", "time_ms": 340},
        {"step": "git_branch_created", "branch": ticket_key, "time_ms": 520},
        {"step": "ai_context_ready", "prompt_length": 2847, "time_ms": 1100},
        {"step": "ai_summary_generated", "summary": f"AI agent analyzing '{summary}'. Context synthesized from 3 Jira comments, 5 Slack messages, and 12 related commits. Developer agent ready to generate code.", "time_ms": 1850},
    ]
    return {"status": "demo_complete", "ticket_key": ticket_key, "total_time_ms": 1850, "steps": steps, "session": {"branch": ticket_key, "slack_channel": f"#{ticket_key.lower()}-channel", "status": "in_progress"}}


@app.post("/api/demo/reset")
async def reset_demo():
    global DEMO_SESSIONS
    DEMO_SESSIONS = [s for s in DEMO_SESSIONS if s["ticket_key"].startswith("KAN-")]
    return {"status": "reset", "sessions_cleared": 1}


@app.post("/api/pipeline/{ticket_key}/start")
async def start_pipeline(ticket_key: str, branch_name: str = ""):
    return {"status": "started", "stage": "developer", "ticket_key": ticket_key}


@app.get("/api/pipeline/{ticket_key}/context")
async def get_pipeline_context(ticket_key: str):
    ctx = DEMO_CONTEXT.get(ticket_key, {}).get("prompt", f"Gathering context for {ticket_key}...")
    return {"ticket_key": ticket_key, "context": ctx, "length": len(ctx)}


@app.get("/api/commits/recent")
async def get_recent_commits(limit: int = 20):
    return {"commits": [{"commit": {"sha": c["sha"], "message": c["message"], "author": c["author"], "timestamp": c["time_ago"]}} for c in DEMO_COMMITS[:limit]]}


# ─── Static Files (Dashboard) ────────────────────────────────────────────

# Serve built dashboard from ./dashboard/dist
DASHBOARD_DIR = Path(__file__).parent / "dashboard" / "dist"

if not DASHBOARD_DIR.exists():
    # Try alternate path (in case of different working directory)
    DASHBOARD_DIR = Path(os.getcwd()) / "dashboard" / "dist"

if DASHBOARD_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(DASHBOARD_DIR / "assets")), name="assets")

    @app.get("/")
    async def serve_root():
        """Serve dashboard index at root."""
        return FileResponse(str(DASHBOARD_DIR / "index.html"))

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the React SPA for any non-API route."""
        file_path = DASHBOARD_DIR / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(DASHBOARD_DIR / "index.html"))
else:
    @app.get("/")
    async def no_dashboard():
        return {"error": "Dashboard not found", "dashboard_dir": str(DASHBOARD_DIR), "cwd": os.getcwd(), "files": os.listdir(".")}


# ─── Run ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5051))
    uvicorn.run(app, host="0.0.0.0", port=port)
