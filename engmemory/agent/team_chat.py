"""
team_chat.py — Team Discussion Integration

Captures team discussions from Slack/Teams channels and makes them
available as context for the agent.

Integration methods:
1. Webhook receiver — Slack/Teams sends messages to our endpoint
2. Manual capture — Developer pastes discussion context
3. Channel auto-creation — When a ticket is created, suggest creating a channel

The key insight: Not everything is discussed in Jira comments.
Developers chat in Slack/Teams about implementation details, blockers,
and decisions. This captures that context.

Storage: .ai_memory/team_discussions/<ticket_id>.json
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class TeamChatIntegration:
    """Manages team discussion context."""

    def __init__(self, repo_path: str = "."):
        self.repo_path = repo_path
        self.storage_dir = Path(repo_path) / ".ai_memory" / "team_discussions"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def add_message(self, message: str, author: str, 
                    channel: Optional[str] = None,
                    ticket_id: Optional[str] = None):
        """Add a team discussion message."""
        entry = {
            "message": message,
            "author": author,
            "channel": channel or "general",
            "ticket_id": ticket_id,
            "timestamp": time.time(),
            "date": time.strftime("%Y-%m-%d %H:%M"),
        }

        # Store by ticket if provided, else by date
        if ticket_id:
            filename = f"{ticket_id.lower()}.json"
        else:
            filename = f"{time.strftime('%Y-%m-%d')}.json"

        filepath = self.storage_dir / filename
        
        # Append to existing file
        messages = []
        if filepath.exists():
            try:
                messages = json.loads(filepath.read_text(encoding="utf-8"))
            except Exception:
                messages = []

        messages.append(entry)
        filepath.write_text(json.dumps(messages, indent=2), encoding="utf-8")
        return entry

    def get_discussion(self, ticket_id: str) -> list[dict]:
        """Get all discussion messages for a ticket."""
        filepath = self.storage_dir / f"{ticket_id.lower()}.json"
        if filepath.exists():
            try:
                return json.loads(filepath.read_text(encoding="utf-8"))
            except Exception:
                pass
        return []

    def get_discussion_context(self, ticket_id: str) -> Optional[str]:
        """Get discussion as formatted context string for the agent."""
        messages = self.get_discussion(ticket_id)
        if not messages:
            return None

        parts = [f"## Team Discussion (Channel: {messages[0].get('channel', 'unknown')})"]
        for msg in messages:
            parts.append(f"  **{msg['author']}** ({msg.get('date', '?')}): {msg['message']}")

        return "\n".join(parts)

    def get_all_recent(self, limit: int = 20) -> list[dict]:
        """Get all recent discussion messages across all channels."""
        all_messages = []
        for f in self.storage_dir.glob("*.json"):
            try:
                messages = json.loads(f.read_text(encoding="utf-8"))
                all_messages.extend(messages)
            except Exception:
                pass

        # Sort by timestamp, most recent first
        all_messages.sort(key=lambda m: m.get("timestamp", 0), reverse=True)
        return all_messages[:limit]

    def search_discussions(self, query: str) -> list[dict]:
        """Search discussions for relevant messages."""
        query_lower = query.lower()
        results = []

        for f in self.storage_dir.glob("*.json"):
            try:
                messages = json.loads(f.read_text(encoding="utf-8"))
                for msg in messages:
                    if query_lower in msg.get("message", "").lower():
                        results.append(msg)
            except Exception:
                pass

        return results[:10]


def create_webhook_app(repo_path: str = "."):
    """
    Create a Flask app that receives webhook messages from Slack/Teams.
    
    Slack webhook format:
        POST /webhook/slack
        {"text": "message", "user_name": "author", "channel_name": "channel"}
    
    Teams webhook format:
        POST /webhook/teams  
        {"text": "message", "from": {"name": "author"}, "channelId": "channel"}
    
    Manual format:
        POST /webhook/message
        {"message": "text", "author": "name", "channel": "channel", "ticket_id": "KAN-1"}
    """
    try:
        from flask import Flask, request, jsonify
    except ImportError:
        raise ImportError("Flask not installed. Run: pip install flask")

    app = Flask(__name__)
    chat = TeamChatIntegration(repo_path=repo_path)

    @app.route("/webhook/slack", methods=["POST"])
    def slack_webhook():
        """Receive messages from Slack incoming webhook."""
        data = request.json or {}
        message = data.get("text", "")
        author = data.get("user_name", "Unknown")
        channel = data.get("channel_name", "general")

        # Try to extract ticket ID from channel name
        import re
        ticket_match = re.search(r'([A-Z][A-Z0-9]+-\d+)', channel.upper())
        ticket_id = ticket_match.group(1) if ticket_match else None

        if message:
            chat.add_message(message, author, channel, ticket_id)
            return jsonify({"status": "ok"}), 200
        return jsonify({"status": "no message"}), 400

    @app.route("/webhook/teams", methods=["POST"])
    def teams_webhook():
        """Receive messages from Microsoft Teams webhook."""
        data = request.json or {}
        message = data.get("text", "")
        author = data.get("from", {}).get("name", "Unknown")
        channel = data.get("channelId", "general")

        import re
        ticket_match = re.search(r'([A-Z][A-Z0-9]+-\d+)', channel.upper())
        ticket_id = ticket_match.group(1) if ticket_match else None

        if message:
            chat.add_message(message, author, channel, ticket_id)
            return jsonify({"status": "ok"}), 200
        return jsonify({"status": "no message"}), 400

    @app.route("/webhook/message", methods=["POST"])
    def manual_message():
        """Receive manually posted messages."""
        data = request.json or {}
        message = data.get("message", "")
        author = data.get("author", "Developer")
        channel = data.get("channel", "general")
        ticket_id = data.get("ticket_id")

        if message:
            chat.add_message(message, author, channel, ticket_id)
            return jsonify({"status": "ok", "message": "Recorded"}), 200
        return jsonify({"status": "error", "message": "No message provided"}), 400

    @app.route("/discussions", methods=["GET"])
    def list_discussions():
        """List recent discussions."""
        return jsonify(chat.get_all_recent(limit=30))

    @app.route("/discussions/<ticket_id>", methods=["GET"])
    def get_ticket_discussion(ticket_id):
        """Get discussions for a specific ticket."""
        return jsonify(chat.get_discussion(ticket_id))

    return app
