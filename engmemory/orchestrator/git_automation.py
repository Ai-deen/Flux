"""
Git Automation - Auto-creates branches and manages local repos for tickets.

When a ticket is assigned:
1. Creates a git branch named after the ticket
2. Optionally creates a folder structure
3. Tracks the branch state
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

from .session import DevSession

log = logging.getLogger(__name__)


class GitAutomation:
    """Handles git branch creation and management for tickets."""

    def __init__(self, repo_path: str):
        """
        Args:
            repo_path: Path to the git repository root.
        """
        self.repo_path = Path(repo_path)

    def _run_git(self, *args) -> tuple[bool, str]:
        """Run a git command and return (success, output)."""
        try:
            result = subprocess.run(
                ["git"] + list(args),
                cwd=self.repo_path,
                capture_output=True,
                text=True,
            )
            return result.returncode == 0, result.stdout.strip()
        except Exception as e:
            return False, str(e)

    def branch_exists(self, branch_name: str) -> bool:
        """Check if a branch already exists (local or remote)."""
        ok, output = self._run_git("branch", "--list", branch_name)
        if ok and output:
            return True
        # Check remote
        ok, output = self._run_git("ls-remote", "--heads", "origin", branch_name)
        return ok and bool(output)

    def create_branch(self, session: DevSession) -> bool:
        """
        Create a git branch for a development session.

        Creates from the current default branch (main/master).
        """
        if not session.needs_branch:
            log.info("Ticket %s doesn't need a branch (has subtasks or is epic)", session.ticket_key)
            return False

        branch_name = session.branch_name

        # Check if already exists
        if self.branch_exists(branch_name):
            log.info("Branch '%s' already exists", branch_name)
            return True

        # Fetch latest from remote
        self._run_git("fetch", "origin")

        # Determine base branch
        base_branch = self._get_default_branch()

        # Create and checkout the branch
        ok, output = self._run_git("checkout", "-b", branch_name, f"origin/{base_branch}")
        if ok:
            log.info("Created branch '%s' from '%s'", branch_name, base_branch)
            session.status = "in_progress"
            return True
        else:
            # Try without origin/ prefix
            ok, output = self._run_git("checkout", "-b", branch_name, base_branch)
            if ok:
                log.info("Created branch '%s' from '%s'", branch_name, base_branch)
                session.status = "in_progress"
                return True
            log.error("Failed to create branch '%s': %s", branch_name, output)
            return False

    def checkout_branch(self, session: DevSession) -> bool:
        """Switch to the session's branch."""
        ok, _ = self._run_git("checkout", session.branch_name)
        return ok

    def get_current_branch(self) -> str:
        """Get the current branch name."""
        ok, output = self._run_git("rev-parse", "--abbrev-ref", "HEAD")
        return output if ok else ""

    def get_uncommitted_changes(self) -> list[str]:
        """Get list of changed files."""
        ok, output = self._run_git("status", "--porcelain")
        if ok and output:
            return [line.strip() for line in output.split("\n") if line.strip()]
        return []

    def commit_changes(self, session: DevSession, message: str) -> bool:
        """Stage all changes and commit with ticket reference."""
        # Stage all
        self._run_git("add", "-A")

        # Commit with ticket key prefix
        commit_msg = f"[{session.ticket_key}] {message}"
        ok, output = self._run_git("commit", "-m", commit_msg)
        if ok:
            log.info("Committed: %s", commit_msg)
            return True
        log.warning("Commit failed: %s", output)
        return False

    def push_branch(self, session: DevSession) -> bool:
        """Push the branch to remote."""
        ok, output = self._run_git("push", "-u", "origin", session.branch_name)
        if ok:
            log.info("Pushed branch '%s' to remote", session.branch_name)
            return True
        log.warning("Push failed: %s", output)
        return False

    def _get_default_branch(self) -> str:
        """Detect the default branch (main or master)."""
        ok, output = self._run_git("symbolic-ref", "refs/remotes/origin/HEAD")
        if ok:
            return output.split("/")[-1]

        # Fallback: check if main exists
        ok, _ = self._run_git("rev-parse", "--verify", "origin/main")
        if ok:
            return "main"
        return "master"

    def get_recent_commits(self, n: int = 10) -> list[str]:
        """Get recent commit messages (for context)."""
        ok, output = self._run_git("log", f"--oneline", f"-{n}")
        if ok:
            return output.split("\n")
        return []

    def detect_ticket_from_branch(self, branch_name: str = None) -> Optional[str]:
        """
        Extract ticket key from branch name.
        e.g. 'kan-42/fix-auth-timeout' → 'KAN-42'
        """
        import re
        if not branch_name:
            branch_name = self.get_current_branch()
        match = re.match(r"([A-Za-z]+-\d+)", branch_name)
        if match:
            return match.group(1).upper()
        return None
