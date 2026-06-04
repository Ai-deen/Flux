"""
Slack Integration Server for EngMemory.

Standalone FastAPI server that handles:
- Jira webhooks → auto-create Slack channels
- Slack Events API → capture team discussions
- Manual capture triggers

Run with: uvicorn engmemory.slack.server:app --host 0.0.0.0 --port 5051 --reload
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .webhooks import router as webhook_router, init_slack_services
from ..utils.config import config

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = FastAPI(
    title="EngMemory Slack Integration",
    description="Auto-creates Slack channels for Jira tickets and captures team discussions",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(webhook_router)


@app.on_event("startup")
async def startup():
    """Initialize Slack services on startup."""
    if config.slack_bot_token:
        init_slack_services()
        log.info("Slack integration ready")
    else:
        log.warning(
            "Slack not configured. Set SLACK_BOT_TOKEN environment variable. "
            "Get it from https://api.slack.com/apps"
        )


@app.get("/")
async def root():
    return {
        "service": "EngMemory Slack Integration",
        "version": "1.0.0",
        "slack_configured": bool(config.slack_bot_token),
        "endpoints": {
            "jira_webhook": "POST /webhooks/jira",
            "slack_events": "POST /webhooks/slack",
            "manual_capture": "POST /api/capture/{ticket_key}",
            "list_channels": "GET /api/channels",
            "health": "GET /health",
        },
    }


@app.get("/health")
async def health():
    return {"status": "healthy", "slack_configured": bool(config.slack_bot_token)}
