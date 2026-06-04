"""
daemon.py — Background Agent Daemon

Runs in the background and:
1. Polls Jira for newly created/assigned tickets
2. When a new ticket is detected:
   - Creates a workspace folder
   - Runs the multi-agent system (Context → Code → Review)
   - Notifies the developer when done
3. Records all activity for the developer to review later

Usage:
    engmemory agent-daemon              # Start background daemon
    engmemory agent-daemon --once       # Single check then exit
    engmemory agent-daemon --status     # Show daemon status
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class AgentDaemon:
    """Background daemon that watches Jira and auto-triggers the agent."""

    def __init__(self, repo_path: str = ".", poll_interval: int = 10,
                 dry_run: bool = False, assignee_filter: Optional[str] = None):
        self.repo_path = os.path.abspath(repo_path)
        self.poll_interval = poll_interval
        self.dry_run = dry_run
        self.assignee_filter = assignee_filter
        self._running = False
        self._processed_file = Path(self.repo_path) / ".ai_memory" / "daemon_processed.json"
        self._processed: set = self._load_processed()

    def start(self):
        """Start the background daemon."""
        self._running = True
        log.info(f"[Daemon] Started. Watching for new tickets every {self.poll_interval}s")
        log.info(f"[Daemon] Repo: {self.repo_path}")
        if self.assignee_filter:
            log.info(f"[Daemon] Filtering tickets assigned to: {self.assignee_filter}")

        while self._running:
            try:
                self._check_for_new_tickets()
            except Exception as exc:
                log.error(f"[Daemon] Error during check: {exc}")

            time.sleep(self.poll_interval)

    def stop(self):
        """Stop the daemon."""
        self._running = False
        log.info("[Daemon] Stopped.")

    def check_once(self):
        """Single check for new tickets (non-daemon mode)."""
        self._check_for_new_tickets()

    def _check_for_new_tickets(self):
        """Poll Jira for new/updated tickets that need work."""
        try:
            import requests
            from requests.auth import HTTPBasicAuth
            from ..utils.config import config

            if not all([config.jira_domain, config.jira_email, config.jira_api_token]):
                log.warning("[Daemon] Jira not configured.")
                return

            # Search for tickets that are:
            # - In "To Do" or "In Progress" status
            # - Optionally assigned to the current user
            jql_parts = ['status in ("To Do", "In Progress", "Selected for Development")']
            if self.assignee_filter:
                jql_parts.append(f'assignee = "{self.assignee_filter}"')
            jql = " AND ".join(jql_parts) + " ORDER BY created DESC"

            url = f"https://{config.jira_domain}/rest/api/3/search/jql"
            headers = {"Accept": "application/json"}
            auth = HTTPBasicAuth(config.jira_email, config.jira_api_token)
            params = {
                "jql": jql,
                "maxResults": 10,
                "fields": "summary,status,assignee,issuetype,created"
            }

            response = requests.get(url, headers=headers, auth=auth, params=params)
            if response.status_code != 200:
                log.warning(f"[Daemon] Jira API returned {response.status_code}")
                return

            data = response.json()
            issues = data.get("issues", [])

            for issue in issues:
                key = issue.get("key")
                if key in self._processed:
                    continue

                # New ticket found!
                summary = issue.get("fields", {}).get("summary", "")
                log.info(f"[Daemon] New ticket detected: {key} — {summary}")

                self._process_ticket(key)
                self._processed.add(key)
                self._save_processed()

        except Exception as exc:
            log.error(f"[Daemon] Failed to check Jira: {exc}")

    def _process_ticket(self, issue_key: str):
        """Process a newly detected ticket with the multi-agent system."""
        log.info(f"[Daemon] Processing {issue_key}...")

        # Create a branch for this ticket
        branch_name = f"feature/{issue_key.lower()}"

        if not self.dry_run:
            try:
                subprocess.run(
                    ["git", "checkout", "-b", branch_name],
                    cwd=self.repo_path,
                    capture_output=True, text=True, timeout=10,
                )
            except Exception as exc:
                log.warning(f"[Daemon] Could not create branch: {exc}")

        # Run multi-agent system
        from .multi_agent import MultiAgentOrchestrator

        def on_complete(result):
            self._notify_developer(issue_key, result)

        orchestrator = MultiAgentOrchestrator(
            repo_path=self.repo_path,
            dry_run=self.dry_run,
            on_complete=on_complete,
        )

        result = orchestrator.run(issue_key=issue_key)

        # Log the result
        log_entry = {
            "issue_key": issue_key,
            "branch": branch_name,
            "result": result,
            "timestamp": time.time(),
        }
        self._save_run_log(log_entry)

        return result

    def _notify_developer(self, issue_key: str, result: dict):
        """Notify developer that the agent has finished work."""
        status = result.get("status", "unknown")
        summary = result.get("summary", "")
        duration = result.get("duration_seconds", 0)

        notification = (
            f"\n{'='*60}\n"
            f"🤖 [EngMemory Agent] Work complete on {issue_key}\n"
            f"   Status: {status}\n"
            f"   Duration: {duration}s\n"
            f"   Summary: {summary}\n"
            f"   \n"
            f"   Review changes: git diff\n"
            f"   Accept changes: git add -A && git commit\n"
            f"{'='*60}\n"
        )
        print(notification)

        # Also write to a notification file
        notif_file = Path(self.repo_path) / ".ai_memory" / "notifications.log"
        notif_file.parent.mkdir(parents=True, exist_ok=True)
        with open(notif_file, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M')}] {issue_key}: {status} — {summary}\n")

    def _load_processed(self) -> set:
        """Load set of already-processed ticket keys."""
        if self._processed_file.exists():
            try:
                data = json.loads(self._processed_file.read_text(encoding="utf-8"))
                return set(data)
            except Exception:
                pass
        return set()

    def _save_processed(self):
        """Save processed tickets to disk."""
        self._processed_file.parent.mkdir(parents=True, exist_ok=True)
        self._processed_file.write_text(
            json.dumps(list(self._processed)), encoding="utf-8"
        )

    def _save_run_log(self, entry: dict):
        """Save a run log entry."""
        log_file = Path(self.repo_path) / ".ai_memory" / "agent_runs.jsonl"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")


def main():
    """CLI entry point for the daemon."""
    import argparse

    parser = argparse.ArgumentParser(description="EngMemory Agent Background Daemon")
    parser.add_argument("--repo", default=".", help="Repository path")
    parser.add_argument("--interval", type=int, default=60, help="Poll interval in seconds")
    parser.add_argument("--assignee", type=str, help="Only process tickets assigned to this user")
    parser.add_argument("--dry-run", action="store_true", help="Don't make actual changes")
    parser.add_argument("--once", action="store_true", help="Single check then exit")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    daemon = AgentDaemon(
        repo_path=args.repo,
        poll_interval=args.interval,
        dry_run=args.dry_run,
        assignee_filter=args.assignee,
    )

    if args.once:
        daemon.check_once()
    else:
        print("🤖 EngMemory Agent Daemon starting...")
        print(f"   Watching Jira every {args.interval}s")
        print(f"   Repo: {os.path.abspath(args.repo)}")
        print("   Press Ctrl+C to stop.\n")
        try:
            daemon.start()
        except KeyboardInterrupt:
            daemon.stop()


if __name__ == "__main__":
    main()
