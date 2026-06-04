"""
EngMemory - Interactive Setup Wizard

Run this once after downloading. It will:
1. Ask you for your project path
2. Ask for API tokens (Jira, Slack, OpenRouter)
3. Ask for Azure credentials OR set up local-only mode
4. Configure everything automatically
5. Install git hook in your project
6. Start the server

Usage:
    python -m engmemory.setup
    OR
    engmemory-setup  (if installed via pip)
"""

import os
import sys
import subprocess
import json
from pathlib import Path


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def banner():
    print()
    print("  ============================================================")
    print("     \u26a1 Flux - From Ticket to Code, Automatically")
    print("     Setup Wizard")
    print("  ============================================================")
    print()


def ask(prompt, default=None, required=True, secret=False):
    """Ask user for input."""
    suffix = f" [{default}]" if default else ""
    suffix += ": "
    
    while True:
        value = input(f"  {prompt}{suffix}").strip()
        if not value and default:
            return default
        if not value and required:
            print("    (required)")
            continue
        return value


def ask_yes_no(prompt, default=True):
    """Ask yes/no question."""
    suffix = " [Y/n]" if default else " [y/N]"
    value = input(f"  {prompt}{suffix}: ").strip().lower()
    if not value:
        return default
    return value in ("y", "yes")


