"""
hook.py

Installs and manages the post-commit git hook.

Commands (called from the CLI):
    engmemory init          → install hook into current repo
    engmemory uninstall     → remove hook from current repo
    engmemory status        → show whether hook is installed

The hook script is written to .git/hooks/post-commit.
If a post-commit hook already exists we append to it so we don't
clobber other tools (husky, pre-commit, etc.).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import git


# ---------------------------------------------------------------------------
# Hook script template
# ---------------------------------------------------------------------------

HOOK_MARKER_START = "# >>> engmemory-hook-start <<<"
HOOK_MARKER_END   = "# >>> engmemory-hook-end <<<"

HOOK_BODY = """\
{start}
# EngMemory: capture commit intelligence
# Installed by `engmemory init` — remove with `engmemory uninstall`
python -m engmemory.core.runner --repo "$(git rev-parse --show-toplevel)"
{end}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def install(repo_path: str = ".") -> str:
    """
    Install the EngMemory post-commit hook.
    Also sets up .gitignore, .ai_memory folder, and installs VS Code extension.
    Returns a status message.
    """
    hook_path = _hook_path(repo_path)
    existing = hook_path.read_text(encoding="utf-8") if hook_path.exists() else ""

    if HOOK_MARKER_START in existing:
        return "EngMemory hook is already installed."

    snippet = HOOK_BODY.format(start=HOOK_MARKER_START, end=HOOK_MARKER_END)

    if existing and not existing.startswith("#!"):
        content = "#!/bin/sh\n" + existing + "\n" + snippet
    elif existing:
        content = existing.rstrip() + "\n\n" + snippet
    else:
        content = "#!/bin/sh\nset -e\n\n" + snippet

    hook_path.write_text(content, encoding="utf-8")
    _make_executable(hook_path)

    # Setup .ai_memory directory
    repo_root = _repo_root(repo_path)
    _setup_ai_memory(repo_root)

    # Update .gitignore
    _update_gitignore(repo_root)

    # Install VS Code extension if available
    _install_vscode_extension(repo_root)

    return f"Hook installed at {hook_path}"


def uninstall(repo_path: str = ".") -> str:
    """
    Remove the EngMemory block from the post-commit hook.
    If the hook is empty afterwards, delete it.
    """
    hook_path = _hook_path(repo_path)
    if not hook_path.exists():
        return "No post-commit hook found — nothing to remove."

    content = hook_path.read_text(encoding="utf-8")
    if HOOK_MARKER_START not in content:
        return "EngMemory hook not found in post-commit — nothing to remove."

    cleaned = _remove_block(content, HOOK_MARKER_START, HOOK_MARKER_END)

    remaining = cleaned.replace("#!/bin/sh", "").replace("set -e", "").strip()
    if not remaining:
        hook_path.unlink()
        return "Hook removed. post-commit file deleted (was empty)."

    hook_path.write_text(cleaned, encoding="utf-8")
    return "EngMemory hook removed from post-commit."


def status(repo_path: str = ".") -> str:
    hook_path = _hook_path(repo_path)
    if not hook_path.exists():
        return "not installed (no post-commit hook)"

    content = hook_path.read_text(encoding="utf-8")
    if HOOK_MARKER_START in content:
        return f"installed ✓  ({hook_path})"
    return "not installed (post-commit exists but EngMemory block not found)"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _hook_path(repo_path: str) -> Path:
    try:
        repo = git.Repo(repo_path, search_parent_directories=True)
    except git.InvalidGitRepositoryError:
        raise ValueError(f"No git repository found at or above: {repo_path}")
    return Path(repo.git_dir) / "hooks" / "post-commit"


def _make_executable(path: Path) -> None:
    current = path.stat().st_mode
    path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _repo_root(repo_path: str) -> Path:
    """Get the root directory of the git repo."""
    repo = git.Repo(repo_path, search_parent_directories=True)
    return Path(repo.working_dir)


def _setup_ai_memory(repo_root: Path) -> None:
    """Create .ai_memory directory structure."""
    ai_memory = repo_root / ".ai_memory"
    commits_dir = ai_memory / "commits"
    commits_dir.mkdir(parents=True, exist_ok=True)

    # Create .ai_memory/.gitignore to keep commits local but track the folder
    gitignore = ai_memory / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("# Keep commit JSONs local (they can be large)\ncommits/*.json\n", encoding="utf-8")


def _update_gitignore(repo_root: Path) -> None:
    """Add EngMemory entries to .gitignore if not already present."""
    gitignore_path = repo_root / ".gitignore"

    entries_to_add = [
        "# EngMemory",
        ".ai_memory/commits/",
        ".ai_memory/ai_sessions/",
        ".ai_memory/engmemory.log",
    ]

    existing = ""
    if gitignore_path.exists():
        existing = gitignore_path.read_text(encoding="utf-8")

    # Check if already present
    if "# EngMemory" in existing:
        return

    # Append
    addition = "\n" + "\n".join(entries_to_add) + "\n"
    with open(gitignore_path, "a", encoding="utf-8") as f:
        f.write(addition)


def _install_vscode_extension(repo_root: Path) -> None:
    """Install the EngMemory VS Code extension if the .vsix is available."""
    import subprocess
    import shutil

    # Find the .vsix file relative to engmemory package installation
    package_dir = Path(__file__).resolve().parents[2]  # commit_hook root
    vsix_path = package_dir / "vscode-extension" / "engmemory-0.1.0.vsix"

    if not vsix_path.exists():
        # Try relative to the current working directory
        vsix_path = Path(os.getcwd()).parent / "commit_hook" / "vscode-extension" / "engmemory-0.1.0.vsix"

    if not vsix_path.exists():
        return  # Extension not found, skip silently

    # Check if VS Code CLI is available
    code_cmd = shutil.which("code")
    if not code_cmd:
        return

    try:
        subprocess.run(
            [code_cmd, "--install-extension", str(vsix_path), "--force"],
            capture_output=True,
            timeout=30,
        )
    except Exception:
        pass  # Non-blocking — don't fail init if extension install fails


def _remove_block(content: str, start_marker: str, end_marker: str) -> str:
    lines = content.splitlines(keepends=True)
    result, inside = [], False
    for line in lines:
        if start_marker in line:
            inside = True
            continue
        if end_marker in line:
            inside = False
            continue
        if not inside:
            result.append(line)
    return "".join(result)