"""
Flux Local Agent — Connects to the live Render dashboard and executes commands locally.

When you "Activate" a ticket on the online dashboard, this agent:
1. Creates the project folder
2. Clones/checks out the branch
3. Opens VS Code
4. Reports back to the dashboard

Usage:
    python -m engmemory.agent.local_agent
    OR
    flux-agent (after pip install -e .)
"""

import os
import sys
import time
import json
import subprocess
import logging
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package required. Run: pip install requests")
    sys.exit(1)

from ..utils.config import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [Agent] %(message)s")
log = logging.getLogger(__name__)

# Server URL — uses Render URL in production, localhost in dev
RENDER_URL = os.getenv("FLUX_DASHBOARD_URL", "https://flux-1yf6.onrender.com")
POLL_INTERVAL = 5  # seconds


def get_project_root() -> Path:
    """Get or create the project root for ticket workspaces."""
    root = Path(os.getenv("ENGMEMORY_PROJECT_ROOT", ""))
    if not root or not root.exists():
        root = Path.home() / "flux-projects"
    root.mkdir(parents=True, exist_ok=True)
    return root


def handle_activate(cmd: dict):
    """Handle 'activate' command — create project folder, open VS Code."""
    ticket_key = cmd.get("ticket_key", "UNKNOWN")
    summary = cmd.get("summary", "")
    branch = cmd.get("branch", ticket_key)

    log.info(f"Activating ticket: {ticket_key} — {summary}")

    project_root = get_project_root()
    ticket_dir = project_root / ticket_key

    # Create ticket directory
    ticket_dir.mkdir(parents=True, exist_ok=True)

    # Clone or init repo
    repo_url = os.getenv("ENGMEMORY_REPO_URL", config.repo_url if hasattr(config, 'repo_url') else "")
    if repo_url and not (ticket_dir / ".git").exists():
        log.info(f"Cloning {repo_url} into {ticket_dir}...")
        try:
            subprocess.run(
                ["git", "clone", "-b", "main", repo_url, str(ticket_dir)],
                check=True, capture_output=True, text=True
            )
        except subprocess.CalledProcessError:
            # If clone fails, just init
            subprocess.run(["git", "init"], cwd=str(ticket_dir), capture_output=True)

    # Create/checkout branch
    try:
        subprocess.run(
            ["git", "checkout", "-b", branch],
            cwd=str(ticket_dir), capture_output=True, text=True
        )
    except Exception:
        pass

    # Write ticket context file
    context_file = ticket_dir / ".flux_ticket.json"
    context_file.write_text(json.dumps({
        "ticket_key": ticket_key,
        "summary": summary,
        "branch": branch,
        "activated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }, indent=2))

    # Open VS Code
    log.info(f"Opening VS Code at {ticket_dir}")
    try:
        subprocess.Popen(["code", str(ticket_dir)], shell=True)
    except Exception as e:
        log.warning(f"Could not open VS Code: {e}")

    return f"Activated {ticket_key} at {ticket_dir}"


def handle_command(cmd: dict) -> str:
    """Route command to appropriate handler."""
    action = cmd.get("action", "")

    if action == "activate":
        return handle_activate(cmd)
    elif action == "ask":
        # Run the ask agent
        question = cmd.get("question", "")
        log.info(f"Ask Agent: {question}")
        try:
            from ..search.rag import ask_question
            answer = ask_question(question)
            return answer
        except Exception as e:
            return f"Error: {e}"
    elif action == "status":
        return "Agent is running"
    else:
        log.warning(f"Unknown action: {action}")
        return f"Unknown action: {action}"


def poll_loop():
    """Main polling loop — connects to Render and waits for commands."""
    log.info(f"╔══════════════════════════════════════════════════╗")
    log.info(f"║  Flux Local Agent                                ║")
    log.info(f"║  Connected to: {RENDER_URL:<33}║")
    log.info(f"║  Polling every {POLL_INTERVAL}s for commands              ║")
    log.info(f"║  Press Ctrl+C to stop                            ║")
    log.info(f"╚══════════════════════════════════════════════════╝")

    consecutive_errors = 0

    while True:
        try:
            resp = requests.get(f"{RENDER_URL}/api/agent/poll", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                commands = data.get("commands", [])
                consecutive_errors = 0

                for cmd in commands:
                    log.info(f"Received command: {cmd.get('action')} — {cmd.get('ticket_key', '')}")
                    result = handle_command(cmd)
                    log.info(f"Result: {result}")

                    # Acknowledge
                    try:
                        requests.post(f"{RENDER_URL}/api/agent/ack", json={
                            "queued_at": cmd.get("queued_at"),
                            "result": result,
                        }, timeout=5)
                    except Exception:
                        pass
            else:
                consecutive_errors += 1
                if consecutive_errors == 1:
                    log.warning(f"Server returned {resp.status_code}")

        except requests.exceptions.ConnectionError:
            consecutive_errors += 1
            if consecutive_errors == 1:
                log.warning("Cannot reach server — will retry...")
        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors <= 3:
                log.error(f"Poll error: {e}")

        time.sleep(POLL_INTERVAL)


def main():
    """Entry point."""
    print("\n⚡ Flux Local Agent — connecting to live dashboard...\n")
    try:
        poll_loop()
    except KeyboardInterrupt:
        log.info("Agent stopped.")


if __name__ == "__main__":
    main()
