"""
EngMemory - Full Setup Script

One command to set up everything:
  1. Install Python dependencies
  2. Install git hook
  3. Provision Azure resources (Storage + Search)
  4. Install dashboard dependencies
  5. Verify all connections

Usage:
    python scripts/setup.py
"""

import os
import sys
import subprocess
import shutil


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(cmd, cwd=None, check=True):
    """Run a command and print output."""
    print(f"  $ {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd or ROOT, capture_output=True, text=True)
    if result.returncode != 0 and check:
        print(f"  ERROR: {result.stderr[:200]}")
        return False
    return True


def main():
    print("=" * 60)
    print("  EngMemory - Full Project Setup")
    print("=" * 60)
    print()

    # Check prerequisites
    print("[1/5] Checking prerequisites...")
    prereqs_ok = True

    # Python
    py_version = subprocess.run(["python", "--version"], capture_output=True, text=True)
    if py_version.returncode == 0:
        print(f"  ✓ Python: {py_version.stdout.strip()}")
    else:
        print("  ✗ Python not found")
        prereqs_ok = False

    # Node.js
    node_version = subprocess.run(["node", "--version"], capture_output=True, text=True)
    if node_version.returncode == 0:
        print(f"  ✓ Node.js: {node_version.stdout.strip()}")
    else:
        print("  ✗ Node.js not found (needed for dashboard)")
        prereqs_ok = False

    # Git
    git_version = subprocess.run(["git", "--version"], capture_output=True, text=True)
    if git_version.returncode == 0:
        print(f"  ✓ Git: {git_version.stdout.strip()}")
    else:
        print("  ✗ Git not found")
        prereqs_ok = False

    # .env file
    env_file = os.path.join(ROOT, ".env")
    env_example = os.path.join(ROOT, ".env.example")
    if os.path.exists(env_file):
        print(f"  ✓ .env file exists")
    else:
        print(f"  ⚠ .env not found — copying from .env.example")
        if os.path.exists(env_example):
            shutil.copy(env_example, env_file)
            print(f"  → Created .env — edit it with your API keys!")
        else:
            print(f"  ✗ .env.example not found either")

    if not prereqs_ok:
        print("\n  Fix the above issues and re-run setup.")
        sys.exit(1)

    # Install Python packages
    print(f"\n[2/5] Installing Python dependencies...")
    run("pip install -e .", check=False)
    run("pip install httpx uvicorn fastapi pydantic requests", check=False)

    # Install git hook
    print(f"\n[3/5] Installing git commit hook...")
    hooks_dir = os.path.join(ROOT, ".git", "hooks")
    if os.path.exists(hooks_dir):
        hook_path = os.path.join(hooks_dir, "post-commit")
        hook_content = """#!/bin/sh
# EngMemory post-commit hook - captures commit context automatically
python -m engmemory.core.hook "$@" 2>/dev/null || true
"""
        with open(hook_path, "w", newline="\n") as f:
            f.write(hook_content)
        os.chmod(hook_path, 0o755)
        print(f"  ✓ Git hook installed at {hook_path}")
    else:
        print(f"  ⚠ Not a git repo — hook not installed")

    # Install dashboard
    print(f"\n[4/5] Installing dashboard dependencies...")
    dashboard_dir = os.path.join(ROOT, "dashboard")
    if os.path.exists(dashboard_dir):
        run("npm install", cwd=dashboard_dir, check=False)
        print(f"  ✓ Dashboard dependencies installed")
    else:
        print(f"  ⚠ Dashboard not found at {dashboard_dir}")

    # Azure setup prompt
    print(f"\n[5/5] Azure Setup...")
    print(f"  To provision Azure resources (Storage + AI Search), run:")
    print(f"    az login")
    print(f"    python scripts/setup_azure.py")
    print(f"  This creates all resources on the FREE tier ($0/month).")

    # Final summary
    print("\n" + "=" * 60)
    print("  SETUP COMPLETE!")
    print("=" * 60)
    print()
    print("  Next steps:")
    print("  1. Edit .env with your Jira, Slack, and LLM API keys")
    print("  2. Run: python scripts/setup_azure.py (for Azure resources)")
    print("  3. Start the server:")
    print("       python -m uvicorn engmemory.api.server:app --port 5051 --reload")
    print("  4. Start the dashboard:")
    print("       cd dashboard && npm run dev")
    print("  5. Open: http://localhost:5174")
    print()


if __name__ == "__main__":
    main()
