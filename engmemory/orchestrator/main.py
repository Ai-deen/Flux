"""
Main Orchestrator - Ties everything together.

This is the main loop that:
1. Watches for new Jira tickets
2. Auto-creates Slack channels and Git branches
3. Gathers context from all sources
4. Feeds context to the AI agent
5. Continuously monitors for updates
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from .session import DevSession
from .poller import Poller
from .context_builder import ContextBuilder
from .git_automation import GitAutomation
from ..slack.client import SlackClient
from ..slack.channel_manager import ChannelManager, TicketInfo
from ..utils.config import config

log = logging.getLogger(__name__)


class Orchestrator:
    """
    Main orchestrator that manages the full development lifecycle.

    Flow:
    1. Detect new tickets (via polling or webhook)
    2. Create session → branch → Slack channel
    3. Gather initial context
    4. Build prompt for AI agent
    5. Monitor for updates (Jira comments, Slack messages)
    6. Feed updates to AI agent when they arrive
    """

    def __init__(self, repo_path: str, slack_client: Optional[SlackClient] = None):
        self.repo_path = repo_path
        self.slack_client = slack_client or (SlackClient() if config.slack_bot_token else None)
        self.channel_manager = ChannelManager(self.slack_client) if self.slack_client else None
        self.git = GitAutomation(repo_path)
        self.context_builder = ContextBuilder()
        self.poller = Poller(slack_client=self.slack_client, poll_interval=10)

    async def handle_new_ticket(self, ticket_data: dict) -> DevSession:
        """
        Handle a newly detected ticket. Creates everything needed.

        Args:
            ticket_data: Jira issue dict (from API or webhook)

        Returns:
            The created DevSession
        """
        fields = ticket_data.get("fields", {})
        key = ticket_data.get("key", "")

        # Check if session already exists
        existing = DevSession.load(key)
        if existing:
            log.info("Session already exists for %s", key)
            return existing

        # Create session
        assignee = fields.get("assignee", {})
        reporter = fields.get("reporter", {})
        parent = fields.get("parent", {})

        session = DevSession(
            ticket_key=key,
            summary=fields.get("summary", "No summary"),
            assignee_email=assignee.get("emailAddress", "") if assignee else "",
            reporter_email=reporter.get("emailAddress", "") if reporter else "",
            priority=fields.get("priority", {}).get("name", "Medium"),
            issue_type=fields.get("issuetype", {}).get("name", "Task"),
            parent_key=parent.get("key", "") if parent else "",
            has_subtasks=bool(fields.get("subtasks", [])),
            repo_path=self.repo_path,
        )

        # Get Jira description
        desc = fields.get("description", "")
        if isinstance(desc, dict):
            # ADF format - extract text
            session.context.jira_description = self.poller._extract_text_from_adf(desc)
        elif desc:
            session.context.jira_description = str(desc)

        log.info("New session: %s [%s] - %s", key, session.issue_type, session.summary)

        # 1. Create Slack channel (if needed)
        if session.needs_channel and self.channel_manager:
            ticket_info = TicketInfo(
                key=key,
                summary=session.summary,
                assignee_email=session.assignee_email,
                reporter_email=session.reporter_email,
                parent_key=session.parent_key or None,
                issue_type=session.issue_type,
                priority=session.priority,
                url=f"https://{config.jira_domain}/browse/{key}",
            )
            channel_id = await self.channel_manager.handle_ticket_created(ticket_info)
            if channel_id:
                session.slack_channel_id = channel_id
                session.slack_channel_name = ticket_info.channel_name
                log.info("Slack channel created: #%s", ticket_info.channel_name)

        # 2. Create Git branch (if needed)
        if session.needs_branch:
            success = self.git.create_branch(session)
            if success:
                log.info("Git branch created: %s", session.branch_name)

        # 3. Get related commit history for context
        recent_commits = self.git.get_recent_commits(20)
        # Filter commits related to similar work
        session.context.related_commits = [
            c for c in recent_commits
            if any(word in c.lower() for word in session.summary.lower().split()[:3])
        ][:5]

        # Save session
        session.status = "in_progress"
        session.save()

        return session

    async def get_ai_prompt(self, ticket_key: str) -> Optional[str]:
        """
        Get the current prompt for the AI agent.
        Returns initial prompt or update prompt depending on state.
        """
        session = DevSession.load(ticket_key)
        if not session:
            return None

        if session.last_ai_interaction:
            # Not first interaction — check for updates
            prompt = self.context_builder.build_update_prompt(session)
            if prompt:
                session.save()
                return prompt
            return None  # No new updates
        else:
            # First interaction — full context
            prompt = self.context_builder.build_initial_prompt(session)
            session.last_ai_interaction = "initialized"
            session.save()
            return prompt

    async def report_ai_response(self, ticket_key: str, response: str):
        """
        Process AI agent's response — detect questions, update session.
        """
        session = DevSession.load(ticket_key)
        if not session:
            return

        # Detect questions
        questions = self.context_builder.extract_questions_from_response(response)
        if questions:
            session.pending_questions = questions
            session.status = "waiting"
            log.info("AI has %d questions for %s", len(questions), ticket_key)
        else:
            session.status = "in_progress"
            session.pending_questions = []

        session.save()

    async def run(self):
        """
        Main orchestrator loop.
        Polls for new tickets and updates continuously.
        """
        log.info("Orchestrator starting (repo=%s)", self.repo_path)

        # Start background poller for existing sessions
        poller_task = asyncio.create_task(self.poller.start())

        try:
            while True:
                # Check for new tickets
                new_tickets = await self.poller.check_for_new_tickets()
                for ticket in new_tickets:
                    await self.handle_new_ticket(ticket)

                # Check if any waiting sessions now have answers
                for session in DevSession.list_active():
                    if session.status == "waiting" and session.has_new_context:
                        log.info(
                            "New context arrived for %s (was waiting) — ready for AI",
                            session.ticket_key
                        )
                        session.status = "in_progress"
                        session.save()

                await asyncio.sleep(self.poller.poll_interval)

        except asyncio.CancelledError:
            pass
        finally:
            self.poller.stop()
            poller_task.cancel()

    # ─── Status & Query ───────────────────────────────────────────────

    def get_session_status(self, ticket_key: str) -> Optional[dict]:
        """Get human-readable status of a session."""
        session = DevSession.load(ticket_key)
        if not session:
            return None

        return {
            "ticket_key": session.ticket_key,
            "summary": session.summary,
            "status": session.status,
            "branch": session.branch_name,
            "slack_channel": session.slack_channel_name,
            "pending_questions": session.pending_questions,
            "updates_waiting": len(session.updates_since_last_check),
            "context": {
                "jira_comments": len(session.context.jira_comments),
                "slack_messages": len(session.context.slack_messages),
                "related_commits": len(session.context.related_commits),
            },
        }

    def list_sessions(self) -> list[dict]:
        """List all active sessions with their status."""
        sessions = DevSession.list_active()
        return [
            {
                "ticket_key": s.ticket_key,
                "summary": s.summary,
                "status": s.status,
                "branch": s.branch_name,
                "has_updates": s.has_new_context,
            }
            for s in sessions
        ]
