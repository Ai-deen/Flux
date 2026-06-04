"""
planner.py — Converts context + trigger into actionable steps.

The planner uses an LLM to:
1. Understand the Jira ticket / task
2. Break it into specific implementation steps
3. Convert each step into tool calls (which files to create/edit, what code to write)

Falls back to rule-based planning if no LLM is available.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

log = logging.getLogger(__name__)


PLANNING_SYSTEM_PROMPT = """You are an AI coding agent planner. Given a task context (Jira ticket, related commits, repo structure), create a step-by-step implementation plan.

Each step should be a specific, actionable instruction like:
- "Create file src/auth/oauth.py with OAuth2 handler class"
- "Edit src/app.py to add the auth route at line 45"
- "Add dependency 'flask-oauth' to requirements.txt"
- "Run tests with: pytest tests/test_auth.py"

Rules:
- Be specific about file paths and what code to write
- Reference the repo structure to use correct paths
- Each step should be independently executable
- Order steps logically (create before import, etc.)
- Include test steps where appropriate
- Maximum 15 steps

Return ONLY a JSON array of step descriptions (strings).
"""

STEP_TO_TOOLS_PROMPT = """You are an AI coding agent executor. Convert this step description into tool calls.

Available tools:
- git_create_branch(branch_name, from_branch="main")
- git_checkout(branch_name)
- git_add_commit(message, files=None)
- file_read(path)
- file_write(path, content)
- file_edit(path, old_text, new_text)
- file_list(directory=".", pattern="*")
- search_code(pattern, file_pattern="*.py")
- shell_run(command, timeout=60)
- copilot_prompt(prompt, file_context=None)

Return a JSON array of tool call objects: [{"tool": "tool_name", "args": {...}}]

If the step requires writing code you're unsure about, use copilot_prompt to get the code first.
If retrying after an error, adjust the tool calls to fix the issue.
"""


class Planner:
    """Plans agent actions using LLM or rule-based fallback."""

    def __init__(self, llm_provider: Optional[str] = None):
        self.llm_provider = llm_provider
        self._llm_client = None

    def create_plan(self, trigger: str, context: str, kwargs: dict) -> list[str]:
        """Create an execution plan from context.

        Args:
            trigger: "jira", "branch", or "manual"
            context: Full gathered context
            kwargs: Original trigger kwargs

        Returns:
            List of step descriptions
        """
        # Try LLM-based planning first
        plan = self._llm_plan(trigger, context, kwargs)
        if plan:
            return plan

        # Fallback: rule-based planning
        return self._rule_based_plan(trigger, context, kwargs)

    def step_to_tool_calls(self, step_description: str, context: str,
                           error: Optional[str] = None) -> list[dict]:
        """Convert a step description into tool calls.

        Args:
            step_description: What needs to be done
            context: Surrounding context
            error: Error from previous attempt (for self-correction)

        Returns:
            List of tool call dicts: [{"tool": "name", "args": {...}}]
        """
        # Try LLM-based conversion
        tool_calls = self._llm_step_to_tools(step_description, context, error)
        if tool_calls:
            return tool_calls

        # Fallback: parse the step description heuristically
        return self._parse_step_heuristic(step_description, error)

    # -----------------------------------------------------------------------
    # LLM-based planning
    # -----------------------------------------------------------------------

    def _llm_plan(self, trigger: str, context: str, kwargs: dict) -> Optional[list[str]]:
        """Use LLM to generate a plan."""
        try:
            client = self._get_llm_client()
            if not client:
                return None

            user_prompt = f"""Trigger: {trigger}
Task data: {json.dumps(kwargs, default=str)}

Context:
{context[:6000]}

Create a step-by-step implementation plan."""

            response = client.chat.completions.create(
                model=self._get_model(),
                messages=[
                    {"role": "system", "content": PLANNING_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=2000,
            )

            content = response.choices[0].message.content
            # Parse JSON from response
            plan = self._extract_json_array(content)
            if plan and isinstance(plan, list):
                return [str(step) for step in plan]

        except Exception as exc:
            log.warning(f"LLM planning failed: {exc}")

        return None

    def _llm_step_to_tools(self, step: str, context: str,
                           error: Optional[str]) -> Optional[list[dict]]:
        """Use LLM to convert step to tool calls."""
        try:
            client = self._get_llm_client()
            if not client:
                return None

            error_context = ""
            if error:
                error_context = f"\n\nPREVIOUS ATTEMPT FAILED with error:\n{error}\nPlease adjust your approach to fix this."

            user_prompt = f"""Step to execute: {step}
{error_context}

