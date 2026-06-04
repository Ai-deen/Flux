"""
engine.py — Core Agent Loop

The agent follows a Plan → Act → Observe → Retry cycle:
1. Receive trigger (Jira ticket, branch creation, manual)
2. Build context from all sources
3. Create a plan (list of steps)
4. Execute each step using tools
5. If a step fails, diagnose and retry (up to max_retries)
6. Report results

The agent is designed to be pluggable into any project.
"""

from __future__ import annotations

import json
import logging
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from .context_builder import ContextBuilder
from .tools import ToolRegistry, ToolResult
from .planner import Planner

log = logging.getLogger(__name__)


class AgentState(Enum):
    IDLE = "idle"
    GATHERING_CONTEXT = "gathering_context"
    PLANNING = "planning"
    EXECUTING = "executing"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class StepResult:
    """Result of executing a single plan step."""
    step_id: int
    description: str
    success: bool
    output: str = ""
    error: str = ""
    retries: int = 0


@dataclass
class AgentRun:
    """Record of a complete agent execution."""
    trigger: str
    trigger_data: dict = field(default_factory=dict)
    context_summary: str = ""
    plan: list[str] = field(default_factory=list)
    results: list[StepResult] = field(default_factory=list)
    state: AgentState = AgentState.IDLE
    started_at: float = 0.0
    completed_at: float = 0.0

    @property
    def success(self) -> bool:
        return self.state == AgentState.COMPLETED and all(r.success for r in self.results)

    def to_dict(self) -> dict:
        return {
            "trigger": self.trigger,
            "trigger_data": self.trigger_data,
            "context_summary": self.context_summary[:500],
            "plan": self.plan,
            "results": [
                {"step": r.step_id, "desc": r.description, "success": r.success,
                 "output": r.output[:200], "error": r.error, "retries": r.retries}
                for r in self.results
            ],
            "state": self.state.value,
            "duration_seconds": round(self.completed_at - self.started_at, 2) if self.completed_at else 0,
        }


