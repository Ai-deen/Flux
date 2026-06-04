"""
Channel Manager - Auto-creates Slack channels from Jira tickets.

When a Jira parent ticket is created, this module:
1. Creates a Slack channel named after the ticket (e.g. #auth-1234-fix-timeout)
2. Invites relevant team members (assignee, reporter, team lead)
3. Posts an initial context message with ticket details
4. Sets channel topic/purpose
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from .client import SlackClient

log = logging.getLogger(__name__)


@dataclass
class TicketInfo:
    """Parsed Jira ticket information."""
    key: str                    # e.g. "AUTH-1234"
    summary: str                # e.g. "Fix auth timeout bug"
    assignee_email: Optional[str] = None
    reporter_email: Optional[str] = None
    parent_key: Optional[str] = None
    issue_type: str = "Task"
    priority: str = "Medium"
    subtask_assignees: list[str] = None
    url: str = ""               # Jira ticket URL

    def __post_init__(self):
        if self.subtask_assignees is None:
            self.subtask_assignees = []

    @property
    def channel_name(self) -> str:
        """Generate a Slack-safe channel name from ticket info."""
        # Slack: lowercase, no spaces, max 80 chars, only letters/numbers/hyphens/underscores
        safe_summary = re.sub(r"[^a-zA-Z0-9\s-]", "", self.summary)
        safe_summary = re.sub(r"\s+", "-", safe_summary.strip())[:40]
        name = f"{self.key}-{safe_summary}".lower()
        return name[:80]

    @property
    def is_parent_ticket(self) -> bool:
        """Check if this is a parent/epic ticket."""
        return self.parent_key is None


class ChannelManager:
    """Manages Slack channels based on Jira ticket lifecycle."""

    def __init__(self, slack_client: SlackClient):
        self.client = slack_client
        # Track created channels: ticket_key -> channel_id
        self._channel_map: dict[str, str] = {}

    async def handle_ticket_created(self, ticket: TicketInfo) -> Optional[str]:
        """
        Handle a new Jira ticket creation.
        Creates a channel if it's a parent ticket, or adds members if subtask.

        Returns:
            Channel ID if created/found, None otherwise.
        """
        if ticket.is_parent_ticket:
            return await self._create_channel_for_ticket(ticket)
        else:
            return await self._add_to_parent_channel(ticket)

    async def _create_channel_for_ticket(self, ticket: TicketInfo) -> str:
        """Create a new Slack channel for a parent ticket."""
        channel_name = ticket.channel_name

        # Create the channel
        channel = await self.client.create_channel(channel_name)
        if not channel or not channel.get("id"):
            log.error("Failed to create channel for ticket %s", ticket.key)
            return None

        channel_id = channel["id"]
        self._channel_map[ticket.key] = channel_id

        # Set topic and purpose
        topic = f"[{ticket.key}] {ticket.summary} | Priority: {ticket.priority}"
        purpose = (
            f"Discussion channel for Jira ticket {ticket.key}. "
            f"All technical discussions here are captured for engineering memory."
        )
        await self.client.set_channel_topic(channel_id, topic[:250])
        await self.client.set_channel_purpose(channel_id, purpose[:250])

        # Invite relevant people
        members_to_add = set()
        if ticket.assignee_email:
            members_to_add.add(ticket.assignee_email)
        if ticket.reporter_email:
            members_to_add.add(ticket.reporter_email)
        for email in ticket.subtask_assignees:
            members_to_add.add(email)

        invited_count = 0
        for email in members_to_add:
            success = await self._invite_by_email(channel_id, email)
            if success:
                invited_count += 1

        # Post initial context message
        await self._post_ticket_context(channel_id, ticket)

        log.info(
            "Created channel #%s with %d/%d members for ticket %s",
            channel_name, invited_count, len(members_to_add), ticket.key
        )
        return channel_id

    async def _add_to_parent_channel(self, ticket: TicketInfo) -> Optional[str]:
        """Add subtask assignee to the parent ticket's channel."""
        parent_channel_id = self._channel_map.get(ticket.parent_key)
        if not parent_channel_id:
            log.warning(
                "No channel found for parent %s (subtask: %s)",
                ticket.parent_key, ticket.key
            )
            return None

        if ticket.assignee_email:
            await self._invite_by_email(parent_channel_id, ticket.assignee_email)

        # Notify channel
        await self.client.send_message(
            parent_channel_id,
            f":new: *Subtask added:* [{ticket.key}] {ticket.summary}\n"
            f"Assigned to: {ticket.assignee_email or 'Unassigned'}"
        )

        return parent_channel_id

    async def _invite_by_email(self, channel_id: str, email: str) -> bool:
        """Find user by email and invite to channel."""
        user = await self.client.find_user_by_email(email)
        if user:
            return await self.client.invite_to_channel(channel_id, user["id"])
        log.warning("Could not find Slack user for: %s", email)
        return False

    async def _post_ticket_context(self, channel_id: str, ticket: TicketInfo):
        """Post initial ticket details as the first message."""
        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"📋 {ticket.key}: {ticket.summary}"}
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Type:*\n{ticket.issue_type}"},
                    {"type": "mrkdwn", "text": f"*Priority:*\n{ticket.priority}"},
                    {"type": "mrkdwn", "text": f"*Assignee:*\n{ticket.assignee_email or 'Unassigned'}"},
                    {"type": "mrkdwn", "text": f"*Reporter:*\n{ticket.reporter_email or 'Unknown'}"},
                ]
            },
            {"type": "divider"},
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": "🤖 This channel was auto-created by EngMemory. "
                                "Technical discussions here are captured for future reference."
                    }
                ]
            },
        ]

        if ticket.url:
            blocks.insert(2, {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"<{ticket.url}|View in Jira>"}
            })

        await self.client.send_message(
            channel_id,
            text=f"[{ticket.key}] {ticket.summary}",
            blocks=blocks,
        )

    def get_channel_for_ticket(self, ticket_key: str) -> Optional[str]:
        """Look up channel ID for a given ticket key."""
        return self._channel_map.get(ticket_key)