Repository context (abbreviated):
{context[:3000]}

Convert this step into tool calls."""

            response = client.chat.completions.create(
                model=self._get_model(),
                messages=[
                    {"role": "system", "content": STEP_TO_TOOLS_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
                max_tokens=2000,
            )

            content = response.choices[0].message.content
            tool_calls = self._extract_json_array(content)
            if tool_calls and isinstance(tool_calls, list):
                return tool_calls

        except Exception as exc:
            log.warning(f"LLM step-to-tools failed: {exc}")

        return None

    # -----------------------------------------------------------------------
    # Rule-based fallback
    # -----------------------------------------------------------------------

    def _rule_based_plan(self, trigger: str, context: str, kwargs: dict) -> list[str]:
        """Generate a basic plan without LLM."""
        plan = []

        issue_key = kwargs.get("issue_key", "")
        branch_name = kwargs.get("branch_name", "")

        if trigger == "jira" and issue_key:
            # Default plan for Jira ticket
            safe_key = issue_key.lower().replace("-", "-")
            plan = [
                f"Create branch feature/{safe_key}",
                f"Analyze the requirements from ticket {issue_key}",
                "Identify which files need to be created or modified",
                "Use copilot to generate the implementation code",
                "Write the generated code to the appropriate files",
                "Run any existing tests to verify nothing is broken",
                f"Commit changes with message: feat({issue_key}): implement ticket requirements",
            ]

        elif trigger == "branch":
            plan = [
                f"Checkout branch {branch_name}",
                "Analyze the context to understand what needs to be done",
                "Use copilot to generate the implementation",
                "Write changes to appropriate files",
                "Run tests",
                "Commit changes",
            ]

        elif trigger == "manual":
            prompt = kwargs.get("prompt", "")
            plan = [
                "Analyze the manual instruction",
                f"Use copilot to solve: {prompt[:200]}",
                "Apply the suggested changes",
                "Verify the changes work",
            ]

        return plan

    def _parse_step_heuristic(self, step: str, error: Optional[str]) -> list[dict]:
        """Parse step description into tool calls using heuristics."""
        step_lower = step.lower()

        # Branch creation
        if "create branch" in step_lower or "checkout -b" in step_lower:
            # Extract branch name
            import re
            match = re.search(r'branch\s+(\S+)', step, re.IGNORECASE)
            branch_name = match.group(1) if match else "feature/agent-work"
            return [{"tool": "git_create_branch", "args": {"branch_name": branch_name}}]

        # Checkout
        if "checkout" in step_lower:
            import re
            match = re.search(r'checkout\s+(\S+)', step, re.IGNORECASE)
            branch = match.group(1) if match else "main"
            return [{"tool": "git_checkout", "args": {"branch_name": branch}}]

        # File creation/writing
        if "create file" in step_lower or "write" in step_lower:
            # Delegate to copilot for actual content
            return [{"tool": "copilot_prompt", "args": {"prompt": step}}]

        # Commit
        if "commit" in step_lower:
            import re
            match = re.search(r'message[:\s]+(.+)', step, re.IGNORECASE)
            msg = match.group(1).strip() if match else "Agent: automated changes"
            return [{"tool": "git_add_commit", "args": {"message": msg}}]

        # Tests
        if "run test" in step_lower or "pytest" in step_lower:
            return [{"tool": "shell_run", "args": {"command": "pytest --tb=short -q"}}]

        # Default: use copilot for anything we can't parse
        return [{"tool": "copilot_prompt", "args": {"prompt": step}}]

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _get_llm_client(self):
        """Get or create an LLM client."""
        if self._llm_client:
            return self._llm_client

        try:
            from openai import OpenAI
            from ..utils.config import config

            if config.openrouter_api_key:
                self._llm_client = OpenAI(
                    api_key=config.openrouter_api_key,
                    base_url="https://openrouter.ai/api/v1",
                )
            elif config.openai_api_key:
                self._llm_client = OpenAI(api_key=config.openai_api_key)
            else:
                return None

            return self._llm_client
        except Exception:
            return None

    def _get_model(self) -> str:
        """Get the model to use."""
        from ..utils.config import config
        if config.openrouter_api_key:
            return config.openrouter_model
        return config.openai_model

    def _extract_json_array(self, text: str) -> Optional[list]:
        """Extract a JSON array from LLM response text."""
        import re
        # Try direct parse
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass

        # Try to find JSON in code blocks
        match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except (json.JSONDecodeError, TypeError):
                pass

        # Try to find bare JSON array
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except (json.JSONDecodeError, TypeError):
                pass

        return None
