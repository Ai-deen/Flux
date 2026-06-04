"""
capture.py

Reads everything we need from the current git commit:
  - commit SHA, message, author, timestamp
  - branch name
  - ticket ID (JIRA-123 or AB#456)
  - per-file diffs (capped to avoid huge payloads)
  - summary stats (files changed, insertions, deletions)

Returns a CommitPayload dataclass ready to be serialised and sent
to the summarisation agent.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import git  # gitpython


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_DIFF_LINES_PER_FILE = 120   # truncate large diffs so the prompt stays lean
MAX_FILES_IN_DIFF = 20          # skip files beyond this (binaries, generated code)

TICKET_PATTERNS = [
    re.compile(r"\b([A-Z]{2,10}-\d+)\b"),          # JIRA-style:  PROJ-123
    re.compile(r"\b(AB#\d+)\b"),                    # Azure DevOps: AB#456
]

SKIP_EXTENSIONS = {
    ".lock", ".min.js", ".min.css", ".map",
    ".png", ".jpg", ".jpeg", ".gif", ".ico",
    ".woff", ".woff2", ".ttf", ".eot",
    ".pdf", ".zip", ".tar", ".gz",
}

SKIP_PATH_FRAGMENTS = {
    "node_modules/", "dist/", "build/", ".next/",
    "vendor/", "__pycache__/", ".ai_memory/",
    "migrations/",  # usually noisy, rarely useful in a summary
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FileDiff:
    path: str
    change_type: str        # "added" | "modified" | "deleted" | "renamed"
    insertions: int
    deletions: int
    diff_text: str          # truncated unified diff


@dataclass
class CommitPayload:
    sha: str
    short_sha: str
    message: str
    author_name: str
    author_email: str
    timestamp: str          # ISO-8601 UTC
    branch: str
    ticket_id: Optional[str]
    repo_name: str
    repo_path: str
    files_changed: int
    total_insertions: int
    total_deletions: int
    file_diffs: list[FileDiff] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def capture_commit(repo_path: str = ".") -> CommitPayload:
    """
    Capture the HEAD commit from the repo at *repo_path*.
    Call this from the post-commit hook immediately after git writes HEAD.
    """
    repo = _open_repo(repo_path)
    commit = repo.head.commit
    return _capture_from_commit(repo, commit, repo_path)


def capture_commit_by_sha(repo_path: str, sha: str) -> CommitPayload:
    """
    Capture a specific commit by SHA (for backfilling old history).
    """
    repo = _open_repo(repo_path)
    commit = repo.commit(sha)
    return _capture_from_commit(repo, commit, repo_path)


def _capture_from_commit(repo, commit, repo_path: str) -> CommitPayload:
    """Shared logic for capturing a commit object."""
    branch = _get_branch(repo)
    message = commit.message.strip()
    ticket_id = _extract_ticket(message, branch)

    stats = commit.stats
    file_diffs = _collect_diffs(repo, commit)

    return CommitPayload(
        sha=commit.hexsha,
        short_sha=commit.hexsha[:8],
        message=message,
        author_name=commit.author.name,
        author_email=commit.author.email,
        timestamp=_utc_iso(commit.authored_datetime),
        branch=branch,
        ticket_id=ticket_id,
        repo_name=Path(repo_path).resolve().name,
        repo_path=str(Path(repo_path).resolve()),
        files_changed=stats.total["files"],
        total_insertions=stats.total["insertions"],
        total_deletions=stats.total["deletions"],
        file_diffs=file_diffs,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _open_repo(path: str) -> git.Repo:
    try:
        return git.Repo(path, search_parent_directories=True)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        raise ValueError(f"No git repository found at or above: {path}")


def _get_branch(repo: git.Repo) -> str:
    try:
        return repo.active_branch.name
    except TypeError:
        # detached HEAD — fall back to short SHA
        return repo.head.commit.hexsha[:8]


def _extract_ticket(message: str, branch: str) -> Optional[str]:
    """
    Try to find a ticket ID in the commit message first, then the branch name.
    Returns the first match or None.
    """
    for src in (message, branch):
        for pattern in TICKET_PATTERNS:
            match = pattern.search(src)
            if match:
                return match.group(1) if pattern.groups else match.group(0)
    return None


def _collect_diffs(repo: git.Repo, commit: git.Commit) -> list[FileDiff]:
    """
    Build a list of FileDiff objects for the HEAD commit.
    Skips binary files, lock files, and generated output directories.
    Caps diff text per file to keep the LLM payload manageable.
    """
    diffs: list[FileDiff] = []

    # Compare against parent; for initial commit compare against empty tree
    if commit.parents:
        diffs_raw = commit.parents[0].diff(commit, create_patch=True)
    else:
        diffs_raw = commit.diff(git.NULL_TREE, create_patch=True)

    for i, d in enumerate(diffs_raw):
        if i >= MAX_FILES_IN_DIFF:
            break

        path = d.b_path or d.a_path
        if _should_skip(path):
            continue

        change_type = _change_type(d)
        diff_text = _extract_diff_text(d)
        ins, dels = _count_lines(diff_text)

        diffs.append(FileDiff(
            path=path,
            change_type=change_type,
            insertions=ins,
            deletions=dels,
            diff_text=diff_text,
        ))

    return diffs


def _should_skip(path: str) -> bool:
    ext = Path(path).suffix.lower()
    if ext in SKIP_EXTENSIONS:
        return True
    for fragment in SKIP_PATH_FRAGMENTS:
        if fragment in path:
            return True
    return False


def _change_type(d: git.Diff) -> str:
    if d.new_file:
        return "added"
    if d.deleted_file:
        return "deleted"
    if d.renamed_file:
        return "renamed"
    return "modified"


def _extract_diff_text(d: git.Diff) -> str:
    try:
        raw = d.diff
        if isinstance(raw, bytes):
            text = raw.decode("utf-8", errors="replace")
        else:
            text = raw or ""
    except Exception:
        return "[diff unavailable]"

    lines = text.splitlines()
    if len(lines) > MAX_DIFF_LINES_PER_FILE:
        kept = lines[:MAX_DIFF_LINES_PER_FILE]
        kept.append(f"... [{len(lines) - MAX_DIFF_LINES_PER_FILE} lines truncated]")
        return "\n".join(kept)
    return text


def _count_lines(diff_text: str) -> tuple[int, int]:
    insertions = sum(1 for l in diff_text.splitlines() if l.startswith("+") and not l.startswith("+++"))
    deletions  = sum(1 for l in diff_text.splitlines() if l.startswith("-") and not l.startswith("---"))
    return insertions, deletions


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()