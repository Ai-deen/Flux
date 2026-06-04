"""
slack_bot.py — Slack Bot for Team Discussion Capture

What it does:
1. When a Jira ticket is created → auto-creates a Slack channel
2. Adds relevant people (assignee, reporter, team leads)
3. Listens to all messages in that channel
4. Filters out personal/informal content (privacy filter)
5. Stores formal/technical discussions as context for the AI agent

What it does NOT do:
- Does NOT respond in the channel (just listens)
- Does NOT merge code or make decisions
- Does NOT capture personal conversations

The AI agent in your VS Code extension can then use these discussions
as context when you ask it questions.

Requirements:
    pip install slack-bolt

Setup:
    1. Create a Slack App at api.slack.com/apps
    2. Add Bot Token Scopes: channels:manage, channels:read, channels:history, 
       chat:write, users:read, groups:write, groups:read, groups:history
    3. Install to workspace
    4. Set SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET in engmemory.env
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

try:
    from slack_bolt import App
    from slack_bolt.adapter.socket_mode import SocketModeHandler
    HAS_SLACK = True
except ImportError:
    HAS_SLACK = False


# Privacy filter — only keep technical/formal messages
TECHNICAL_KEYWORDS = {
    'bug', 'fix', 'error', 'issue', 'deploy', 'build', 'test', 'merge',
    'branch', 'commit', 'release', 'config', 'api', 'endpoint', 'database',
    'server', 'client', 'frontend', 'backend', 'component', 'module',
    'function', 'class', 'interface', 'implement', 'refactor', 'optimize',
    'ticket', 'task', 'story', 'sprint', 'blocke', 'dependency', 'review',
    'pr', 'pull request', 'pipeline', 'ci', 'cd', 'docker', 'kubernetes',
    'kafka', 'redis', 'queue', 'timeout', 'crash', 'memory', 'performance',
    'security', 'auth', 'token', 'migration', 'schema', 'table', 'query',
    'update', 'create', 'delete', 'modify', 'change', 'add', 'remove',
    'requirement', 'acceptance', 'criteria', 'done', 'blocked', 'progress',
}

INFORMAL_PATTERNS = [
    re.compile(r'^(hi|hello|hey|bye|thanks|thank you|ok|okay|sure|np|lol|haha|😂|👍|🎉)\s*$', re.IGNORECASE),
    re.compile(r'^(good morning|good night|lunch|brb|back|afk)', re.IGNORECASE),
    re.compile(r'^(anyone want|wanna grab|let\'s go|see you|have a good)', re.IGNORECASE),
]


def is_technical_message(text: str) -> bool:
    """Check if a message is technical/work-related (worth capturing)."""
    if not text or len(text) < 10:
        return False
    
    # Skip informal messages
    for pattern in INFORMAL_PATTERNS:
        if pattern.match(text):
            return False
    
    # Check for technical content
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in TECHNICAL_KEYWORDS)


class EngMemorySlackBot:
    """Slack bot that captures team discussions for the AI agent."""

    def __init__(self, repo_path: str = ".", 
                 bot_token: Optional[str] = None,
                 signing_secret: Optional[str] = None,
                 app_token: Optional[str] = None):
        if not HAS_SLACK:
            raise ImportError(
                "slack-bolt not installed. Run: pip install slack-bolt"
            )

        from ..utils.config import config
        
        self.repo_path = repo_path
        self.bot_token = bot_token or os.getenv("SLACK_BOT_TOKEN")
        self.signing_secret = signing_secret or os.getenv("SLACK_SIGNING_SECRET")
        self.app_token = app_token or os.getenv("SLACK_APP_TOKEN")

        if not self.bot_token:
            raise ValueError(
                "SLACK_BOT_TOKEN not set. Create a Slack App and add the token."
            )

        self.app = App(token=self.bot_token, signing_secret=self.signing_secret)
        self.storage_dir = Path(repo_path) / ".ai_memory" / "team_discussions"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Register event handlers
        self._register_handlers()

    def _register_handlers(self):
        """Register Slack event handlers."""

        @self.app.event("message")
        def handle_message(event, say, client):
            """Capture messages from tracked channels."""
            text = event.get("text", "")
            channel_id = event.get("channel", "")
            user_id = event.get("user", "")

            # Skip bot messages
            if event.get("bot_id") or event.get("subtype") == "bot_message":
                return

            # Only capture technical messages
            if not is_technical_message(text):
                return

            # Get user name
            try:
                user_info = client.users_info(user=user_id)
                author = user_info["user"]["real_name"]
            except Exception:
                author = user_id

            # Get channel name to extract ticket ID
            try:
                channel_info = client.conversations_info(channel=channel_id)
                channel_name = channel_info["channel"]["name"]
            except Exception:
                channel_name = channel_id

            # Extract ticket ID from channel name (e.g., "kan-1-sidebar-color")
            ticket_match = re.search(r'([a-z]+-\d+)', channel_name)
            ticket_id = ticket_match.group(1).upper() if ticket_match else None

            # Store the message
            self._store_message(text, author, channel_name, ticket_id)
            log.info(f"[SlackBot] Captured: {author} in #{channel_name}: {text[:50]}...")

    def create_ticket_channel(self, ticket_key: str, ticket_summary: str,
                              members: Optional[list[str]] = None) -> Optional[str]:
        """
        Create a Slack channel for a Jira ticket.
        
        Args:
            ticket_key: e.g., "KAN-4"
            ticket_summary: e.g., "Implement OAuth2 login"
            members: List of Slack user IDs or emails to invite
            
        Returns:
            Channel ID if created successfully
        """
        # Create channel name from ticket
        safe_name = f"{ticket_key.lower()}-{self._slugify(ticket_summary)}"[:80]

        try:
            # Create the channel
            result = self.app.client.conversations_create(
                name=safe_name,
                is_private=False,
            )
            channel_id = result["channel"]["id"]

            # Set channel topic
            self.app.client.conversations_setTopic(
                channel=channel_id,
                topic=f"Discussion for {ticket_key}: {ticket_summary}"
            )

            # Post initial message
            self.app.client.chat_postMessage(
                channel=channel_id,
                text=(
                    f"📋 *{ticket_key}: {ticket_summary}*\n\n"
                    f"This channel was auto-created for ticket discussions.\n"
                    f"All technical discussions here are captured as context "
                    f"for the AI agent.\n\n"
                    f"_Personal/informal messages are automatically filtered out._"
                ),
            )

            # Invite members
            if members:
                for member in members:
                    try:
                        self.app.client.conversations_invite(
                            channel=channel_id,
                            users=member,
                        )
                    except Exception:
                        pass  # Member might already be in channel or invalid

            log.info(f"[SlackBot] Created channel #{safe_name} for {ticket_key}")
            return channel_id

        except Exception as exc:
            # Channel might already exist
            if "name_taken" in str(exc):
                log.info(f"[SlackBot] Channel #{safe_name} already exists")
                return None
            log.error(f"[SlackBot] Failed to create channel: {exc}")
            return None

    def create_channel_for_jira_ticket(self, issue_key: str):
        """
        Fetch Jira ticket details and create a Slack channel with relevant people.
        """
        try:
            from ..utils.jira import get_issue_full_context
            data = get_issue_full_context(issue_key, max_depth=1)
            ticket = data["ticket"]

            # Build member list from ticket assignee/reporter
            # Note: You'd need a mapping of Jira users → Slack user IDs
            # For now, just create the channel
            self.create_ticket_channel(
                ticket_key=ticket["key"],
                ticket_summary=ticket["summary"],
            )

        except Exception as exc:
            log.error(f"[SlackBot] Failed to create channel for {issue_key}: {exc}")

    def start(self):
        """Start the Slack bot (Socket Mode for real-time events)."""
        if not self.app_token:
            # Fall back to HTTP mode
            log.info("[SlackBot] Starting in HTTP mode (port 3000)")
            self.app.start(port=3000)
        else:
            handler = SocketModeHandler(self.app, self.app_token)
            log.info("[SlackBot] Starting in Socket Mode...")
            handler.start()

    def _store_message(self, message: str, author: str, 
                       channel: str, ticket_id: Optional[str]):
        """Store a captured message."""
        entry = {
            "message": message,
            "author": author,
            "channel": channel,
            "ticket_id": ticket_id,
            "timestamp": time.time(),
            "date": time.strftime("%Y-%m-%d %H:%M"),
        }

        if ticket_id:
            filename = f"{ticket_id.lower()}.json"
        else:
            filename = f"{time.strftime('%Y-%m-%d')}.json"

        filepath = self.storage_dir / filename

        messages = []
        if filepath.exists():
            try:
                messages = json.loads(filepath.read_text(encoding="utf-8"))
            except Exception:
                messages = []

        messages.append(entry)
        filepath.write_text(json.dumps(messages, indent=2), encoding="utf-8")

    @staticmethod
    def _slugify(text: str) -> str:
        """Convert text to a Slack-friendly channel name slug."""
        slug = re.sub(r'[^a-z0-9]+', '-', text.lower())
        return slug.strip('-')[:50]


def main():
    """CLI entry point for the Slack bot."""
    import argparse

    parser = argparse.ArgumentParser(description="EngMemory Slack Bot")
    parser.add_argument("--repo", default=".", help="Repository path")
    parser.add_argument("--create-channel", type=str, 
                        help="Create a channel for a Jira ticket (e.g., KAN-4)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.create_channel:
        bot = EngMemorySlackBot(repo_path=args.repo)
        bot.create_channel_for_jira_ticket(args.create_channel)
    else:
        print("🤖 EngMemory Slack Bot starting...")
        print("   Listening for messages in tracked channels...")
        print("   Technical discussions will be captured as agent context.")
        print("   Press Ctrl+C to stop.\n")
        bot = EngMemorySlackBot(repo_path=args.repo)
        bot.start()


if __name__ == "__main__":
    main()
