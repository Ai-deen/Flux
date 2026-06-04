"""
context_builder.py — Gathers context from all available sources.

Sources:
- Jira tickets (description, comments, acceptance criteria)
- Commit history (related commits from Azure AI Search)
- AI session context (Copilot chat summaries)
- Repository structure (file tree, key files)
- Discussions (from Jira comments, PR comments)

Produces a comprehensive context document that can be used to:
1. Generate a plan for solving a ticket
2. Create an informed prompt for GitHub Copilot
3. Understand the full picture before making changes
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class ContextBuilder:
    """Builds comprehensive context from all available sources."""

    def __init__(self, repo_path: str = "."):
        self.repo_path = os.path.abspath(repo_path)

    def extract_ticket_from_branch(self, branch_name: str) -> Optional[str]:
        """Extract Jira ticket key from branch name.

        Handles patterns like:
            feature/ENG-456-implement-auth
            bugfix/PROJ-123
            ENG-789-quick-fix
        """
        match = re.search(r'([A-Z][A-Z0-9]+-\d+)', branch_name.upper())
        if match:
            return match.group(1)
        return None

    def get_jira_context(self, issue_key: str) -> Optional[str]:
        """Fetch full Jira ticket context including parent, subtasks, links, and comments.
        
        Recursively traverses:
        - UP: parent epic/story (to get full requirements)
        - DOWN: subtasks (to see what's been done)
        - SIDEWAYS: linked tickets (related work, blockers)
        - All comments across the hierarchy
        """
        try:
            from ..utils.jira import get_issue_full_context
            data = get_issue_full_context(issue_key, max_depth=2)
            return data["context_summary"]

        except Exception as exc:
            # Fallback to simple fetch if recursive fails
            log.warning(f"Recursive Jira fetch failed for {issue_key}: {exc}")
            try:
                from ..utils.jira import get_issue_details
                details = get_issue_details(issue_key)
                parts = [
                    f"## Jira Ticket: {details['key']}",
                    f"**Summary:** {details['summary']}",
                    f"**Type:** {details['issue_type']} | **Priority:** {details['priority']} | **Status:** {details['status']}",
                    f"**Assignee:** {details['assignee']}",
                    "",
                    "### Description",
                    details.get('description', 'No description'),
                ]
                if details.get('comments'):
                    parts.append("\n### Comments")
                    for comment in details['comments']:
                        parts.append(f"**{comment['author']}**: {comment['text']}")
                return "\n".join(parts)
            except Exception as exc2:
                log.warning(f"Simple Jira fetch also failed: {exc2}")
                return None

    def get_commit_context(self, search_query: str, top_k: int = 5) -> Optional[str]:
        """Search related commits using Azure AI Search."""
        try:
            from ..search.azure_search import search_commits
            commits = search_commits(search_query, top_k=top_k)

            if not commits:
                return None

            parts = ["## Related Commits"]
            for commit in commits:
                ticket = f" [{commit.get('ticket_id')}]" if commit.get('ticket_id') else ""
                parts.append(
                    f"\n**{commit.get('sha', '?')[:8]}**{ticket} — {commit.get('commit_message', '')}\n"
                    f"  Files: {commit.get('file_name', 'unknown')}\n"
                    f"  Analysis: {commit.get('analysis', '')[:200]}"
                )

            return "\n".join(parts)

        except Exception as exc:
            log.warning(f"Could not fetch commit context: {exc}")
            return None

    def get_ai_session_context(self) -> Optional[str]:
        """Get recent AI/Copilot session context."""
        try:
            from ..ai_context import create_ai_context_summary
            result = create_ai_context_summary(self.repo_path)

            if result and result.get("summary"):
                return f"## Recent AI Session Context\n\n{result['summary']}"
            return None

        except Exception as exc:
            log.warning(f"Could not fetch AI session context: {exc}")
            return None

    def get_repo_structure(self, max_depth: int = 3) -> Optional[str]:
        """Get a summary of the repository structure."""
        try:
            repo_root = Path(self.repo_path)
            if not repo_root.exists():
                return None

            parts = ["## Repository Structure"]
            ignore_dirs = {'.git', 'node_modules', '__pycache__', '.venv', 'venv',
                         'dist', 'build', '.ai_memory', '.egg-info', 'egg-info'}
            ignore_exts = {'.pyc', '.pyo', '.egg', '.whl'}

            def _walk(path: Path, depth: int = 0, prefix: str = ""):
                if depth > max_depth:
                    return
                try:
                    entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
                except PermissionError:
                    return

                for entry in entries:
                    if entry.name.startswith('.') and entry.name not in ('.env.example',):
                        continue
                    if entry.name in ignore_dirs:
                        continue
                    if entry.suffix in ignore_exts:
                        continue

                    if entry.is_dir():
                        parts.append(f"{prefix}{entry.name}/")
                        _walk(entry, depth + 1, prefix + "  ")
                    else:
                        parts.append(f"{prefix}{entry.name}")

            _walk(repo_root)
            return "\n".join(parts[:100])  # Cap at 100 lines

        except Exception as exc:
            log.warning(f"Could not get repo structure: {exc}")
            return None

    def build_full_context(self, issue_key: Optional[str] = None,
                           branch_name: Optional[str] = None,
                           search_query: Optional[str] = None) -> str:
        """Build complete context from all sources.

        This is the main method — produces a comprehensive document
        that can be fed to any LLM or GitHub Copilot.
        """
        # Try to determine issue key from branch if not provided
        if not issue_key and branch_name:
            issue_key = self.extract_ticket_from_branch(branch_name)

        parts = []

        # Jira context (primary source of truth for requirements)
        if issue_key:
            jira = self.get_jira_context(issue_key)
            if jira:
                parts.append(jira)

        # Related commits
        query = search_query or issue_key or ""
        if query:
            commits = self.get_commit_context(query)
            if commits:
                parts.append(commits)

        # AI session context
        ai = self.get_ai_session_context()
        if ai:
            parts.append(ai)

        # Repo structure
        structure = self.get_repo_structure()
        if structure:
            parts.append(structure)

        if not parts:
            return "No context could be gathered. Proceeding with minimal information."

        return "\n\n---\n\n".join(parts)

    def reverse_lookup(self, query: str) -> Optional[str]:
        """Reverse lookup: given a code change or question, trace back to the ticket.

        Flow: search query → find matching commits → extract ticket IDs → 
              fetch full ticket context (with parent/links).

        This answers: "which ticket caused this change?" or 
                     "what was the context behind this code?"
        """
        try:
            from ..search.azure_search import search_commits
            import re

            # Search commits for the query
            commits = search_commits(query, top_k=5)
            if not commits:
                return None

            parts = ["## Reverse Lookup Results"]
            seen_tickets = set()

            for commit in commits:
                ticket_id = commit.get("ticket_id", "")
                # Also try to extract from commit message
                if not ticket_id:
                    msg = commit.get("commit_message", "")
                    match = re.search(r'([A-Z][A-Z0-9]+-\d+)', msg)
                    if match:
                        ticket_id = match.group(1)

                sha = commit.get("sha", "?")[:8]
                msg = commit.get("commit_message", "")
                parts.append(f"\n**Commit {sha}**: {msg}")

                if ticket_id and ticket_id not in seen_tickets:
                    seen_tickets.add(ticket_id)
                    # Fetch full ticket context (recursive)
                    try:
                        from ..utils.jira import get_issue_full_context
                        ticket_data = get_issue_full_context(ticket_id, max_depth=2)
                        parts.append(f"\n{ticket_data['context_summary']}")
                    except Exception:
                        parts.append(f"  → Ticket: {ticket_id} (could not fetch details)")

            if not seen_tickets:
                parts.append("\nNo tickets found associated with these commits.")

            return "\n".join(parts)

        except Exception as exc:
            log.warning(f"Reverse lookup failed: {exc}")
            return None
