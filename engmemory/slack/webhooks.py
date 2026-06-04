"""
Webhook server for Slack + Jira integration.

Endpoints:
- POST /webhooks/jira       — Jira ticket created/updated → create Slack channel
- POST /webhooks/slack      — Slack Events API (message capture)
- POST /api/capture/{key}   — Manual trigger: capture messages for a ticket
- GET  /api/channels        — List tracked channels
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Optional

from fastapi import APIRouter, Request, Response, HTTPException
from pydantic import BaseModel

from .client import SlackClient
from .channel_manager import ChannelManager, TicketInfo
from .message_capture import MessageCapture
from ..orchestrator.session import DevSession
from ..orchestrator.main import Orchestrator
from ..utils.config import config

log = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])

# Services (initialized on startup)
_slack_client: Optional[SlackClient] = None
_channel_manager: Optional[ChannelManager] = None
_message_capture: Optional[MessageCapture] = None


def init_slack_services():
    """Initialize Slack services. Call on app startup."""
    global _slack_client, _channel_manager, _message_capture

    if not config.slack_bot_token:
        log.warning("Slack not configured — set SLACK_BOT_TOKEN")
        return

    _slack_client = SlackClient()
    _channel_manager = ChannelManager(_slack_client)
    _message_capture = MessageCapture(_slack_client)
    log.info("Slack integration initialized")


# ─── Jira Webhook ─────────────────────────────────────────────────────────


@router.post("/webhooks/jira")
async def handle_jira_webhook(request: Request):
    """
    Handle Jira webhook for issue creation/update.
    Creates Slack channel on parent ticket creation.
    """
    if not _channel_manager:
        raise HTTPException(status_code=503, detail="Slack not configured")

    body = await request.json()
    event = body.get("webhookEvent", "")

    if event == "jira:issue_created":
        issue = body.get("issue", {})
        fields = issue.get("fields", {})

        ticket = TicketInfo(
            key=issue.get("key", "UNKNOWN-0"),
            summary=fields.get("summary", "No summary"),
            assignee_email=_get_email(fields.get("assignee")),
            reporter_email=_get_email(fields.get("reporter")),
            parent_key=_get_parent_key(fields),
            issue_type=fields.get("issuetype", {}).get("name", "Task"),
            priority=fields.get("priority", {}).get("name", "Medium"),
            subtask_assignees=_get_subtask_assignees(fields),
            url=f"https://{config.jira_domain}/browse/{issue.get('key', '')}",
        )

        channel_id = await _channel_manager.handle_ticket_created(ticket)

        return {
            "status": "ok",
            "action": "channel_created" if ticket.is_parent_ticket else "member_added",
            "ticket": ticket.key,
            "channel_id": channel_id,
        }

    elif event == "jira:issue_updated":
        issue = body.get("issue", {})
        fields = issue.get("fields", {})
        changelog = body.get("changelog", {}).get("items", [])

        for change in changelog:
            if change.get("field") == "assignee":
                new_assignee = _get_email(fields.get("assignee"))
                if new_assignee:
                    ticket_key = issue.get("key", "")
                    parent_key = _get_parent_key(fields) or ticket_key
                    channel_id = _channel_manager.get_channel_for_ticket(parent_key)
                    if channel_id:
                        user = await _slack_client.find_user_by_email(new_assignee)
                        if user:
                            await _slack_client.invite_to_channel(channel_id, user["id"])
                        return {"status": "ok", "action": "assignee_added"}

        return {"status": "ok", "action": "no_action"}

    return {"status": "ok", "action": "ignored", "event": event}


# ─── Slack Events API ─────────────────────────────────────────────────────


@router.post("/webhooks/slack")
async def handle_slack_event(request: Request):
    """
    Handle Slack Events API callbacks.

    Slack sends:
    - url_verification challenge on setup
    - event_callback with message events
    """
    body = await request.json()

    # Handle URL verification (Slack sends this when you register the endpoint)
    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge", "")}

    # Verify request is from Slack (optional but recommended)
    if config.slack_signing_secret:
        if not _verify_slack_signature(request, await request.body()):
            raise HTTPException(status_code=401, detail="Invalid signature")

    # Handle events
    if body.get("type") == "event_callback":
        event = body.get("event", {})
        event_type = event.get("type")
        subtype = event.get("subtype")

        # New message (no subtype) or thread reply (has thread_ts)
        if event_type == "message" and not subtype:
            channel_id = event.get("channel", "")
            ticket_key = _find_ticket_for_channel(channel_id)

            if ticket_key and _message_capture:
                summary = await _message_capture.capture_channel_messages(
                    channel_id=channel_id,
                    ticket_key=ticket_key,
                    channel_name=f"channel-{ticket_key}",
                )
                if summary.messages:
                    await _message_capture.store_discussion(summary)

        # Message edited/updated
        elif event_type == "message" and subtype == "message_changed":
            channel_id = event.get("channel", "")
            ticket_key = _find_ticket_for_channel(channel_id)

            if ticket_key and _message_capture:
                new_message = event.get("message", {})
                text = new_message.get("text", "")
                user = new_message.get("user", "unknown")

                if _message_capture.is_technical_message(text):
                    summary = await _message_capture.capture_channel_messages(
                        channel_id=channel_id,
                        ticket_key=ticket_key,
                        channel_name=f"channel-{ticket_key}",
                    )
                    if summary.messages:
                        await _message_capture.store_discussion(summary)

    # Slack expects a 200 within 3 seconds
    return {"status": "ok"}


# ─── Manual Capture Endpoint ──────────────────────────────────────────────


@router.post("/api/capture/{ticket_key}")
async def manual_capture(ticket_key: str):
    """Manually trigger message capture for a specific ticket's channel."""
    if not _message_capture or not _channel_manager:
        raise HTTPException(status_code=503, detail="Slack not configured")

    channel_id = _channel_manager.get_channel_for_ticket(ticket_key)
    if not channel_id:
        raise HTTPException(status_code=404, detail=f"No channel for ticket {ticket_key}")

    summary = await _message_capture.capture_channel_messages(
        channel_id=channel_id,
        ticket_key=ticket_key,
        channel_name=f"channel-{ticket_key}",
    )

    blob_name = None
    if summary.messages:
        blob_name = await _message_capture.store_discussion(summary)

    return {
        "status": "ok",
        "ticket_key": ticket_key,
        "messages_captured": len(summary.messages),
        "issues_found": summary.issues_found,
        "decisions_made": summary.decisions_made,
        "stored_as": blob_name,
    }


