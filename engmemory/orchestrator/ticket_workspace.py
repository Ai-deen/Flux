r"""
Ticket Workspace Manager

When a subtask is activated, this:
1. Creates {PROJECT_ROOT}\{TICKET_KEY}\
2. Clones the repo (or pulls latest master)
3. Creates and checks out the ticket branch
4. Writes a .ticket-context.md with the full AI prompt
5. Returns the workspace path for the agent to work in
"""

import os
import subprocess
import json
from pathlib import Path

import httpx

from ..utils.config import config

ENGMEMORY_API = "http://localhost:5051"


def _get_project_root() -> Path:
    """Get the project root directory dynamically based on current config."""
    # Priority: explicit env var > sibling of repo path > home fallback
    explicit = os.getenv("ENGMEMORY_PROJECT_ROOT")
    if explicit:
        return Path(explicit)
    if config.repo_path:
        return Path(config.repo_path).parent / "project"
    return Path.home() / "engmemory-projects"


def _get_repo_url() -> str:
    """Get the repo URL dynamically based on current config."""
    return os.getenv("ENGMEMORY_REPO_URL") or config.repo_url or "https://github.com/Ai-deen/AI-DOCS.git"


def setup_ticket_workspace(ticket_key: str, session_data: dict = None, context_data: dict = None) -> dict:
    """
    Set up a full workspace for a ticket.
    Can accept session/context data directly (when called from server) or fetch from API.
    Returns workspace info for the agent.
    """
    project_root = _get_project_root()
    repo_url = _get_repo_url()

    workspace_dir = project_root / ticket_key
    workspace_dir.mkdir(parents=True, exist_ok=True)

    # 1. Clone or pull
    if (workspace_dir / ".git").exists():
        # Already cloned — fetch latest
        _run_git(workspace_dir, "fetch", "origin")
        _run_git(workspace_dir, "checkout", "main")
        _run_git(workspace_dir, "pull", "origin", "main")
    else:
        # Fresh clone
        subprocess.run(
            ["git", "clone", repo_url, str(workspace_dir)],
            check=True, capture_output=True, text=True
        )

    # 2. Get session/context info
    if context_data:
        context = context_data
    else:
        r = httpx.get(f"{ENGMEMORY_API}/api/sessions/{ticket_key}/context", timeout=10)
        context = r.json()

    branch_name = ""
    if session_data:
        branch_name = session_data.get("branch", "")
    else:
        r2 = httpx.get(f"{ENGMEMORY_API}/api/sessions/{ticket_key}", timeout=10)
        if r2.status_code == 200:
            session_info = r2.json()
            branch_name = session_info.get("branch", "")

    # 3. Create and checkout branch
    if branch_name:
        # Check if branch exists
        result = subprocess.run(
            ["git", "branch", "--list", branch_name],
            capture_output=True, text=True, cwd=workspace_dir
        )
        if branch_name in result.stdout:
            _run_git(workspace_dir, "checkout", branch_name)
        else:
            _run_git(workspace_dir, "checkout", "-b", branch_name)

    # 4. Write context file for the agent
    prompt = context.get("prompt") or ""
    context_file = workspace_dir / ".ticket-context.md"
    context_file.write_text(prompt, encoding="utf-8")

    # 5. Write full context as JSON (for programmatic access)
    context_json = workspace_dir / ".ticket-context.json"
    context_json.write_text(json.dumps(context, indent=2), encoding="utf-8")

    # 6. Create .vscode/settings.json for workspace config
    vscode_dir = workspace_dir / ".vscode"
    vscode_dir.mkdir(exist_ok=True)

    settings = {
        "chat.agent.enabled": True,
        "github.copilot.chat.agent.autoTrigger": True,
    }
    (vscode_dir / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")

    # 6b. Create extensions.json to recommend engmemory extension
    extensions_json = {
        "recommendations": ["engmemory-team.engmemory"]
    }
    (vscode_dir / "extensions.json").write_text(json.dumps(extensions_json, indent=2), encoding="utf-8")

    # 7. Create .github/agents for this workspace
    agents_dir = workspace_dir / ".github" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    # Copy agent definitions
    _create_workspace_agents(agents_dir, ticket_key)

    # 8. Create helper script for querying engmemory
    _create_ask_helper(workspace_dir, ticket_key)

    return {
        "workspace": str(workspace_dir),
        "branch": branch_name,
        "ticket_key": ticket_key,
        "prompt_length": len(prompt),
        "context_file": str(context_file),
    }


def _create_ask_helper(workspace_dir: Path, ticket_key: str):
    """Create a helper script agents can use to query engmemory."""
    helper = workspace_dir / ".engmemory-ask.py"
    helper.write_text(f'''"""Query engmemory for context. Usage: python .engmemory-ask.py <question>"""
import sys, httpx, json

API = "http://localhost:5051"
TICKET = "{ticket_key}"

def ask(question: str):
    """Get additional context from engmemory."""
    r = httpx.get(f"{{API}}/api/sessions/{{TICKET}}/context", timeout=10)
    ctx = r.json()
    print("=== TICKET CONTEXT ===")
    print(f"Ticket: {{TICKET}}")
    print(f"Prompt length: {{len(ctx.get('prompt') or '')}}")
    print()
    if ctx.get("context"):
        c = ctx["context"]
        if c.get("jira_comments"):
            print("=== JIRA COMMENTS ===")
            for comment in c["jira_comments"]:
                print(f"  - {{comment}}")
        if c.get("slack_messages"):
            print("=== SLACK MESSAGES ===")
            for msg in c["slack_messages"][-10:]:
                print(f"  - {{msg}}")
    print(f"\\nYour question: {{question}}")
    print("(Check .ticket-context.md for full context)")

if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Show all context"
    ask(q)
''', encoding="utf-8")


def _create_workspace_agents(agents_dir: Path, ticket_key: str):
    """Create agent definitions in the workspace."""
    developer_agent = f'''---
name: developer
description: "Developer agent for {ticket_key}. Reads .ticket-context.md and implements code changes."
tools:
  - run_in_terminal
  - read_file
  - create_file
  - replace_string_in_file
  - file_search
  - grep_search
  - semantic_search
  - list_dir
---

# Developer Agent — {ticket_key}

You are the developer agent for ticket {ticket_key}.

## First Step
Read `.ticket-context.md` in the workspace root. It has your full instructions.

## Workflow
1. Read and understand the ticket context
2. Explore the codebase to understand the existing structure
3. Implement the required changes
4. If you need more context, query: `GET http://localhost:5051/api/sessions/{ticket_key}/context`
5. If you have questions you cannot answer, ASK THE USER
6. When done, commit: `git add . && git commit -m "feat({ticket_key}): <description>"`

## After Completion
Tell the user: "Development complete. Run @reviewer to review, then @tester to test."
'''

    reviewer_agent = f'''---
name: reviewer
description: "Reviews code changes for {ticket_key}."
tools:
  - read_file
  - file_search
  - grep_search
  - semantic_search
  - list_dir
  - run_in_terminal
---

# Reviewer Agent — {ticket_key}

Review the changes made for {ticket_key}.

1. Read `.ticket-context.md` to understand requirements
2. Run `git diff master` to see all changes
3. Review each file for correctness, security, patterns
4. Provide verdict: APPROVED, CHANGES_REQUESTED, or QUESTIONS
'''

    tester_agent = f'''---
name: tester
description: "Tests implementation for {ticket_key}."
tools:
  - run_in_terminal
  - read_file
  - create_file
  - replace_string_in_file
  - file_search
  - grep_search
  - list_dir
---

# Tester Agent — {ticket_key}

Test the changes made for {ticket_key}.

1. Read `.ticket-context.md` to understand what to test
2. Run existing tests if any
3. Write new tests for the new functionality
4. Provide verdict: PASSED, FAILED, or PARTIAL
'''

    (agents_dir / "developer.agent.md").write_text(developer_agent, encoding="utf-8")
    (agents_dir / "reviewer.agent.md").write_text(reviewer_agent, encoding="utf-8")
    (agents_dir / "tester.agent.md").write_text(tester_agent, encoding="utf-8")


def _run_git(cwd: Path, *args) -> tuple[bool, str]:
    """Run a git command in the given directory."""
    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True, text=True, cwd=cwd
    )
    return result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python ticket_workspace.py <TICKET_KEY>")
        sys.exit(1)

    ticket_key = sys.argv[1].upper()
    print(f"Setting up workspace for {ticket_key}...")
    result = setup_ticket_workspace(ticket_key)
    print(json.dumps(result, indent=2))
