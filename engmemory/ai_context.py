"""
ai_context.py

Captures AI session context (Copilot chat) from VS Code's workspace storage
and creates sanitized technical summaries to attach to commits.

Privacy-first approach:
- Only extracts technical content
- Filters personal opinions, emotions, non-work conversations
- Never stores raw chat logs
- Summary is bullet points only
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import sqlite3
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Privacy filter patterns — things to REMOVE before processing
# ---------------------------------------------------------------------------

SENSITIVE_PATTERNS = [
    # API keys, tokens, secrets
    re.compile(r'(sk-[a-zA-Z0-9_-]{20,})'),
    re.compile(r'(token|key|secret|password|passwd|pwd)\s*[:=]\s*\S+', re.IGNORECASE),
    # Personal info
    re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),  # emails
    re.compile(r'\b\d{10,}\b'),  # phone numbers
    # Windows paths with usernames
    re.compile(r'C:\\Users\\[^\\]+', re.IGNORECASE),
]


def _redact_sensitive(text: str) -> str:
    """Remove sensitive patterns from text."""
    for pattern in SENSITIVE_PATTERNS:
        text = pattern.sub('[REDACTED]', text)
    return text


# ---------------------------------------------------------------------------
# Read Copilot sessions from VS Code state DB
# ---------------------------------------------------------------------------

def _find_vscode_state_db(repo_path: str) -> Optional[Path]:
    """
    Find the VS Code state.vscdb for the workspace containing this repo.
    """
    if platform.system() == 'Windows':
        base = Path(os.environ.get('APPDATA', '')) / 'Code' / 'User' / 'workspaceStorage'
    elif platform.system() == 'Darwin':
        base = Path.home() / 'Library' / 'Application Support' / 'Code' / 'User' / 'workspaceStorage'
    else:
        base = Path.home() / '.config' / 'Code' / 'User' / 'workspaceStorage'

    if not base.exists():
        return None

    # Search workspace storage folders for one matching our repo
    repo_path_resolved = str(Path(repo_path).resolve()).lower()

    for ws_dir in base.iterdir():
        if not ws_dir.is_dir():
            continue
        workspace_json = ws_dir / 'workspace.json'
        if workspace_json.exists():
            try:
                ws_data = json.loads(workspace_json.read_text(encoding='utf-8'))
                folder = ws_data.get('folder', '')
                # Convert URI to path
                if folder.startswith('file:///'):
                    folder_path = folder[8:] if platform.system() == 'Windows' else folder[7:]
                    folder_path = folder_path.replace('/', os.sep).lower()
                    # URL decode
                    from urllib.parse import unquote
                    folder_path = unquote(folder_path)
                    if repo_path_resolved.startswith(folder_path) or folder_path.startswith(repo_path_resolved):
                        state_db = ws_dir / 'state.vscdb'
                        if state_db.exists():
                            return state_db
            except Exception:
                continue

    return None


def _extract_user_messages(state_db: Path, since_minutes: int = 120) -> list[str]:
    """
    Extract ALL user messages from Copilot chat sessions.
    Returns the full conversation history (user side).
    """
    messages = []
    try:
        conn = sqlite3.connect(str(state_db), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        cur = conn.cursor()
        cur.execute("SELECT value FROM ItemTable WHERE key = 'memento/interactive-session'")
        row = cur.fetchone()
        conn.close()

        if not row:
            return messages

        data = json.loads(row[0])
        sessions = data.get('history', {}).get('copilot', [])

        for session in sessions:
            if isinstance(session, dict):
                input_text = session.get('inputText', '').strip()
                if input_text and len(input_text) > 10:
                    messages.append(input_text)

    except Exception as exc:
        log.debug(f"Could not read VS Code state: {exc}")

    return messages


def extract_new_messages(repo_path: str) -> list[str]:
    """
    Extract only NEW messages since the last commit.
    Uses a marker file to track where we left off.
    """
    state_db = _find_vscode_state_db(repo_path)
    if not state_db:
        return []

    all_messages = _extract_user_messages(state_db)
    if not all_messages:
        return []

    # Read the last processed index
    marker_file = Path(repo_path) / ".ai_memory" / "ai_sessions" / ".last_index"
    last_index = 0
    if marker_file.exists():
        try:
            last_index = int(marker_file.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            last_index = 0

    # Get only new messages since last commit
    new_messages = all_messages[last_index:]

    return new_messages


def save_message_marker(repo_path: str) -> None:
    """Save the current message count so next commit starts fresh."""
    state_db = _find_vscode_state_db(repo_path)
    if not state_db:
        return

    all_messages = _extract_user_messages(state_db)
    marker_file = Path(repo_path) / ".ai_memory" / "ai_sessions" / ".last_index"
    marker_file.parent.mkdir(parents=True, exist_ok=True)
    marker_file.write_text(str(len(all_messages)), encoding="utf-8")


# ---------------------------------------------------------------------------
# LLM Privacy Filter — the core of the sanitization
# ---------------------------------------------------------------------------

PRIVACY_FILTER_PROMPT = """You are a strict technical content filter for a development team's AI session logs.

