"""
Poller - Periodically checks Jira & Slack for updates.

Instead of relying on webhooks (which need ngrok/public URL),
this polls sources every N seconds and feeds updates into sessions.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from requests.auth import HTTPBasicAuth

from .session import DevSession
from ..slack.client import SlackClient
from ..slack.message_capture import MessageCapture
from ..utils.config import config

log = logging.getLogger(__name__)


class Poller:
    """Polls Jira and Slack for new updates on active sessions."""

    def __init__(
        self,
        slack_client: Optional[SlackClient] = None,
        poll_interval: int = 10,
        on_new_update=None,  # callback: async fn(ticket_key, update_text, source)
        on_session_done=None,  # callback: async fn(ticket_key) — when Jira moves to Done
    ):
        self.slack_client = slack_client
        self.poll_interval = poll_interval
        self._running = False
        self.on_new_update = on_new_update  # Pipeline auto-trigger callback
        self.on_session_done = on_session_done  # Session completion callback
        # Slack message relevance filter
        self._message_filter = MessageCapture(slack_client) if slack_client else None

    async def start(self):
        """Start the polling loop."""
        self._running = True
        log.info("Poller started (interval=%ds)", self.poll_interval)

        while self._running:
            try:
                await self._poll_cycle()
            except Exception as e:
                log.error("Poll cycle error: %s", e)
            await asyncio.sleep(self.poll_interval)

    def stop(self):
        """Stop the polling loop."""
        self._running = False
        log.info("Poller stopped")

    async def _poll_cycle(self):
        """Run one poll cycle: check all active sessions for updates."""
        sessions = DevSession.list_active()
        if not sessions:
            return

        for session in sessions:
            await self._check_jira_updates(session)
            await self._check_slack_updates(session)
            session.save()

    # ─── Jira Polling ─────────────────────────────────────────────────

    async def _check_jira_updates(self, session: DevSession):
        """Check Jira for new comments or status changes on a ticket."""
        if not config.jira_domain or not config.jira_api_token:
            return

        try:
            url = f"https://{config.jira_domain}/rest/api/3/issue/{session.ticket_key}"
            params = {"fields": "comment,status,assignee,subtasks"}

            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    url,
                    params=params,
                    auth=(config.jira_email, config.jira_api_token),
                )

                if resp.status_code != 200:
                    return

                data = resp.json()
                fields = data.get("fields", {})

                # Check for new comments
                comments = fields.get("comment", {}).get("comments", [])
                new_comments = self._get_new_comments(
                    comments, session.last_jira_check
                )

                # Deduplicate using comment IDs (more reliable than text comparison)
                seen_comment_ids = getattr(session, '_seen_comment_ids', set())
                if not seen_comment_ids and hasattr(session.context, 'jira_comments'):
                    # Build from existing comments count as a rough proxy
                    seen_comment_ids = set()

                for comment in new_comments:
                    comment_id = comment.get("id", "")
                    if comment_id in seen_comment_ids:
                        continue
                    seen_comment_ids.add(comment_id)

                    body = comment.get("body", "")
                    # Jira API v3 uses ADF format, extract text
                    text = self._extract_text_from_adf(body) if isinstance(body, dict) else str(body)
                    author = comment.get("author", {}).get("displayName", "Unknown")
                    full_text = f"{author}: {text}"

                    # Also skip if identical text already exists
                    existing_texts = set(session.context.jira_comments) if hasattr(session.context, 'jira_comments') else set()
                    if full_text in existing_texts:
                        continue

                    session.add_update("jira", f"{author}: {text[:200]}")
                    session.context.jira_comments.append(full_text)

                    # Notify pipeline of new update — this triggers the agent chain
                    if self.on_new_update:
                        log.info(f"[Poller] NEW Jira comment on {session.ticket_key}: {text[:80]}")
                        await self.on_new_update(session.ticket_key, f"{author}: {text[:200]}", "jira")

                session._seen_comment_ids = seen_comment_ids

                # Check for subtask changes
                subtasks = fields.get("subtasks", [])
                if subtasks and not session.has_subtasks:
                    session.has_subtasks = True
                    session.add_update("jira", f"Ticket now has {len(subtasks)} subtasks")

                # Check if Jira ticket was moved to Done/Closed
                jira_status = fields.get("status", {}).get("name", "").lower()
                done_statuses = ("done", "closed", "resolved", "complete", "completed")
                if jira_status in done_statuses and session.status != "done":
                    log.info(
                        "[Poller] Jira ticket %s moved to '%s' — closing session",
                        session.ticket_key, jira_status
                    )
                    session.status = "done"
                    session.add_update("jira", f"Ticket moved to '{jira_status}' — session closed")

                    # Also mark pipeline as DONE if it exists
                    if self.on_session_done:
                        await self.on_session_done(session.ticket_key)

                session.last_jira_check = datetime.now(timezone.utc).isoformat()

        except Exception as e:
            log.warning("Failed to poll Jira for %s: %s", session.ticket_key, e)

    def _get_new_comments(self, comments: list, since: str) -> list:
        """Filter comments that are newer than 'since' timestamp."""
        if not since:
            # First time — return last 3 comments as context (don't trigger callback)
            return comments[-3:]

        # Parse 'since' to epoch for reliable comparison
        try:
            from datetime import datetime as dt
            since_dt = dt.fromisoformat(since.replace('+0000', '+00:00'))
            since_epoch = since_dt.timestamp()
        except (ValueError, TypeError):
            return []

        new = []
        for comment in comments:
            created = comment.get("created", "")
            if not created:
                continue
            try:
                # Jira format: 2026-05-30T10:25:00.000+0000
                created_clean = created.replace('+0000', '+00:00').replace('Z', '+00:00')
                created_dt = dt.fromisoformat(created_clean)
                if created_dt.timestamp() > since_epoch:
                    new.append(comment)
            except (ValueError, TypeError):
                # If parsing fails, use string comparison as fallback
                if created > since:
                    new.append(comment)
        return new

    def _extract_text_from_adf(self, adf: dict) -> str:
        """Extract plain text from Atlassian Document Format."""
        texts = []

        def walk(node):
            if isinstance(node, dict):
                if node.get("type") == "text":
                    texts.append(node.get("text", ""))
                for child in node.get("content", []):
                    walk(child)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(adf)
        return " ".join(texts)

    # ─── Slack Polling ────────────────────────────────────────────────

    async def _check_slack_updates(self, session: DevSession):
        """Check Slack channel for new messages and thread replies."""
        if not self.slack_client or not session.slack_channel_id:
            return

        try:
            # Convert ISO timestamp to Unix epoch for Slack API
            oldest_ts = None
            if session.last_slack_check:
                try:
                    from datetime import datetime as dt
                    parsed = dt.fromisoformat(session.last_slack_check)
                    oldest_ts = str(parsed.timestamp())
                except (ValueError, TypeError):
                    oldest_ts = None

            messages = await self.slack_client.get_channel_history(
                session.slack_channel_id,
                limit=20,
                oldest=oldest_ts,
            )

            for msg in messages:
                # Skip bot messages and channel setup
                if msg.get("subtype") in ("bot_message", "channel_join", "channel_topic", "channel_purpose", "channel_name"):
                    continue

                text = msg.get("text", "")
                user = msg.get("user", "unknown")

                # Handle edited messages — use latest text
                if msg.get("subtype") == "message_changed":
                    inner = msg.get("message", {})
                    text = inner.get("text", "")
                    user = inner.get("user", "unknown")

                # All messages in a ticket channel are relevant — only skip
                # very short/trivial ones (emoji-only, "ok", etc.)
                if len(text.strip()) <= 3:
                    continue

                if len(text.strip()) > 3:  # Capture all substantive messages
                    full_text = f"{user}: {text}"

                    # Skip duplicates
                    if full_text in (session.context.slack_messages or []):
                        continue

                    session.add_update("slack", f"{user}: {text[:200]}")
                    session.context.slack_messages.append(full_text)

                    # Notify pipeline of new update
                    if self.on_new_update:
                        log.info(f"[Poller] NEW Slack message on {session.ticket_key}: {text[:80]}")
                        await self.on_new_update(session.ticket_key, f"{user}: {text[:200]}", "slack")

                # Check thread replies for this message
                thread_ts = msg.get("thread_ts") or msg.get("ts")
                reply_count = msg.get("reply_count", 0)
                if reply_count > 0 and thread_ts:
                    replies = await self.slack_client.get_thread_replies(
                        session.slack_channel_id, thread_ts, oldest=oldest_ts
                    )
                    for reply in replies:
                        reply_text = reply.get("text", "")
                        reply_user = reply.get("user", "unknown")

                        if self._message_filter and not self._message_filter.is_technical_message(reply_text):
                            continue

                        if len(reply_text.strip()) > 5:
                            full_reply = f"{reply_user} (thread): {reply_text}"

                            if full_reply in (session.context.slack_messages or []):
                                continue

                            session.add_update("slack", f"{reply_user} (thread): {reply_text[:200]}")
                            session.context.slack_messages.append(full_reply)

                            if self.on_new_update:
                                log.info(f"[Poller] NEW Slack thread reply on {session.ticket_key}: {reply_text[:80]}")
                                await self.on_new_update(session.ticket_key, f"{reply_user} (thread): {reply_text[:200]}", "slack")

            session.last_slack_check = datetime.now(timezone.utc).isoformat()

        except Exception as e:
            log.warning("Failed to poll Slack for %s: %s", session.ticket_key, e)

    # ─── New Ticket Detection ─────────────────────────────────────────

    async def check_for_new_tickets(self) -> list[dict]:
        """
        Poll Jira for recently created tickets that don't have sessions yet.
        Returns list of new ticket dicts.
        """
        if not config.jira_domain or not config.jira_api_token:
            return []

        try:
            url = f"https://{config.jira_domain}/rest/api/3/search/jql"
            params = {
                "jql": "created >= -1h ORDER BY created DESC",
                "maxResults": 10,
                "fields": "summary,assignee,reporter,issuetype,priority,parent,subtasks",
            }

            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    url,
                    params=params,
                    auth=(config.jira_email, config.jira_api_token),
                )

                if resp.status_code != 200:
                    return []

                data = resp.json()
                new_tickets = []

                for issue in data.get("issues", []):
                    key = issue["key"]
                    # Skip if session already exists
                    if DevSession.load(key):
                        continue
                    new_tickets.append(issue)

                return new_tickets

        except Exception as e:
            log.warning("Failed to check for new tickets: %s", e)
            return []
