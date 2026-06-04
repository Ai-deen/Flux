"""
local.py

Writes CommitPayload JSON to .ai_memory/commits/ inside the repo.
Also maintains a lightweight index file so you can list recent commits
without scanning every file.

Directory layout:
    repo/
    └── .ai_memory/
        ├── commits/
        │   └── 2026-05-17T10-32-11_abc12345.json
        └── index.jsonl          ← one line per commit, lightweight metadata only
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..core.capture import CommitPayload


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MEMORY_DIR = ".ai_memory"
COMMITS_DIR = "commits"
INDEX_FILE = "index.jsonl"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_commit(payload: CommitPayload, repo_path: str = ".") -> Path:
    """
    Persist *payload* to disk.
    Returns the path of the written JSON file.
    """
    commits_dir = _ensure_commits_dir(repo_path)
    json_path = commits_dir / _filename(payload)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload.to_dict(), f, indent=2, ensure_ascii=False)

    _append_index(payload, repo_path)
    return json_path


def read_recent(repo_path: str = ".", limit: int = 20) -> list[dict]:
    """
    Return the *limit* most recent index entries (lightweight metadata).
    Reads from index.jsonl, so it's fast even with thousands of commits.
    """
    index_path = _memory_dir(repo_path) / INDEX_FILE
    if not index_path.exists():
        return []

    lines = index_path.read_text(encoding="utf-8").strip().splitlines()
    entries = []
    for line in reversed(lines):
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(entries) >= limit:
            break
    return entries


def read_commit(sha: str, repo_path: str = ".") -> dict | None:
    """
    Load the full commit JSON for a given SHA prefix or full SHA.
    Returns None if not found.
    """
    commits_dir = _memory_dir(repo_path) / COMMITS_DIR
    if not commits_dir.exists():
        return None

    for json_file in commits_dir.glob("*.json"):
        if sha in json_file.stem:
            return json.loads(json_file.read_text(encoding="utf-8"))
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _memory_dir(repo_path: str) -> Path:
    return Path(repo_path).resolve() / MEMORY_DIR


def _ensure_commits_dir(repo_path: str) -> Path:
    commits_dir = _memory_dir(repo_path) / COMMITS_DIR
    commits_dir.mkdir(parents=True, exist_ok=True)

    # Write a .gitignore so the raw JSON never gets accidentally committed
    gitignore = _memory_dir(repo_path) / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(
            "# EngMemory — local engineering memory\n"
            "# Do not commit raw capture files; summaries are stored in Azure AI Search\n"
            "commits/\n"
            "index.jsonl\n",
            encoding="utf-8",
        )

    return commits_dir


def _filename(payload: CommitPayload) -> str:
    # Use a sortable timestamp prefix so ls gives chronological order
    ts = payload.timestamp.replace(":", "-").replace("+", "").split(".")[0]
    return f"{ts}_{payload.short_sha}.json"


def _append_index(payload: CommitPayload, repo_path: str) -> None:
    index_path = _memory_dir(repo_path) / INDEX_FILE
    entry = {
        "sha": payload.short_sha,
        "timestamp": payload.timestamp,
        "branch": payload.branch,
        "ticket_id": payload.ticket_id,
        "repo": payload.repo_name,
        "message": payload.message.splitlines()[0][:120],  # first line only
        "files_changed": payload.files_changed,
        "insertions": payload.total_insertions,
        "deletions": payload.total_deletions,
    }
    with open(index_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
