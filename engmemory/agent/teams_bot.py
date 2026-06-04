"""
teams_bot.py — Microsoft Teams Bot for Team Discussion Capture

Same concept as the Slack bot but for Microsoft Teams:
1. Auto-creates a Teams channel when a Jira ticket is created
2. Adds relevant people
3. Captures technical discussions
4. Filters out personal/informal content
5. Stores as context for the AI agent

Uses Microsoft Bot Framework SDK.

Requirements:
    pip install botbuilder-core botbuilder-schema aiohttp

Setup:
    1. Register a bot at dev.botframework.com or Azure Bot Service
    2. Set TEAMS_APP_ID and TEAMS_APP_PASSWORD in engmemory.env
    3. Set up ngrok or Azure endpoint for webhooks
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
    from botbuilder.core import ActivityHandler, TurnContext, MessageFactory
    from botbuilder.schema import Activity, ActivityTypes
    HAS_TEAMS_SDK = True
except ImportError:
    HAS_TEAMS_SDK = False

from .slack_bot import is_technical_message


class EngMemoryTeamsBot(ActivityHandler if HAS_TEAMS_SDK else object):
    """
    Microsoft Teams bot that captures team discussions.
    
    Behavior:
    - Listens to messages in channels it's added to
    - Only captures technical/formal messages (privacy filter)
    - Stores discussions as context for the AI agent
    - Does NOT respond unless directly @mentioned with a question
    """

    def __init__(self, repo_path: str = "."):
        if HAS_TEAMS_SDK:
            super().__init__()
        self.repo_path = repo_path
        self.storage_dir = Path(repo_path) / ".ai_memory" / "team_discussions"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    async def on_message_activity(self, turn_context: TurnContext):
        """Handle incoming messages."""
        text = turn_context.activity.text or ""
        
        # Skip if not technical
        if not is_technical_message(text):
            return

        # Extract info
        author = turn_context.activity.from_property.name or "Unknown"
        channel_id = turn_context.activity.channel_id or ""
        conversation = turn_context.activity.conversation
        channel_name = conversation.name if conversation else channel_id

        # Extract ticket ID from channel name
        ticket_match = re.search(r'([A-Z][A-Z0-9]+-\d+)', channel_name.upper())
        ticket_id = ticket_match.group(1) if ticket_match else None

        # Store the message
        self._store_message(text, author, channel_name, ticket_id)
        log.info(f"[TeamsBot] Captured: {author}: {text[:50]}...")

        # If directly @mentioned, respond with context
        if turn_context.activity.text and "@engmemory" in text.lower():
            await self._handle_mention(turn_context, text)

    async def _handle_mention(self, turn_context: TurnContext, text: str):
        """Handle when bot is @mentioned — provide helpful context."""
        # Remove the @mention
        query = re.sub(r'@\w+', '', text).strip()
        
        if not query:
            await turn_context.send_activity(
                "I'm capturing discussions in this channel as context. "
                "Ask me about related tickets or past issues!"
            )
            return

        # Search for relevant context
        try:
            from ..search.rag import ask_question
            answer = ask_question(query, repo_path=self.repo_path)
            await turn_context.send_activity(answer[:2000])
        except Exception as exc:
            await turn_context.send_activity(
                f"I couldn't search right now, but I've noted your question."
            )

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
            "source": "teams",
        }

        if ticket_id:
            filename = f"{ticket_id.lower()}.json"
        else:
            filename = f"teams-{time.strftime('%Y-%m-%d')}.json"

        filepath = self.storage_dir / filename

        messages = []
        if filepath.exists():
            try:
                messages = json.loads(filepath.read_text(encoding="utf-8"))
            except Exception:
                messages = []

        messages.append(entry)
        filepath.write_text(json.dumps(messages, indent=2), encoding="utf-8")


async def create_teams_channel(team_id: str, ticket_key: str, 
                                ticket_summary: str,
                                members: Optional[list[str]] = None):
    """
    Create a Teams channel for a Jira ticket using Microsoft Graph API.
    
    Requires:
        - TEAMS_APP_ID
        - TEAMS_APP_PASSWORD  
        - Microsoft Graph permissions: Channel.Create, ChannelMember.ReadWrite.All
    """
    try:
        import aiohttp
    except ImportError:
        log.warning("aiohttp not installed. Run: pip install aiohttp")
        return None

    app_id = os.getenv("TEAMS_APP_ID")
    app_password = os.getenv("TEAMS_APP_PASSWORD")
    tenant_id = os.getenv("TEAMS_TENANT_ID")

    if not all([app_id, app_password, tenant_id]):
        log.warning("Teams not configured. Set TEAMS_APP_ID, TEAMS_APP_PASSWORD, TEAMS_TENANT_ID")
        return None

    # Get access token
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    token_data = {
        "grant_type": "client_credentials",
        "client_id": app_id,
        "client_secret": app_password,
        "scope": "https://graph.microsoft.com/.default",
    }

    async with aiohttp.ClientSession() as session:
        # Get token
        async with session.post(token_url, data=token_data) as resp:
            if resp.status != 200:
                log.error(f"Failed to get Teams token: {await resp.text()}")
                return None
            token_resp = await resp.json()
            access_token = token_resp["access_token"]

        # Create channel
        channel_name = f"{ticket_key} - {ticket_summary}"[:50]
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        channel_data = {
            "displayName": channel_name,
            "description": f"Discussion channel for {ticket_key}: {ticket_summary}",
            "membershipType": "standard",
        }

        graph_url = f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels"
        async with session.post(graph_url, headers=headers, json=channel_data) as resp:
            if resp.status in (200, 201):
                result = await resp.json()
                channel_id = result["id"]
                log.info(f"[TeamsBot] Created channel: {channel_name}")

                # Add members if provided
                if members:
                    for member_id in members:
                        member_data = {
                            "@odata.type": "#microsoft.graph.aadUserConversationMember",
                            "roles": ["member"],
                            "user@odata.bind": f"https://graph.microsoft.com/v1.0/users/{member_id}"
                        }
                        member_url = f"https://graph.microsoft.com/v1.0/teams/{team_id}/channels/{channel_id}/members"
                        await session.post(member_url, headers=headers, json=member_data)

                return channel_id
            else:
                error = await resp.text()
                log.error(f"[TeamsBot] Failed to create channel: {error}")
                return None


def run_teams_bot(repo_path: str = ".", port: int = 3978):
    """Run the Teams bot as a web server."""
    if not HAS_TEAMS_SDK:
        print("botbuilder-core not installed. Run: pip install botbuilder-core aiohttp")
        return

    import asyncio
    from aiohttp import web
    from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings

    app_id = os.getenv("TEAMS_APP_ID", "")
    app_password = os.getenv("TEAMS_APP_PASSWORD", "")

    settings = BotFrameworkAdapterSettings(app_id, app_password)
    adapter = BotFrameworkAdapter(settings)
    bot = EngMemoryTeamsBot(repo_path=repo_path)

    async def messages(req):
        body = await req.json()
        activity = Activity().deserialize(body)
        auth_header = req.headers.get("Authorization", "")
        await adapter.process_activity(activity, auth_header, bot.on_turn)
        return web.Response(status=200)

    app = web.Application()
    app.router.add_post("/api/messages", messages)

    print(f"🤖 EngMemory Teams Bot running on port {port}")
    print(f"   Endpoint: http://localhost:{port}/api/messages")
    print("   Configure this URL in Azure Bot Service.")
    print("   Press Ctrl+C to stop.\n")

    web.run_app(app, host="0.0.0.0", port=port)
