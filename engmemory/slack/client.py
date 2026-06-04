"""
Slack API client for EngMemory.

Handles channel creation, member management, and message operations.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from ..utils.config import config

log = logging.getLogger(__name__)

SLACK_BASE = "https://slack.com/api"


class SlackClient:
    """Client for Slack Web API."""

    def __init__(self, bot_token: Optional[str] = None):
        self.bot_token = bot_token or config.slack_bot_token
        if not self.bot_token:
            raise ValueError("SLACK_BOT_TOKEN is required")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/json",
        }

    async def _post(self, method: str, data: dict) -> dict:
        """Make a Slack API call."""
        url = f"{SLACK_BASE}/{method}"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=data, headers=self._headers())
            resp.raise_for_status()
            result = resp.json()
            if not result.get("ok"):
                error = result.get("error", "unknown_error")
                log.error("Slack API error (%s): %s", method, error)
            return result

    async def _get(self, method: str, params: dict = None) -> dict:
        """Make a Slack API GET call."""
        url = f"{SLACK_BASE}/{method}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, params=params or {},
                headers={"Authorization": f"Bearer {self.bot_token}"}
            )
            resp.raise_for_status()
            return resp.json()

    # ─── Channels ─────────────────────────────────────────────────────

    async def create_channel(self, name: str, is_private: bool = False) -> dict:
        """
        Create a Slack channel.

        Args:
            name: Channel name (lowercase, no spaces, max 80 chars).
                  Will be auto-sanitized.
            is_private: Whether to create a private channel.

        Returns:
            Channel object from Slack API.
        """
        # Slack channel names: lowercase, no spaces, hyphens OK
        clean_name = name.lower().replace(" ", "-")[:80]

        result = await self._post("conversations.create", {
            "name": clean_name,
            "is_private": is_private,
        })

        if result.get("ok"):
            channel = result["channel"]
            log.info("Created Slack channel: #%s (id=%s)", clean_name, channel["id"])
            return channel
        elif result.get("error") == "name_taken":
            # Channel already exists, find it
            log.info("Channel #%s already exists, looking it up", clean_name)
            return await self.find_channel(clean_name)
        else:
            log.error("Failed to create channel #%s: %s", clean_name, result.get("error"))
            return {}

    async def find_channel(self, name: str) -> dict:
        """Find a channel by name."""
        result = await self._get("conversations.list", {
            "types": "public_channel,private_channel",
            "limit": 200,
        })
        if result.get("ok"):
            for ch in result.get("channels", []):
                if ch["name"] == name:
                    return ch
        return {}

    async def invite_to_channel(self, channel_id: str, user_id: str) -> bool:
        """Invite a user to a channel."""
        result = await self._post("conversations.invite", {
            "channel": channel_id,
            "users": user_id,
        })
        if result.get("ok"):
            log.info("Invited user %s to channel %s", user_id, channel_id)
            return True
        elif result.get("error") == "already_in_channel":
            return True
        else:
            log.warning("Failed to invite %s: %s", user_id, result.get("error"))
            return False

    async def set_channel_topic(self, channel_id: str, topic: str) -> bool:
        """Set channel topic."""
        result = await self._post("conversations.setTopic", {
            "channel": channel_id,
            "topic": topic,
        })
        return result.get("ok", False)

    async def set_channel_purpose(self, channel_id: str, purpose: str) -> bool:
        """Set channel purpose/description."""
        result = await self._post("conversations.setPurpose", {
            "channel": channel_id,
            "purpose": purpose,
        })
        return result.get("ok", False)

    # ─── Messages ─────────────────────────────────────────────────────

    async def send_message(
        self, channel_id: str, text: str, blocks: list = None
    ) -> dict:
        """Send a message to a channel."""
        data = {"channel": channel_id, "text": text}
        if blocks:
            data["blocks"] = blocks
        result = await self._post("chat.postMessage", data)
        return result

    async def get_channel_history(
        self, channel_id: str, limit: int = 100, oldest: str = None
    ) -> list[dict]:
        """
        Fetch message history from a channel.

        Args:
            channel_id: Channel to fetch from
            limit: Max messages to return
            oldest: Only messages after this timestamp (epoch string)
        """
        params = {"channel": channel_id, "limit": limit}
        if oldest:
            params["oldest"] = oldest

        result = await self._get("conversations.history", params)
        if result.get("ok"):
            return result.get("messages", [])
        return []

    async def get_thread_replies(
        self, channel_id: str, thread_ts: str, oldest: str = None
    ) -> list[dict]:
        """
        Fetch replies in a thread.

        Args:
            channel_id: Channel containing the thread
            thread_ts: Timestamp of the parent message
            oldest: Only replies after this timestamp
        """
        params = {"channel": channel_id, "ts": thread_ts, "limit": 100}
        if oldest:
            params["oldest"] = oldest

        result = await self._get("conversations.replies", params)
        if result.get("ok"):
            # First message is the parent; skip it to get only replies
            messages = result.get("messages", [])
            return [m for m in messages if m.get("ts") != thread_ts]
        return []

    # ─── Users ────────────────────────────────────────────────────────

    async def find_user_by_email(self, email: str) -> Optional[dict]:
        """Look up a Slack user by email. Falls back to listing users if exact match fails."""
        result = await self._get("users.lookupByEmail", {"email": email})
        if result.get("ok"):
            return result.get("user")

        # Fallback: search through all users for a partial email match
        # (handles cases where Jira email != Slack email but same person)
        log.info("Exact email lookup failed for %s, trying user list fallback", email)
        email_prefix = email.split("@")[0].lower() if email else ""
        if email_prefix:
            users = await self.list_users()
            for user in users:
                if user.get("deleted") or user.get("is_bot"):
                    continue
                profile = user.get("profile", {})
                user_email = profile.get("email", "").lower()
                # Match on exact email or same username prefix
                if user_email == email.lower():
                    return user
                if user_email and user_email.split("@")[0] == email_prefix:
                    log.info("Found user by email prefix match: %s -> %s", email, user_email)
                    return user

        log.warning("User not found for email: %s", email)
        return None

    async def get_user_info(self, user_id: str) -> Optional[dict]:
        """Get user info by ID."""
        result = await self._get("users.info", {"user": user_id})
        if result.get("ok"):
            return result.get("user")
        return None

    async def list_users(self) -> list[dict]:
        """List all workspace users."""
        result = await self._get("users.list")
        if result.get("ok"):
            return result.get("members", [])
        return []
