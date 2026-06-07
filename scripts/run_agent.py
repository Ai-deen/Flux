"""Standalone agent launcher - zero dependency on pip install.
This is a self-contained copy of the local agent logic that works
when launched via Start-Process from install.ps1 / START.bat.
"""
import os
import sys
import time
import json
import subprocess
import logging
from pathlib import Path

# Load .env file FIRST
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_script_dir)
env_file = os.path.join(_project_root, ".env")
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package required. Run: pip install requests")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [Agent] %(message)s")
log = logging.getLogger("flux-agent")

RENDER_URL = os.getenv("FLUX_DASHBOARD_URL", "https://flux-1yf6.onrender.com")
POLL_INTERVAL = 5


def get_project_root():
    pr = os.getenv("ENGMEMORY_PROJECT_ROOT", "")
    if pr and os.path.isdir(pr):
        return Path(pr)
    root = Path(_project_root) / "project"
    root.mkdir(parents=True, exist_ok=True)
    return root


def handle_activate(cmd):
    ticket_key = cmd.get("ticket_key", "UNKNOWN")
    summary = cmd.get("summary", "")
    branch = cmd.get("branch", ticket_key)
    log.info(f"Activating ticket: {ticket_key} - {summary}")

    project_root = get_project_root()
    ticket_dir = project_root / ticket_key
    ticket_dir.mkdir(parents=True, exist_ok=True)

    # Clone repo
    repo_url = os.getenv("ENGMEMORY_REPO_URL", "")
    if repo_url and not (ticket_dir / ".git").exists():
        log.info(f"Cloning {repo_url} into {ticket_dir}...")
        try:
            subprocess.run(["git", "clone", "-b", "main", repo_url, str(ticket_dir)],
                           check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError:
            subprocess.run(["git", "init"], cwd=str(ticket_dir), capture_output=True)

    # Create branch
    try:
        subprocess.run(["git", "checkout", "-b", branch],
                       cwd=str(ticket_dir), capture_output=True, text=True)
    except Exception:
        pass

    # Write ticket json
    (ticket_dir / ".flux_ticket.json").write_text(json.dumps({
        "ticket_key": ticket_key, "summary": summary,
        "branch": branch, "activated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }, indent=2))

    # Fetch AI context
    log.info(f"Fetching AI context for {ticket_key}...")
    try:
        resp = requests.get(f"{RENDER_URL}/api/pipeline/{ticket_key}/developer-prompt", timeout=15)
        if resp.status_code == 200:
            prompt = resp.json().get("prompt", "")
            if prompt:
                (ticket_dir / ".ticket-context.md").write_text(prompt, encoding="utf-8")
                log.info(f"Wrote .ticket-context.md ({len(prompt)} chars)")
        else:
            log.warning(f"Could not fetch context (status {resp.status_code})")
    except Exception as e:
        log.warning(f"Failed to fetch AI context: {e}")

    # Open VS Code
    log.info(f"Opening VS Code at {ticket_dir}")
    try:
        subprocess.Popen(["code", str(ticket_dir)], shell=True)
    except Exception as e:
        log.warning(f"Could not open VS Code: {e}")

    return f"Activated {ticket_key} at {ticket_dir}"


def handle_command(cmd):
    action = cmd.get("action", "")
    if action == "activate":
        return handle_activate(cmd)
    elif action == "status":
        return "Agent is running"
    else:
        return f"Unknown action: {action}"


def poll_loop():
    log.info("==================================================")
    log.info("  Flux Local Agent")
    log.info(f"  Connected to: {RENDER_URL}")
    log.info(f"  Polling every {POLL_INTERVAL}s for commands")
    log.info("  Press Ctrl+C to stop")
    log.info("==================================================")

    consecutive_errors = 0
    while True:
        try:
            resp = requests.get(f"{RENDER_URL}/api/agent/poll", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                commands = data.get("commands", [])
                consecutive_errors = 0
                for cmd in commands:
                    log.info(f"Received command: {cmd.get('action')} - {cmd.get('ticket_key', '')}")
                    result = handle_command(cmd)
                    log.info(f"Result: {result}")
                    try:
                        requests.post(f"{RENDER_URL}/api/agent/ack",
                                      json={"queued_at": cmd.get("queued_at"), "result": result}, timeout=5)
                    except Exception:
                        pass
            else:
                consecutive_errors += 1
                if consecutive_errors == 1:
                    log.warning(f"Server returned {resp.status_code}")
        except requests.exceptions.ConnectionError:
            consecutive_errors += 1
            if consecutive_errors == 1:
                log.warning("Cannot reach server - will retry...")
        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors <= 3:
                log.error(f"Poll error: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    print("\n[Flux] Local Agent - connecting to live dashboard...\n")
    try:
        poll_loop()
    except KeyboardInterrupt:
        log.info("Agent stopped.")