From the following AI chat messages, extract ONLY technical/work-related content.

RULES:
1. ONLY output technical facts: bugs discussed, approaches tried, files mentioned, decisions made
2. COMPLETELY IGNORE AND REMOVE:
   - Personal opinions about people (managers, colleagues, anyone)
   - Emotional expressions (frustration, anger, happiness, boredom)
   - Non-work conversations (shopping, health, family, hobbies, food)
   - Complaints, rants, trash talk about anyone or anything
   - Personal life details
   - Tone, attitude, behavioral patterns
   - Jokes, sarcasm, casual chat
3. If a message is mixed (technical + personal), extract ONLY the technical part
4. If ALL messages are non-technical, respond with exactly: NO_TECHNICAL_CONTENT
5. Output 3-7 bullet points maximum
6. Each bullet should be a factual technical statement
7. Never mention names of people being discussed negatively

Messages to filter:
---
{messages}
---

Output (technical bullet points only):"""


def create_ai_context_summary(
    repo_path: str,
    messages: Optional[list[str]] = None,
) -> Optional[dict]:
    """
    Create a sanitized AI context summary from NEW Copilot messages
    (only since the last commit).
    Uses LLM to extract technical content and filter personal stuff.
    
    Returns:
        Dict with 'summary' (bullet points) and message count
        None if no technical content found
    """
    # Get only NEW messages since last commit
    if messages is None:
        messages = extract_new_messages(repo_path)

    if not messages:
        return None

    # Pre-filter: redact sensitive data
    cleaned_messages = [_redact_sensitive(msg) for msg in messages]

    # Combine all new messages
    combined = "\n".join(f"- {msg[:800]}" for msg in cleaned_messages)
    # Cap at 4000 chars to stay within LLM limits
    if len(combined) > 4000:
        combined = combined[-4000:]

    # Run through LLM privacy filter
    summary = _run_privacy_filter(combined)

    if not summary or summary.strip() == "NO_TECHNICAL_CONTENT":
        return None

    return {
        "summary": summary,
        "message_count": len(cleaned_messages),
        "source": "copilot_chat",
    }


def _run_privacy_filter(messages_text: str) -> Optional[str]:
    """Run messages through LLM to extract only technical content."""
    try:
        import requests
    except ImportError:
        # Fallback: basic keyword filtering without LLM
        return _basic_filter(messages_text)

    from .utils.config import config

    prompt = PRIVACY_FILTER_PROMPT.format(messages=messages_text)

    # Try OpenRouter
    if config.openrouter_api_key:
        try:
            response = requests.post(
                url="https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.openrouter_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "google/gemini-2.0-flash-001",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 500,
                    "temperature": 0.1,
                },
                timeout=15,
            )
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            log.debug(f"OpenRouter call failed for privacy filter: {exc}")

    # Fallback to basic filter
    return _basic_filter(messages_text)


def _basic_filter(messages_text: str) -> Optional[str]:
    """
    Basic keyword-based filter when LLM is not available.
    Only keeps lines that mention technical terms.
    Strips non-technical noise aggressively.
    """
    technical_keywords = {
        'bug', 'fix', 'error', 'function', 'api', 'endpoint', 'database',
        'file', 'component', 'module', 'class', 'method', 'deploy', 'build',
        'test', 'commit', 'branch', 'merge', 'config', 'import', 'export',
        'server', 'client', 'frontend', 'backend', 'route', 'handler',
        'install', 'package', 'dependency', 'docker', 'azure', 'aws',
        'react', 'python', 'javascript', 'typescript', 'sql', 'css',
        'hook', 'webhook', 'pipeline', 'ci', 'cd', 'refactor', 'optimize',
        'feature', 'implement', 'create', 'update', 'delete', 'add',
    }

    # Words that indicate non-technical/personal content
    noise_keywords = {
        'feel', 'stupid', 'hate', 'love', 'angry', 'frustrated',
        'shopping', 'buy', 'food', 'lunch', 'dinner', 'health',
        'family', 'friend', 'girlfriend', 'boyfriend', 'manager',
        'boring', 'tired', 'sleepy', 'bored',
    }

    lines = messages_text.split('\n')
    technical_lines = []

    for line in lines:
        line_lower = line.lower().strip()
        if not line_lower or len(line_lower) < 15:
            continue
        
        # Skip if it contains noise keywords
        if any(kw in line_lower for kw in noise_keywords):
            continue
        
        # Keep only if it has technical keywords
        tech_count = sum(1 for kw in technical_keywords if kw in line_lower)
        if tech_count >= 2:  # Require at least 2 technical keywords
            # Truncate long lines to key points
            clean_line = line.strip()[:200]
            technical_lines.append(clean_line)

    if not technical_lines:
        return None

    return "\n".join(technical_lines[:7])
