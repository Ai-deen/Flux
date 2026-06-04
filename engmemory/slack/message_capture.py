"""
Message Capture - Captures and filters Slack discussions.

Filters out informal/personal messages, captures technical discussions,
detects issues/blockers and decisions, stores in engineering memory.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional

from .client import SlackClient
from ..storage.azure_blob import upload_commit_to_blob
from ..utils.config import config

log = logging.getLogger(__name__)


# Keywords indicating technical/formal discussion
TECHNICAL_KEYWORDS = [
    "bug", "error", "fix", "issue", "broken", "failing", "crash",
    "deploy", "release", "merge", "PR", "pull request", "review",
    "blocked", "blocker", "stuck", "help", "debug", "trace",
    "timeout", "performance", "memory", "leak", "race condition",
    "API", "endpoint", "database", "migration", "config",
    "test", "CI", "pipeline", "build", "branch",
    "decision", "agreed", "approach", "solution", "workaround",
    "root cause", "investigation", "found", "resolved",
]

# Patterns for informal messages to filter out
INFORMAL_PATTERNS = [
    r"^(lol|haha|lmao|rofl)",
    r"^(hey|hi|hello|sup|yo)\s*$",
    r"^(good morning|good night|bye|ttyl|brb)",
    r"^(lunch|coffee|break|meeting room)\??\s*$",
    r"^[\U0001f600-\U0001f64f\U0001f680-\U0001f6ff\u2600-\u26ff\u2700-\u27bf]+\s*$",
    r"^(ok|okay|sure|np|no problem|thanks|ty|thx)\s*$",
    r"^:\w+:\s*$",  # Slack emoji reactions like :thumbsup:
]


@dataclass
class CapturedMessage:
    """A captured message from Slack."""
    message_id: str
    sender_id: str
    sender_name: str
    content: str
    timestamp: str
    channel_id: str
    ticket_key: str
    is_technical: bool = True
    topics: list[str] = field(default_factory=list)


@dataclass
class DiscussionSummary:
    """A summarized discussion thread."""
    ticket_key: str
    channel_name: str
    messages: list[CapturedMessage]
    captured_at: str = ""
    summary: str = ""
    issues_found: list[str] = field(default_factory=list)
    decisions_made: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.captured_at:
            self.captured_at = datetime.now(timezone.utc).isoformat()


class MessageCapture:
    """Captures and processes messages from Slack channels."""

    def __init__(self, slack_client: SlackClient):
        self.client = slack_client
        # Track last captured timestamp per channel
        self._last_captured: dict[str, str] = {}

    def is_technical_message(self, content: str) -> bool:
        """
        Determine if a message is worth capturing.
        Returns True for technical discussions, False for informal chatter.
        """
        if not content or len(content.strip()) < 5:
            return False

        clean = content.strip().lower()

        # Filter out informal
        for pattern in INFORMAL_PATTERNS:
            if re.match(pattern, clean, re.IGNORECASE):
                return False

        # Check for technical keywords
        for keyword in TECHNICAL_KEYWORDS:
            if keyword.lower() in clean:
                return True

        # Longer messages are likely substantive
        if len(clean) > 50:
            return True

        return False

    def extract_topics(self, content: str) -> list[str]:
        """Extract technical topics from a message."""
        topics = []
        clean = content.lower()
        for keyword in TECHNICAL_KEYWORDS:
            if keyword.lower() in clean:
                topics.append(keyword)
        return topics[:5]

    def detect_issues(self, messages: list[CapturedMessage]) -> list[str]:
        """Detect issues/blockers in messages."""
        issue_patterns = [
            r"(not working|broken|failing|crashed|down)",
            r"(blocked|stuck|can't|cannot|unable to)",
            r"(bug|error|exception|timeout|500|404)",
            r"(regression|broke|was working)",
        ]
        issues = []
        for msg in messages:
            for pattern in issue_patterns:
                if re.search(pattern, msg.content, re.IGNORECASE):
                    snippet = msg.content[:150]
                    issues.append(f"[{msg.sender_name}] {snippet}")
                    break
        return issues

    def detect_decisions(self, messages: list[CapturedMessage]) -> list[str]:
        """Detect decisions made in messages."""
        decision_patterns = [
            r"(let's go with|we'll use|decided to|agreed on|going with)",
            r"(the plan is|approach will be|solution is to)",
            r"(confirmed|approved|signed off|LGTM|lgtm)",
        ]
        decisions = []
        for msg in messages:
            for pattern in decision_patterns:
                if re.search(pattern, msg.content, re.IGNORECASE):
                    snippet = msg.content[:150]
                    decisions.append(f"[{msg.sender_name}] {snippet}")
                    break
        return decisions

    async def capture_channel_messages(
        self, channel_id: str, ticket_key: str, channel_name: str
    ) -> DiscussionSummary:
        """
        Capture and filter messages from a Slack channel.

        Args:
            channel_id: Slack channel ID
            ticket_key: Associated Jira ticket (e.g. "AUTH-1234")
            channel_name: Human-readable channel name

        Returns:
            DiscussionSummary with filtered technical messages.
        """
        # Only fetch messages since last capture
        oldest = self._last_captured.get(channel_id)

        raw_messages = await self.client.get_channel_history(
            channel_id, limit=100, oldest=oldest
        )

        captured = []
        for msg in raw_messages:
            # Skip bot messages and system messages
            if msg.get("subtype") in ("bot_message", "channel_join", "channel_leave"):
                continue

            content = msg.get("text", "")
            if not self.is_technical_message(content):
                continue

            captured_msg = CapturedMessage(
                message_id=msg.get("ts", ""),
                sender_id=msg.get("user", ""),
                sender_name=msg.get("user", "unknown"),  # Will be resolved later
                content=content,
                timestamp=msg.get("ts", ""),
                channel_id=channel_id,
                ticket_key=ticket_key,
                is_technical=True,
                topics=self.extract_topics(content),
            )
            captured.append(captured_msg)

        # Update last captured timestamp
        if raw_messages:
            self._last_captured[channel_id] = raw_messages[0].get("ts", "")

        # Build summary
        summary = DiscussionSummary(
            ticket_key=ticket_key,
            channel_name=channel_name,
            messages=captured,
            issues_found=self.detect_issues(captured),
            decisions_made=self.detect_decisions(captured),
        )

        log.info(
            "Captured %d/%d messages from #%s (issues: %d, decisions: %d)",
            len(captured), len(raw_messages), channel_name,
            len(summary.issues_found), len(summary.decisions_made)
        )

        return summary

    async def store_discussion(self, summary: DiscussionSummary) -> Optional[str]:
        """Store captured discussion in Azure Blob Storage."""
        payload = {
            "type": "slack_discussion",
            "ticket_key": summary.ticket_key,
            "channel_name": summary.channel_name,
            "captured_at": summary.captured_at,
            "message_count": len(summary.messages),
            "issues_found": summary.issues_found,
            "decisions_made": summary.decisions_made,
            "messages": [asdict(m) for m in summary.messages],
        }

        commit_data = {
            "timestamp": summary.captured_at,
            "short_sha": f"slack-{summary.ticket_key}",
            "type": "discussion",
            "ticket_key": summary.ticket_key,
        }

        blob_name = upload_commit_to_blob(commit_data, analysis=payload)
        if blob_name:
            log.info("Stored discussion for %s: %s", summary.ticket_key, blob_name)
        return blob_name
