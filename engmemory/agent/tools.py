"""
tools.py — Tool system for the agent.

Tools are actions the agent can take:
- git_create_branch: Create a new git branch
- git_checkout: Switch to a branch
- file_read: Read file contents
- file_write: Write/create a file
- file_edit: Edit specific lines in a file
- shell_run: Run a shell command
- search_code: Search for code patterns in the repo
- copilot_prompt: Send a prompt to GitHub Copilot via CLI

Each tool is registered with the ToolRegistry and can be called by name.
The agent's planner decides which tools to use.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """Result from executing a tool."""
    success: bool
    output: str = ""
    error: str = ""
    data: Any = None


class ToolRegistry:
    """Registry of tools the agent can use."""

    def __init__(self, repo_path: str = ".", dry_run: bool = False):
        self.repo_path = os.path.abspath(repo_path)
        self.dry_run = dry_run
        self._tools: dict[str, Callable] = {}
        self._register_builtins()

    def register(self, name: str, func: Callable):
        """Register a custom tool."""
        self._tools[name] = func

    def list_tools(self) -> list[str]:
        """List all available tool names."""
        return list(self._tools.keys())

    def execute(self, tool_name: str, args: dict) -> ToolResult:
        """Execute a tool by name with given arguments."""
        if tool_name not in self._tools:
            return ToolResult(success=False, error=f"Unknown tool: {tool_name}")

        if self.dry_run:
            return ToolResult(success=True, output=f"[DRY RUN] {tool_name}({args})")

        try:
            return self._tools[tool_name](**args)
        except Exception as exc:
            log.error(f"Tool '{tool_name}' failed: {exc}")
            return ToolResult(success=False, error=str(exc))

    def _register_builtins(self):
        """Register all built-in tools."""
        self._tools = {
            "git_create_branch": self._git_create_branch,
            "git_checkout": self._git_checkout,
            "git_current_branch": self._git_current_branch,
            "git_add_commit": self._git_add_commit,
            "file_read": self._file_read,
            "file_write": self._file_write,
            "file_edit": self._file_edit,
            "file_list": self._file_list,
            "search_code": self._search_code,
            "shell_run": self._shell_run,
            "copilot_prompt": self._copilot_prompt,
        }

    # -----------------------------------------------------------------------
    # Git tools
    # -----------------------------------------------------------------------

    def _git_create_branch(self, branch_name: str, from_branch: str = "main") -> ToolResult:
        """Create and checkout a new git branch."""
        result = self._run_git(["checkout", "-b", branch_name, from_branch])
        if result.returncode != 0:
            # Maybe from_branch doesn't exist, try without it
            result = self._run_git(["checkout", "-b", branch_name])
        if result.returncode == 0:
            return ToolResult(success=True, output=f"Created branch: {branch_name}")
        return ToolResult(success=False, error=result.stderr)

    def _git_checkout(self, branch_name: str) -> ToolResult:
        """Checkout an existing branch."""
        result = self._run_git(["checkout", branch_name])
        if result.returncode == 0:
            return ToolResult(success=True, output=f"Checked out: {branch_name}")
        return ToolResult(success=False, error=result.stderr)

    def _git_current_branch(self) -> ToolResult:
        """Get the current branch name."""
        result = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"])
        if result.returncode == 0:
            return ToolResult(success=True, output=result.stdout.strip())
        return ToolResult(success=False, error=result.stderr)

    def _git_add_commit(self, message: str, files: Optional[list[str]] = None) -> ToolResult:
        """Stage files and commit."""
        if files:
            for f in files:
                self._run_git(["add", f])
        else:
            self._run_git(["add", "-A"])

        result = self._run_git(["commit", "-m", message, "--no-verify"])
        if result.returncode == 0:
            return ToolResult(success=True, output=f"Committed: {message}")
        return ToolResult(success=False, error=result.stderr)

    def _run_git(self, args: list[str]) -> subprocess.CompletedProcess:
        """Run a git command in the repo directory."""
        return subprocess.run(
            ["git"] + args,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

    # -----------------------------------------------------------------------
    # File tools
    # -----------------------------------------------------------------------

    def _file_read(self, path: str) -> ToolResult:
        """Read a file's contents."""
        full_path = self._resolve_path(path)
        if not full_path.exists():
            return ToolResult(success=False, error=f"File not found: {path}")
        try:
            content = full_path.read_text(encoding="utf-8")
            return ToolResult(success=True, output=content, data={"path": str(full_path)})
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))

    def _file_write(self, path: str, content: str) -> ToolResult:
        """Write content to a file (creates directories if needed)."""
        full_path = self._resolve_path(path)
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
            return ToolResult(success=True, output=f"Written: {path}")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))

    def _file_edit(self, path: str, old_text: str, new_text: str) -> ToolResult:
        """Replace text in a file."""
        full_path = self._resolve_path(path)
        if not full_path.exists():
            return ToolResult(success=False, error=f"File not found: {path}")
        try:
            content = full_path.read_text(encoding="utf-8")
            if old_text not in content:
                return ToolResult(success=False, error=f"Text not found in {path}")
            new_content = content.replace(old_text, new_text, 1)
            full_path.write_text(new_content, encoding="utf-8")
            return ToolResult(success=True, output=f"Edited: {path}")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))

    def _file_list(self, directory: str = ".", pattern: str = "*") -> ToolResult:
        """List files in a directory."""
        full_path = self._resolve_path(directory)
        if not full_path.exists():
            return ToolResult(success=False, error=f"Directory not found: {directory}")
        try:
            files = [str(p.relative_to(full_path)) for p in full_path.rglob(pattern)
                     if p.is_file() and '.git' not in str(p)]
            return ToolResult(success=True, output="\n".join(files[:50]), data=files)
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))

    # -----------------------------------------------------------------------
    # Search tools
    # -----------------------------------------------------------------------

    def _search_code(self, pattern: str, file_pattern: str = "*.py") -> ToolResult:
        """Search for a regex pattern in code files."""
        try:
            results = []
            repo_root = Path(self.repo_path)
            regex = re.compile(pattern, re.IGNORECASE)

            for file_path in repo_root.rglob(file_pattern):
                if '.git' in str(file_path) or 'node_modules' in str(file_path):
                    continue
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    for i, line in enumerate(content.splitlines(), 1):
                        if regex.search(line):
                            rel_path = file_path.relative_to(repo_root)
                            results.append(f"{rel_path}:{i}: {line.strip()}")
                except Exception:
                    continue

            if results:
                return ToolResult(success=True, output="\n".join(results[:30]), data=results)
            return ToolResult(success=True, output="No matches found.")

        except Exception as exc:
            return ToolResult(success=False, error=str(exc))

    # -----------------------------------------------------------------------
    # Shell tools
    # -----------------------------------------------------------------------

    def _shell_run(self, command: str, timeout: int = 60) -> ToolResult:
        """Run a shell command. Limited to safe operations."""
        # Safety: block dangerous commands
        dangerous = ['rm -rf /', 'format ', 'del /s', 'rmdir /s']
        if any(d in command.lower() for d in dangerous):
            return ToolResult(success=False, error="Command blocked for safety.")

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if result.returncode == 0:
                return ToolResult(success=True, output=result.stdout[:5000])
            return ToolResult(success=False, error=result.stderr[:2000], output=result.stdout[:2000])
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error=f"Command timed out after {timeout}s")
        except Exception as exc:
            return ToolResult(success=False, error=str(exc))

    # -----------------------------------------------------------------------
    # Copilot integration
    # -----------------------------------------------------------------------

    def _copilot_prompt(self, prompt: str, file_context: Optional[list[str]] = None) -> ToolResult:
        """
        Send a structured prompt to GitHub Copilot CLI or LLM fallback.
        
        This creates a prompt file that can be consumed by:
        1. GitHub Copilot Chat (via @workspace mention)
        2. gh copilot suggest (CLI)
        3. Direct LLM API call (fallback)
        """
        try:
            from .copilot_bridge import send_to_copilot
            result = send_to_copilot(prompt, self.repo_path, file_context)
            return ToolResult(success=True, output=result)
        except Exception as exc:
            return ToolResult(success=False, error=f"Copilot integration failed: {exc}")

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _resolve_path(self, path: str) -> Path:
        """Resolve a relative path against repo root."""
        p = Path(path)
        if p.is_absolute():
            return p
        return Path(self.repo_path) / path
