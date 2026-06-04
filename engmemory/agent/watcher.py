"""
watcher.py — Watches for triggers that start the agent.

Triggers:
1. New branch created (with ticket ID in name) → auto-solve
2. Jira ticket assigned → fetch and plan
3. Git hook (post-checkout) → detect new feature branch
4. Manual CLI invocation

The watcher can run as:
- A background daemon (watches for git events)
- A git hook (post-checkout, post-merge)
- A one-shot CLI command
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)


class Watcher:
    """Watches for events that trigger the agent."""

    def __init__(self, repo_path: str = ".", on_trigger: Optional[Callable] = None):
        self.repo_path = os.path.abspath(repo_path)
        self.on_trigger = on_trigger
        self._last_branch: Optional[str] = None
        self._running = False

    def install_hooks(self) -> str:
        """Install git hooks that trigger the agent."""
        hooks_dir = Path(self.repo_path) / ".git" / "hooks"
        if not hooks_dir.exists():
            return "Not a git repository (no .git/hooks directory)"

        # Post-checkout hook — fires when branch changes
        post_checkout = hooks_dir / "post-checkout"
        hook_content = '''#!/bin/sh
# EngMemory Agent — auto-triggered on branch checkout
# Detects feature branches and starts the agent

PREV_HEAD=$1
NEW_HEAD=$2
BRANCH_FLAG=$3

# Only trigger on branch checkout (flag=1), not file checkout
if [ "$BRANCH_FLAG" = "1" ]; then
    BRANCH=$(git rev-parse --abbrev-ref HEAD)
    # Check if branch looks like a feature branch with a ticket
    if echo "$BRANCH" | grep -qE '[A-Z]+-[0-9]+'; then
        echo "[EngMemory Agent] Detected feature branch: $BRANCH"
        python -m engmemory.agent.watcher --trigger branch --branch "$BRANCH" --repo "$(pwd)" &
    fi
fi
'''
        post_checkout.write_text(hook_content, encoding="utf-8")
        # Make executable (no-op on Windows but needed for Unix)
        try:
            os.chmod(str(post_checkout), 0o755)
        except Exception:
            pass

        return f"Installed post-checkout hook at {post_checkout}"

    def check_current_branch(self) -> Optional[dict]:
        """Check if current branch is a feature branch that should trigger agent."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.repo_path,
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return None

            branch = result.stdout.strip()

            # Check if it has a Jira ticket pattern
            match = re.search(r'([A-Z][A-Z0-9]+-\d+)', branch.upper())
            if match:
                return {
                    "trigger": "branch",
                    "branch_name": branch,
                    "issue_key": match.group(1),
                }

        except Exception as exc:
            log.warning(f"Could not check branch: {exc}")

        return None

    def watch(self, poll_interval: int = 5, timeout: int = 0):
        """
        Poll for branch changes. Triggers agent when a new feature branch is detected.

        Args:
            poll_interval: Seconds between checks
            timeout: Stop after this many seconds (0 = forever)
        """
        self._running = True
        self._last_branch = self._get_current_branch()
        start_time = time.time()

        log.info(f"[Watcher] Watching {self.repo_path} (current: {self._last_branch})")

        while self._running:
            if timeout and (time.time() - start_time) > timeout:
                log.info("[Watcher] Timeout reached, stopping.")
                break

            current = self._get_current_branch()
            if current and current != self._last_branch:
                log.info(f"[Watcher] Branch changed: {self._last_branch} → {current}")
                self._last_branch = current

                # Check if it's a feature branch
                trigger_data = self.check_current_branch()
                if trigger_data and self.on_trigger:
                    self.on_trigger(trigger_data)

            time.sleep(poll_interval)

    def stop(self):
        """Stop the watcher."""
        self._running = False

    def _get_current_branch(self) -> Optional[str]:
        """Get current git branch name."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.repo_path,
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except Exception:
            return None


# ---------------------------------------------------------------------------
# CLI entry point for hook-triggered execution
# ---------------------------------------------------------------------------

def main():
    """Entry point when triggered by git hook or CLI."""
    import argparse

    parser = argparse.ArgumentParser(description="EngMemory Agent Watcher")
    parser.add_argument("--trigger", choices=["branch", "jira", "watch"], default="branch")
    parser.add_argument("--branch", help="Branch name")
    parser.add_argument("--issue", help="Jira issue key")
    parser.add_argument("--repo", default=".", help="Repository path")
    parser.add_argument("--dry-run", action="store_true", help="Don't make actual changes")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.trigger == "watch":
        # Daemon mode — watch for branch changes
        from .engine import Agent

        def on_trigger(data):
            agent = Agent(repo_path=args.repo, dry_run=args.dry_run)
            result = agent.run(**data)
            log.info(f"Agent run: {result.state.value}")

        watcher = Watcher(repo_path=args.repo, on_trigger=on_trigger)
        try:
            watcher.watch()
        except KeyboardInterrupt:
            watcher.stop()

    elif args.trigger == "branch":
        from .engine import Agent
        agent = Agent(repo_path=args.repo, dry_run=args.dry_run)
        result = agent.run(
            trigger="branch",
            branch_name=args.branch or "",
        )
        print(f"\nAgent result: {result.state.value}")
        if result.results:
            for r in result.results:
                status = "✓" if r.success else "✗"
                print(f"  {status} Step {r.step_id}: {r.description}")

    elif args.trigger == "jira":
        from .engine import Agent
        if not args.issue:
            print("Error: --issue required for jira trigger")
            return
        agent = Agent(repo_path=args.repo, dry_run=args.dry_run)
        result = agent.run(trigger="jira", issue_key=args.issue)
        print(f"\nAgent result: {result.state.value}")


if __name__ == "__main__":
    main()