class Agent:
    """
    Autonomous AI Agent that gathers context, plans, and executes.

    Usage:
        agent = Agent(repo_path="/path/to/project")
        result = agent.run(trigger="jira", issue_key="ENG-456")
        # or
        result = agent.run(trigger="branch", branch_name="feature/ENG-456-auth")
    """

    def __init__(
        self,
        repo_path: str = ".",
        max_retries: int = 3,
        max_steps: int = 20,
        llm_provider: Optional[str] = None,
        on_step_complete: Optional[Callable[[StepResult], None]] = None,
        dry_run: bool = False,
    ):
        self.repo_path = repo_path
        self.max_retries = max_retries
        self.max_steps = max_steps
        self.dry_run = dry_run
        self.on_step_complete = on_step_complete

        self.context_builder = ContextBuilder(repo_path=repo_path)
        self.tools = ToolRegistry(repo_path=repo_path, dry_run=dry_run)
        self.planner = Planner(llm_provider=llm_provider)
        self._run: Optional[AgentRun] = None

    def run(self, trigger: str, **kwargs) -> AgentRun:
        """
        Execute the full agent loop.

        Args:
            trigger: What triggered this run ("jira", "branch", "manual")
            **kwargs: Trigger-specific data:
                - issue_key: Jira issue key (for trigger="jira")
                - branch_name: Git branch name (for trigger="branch")
                - prompt: Manual instruction (for trigger="manual")

        Returns:
            AgentRun with full execution record
        """
        self._run = AgentRun(trigger=trigger, trigger_data=kwargs)
        self._run.started_at = time.time()

        try:
            # Phase 1: Gather context
            self._run.state = AgentState.GATHERING_CONTEXT
            log.info(f"[Agent] Gathering context for trigger={trigger} {kwargs}")
            context = self._gather_context(trigger, kwargs)
            self._run.context_summary = context

            # Phase 2: Create plan
            self._run.state = AgentState.PLANNING
            log.info("[Agent] Creating execution plan...")
            plan = self.planner.create_plan(trigger, context, kwargs)
            self._run.plan = plan
            log.info(f"[Agent] Plan has {len(plan)} steps")

            if not plan:
                self._run.state = AgentState.COMPLETED
                self._run.completed_at = time.time()
                return self._run

            # Phase 3: Execute steps
            self._run.state = AgentState.EXECUTING
            for i, step_description in enumerate(plan[:self.max_steps]):
                result = self._execute_step(i + 1, step_description, context)
                self._run.results.append(result)

                if self.on_step_complete:
                    self.on_step_complete(result)

                if not result.success and result.retries >= self.max_retries:
                    log.warning(f"[Agent] Step {i+1} failed after {self.max_retries} retries. Stopping.")
                    self._run.state = AgentState.FAILED
                    break
            else:
                self._run.state = AgentState.COMPLETED

        except Exception as exc:
            log.error(f"[Agent] Fatal error: {exc}")
            self._run.state = AgentState.FAILED
            self._run.results.append(StepResult(
                step_id=0, description="Agent execution", success=False,
                error=traceback.format_exc()
            ))

        self._run.completed_at = time.time()
        log.info(f"[Agent] Run completed: {self._run.state.value}")
        return self._run

    def _gather_context(self, trigger: str, kwargs: dict) -> str:
        """Gather context from all available sources."""
        context_parts = []

        # Always try to get Jira context
        issue_key = kwargs.get("issue_key")
        if not issue_key and kwargs.get("branch_name"):
            # Try to extract ticket from branch name (e.g., feature/ENG-456-auth)
            issue_key = self.context_builder.extract_ticket_from_branch(kwargs["branch_name"])

        if issue_key:
            jira_context = self.context_builder.get_jira_context(issue_key)
            if jira_context:
                context_parts.append(jira_context)

        # Get related commits from search
        search_query = kwargs.get("prompt") or kwargs.get("issue_key", "")
        if search_query:
            commit_context = self.context_builder.get_commit_context(search_query)
            if commit_context:
                context_parts.append(commit_context)

        # Get AI session context (what developer was discussing with Copilot)
        ai_context = self.context_builder.get_ai_session_context()
        if ai_context:
            context_parts.append(ai_context)

        # Get repo structure context
        repo_context = self.context_builder.get_repo_structure()
        if repo_context:
            context_parts.append(repo_context)

        return "\n\n---\n\n".join(context_parts) if context_parts else "No context available."

    def _execute_step(self, step_id: int, description: str, context: str) -> StepResult:
        """Execute a single plan step with retry logic."""
        result = StepResult(step_id=step_id, description=description, success=False)

        for attempt in range(self.max_retries + 1):
            try:
                if self.dry_run:
                    result.success = True
                    result.output = f"[DRY RUN] Would execute: {description}"
                    break

                # Ask the planner to convert step description into tool calls
                tool_calls = self.planner.step_to_tool_calls(description, context, 
                                                             error=result.error if attempt > 0 else None)

                # Execute each tool call
                outputs = []
                for tool_call in tool_calls:
                    tool_result = self.tools.execute(tool_call["tool"], tool_call.get("args", {}))
                    outputs.append(tool_result)

                    if not tool_result.success:
                        result.error = tool_result.error
                        raise ToolExecutionError(tool_result.error)

                result.success = True
                result.output = "\n".join(r.output for r in outputs)
                break

            except ToolExecutionError as exc:
                result.retries = attempt + 1
                result.error = str(exc)
                if attempt < self.max_retries:
                    self._run.state = AgentState.RETRYING
                    log.warning(f"[Agent] Step {step_id} attempt {attempt+1} failed: {exc}. Retrying...")
                    # Let planner see the error on next attempt to self-correct

            except Exception as exc:
                result.retries = attempt + 1
                result.error = traceback.format_exc()
                if attempt < self.max_retries:
                    log.warning(f"[Agent] Step {step_id} unexpected error: {exc}. Retrying...")

        return result


class ToolExecutionError(Exception):
    """Raised when a tool execution fails."""
    pass