def test_jira(domain, email, token):
    """Test Jira connection."""
    try:
        import requests
        from requests.auth import HTTPBasicAuth
        resp = requests.get(
            f"https://{domain}/rest/api/3/myself",
            auth=HTTPBasicAuth(email, token),
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


def test_slack(token):
    """Test Slack connection."""
    try:
        import requests
        resp = requests.post(
            "https://slack.com/api/auth.test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        data = resp.json()
        return data.get("ok", False)
    except Exception:
        return False


def test_openrouter(key):
    """Test OpenRouter connection."""
    try:
        import requests
        resp = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


def main():
    clear()
    banner()

    print("  This wizard will set up Flux for your project.")
    print("  It takes about 2 minutes. You'll need:")
    print("    - Your project's local path")
    print("    - Jira API token (free: https://id.atlassian.com/manage-profile/security/api-tokens)")
    print("    - Slack Bot token (free: https://api.slack.com/apps)")
    print("    - OpenRouter API key (free: https://openrouter.ai/)")
    print("    - Azure account (optional - can run without it)")
    print()
    input("  Press Enter to begin...")

    config = {}

    # ─── Step 1: Project Path ─────────────────────────────────────────────
    clear()
    banner()
    print("  STEP 1/5: Project Path")
    print("  " + "-" * 50)
    print()
    print("  Which project should EngMemory manage?")
    print("  (This is where your code is, where commits happen)")
    print()
    
    default_path = os.getcwd()
    config["repo_path"] = ask("Project path", default=default_path)
    
    # Verify it's a git repo
    git_dir = os.path.join(config["repo_path"], ".git")
    if not os.path.exists(git_dir):
        print(f"\n    WARNING: {config['repo_path']} is not a git repository.")
        if ask_yes_no("    Initialize git here?"):
            subprocess.run(["git", "init"], cwd=config["repo_path"])
            print("    Done.")
    
    print(f"\n  [OK] Project: {config['repo_path']}")

    # ─── Step 2: Jira ─────────────────────────────────────────────────────
    clear()
    banner()
    print("  STEP 2/5: Jira Integration")
    print("  " + "-" * 50)
    print()
    print("  EngMemory auto-detects Jira tickets from commits and")
    print("  creates Slack channels + git branches for each ticket.")
    print()
    print("  Get your token: https://id.atlassian.com/manage-profile/security/api-tokens")
    print()

    config["jira_domain"] = ask("Jira domain (e.g. your-team.atlassian.net)")
    config["jira_email"] = ask("Jira email")
    config["jira_api_token"] = ask("Jira API token")

    print("\n  Testing Jira connection...")
    if test_jira(config["jira_domain"], config["jira_email"], config["jira_api_token"]):
        print("  [OK] Jira connected!")
    else:
        print("  [!] Could not connect to Jira. Check your credentials.")
        if not ask_yes_no("  Continue anyway?"):
            sys.exit(1)

    # ─── Step 3: Slack ────────────────────────────────────────────────────
    clear()
    banner()
    print("  STEP 3/5: Slack Integration")
    print("  " + "-" * 50)
    print()
    print("  EngMemory creates discussion channels for tickets")
    print("  and captures technical conversations for AI context.")
    print()
    print("  Create a Slack app: https://api.slack.com/apps")
    print("  Required scopes: channels:manage, channels:read,")
    print("    channels:history, chat:write, users:read, users:read.email")
    print()

    config["slack_bot_token"] = ask("Slack Bot Token (xoxb-...)")
    config["slack_signing_secret"] = ask("Slack Signing Secret")

    print("\n  Testing Slack connection...")
    if test_slack(config["slack_bot_token"]):
        print("  [OK] Slack connected!")
    else:
        print("  [!] Could not connect to Slack. Check your token.")
        if not ask_yes_no("  Continue anyway?"):
            sys.exit(1)

    # ─── Step 4: LLM ─────────────────────────────────────────────────────
    clear()
    banner()
    print("  STEP 4/5: AI / LLM Provider")
    print("  " + "-" * 50)
    print()
    print("  EngMemory uses AI to analyze commits, generate summaries,")
    print("  and build intelligent context for the coding agent.")
    print()
    print("  OpenRouter is recommended (free tier available):")
    print("    https://openrouter.ai/")
    print()

    config["openrouter_api_key"] = ask("OpenRouter API Key (sk-or-...)")
    config["openrouter_model"] = ask("Model", default="google/gemini-2.0-flash-001")

    print("\n  Testing LLM connection...")
    if test_openrouter(config["openrouter_api_key"]):
        print("  [OK] LLM connected!")
    else:
        print("  [!] Could not verify. May still work.")

    # ─── Step 5: Azure (Optional) ────────────────────────────────────────
    clear()
    banner()
    print("  STEP 5/5: Azure Storage (Optional)")
    print("  " + "-" * 50)
    print()
    print("  Azure Blob Storage persists all captured context.")
    print("  Azure AI Search enables semantic search over commits.")
    print()
    print("  Without Azure: EngMemory works with LOCAL storage only.")
    print("  All data saved to ~/.engmemory/ on your machine.")
    print()

    use_azure = ask_yes_no("  Do you have an Azure account?", default=False)

    if use_azure:
        print()
        print("  Option A: Provide existing connection string")
        print("  Option B: Let us create resources (requires: az login)")
        print()
        
        has_existing = ask_yes_no("  Do you already have a Storage Account?", default=False)
        
        if has_existing:
            config["azure_storage_connection_string"] = ask("Azure Storage Connection String")
            config["azure_search_endpoint"] = ask("Azure Search Endpoint (or skip)", required=False)
            config["azure_search_key"] = ask("Azure Search Admin Key (or skip)", required=False)
        else:
            print("\n  We'll create Azure resources for you (FREE tier).")
            print("  Make sure you've run: az login")
            print()
            config["_setup_azure"] = True
    else:
        print("\n  [OK] Running in LOCAL mode (no Azure).")
        print("  Data will be stored at: ~/.engmemory/")
        config["_local_only"] = True

    # ─── Write Configuration ──────────────────────────────────────────────
    clear()
    banner()
    print("  Writing configuration...")
    print()

    # Write .env file
    engmemory_root = Path(__file__).parent.parent
    env_path = engmemory_root / ".env"
    
    env_lines = [
        "# EngMemory Configuration (auto-generated by setup wizard)",
        f"ENGMEMORY_REPO_PATH={config['repo_path']}",
        "",
        "# Jira",
        f"JIRA_DOMAIN={config['jira_domain']}",
        f"JIRA_EMAIL={config['jira_email']}",
        f"JIRA_API_TOKEN={config['jira_api_token']}",
        "",
        "# Slack",
        f"SLACK_BOT_TOKEN={config['slack_bot_token']}",
        f"SLACK_SIGNING_SECRET={config['slack_signing_secret']}",
        "",
        "# LLM",
        f"OPENROUTER_API_KEY={config['openrouter_api_key']}",
        f"OPENROUTER_MODEL={config['openrouter_model']}",
    ]

    if config.get("azure_storage_connection_string"):
        env_lines += [
            "",
            "# Azure",
            f"AZURE_STORAGE_CONNECTION_STRING={config['azure_storage_connection_string']}",
            "AZURE_STORAGE_CONTAINER=engmemory",
        ]
        if config.get("azure_search_endpoint"):
            env_lines.append(f"AZURE_SEARCH_ENDPOINT={config['azure_search_endpoint']}")
            env_lines.append(f"AZURE_SEARCH_KEY={config.get('azure_search_key', '')}")
            env_lines.append("AZURE_SEARCH_INDEX=engmemory-commits")

    with open(env_path, "w") as f:
        f.write("\n".join(env_lines) + "\n")
    print(f"  [OK] Configuration saved to: {env_path}")

    # Install git hook in the target project
    print("\n  Installing git hook in your project...")
    hooks_dir = Path(config["repo_path"]) / ".git" / "hooks"
    if hooks_dir.exists():
        hook_path = hooks_dir / "post-commit"
        hook_content = "#!/bin/sh\npython -m engmemory.core.hook \"$@\" 2>/dev/null || true\n"
        with open(hook_path, "w", newline="\n") as f:
            f.write(hook_content)
        if os.name != "nt":
            os.chmod(hook_path, 0o755)
        print(f"  [OK] Git hook installed")
    else:
        print(f"  [!] Could not install hook (not a git repo)")

    # Run Azure setup if needed
    if config.get("_setup_azure"):
        print("\n  Provisioning Azure resources...")
        azure_script = engmemory_root / "scripts" / "setup_azure.py"
        if azure_script.exists():
            subprocess.run([sys.executable, str(azure_script)], env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        else:
            print("  [!] Azure setup script not found")

    # Final instructions
    print()
    print("  " + "=" * 50)
    print("  SETUP COMPLETE!")
    print("  " + "=" * 50)
    print()
    print("  Start EngMemory:")
    print(f"    cd {engmemory_root}")
    print("    python -m uvicorn engmemory.api.server:app --port 5051 --reload")
    print()
    print("  Start Dashboard:")
    print(f"    cd {engmemory_root / 'dashboard'}")
    print("    npm run dev")
    print()
    print("  Then open: http://localhost:5174")
    print()
    
    if ask_yes_no("  Start the server now?"):
        os.environ["PYTHONIOENCODING"] = "utf-8"
        subprocess.run(
            [sys.executable, "-m", "uvicorn", "engmemory.api.server:app", "--port", "5051", "--reload"],
            cwd=str(engmemory_root),
        )


if __name__ == "__main__":
    main()
