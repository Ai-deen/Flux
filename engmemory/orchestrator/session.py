"""
Session Manager - Tracks active development sessions per ticket.

A "session" represents the full lifecycle of working on a ticket:
- Context gathered (Jira, Slack, commits, AI history)
- Current state (in_progress, waiting_for_input, blocked, done)
- Pending questions the AI agent has
- Updates received since last AI interaction
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

SESSION_DIR = Path.home() / ".engmemory" / "sessions"


@dataclass
class SessionContext:
    """All context gathered for a session."""
    jira_description: str = ""
    jira_comments: list[str] = field(default_factory=list)
    slack_messages: list[str] = field(default_factory=list)
    related_commits: list[str] = field(default_factory=list)
    ai_history: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)


@dataclass
class DevSession:
    """A development session tied to a single ticket."""
    ticket_key: str
    summary: str
    branch_name: str = ""
    slack_channel_id: str = ""
    slack_channel_name: str = ""
    repo_path: str = ""

    # State
    status: str = "new"  # new, in_progress, waiting, blocked, done
    pending_questions: list[str] = field(default_factory=list)
    updates_since_last_check: list[str] = field(default_factory=list)

    # Context
    context: SessionContext = field(default_factory=SessionContext)

    # Tracking timestamps
    created_at: str = ""
    last_jira_check: str = ""
    last_slack_check: str = ""
    last_git_check: str = ""
    last_ai_interaction: str = ""

    # Ticket metadata
    assignee_email: str = ""
    reporter_email: str = ""
    priority: str = "Medium"
    issue_type: str = "Task"
    parent_key: str = ""
    has_subtasks: bool = False

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.branch_name:
            self.branch_name = self._generate_branch_name()

    def _generate_branch_name(self) -> str:
        """Generate git branch name from ticket."""
        import re
        safe = re.sub(r"[^a-zA-Z0-9\s-]", "", self.summary)
        safe = re.sub(r"\s+", "-", safe.strip())[:40].lower()
        return f"{self.ticket_key.lower()}/{safe}"

    @property
    def needs_branch(self) -> bool:
        """Determine if this ticket needs its own git branch."""
        # Parent tickets with subtasks don't need a branch
        if self.has_subtasks:
            return False
        # Epics don't need branches
        if self.issue_type.lower() in ("epic",):
            return False
        # Everything else gets a branch
        return True

    @property
    def needs_channel(self) -> bool:
        """Determine if this ticket needs its own Slack channel."""
        # Subtasks use parent's channel
        if self.parent_key:
            return False
        # Everything else gets a channel
        return True

    @property
    def has_new_context(self) -> bool:
        """Check if there's new context since last AI interaction."""
        return len(self.updates_since_last_check) > 0

    def add_update(self, source: str, content: str):
        """Record a new update from any source."""
        timestamp = datetime.now(timezone.utc).strftime("%H:%M")
        self.updates_since_last_check.append(f"[{timestamp} {source}] {content}")

    def consume_updates(self) -> list[str]:
        """Get and clear pending updates (for feeding to AI agent)."""
        updates = self.updates_since_last_check.copy()
        self.updates_since_last_check = []
        self.last_ai_interaction = datetime.now(timezone.utc).isoformat()
        return updates

    def save(self):
        """Persist session to disk."""
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        path = SESSION_DIR / f"{self.ticket_key}.json"
        with open(path, "w") as f:
            json.dump(asdict(self), f, indent=2)
        log.debug("Saved session: %s", self.ticket_key)

    @classmethod
    def load(cls, ticket_key: str) -> Optional["DevSession"]:
        """Load session from disk."""
        path = SESSION_DIR / f"{ticket_key}.json"
        if not path.exists():
            return None
        with open(path) as f:
            data = json.load(f)
        # Reconstruct nested dataclass
        ctx_data = data.pop("context", {})
        # Remove unknown fields that may exist in older session files
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        data = {k: v for k, v in data.items() if k in valid_fields}
        ctx_valid = {f.name for f in SessionContext.__dataclass_fields__.values()}
        ctx_data = {k: v for k, v in ctx_data.items() if k in ctx_valid}
        session = cls(**data)
        session.context = SessionContext(**ctx_data)
        return session

    @classmethod
    def list_active(cls) -> list["DevSession"]:
        """List all active (non-done) sessions."""
        SESSION_DIR.mkdir(parents=True, exist_ok=True)
        sessions = []
        for path in SESSION_DIR.glob("*.json"):
            try:
                s = cls.load(path.stem)
                if s and s.status != "done":
                    sessions.append(s)
            except Exception as e:
                log.warning("Failed to load session %s: %s", path.name, e)
        return sessions
