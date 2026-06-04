"""
Context Builder - Assembles all context into a rich prompt for the AI agent.

Combines:
- Jira ticket details (description, comments, subtasks)
- Slack discussions (filtered technical messages)
- Related commit history (similar past work)
- AI session history (what was tried, what questions remain)
- Current file state (what's been changed)
"""

from __future__ import annotations

import logging
from typing import Optional

from .session import DevSession
from ..utils.config import config

log = logging.getLogger(__name__)


class ContextBuilder:
    """Builds rich context prompts from a DevSession."""

    def build_initial_prompt(self, session: DevSession) -> str:
        """
        Build the initial prompt when starting work on a ticket.
        This is the first context the AI agent receives.
        """
        sections = []

        # Header
        sections.append(f"# Task: [{session.ticket_key}] {session.summary}")
        sections.append(f"**Branch:** `{session.branch_name}`")
        sections.append(f"**Priority:** {session.priority} | **Type:** {session.issue_type}")
        sections.append("")

        # Jira description
        if session.context.jira_description:
            sections.append("## Ticket Description")
            sections.append(session.context.jira_description)
            sections.append("")

        # Jira comments (existing context from team)
        if session.context.jira_comments:
            sections.append("## Team Comments (from Jira)")
            for comment in session.context.jira_comments[-5:]:
                sections.append(f"- {comment}")
            sections.append("")

        # Slack discussions
        if session.context.slack_messages:
            sections.append("## Team Discussion (from Slack)")
            for msg in session.context.slack_messages[-10:]:
                sections.append(f"- {msg}")
            sections.append("")

        # Related past work
        if session.context.related_commits:
            sections.append("## Related Past Work")
            for commit in session.context.related_commits[-5:]:
                sections.append(f"- {commit}")
            sections.append("")

        # Instructions
        sections.append("## Instructions")
        sections.append(
            "Work on this ticket. Create the necessary code changes. "
            "If you need clarification, state your question clearly and I will "
            "check Jira/Slack for answers. Commit your changes with a message "
            f"referencing {session.ticket_key}."
        )

        return "\n".join(sections)

    def build_update_prompt(self, session: DevSession) -> Optional[str]:
        """
        Build a follow-up prompt with new context since last interaction.
        Returns None if there are no updates.
        """
        updates = session.consume_updates()
        if not updates:
            return None

        sections = []
        sections.append(f"# Update for [{session.ticket_key}] {session.summary}")
        sections.append("")
        sections.append("New information has arrived since your last interaction:")
        sections.append("")

        for update in updates:
            sections.append(f"- {update}")

        sections.append("")
        sections.append(
            "Please review these updates and continue your work. "
            "If any of these answer a previous question you had, proceed with the implementation. "
            "If you have new questions based on this info, state them clearly."
        )

        return "\n".join(sections)

    def build_summary_prompt(self, session: DevSession) -> str:
        """
        Build a summary of the current session state.
        Useful for the AI agent to understand where things stand.
        """
        sections = []
        sections.append(f"# Session Status: [{session.ticket_key}] {session.summary}")
        sections.append(f"**Status:** {session.status}")
        sections.append(f"**Branch:** `{session.branch_name}`")
        sections.append("")

        if session.pending_questions:
            sections.append("## Pending Questions (waiting for answers)")
            for q in session.pending_questions:
                sections.append(f"- ❓ {q}")
            sections.append("")

        if session.context.files_changed:
            sections.append("## Files Changed So Far")
            for f in session.context.files_changed:
                sections.append(f"- {f}")
            sections.append("")

        if session.updates_since_last_check:
            sections.append(f"## Pending Updates ({len(session.updates_since_last_check)} new)")
            for u in session.updates_since_last_check[:5]:
                sections.append(f"- {u}")
            sections.append("")

        return "\n".join(sections)

    def extract_questions_from_response(self, ai_response: str) -> list[str]:
        """
        Parse AI agent response to detect questions it's asking.
        These get stored in the session so we know what to watch for.
        """
        questions = []
        lines = ai_response.split("\n")
        for line in lines:
            clean = line.strip()
            if clean.endswith("?") and len(clean) > 15:
                questions.append(clean)
            elif clean.lower().startswith(("need", "require", "clarif", "what is", "how do", "where")):
                if "?" in clean or len(clean) > 30:
                    questions.append(clean)
        return questions[:5]  # Max 5 questions