# ─── Status Endpoints ────────────────────────────────────────────────────


@router.get("/api/channels")
async def list_channels():
    """List all tracked ticket → channel mappings."""
    if not _channel_manager:
        return {"channels": {}}
    return {"channels": _channel_manager._channel_map}


# ─── Helpers ──────────────────────────────────────────────────────────────


def _get_email(user_field: Optional[dict]) -> Optional[str]:
    """Extract email from Jira user field."""
    if not user_field:
        return None
    return user_field.get("emailAddress") or user_field.get("email")


def _get_parent_key(fields: dict) -> Optional[str]:
    """Extract parent ticket key from Jira fields."""
    parent = fields.get("parent")
    if parent:
        return parent.get("key")
    return None


def _get_subtask_assignees(fields: dict) -> list[str]:
    """Extract emails of subtask assignees."""
    emails = []
    subtasks = fields.get("subtasks", [])
    for subtask in subtasks:
        assignee = subtask.get("fields", {}).get("assignee")
        email = _get_email(assignee)
        if email:
            emails.append(email)
    return emails


def _find_ticket_for_channel(channel_id: str) -> Optional[str]:
    """Reverse lookup: find ticket key for a channel."""
    if not _channel_manager:
        return None
    for ticket_key, ch_id in _channel_manager._channel_map.items():
        if ch_id == channel_id:
            return ticket_key
    return None


def _verify_slack_signature(request: Request, body: bytes) -> bool:
    """Verify Slack request signature."""
    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    if not timestamp or not signature:
        return False

    # Prevent replay attacks (5 min window)
    if abs(time.time() - int(timestamp)) > 300:
        return False

    sig_basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    computed = "v0=" + hmac.new(
        config.slack_signing_secret.encode(),
        sig_basestring.encode(),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed, signature)
