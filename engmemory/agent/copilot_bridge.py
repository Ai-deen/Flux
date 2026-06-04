"""
copilot_bridge.py — Integration with GitHub Copilot.

Provides multiple strategies for getting code from Copilot:

1. **Prompt File** (primary): Creates a structured .copilot-prompt.md file that
   can be consumed by GitHub Copilot Chat with @workspace context.

2. **GH CLI** (if available): Uses `gh copilot suggest` for code suggestions.

3. **LLM Fallback**: Uses OpenAI/OpenRouter API directly if Copilot isn't available.

The key insight: we build a comprehensive, informed prompt from all our context
(Jira, commits, AI sessions) and feed it to whichever code generation backend
is available.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def send_to_copilot(prompt: str, repo_path: str,
                    file_context: Optional[list[str]] = None) -> str:
    """
    Send a prompt to the best available code generation backend.

    Strategy:
    1. Try GH Copilot CLI if available
    2. Fall back to direct LLM API call
    3. If all else fails, save prompt file for manual Copilot use

    Returns:
        Generated code/response string
    """
    # Strategy 1: Try GitHub Copilot CLI
    result = _try_gh_copilot(prompt, repo_path)
    if result:
        return result

    # Strategy 2: Direct LLM API call
    result = _try_llm_direct(prompt, file_context, repo_path)
    if result:
        return result

    # Strategy 3: Save prompt for manual use with Copilot Chat
    prompt_path = _save_prompt_file(prompt, repo_path, file_context)
    return (
        f"[Agent] Prompt saved to: {prompt_path}\n"
        "Open this file in VS Code and use Copilot Chat with @workspace to execute.\n"
        "Or configure an LLM API key for fully autonomous operation."
    )


def build_copilot_prompt(context: str, task: str,
                         file_context: Optional[list[str]] = None) -> str:
    """
    Build a comprehensive prompt optimized for GitHub Copilot.

    This is the core value add — we enrich a simple task with full context
    from Jira, commits, AI sessions, and repo structure.
    """
    parts = [
        "# Task",
        task,
        "",
        "# Context",
        context,
    ]

    if file_context:
        parts.extend([
            "",
            "# Relevant Files",
            "Focus your changes on these files:",
        ])
        for f in file_context:
            parts.append(f"- {f}")

    parts.extend([
        "",
        "# Instructions",
        "1. Implement the task described above",
        "2. Follow existing code patterns and conventions in the repository",
        "3. Write clean, production-ready code",
        "4. Include appropriate error handling",
        "5. Add brief inline comments only for complex logic",
        "",
        "Respond with the complete file contents for each file that needs to be created or modified.",
        "Format: ```filepath:path/to/file.ext``` followed by the code block.",
    ])

    return "\n".join(parts)


def _try_gh_copilot(prompt: str, repo_path: str) -> Optional[str]:
    """Try using GitHub Copilot CLI."""
    try:
        # Check if gh CLI is available with copilot extension
        check = subprocess.run(
            ["gh", "copilot", "--help"],
            capture_output=True, text=True, timeout=5,
        )
        if check.returncode != 0:
            return None

        # Use gh copilot suggest
        result = subprocess.run(
            ["gh", "copilot", "suggest", "-t", "code", prompt[:500]],
            cwd=repo_path,
            capture_output=True, text=True, timeout=60,
        )

        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()

    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None


def _try_llm_direct(prompt: str, file_context: Optional[list[str]],
                    repo_path: str) -> Optional[str]:
    """Try direct LLM API call."""
    try:
        from openai import OpenAI
        from ..utils.config import config

        if config.openrouter_api_key:
            client = OpenAI(
                api_key=config.openrouter_api_key,
                base_url="https://openrouter.ai/api/v1",
            )
            model = config.openrouter_model
        elif config.openai_api_key:
            client = OpenAI(api_key=config.openai_api_key)
            model = config.openai_model
        else:
            return None

        # Include file contents in context if specified
        file_contents = ""
        if file_context:
            for fpath in file_context[:5]:  # Limit to 5 files
                full_path = Path(repo_path) / fpath
                if full_path.exists():
                    try:
                        content = full_path.read_text(encoding="utf-8")[:3000]
                        file_contents += f"\n\n--- {fpath} ---\n{content}"
                    except Exception:
                        pass

        system_msg = (
            "You are an expert software engineer. Generate clean, production-ready code. "
            "When creating or modifying files, format your response as:\n"
            "```filepath:path/to/file.ext```\n"
            "followed by the complete file content in a code block.\n"
            "Only output code and brief explanations. No unnecessary commentary."
        )

        user_msg = prompt
        if file_contents:
            user_msg += f"\n\n# Existing file contents for reference:{file_contents}"

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.2,
            max_tokens=4000,
        )

        return response.choices[0].message.content

    except Exception as exc:
        log.warning(f"LLM direct call failed: {exc}")
        return None


def _save_prompt_file(prompt: str, repo_path: str,
                      file_context: Optional[list[str]] = None) -> str:
    """Save prompt to a file for manual Copilot Chat use."""
    prompt_dir = Path(repo_path) / ".ai_memory" / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)

    import time
    filename = f"prompt_{int(time.time())}.md"
    prompt_path = prompt_dir / filename

    content = f"""# Agent-Generated Prompt

Use this with GitHub Copilot Chat: Select all text below and paste into Copilot Chat with @workspace.

---

{prompt}
"""
    if file_context:
        content += "\n\n## Relevant Files\n"
        for f in file_context:
            content += f"- `{f}`\n"

    prompt_path.write_text(content, encoding="utf-8")
    return str(prompt_path)


def parse_copilot_response(response: str) -> list[dict]:
    """
    Parse a Copilot/LLM response into file operations.

    Looks for patterns like:
        ```filepath:src/auth.py```
        ```python
        ... code ...
        ```

    Returns:
        List of {"path": "...", "content": "..."} dicts
    """
    import re
    files = []

    # Pattern: ```filepath:path/to/file``` followed by code block
    pattern = r'```filepath:(.+?)```\s*```\w*\n(.*?)```'
    matches = re.findall(pattern, response, re.DOTALL)

    for path, content in matches:
        files.append({"path": path.strip(), "content": content.strip()})

    if not files:
        # Alternative pattern: ### path/to/file followed by code block
        pattern = r'###?\s+`?([^\n`]+\.\w+)`?\s*\n```\w*\n(.*?)```'
        matches = re.findall(pattern, response, re.DOTALL)
        for path, content in matches:
            files.append({"path": path.strip(), "content": content.strip()})

    return files
