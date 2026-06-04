"""
ask_orchestrator.py — Central Ask Memory Orchestrator

The "brain" that coordinates all agent activity:

1. Pulls context from Jira, commits, AI sessions (via RAG)
2. Builds the developer prompt using ask_memory intelligence
3. Triggers developer agent → waits for completion
4. Triggers reviewer agent → checks against requirements
5. Triggers tester agent → validates implementation
6. Creates PR when all pass
7. Logs all inter-agent conversations for visibility
8. Developer agent queries this instead of asking the user directly

Flow:
    ask_orchestrator.start(ticket_key)
    → gathers context (Jira + commits + AI sessions + main branch diff)
    → builds prompt for developer
    → developer works (can query ask_orchestrator mid-work)
    → developer signals done
    → reviewer checks
    → if reviewer rejects → back to developer with feedback
    → tester validates
    → if tester fails → back to developer with errors
    → creates PR
    → notifies user for merge approval
"""

from __future__ import annotations

import json
import logging
import time
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Callable

from ..search.rag import ask_question
from ..utils.config import config

log = logging.getLogger(__name__)


class PipelineStage(Enum):
    IDLE = "idle"
    CONTEXT_GATHERING = "context_gathering"
    DEVELOPER = "developer"
    REVIEW = "review"
    TESTING = "testing"
    PR_CREATION = "pr_creation"
    WAITING_FOR_MERGE = "waiting_for_merge"
    DONE = "done"
    FAILED = "failed"


class ConversationRole(Enum):
    ORCHESTRATOR = "orchestrator"
    DEVELOPER = "developer"
    REVIEWER = "reviewer"
    TESTER = "tester"
    USER = "user"


@dataclass
class ConversationMessage:
    """A single message in the inter-agent conversation log."""
    role: ConversationRole
    content: str
    timestamp: str = ""
    stage: str = ""
    query_to: str = ""  # who is being asked (for Q&A tracking)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "role": self.role.value,
            "content": self.content,
            "timestamp": self.timestamp,
            "stage": self.stage,
            "query_to": self.query_to,
        }


@dataclass
class PipelineState:
    """Full state of the ask_orchestrator pipeline for a ticket."""
    ticket_key: str
    stage: PipelineStage = PipelineStage.IDLE
    conversation: list[ConversationMessage] = field(default_factory=list)
    context_prompt: str = ""
    developer_result: str = ""
    reviewer_verdict: str = ""  # APPROVED, CHANGES_REQUESTED, QUESTIONS
    reviewer_feedback: str = ""
    tester_verdict: str = ""  # PASSED, FAILED, PARTIAL
    tester_feedback: str = ""
    pr_url: str = ""
    iteration: int = 0
    max_iterations: int = 3
    started_at: str = ""
    completed_at: str = ""
    repo_path: str = ""
    branch_name: str = ""

    # Command blocklist - developer cannot run these
    blocked_commands: list[str] = field(default_factory=lambda: [
        "git push origin main",
        "git push origin master",
        "git merge main",
        "git merge master",
        "git reset --hard",
        "rm -rf /",
        "Remove-Item -Recurse -Force C:\\",
        "format ",
    ])

    # Commands that need explicit user approval
    approval_commands: list[str] = field(default_factory=lambda: [
        "git push",
        "git merge",
    ])

    def __post_init__(self):
        if not self.started_at:
            self.started_at = datetime.now(timezone.utc).isoformat()

    def add_message(self, role: ConversationRole, content: str,
                    query_to: str = "") -> ConversationMessage:
        msg = ConversationMessage(
            role=role,
            content=content,
            stage=self.stage.value,
            query_to=query_to,
        )
        self.conversation.append(msg)
        self._save()
        return msg

    def is_command_blocked(self, command: str) -> bool:
        """Check if a command is in the blocklist."""
        cmd_lower = command.lower().strip()
        for blocked in self.blocked_commands:
            if blocked.lower() in cmd_lower:
                return True
        return False

    def is_command_auto_allowed(self, command: str) -> bool:
        """Check if a command can run without user approval.
        
        Everything is auto-allowed EXCEPT:
        - Blocked commands (always rejected)
        - Push/merge to main/master (needs user approval)
        """
        if self.is_command_blocked(command):
            return False
        cmd_lower = command.lower().strip()
        for approval_cmd in self.approval_commands:
            if approval_cmd.lower() in cmd_lower:
                return False
        return True

    def _save(self):
        """Persist state to disk."""
        state_dir = Path.home() / ".engmemory" / "pipeline"
        state_dir.mkdir(parents=True, exist_ok=True)
        state_file = state_dir / f"{self.ticket_key}.json"
        state_file.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    def to_dict(self) -> dict:
        return {
            "ticket_key": self.ticket_key,
            "stage": self.stage.value,
            "conversation": [m.to_dict() for m in self.conversation],
            "context_prompt": self.context_prompt[:5000],
            "developer_result": self.developer_result[:2000],
            "reviewer_verdict": self.reviewer_verdict,
            "reviewer_feedback": self.reviewer_feedback[:2000],
            "tester_verdict": self.tester_verdict,
            "tester_feedback": self.tester_feedback[:2000],
            "pr_url": self.pr_url,
            "iteration": self.iteration,
            "max_iterations": self.max_iterations,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "repo_path": self.repo_path,
            "branch_name": self.branch_name,
        }

    @classmethod
    def load(cls, ticket_key: str) -> Optional["PipelineState"]:
        """Load pipeline state from disk."""
        state_file = Path.home() / ".engmemory" / "pipeline" / f"{ticket_key}.json"
        if not state_file.exists():
            return None
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            state = cls(ticket_key=ticket_key)
            state.stage = PipelineStage(data.get("stage", "idle"))
            state.context_prompt = data.get("context_prompt", "")
            state.developer_result = data.get("developer_result", "")
            state.reviewer_verdict = data.get("reviewer_verdict", "")
            state.reviewer_feedback = data.get("reviewer_feedback", "")
            state.tester_verdict = data.get("tester_verdict", "")
            state.tester_feedback = data.get("tester_feedback", "")
            state.pr_url = data.get("pr_url", "")
            state.iteration = data.get("iteration", 0)
            state.max_iterations = data.get("max_iterations", 3)
            state.started_at = data.get("started_at", "")
            state.completed_at = data.get("completed_at", "")
            state.repo_path = data.get("repo_path", "")
            state.branch_name = data.get("branch_name", "")
            # Rebuild conversations
            for msg_data in data.get("conversation", []):
                msg = ConversationMessage(
                    role=ConversationRole(msg_data["role"]),
                    content=msg_data["content"],
                    timestamp=msg_data.get("timestamp", ""),
                    stage=msg_data.get("stage", ""),
                    query_to=msg_data.get("query_to", ""),
                )
                state.conversation.append(msg)
            return state
        except Exception as exc:
            log.warning(f"Failed to load pipeline state for {ticket_key}: {exc}")
            return None


class AskOrchestrator:
    """
    Central intelligence that coordinates the full development pipeline.
    
    Uses ask_memory (RAG) as its knowledge base to:
    - Build context for the developer
    - Answer developer questions mid-implementation
    - Validate reviewer decisions against context
    - Sync with main branch before PR
    """

    def __init__(self, repo_path: str = ".", on_notification: Optional[Callable] = None):
        self.repo_path = repo_path
        self.on_notification = on_notification  # callback for user notifications
        self._state: Optional[PipelineState] = None

    @property
    def state(self) -> Optional[PipelineState]:
        return self._state

    def start_pipeline(self, ticket_key: str, branch_name: str = "") -> PipelineState:
        """
        Start the full pipeline for a ticket.
        
        Returns the PipelineState which tracks everything.
        """
        # Check for existing pipeline
        existing = PipelineState.load(ticket_key)
        if existing and existing.stage not in (PipelineStage.DONE, PipelineStage.FAILED):
            log.info(f"Resuming existing pipeline for {ticket_key} at stage {existing.stage.value}")
            self._state = existing
            return existing

        self._state = PipelineState(
            ticket_key=ticket_key,
            repo_path=self.repo_path,
            branch_name=branch_name or f"{ticket_key.lower()}/implementation",
        )
        self._state._save()
        return self._state

    def gather_context(self, ticket_key: str) -> str:
        """
        Phase 1: Use ask_memory to gather all context and build the developer prompt.
        
        This queries:
        - Jira ticket (full hierarchy)
        - Related commits
        - AI session history
        - Main branch recent changes (for awareness)
        """
        if not self._state:
            self.start_pipeline(ticket_key)

        self._state.stage = PipelineStage.CONTEXT_GATHERING
        self._state.add_message(
            ConversationRole.ORCHESTRATOR,
            f"Starting context gathering for {ticket_key}..."
        )

        parts = []

        # 1. Get Jira context via RAG
        jira_answer = ask_question(
            f"Give me all details about ticket {ticket_key} including description, "
            f"acceptance criteria, comments, parent ticket context, and any related tickets",
            top_k=5,
            repo_path=self.repo_path,
        )
        if jira_answer and "No relevant commits" not in jira_answer:
            parts.append(f"## Ticket Context\n{jira_answer}")

        # Delay between LLM calls to avoid rate limits
        import time
        time.sleep(2)

        # 2. Get related commit history
        commit_answer = ask_question(
            f"What code changes are related to {ticket_key}? "
            f"Show me relevant commits, files changed, and implementation patterns",
            top_k=5,
            repo_path=self.repo_path,
        )
        if commit_answer and "No relevant commits" not in commit_answer:
            parts.append(f"## Related Past Work\n{commit_answer}")

        # 3. Check main branch recent changes for awareness
        main_changes = self._get_main_branch_changes()
        if main_changes:
            parts.append(f"## Recent Main Branch Changes (be aware of these)\n{main_changes}")

        time.sleep(2)

        # 4. Get any previous AI session context for this ticket
        ai_session_answer = ask_question(
            f"What has the developer been working on for {ticket_key}? "
            f"Any previous AI conversations or session notes?",
            top_k=3,
            repo_path=self.repo_path,
        )
        if ai_session_answer and "No relevant commits" not in ai_session_answer:
            parts.append(f"## Previous AI Sessions\n{ai_session_answer}")

        # Build the full context prompt
        context = "\n\n---\n\n".join(parts) if parts else f"No context found for {ticket_key}. Please check Jira directly."

        self._state.context_prompt = context
        self._state.add_message(
            ConversationRole.ORCHESTRATOR,
            f"Context gathered ({len(context)} chars). Ready for developer."
        )
        self._state._save()

        return context

    def get_developer_prompt(self, ticket_key: str) -> str:
        """
        Build the complete prompt to send to the developer agent.
        Includes context + instructions + constraints.
        """
        if not self._state or not self._state.context_prompt:
            self.gather_context(ticket_key)

        prompt = f"""# Task: Implement {ticket_key}

## Context (from EngMemory)

{self._state.context_prompt}

## Instructions

1. Implement the changes required by the ticket
2. Follow existing code patterns in the project
3. If you're unsure about something, ask the ask_memory agent BEFORE asking the user
4. Commit your changes with message: `feat({ticket_key}): <description>`
5. Do NOT push to main/master — only commit to the feature branch

## If You Have Questions

Before asking the user, try querying the engineering memory:
- Run: `python -m engmemory.cli ask "your question here"`
- This searches commit history, Jira, and AI sessions for answers

Only escalate to the user if ask_memory can't answer your question.

## Constraints
- Do NOT run `git push origin main` or `git merge main`
- Do NOT delete files outside the project scope  
- All commands are auto-allowed except push/merge to main
- Stay focused on the ticket scope
"""

        if self._state.reviewer_feedback and self._state.iteration > 0:
            prompt += f"""

## Reviewer Feedback (iteration {self._state.iteration})
The reviewer found issues. Fix them:

{self._state.reviewer_feedback}
"""

        if self._state.tester_feedback and self._state.iteration > 0:
            prompt += f"""

## Test Failures (iteration {self._state.iteration})
The tester found problems. Fix them:

{self._state.tester_feedback}
"""

        self._state.stage = PipelineStage.DEVELOPER
        self._state.add_message(
            ConversationRole.ORCHESTRATOR,
            f"Developer prompt built. Iteration {self._state.iteration + 1}."
        )
        self._state._save()
        return prompt

    def handle_developer_question(self, question: str) -> str:
        """
        Developer agent asks a question — answer using ask_memory.
        If ask_memory can't answer, flag for user escalation.
        
        Returns the answer (or escalation notice).
        """
        if not self._state:
            return "No active pipeline. Start one first."

        self._state.add_message(
            ConversationRole.DEVELOPER,
            question,
            query_to="orchestrator",
        )

        # Try answering via RAG
        answer = ask_question(question, top_k=5, repo_path=self.repo_path)

        if answer and "No relevant commits" not in answer and "AI temporarily unavailable" not in answer:
            self._state.add_message(
                ConversationRole.ORCHESTRATOR,
                answer,
            )
            return answer
        else:
            # Can't answer — escalate to user
            escalation_msg = (
                f"I couldn't find an answer in the engineering memory. "
                f"Escalating to user.\n\nOriginal question: {question}"
            )
            self._state.add_message(
                ConversationRole.ORCHESTRATOR,
                escalation_msg,
            )
            # Notify user
            if self.on_notification:
                self.on_notification(
                    f"Developer agent has a question about {self._state.ticket_key}:\n{question}"
                )
            return f"ESCALATE_TO_USER: {question}"

    def handle_developer_done(self, summary: str) -> str:
        """
        Developer signals completion. Move to review phase.
        
        Returns the next action to take.
        """
        if not self._state:
            return "No active pipeline."

        self._state.developer_result = summary
        self._state.add_message(
            ConversationRole.DEVELOPER,
            f"Implementation complete: {summary}",
        )

        # Move to review
        self._state.stage = PipelineStage.REVIEW
        self._state._save()

        return "review"

    def get_reviewer_prompt(self) -> str:
        """Build prompt for the reviewer agent."""
        if not self._state:
            return ""

        return f"""# Review Task: {self._state.ticket_key}

## Original Requirements

{self._state.context_prompt[:3000]}

## Developer's Implementation Summary

{self._state.developer_result}

## Instructions

1. Run `git diff main` to see all changes
2. Read the modified/new files
3. Check against the requirements above
4. Provide verdict: APPROVED, CHANGES_REQUESTED, or QUESTIONS

## Evaluation Criteria
- Does the code fulfill the ticket requirements?
- Are there security issues (OWASP top 10)?
- Does it follow existing code patterns?
- Are edge cases handled?
- Is anything missing from the requirements?

## Response Format
Start your response with one of:
- `VERDICT: APPROVED` — ready for testing
- `VERDICT: CHANGES_REQUESTED` — list issues to fix
- `VERDICT: QUESTIONS` — need clarification
"""

    def handle_reviewer_response(self, response: str) -> str:
        """
        Process reviewer's response. Route to next stage.
        
        Returns: "developer" (needs fixes), "testing" (approved), or "questions" (needs answers)
        """
        if not self._state:
            return "No active pipeline."

        self._state.add_message(ConversationRole.REVIEWER, response)

        # Parse verdict
        response_upper = response.upper()
        if "VERDICT: APPROVED" in response_upper or "APPROVED" in response_upper[:50]:
            self._state.reviewer_verdict = "APPROVED"
            self._state.stage = PipelineStage.TESTING
            self._state._save()
            return "testing"
        elif "VERDICT: CHANGES_REQUESTED" in response_upper or "CHANGES_REQUESTED" in response_upper[:50]:
            self._state.reviewer_verdict = "CHANGES_REQUESTED"
            self._state.reviewer_feedback = response
            self._state.iteration += 1
            if self._state.iteration >= self._state.max_iterations:
                self._state.stage = PipelineStage.FAILED
                self._state._save()
                return "max_iterations"
            self._state.stage = PipelineStage.DEVELOPER
            self._state._save()
            return "developer"
        else:
            self._state.reviewer_verdict = "QUESTIONS"
            self._state.reviewer_feedback = response
            # Try answering the questions via ask_memory
            answer = self.handle_developer_question(response)
            if "ESCALATE_TO_USER" in answer:
                return "questions"
            # Answer found — send back to reviewer
            self._state.add_message(
                ConversationRole.ORCHESTRATOR,
                f"Answer to your questions:\n{answer}",
            )
            return "review_continue"

    def get_tester_prompt(self) -> str:
        """Build prompt for the tester agent."""
        if not self._state:
            return ""

        return f"""# Test Task: {self._state.ticket_key}

## What Was Implemented

{self._state.developer_result}

## Original Requirements

{self._state.context_prompt[:2000]}

## Instructions

1. Run `git diff main` to see changes
2. Run any existing tests (`pytest`, `npm test`, etc.)
3. Test the new functionality manually if needed
4. Write basic tests for the new code if none exist
5. Verify no regressions

## Response Format
Start your response with one of:
- `VERDICT: PASSED` — all tests pass
- `VERDICT: FAILED` — list what broke
- `VERDICT: PARTIAL` — some pass, some fail

Include details of what was tested and results.
"""

    def handle_tester_response(self, response: str) -> str:
        """
        Process tester's response. Route to next stage.
        
        Returns: "developer" (test failures), "pr_creation" (all pass)
        """
        if not self._state:
            return "No active pipeline."

        self._state.add_message(ConversationRole.TESTER, response)

        response_upper = response.upper()
        if "VERDICT: PASSED" in response_upper or "PASSED" in response_upper[:50]:
            self._state.tester_verdict = "PASSED"
            self._state.stage = PipelineStage.PR_CREATION
            self._state._save()
            return "pr_creation"
        elif "VERDICT: FAILED" in response_upper or "FAILED" in response_upper[:50]:
            self._state.tester_verdict = "FAILED"
            self._state.tester_feedback = response
            self._state.iteration += 1
            if self._state.iteration >= self._state.max_iterations:
                self._state.stage = PipelineStage.FAILED
                self._state._save()
                return "max_iterations"
            self._state.stage = PipelineStage.DEVELOPER
            self._state._save()
            return "developer"
        else:
            # Partial — treat as needing fixes
            self._state.tester_verdict = "PARTIAL"
            self._state.tester_feedback = response
            self._state.iteration += 1
            self._state.stage = PipelineStage.DEVELOPER
            self._state._save()
            return "developer"

    def create_pr(self) -> str:
        """
        Create a pull request after tests pass.
        
        1. Fetch latest main
        2. Rebase/merge if needed
        3. Push branch
        4. Create PR via GitHub API
        """
        if not self._state:
            return "No active pipeline."

        self._state.stage = PipelineStage.PR_CREATION
        self._state.add_message(
            ConversationRole.ORCHESTRATOR,
            "Creating pull request..."
        )

        # Sync with main first
        sync_result = self._sync_with_main()
        if sync_result:
            self._state.add_message(
                ConversationRole.ORCHESTRATOR,
                f"Main branch sync: {sync_result}"
            )

        # Push branch
        push_result = self._run_git(["push", "origin", self._state.branch_name, "--set-upstream"])
        if push_result.get("error"):
            self._state.add_message(
                ConversationRole.ORCHESTRATOR,
                f"Push failed: {push_result['error']}"
            )
            return f"Push failed: {push_result['error']}"

        # Create PR (via GitHub CLI if available, otherwise just report)
        pr_result = self._create_github_pr()
        self._state.pr_url = pr_result.get("url", "")
        self._state.stage = PipelineStage.WAITING_FOR_MERGE
        self._state.add_message(
            ConversationRole.ORCHESTRATOR,
            f"PR created: {self._state.pr_url}. Waiting for user to review and merge."
        )

        # Notify user
        if self.on_notification:
            self.on_notification(
                f"PR ready for {self._state.ticket_key}: {self._state.pr_url}\n"
                f"Please review and merge when ready."
            )

        self._state._save()
        return self._state.pr_url

    def handle_user_instruction(self, instruction: str) -> str:
        """
        User provides additional instructions (after PR, or mid-work).
        Routes to appropriate stage.
        """
        if not self._state:
            return "No active pipeline. Use start_pipeline() first."

        self._state.add_message(ConversationRole.USER, instruction)

        # If waiting for merge and user says merge
        if self._state.stage == PipelineStage.WAITING_FOR_MERGE:
            if any(word in instruction.lower() for word in ["merge", "approve", "lgtm", "ship"]):
                return self._do_merge()
            elif any(word in instruction.lower() for word in ["fix", "change", "update"]):
                # User wants more changes after PR
                self._state.stage = PipelineStage.DEVELOPER
                self._state.reviewer_feedback = instruction
                self._state._save()
                return "developer"

        # General instruction — feed to developer
        self._state.stage = PipelineStage.DEVELOPER
        self._state._save()
        return "developer"

    def _sync_with_main(self) -> str:
        """Fetch and merge main into current branch."""
        # Fetch
        fetch_result = self._run_git(["fetch", "origin", "main"])
        if fetch_result.get("error"):
            return f"Fetch failed: {fetch_result['error']}"

        # Try merge
        merge_result = self._run_git(["merge", "origin/main", "--no-edit"])
        if merge_result.get("error"):
            if "CONFLICT" in merge_result.get("output", ""):
                return "MERGE_CONFLICT: Manual resolution needed"
            return f"Merge failed: {merge_result['error']}"

        return merge_result.get("output", "Up to date")

    def _get_main_branch_changes(self) -> str:
        """Get recent changes on main for context."""
        result = self._run_git(["log", "origin/main", "--oneline", "-10"])
        return result.get("output", "")

    def _create_github_pr(self) -> dict:
        """Create PR using GitHub CLI (gh) if available."""
        try:
            result = subprocess.run(
                ["gh", "pr", "create",
                 "--title", f"[{self._state.ticket_key}] {self._state.developer_result[:60]}",
                 "--body", self._build_pr_body(),
                 "--base", "main",
                 "--head", self._state.branch_name],
                cwd=self.repo_path,
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                url = result.stdout.strip()
                return {"url": url, "success": True}
            else:
                return {"error": result.stderr, "success": False}
        except FileNotFoundError:
            return {"error": "GitHub CLI (gh) not installed", "success": False, "url": ""}
        except Exception as exc:
            return {"error": str(exc), "success": False, "url": ""}

    def _build_pr_body(self) -> str:
        """Build PR description."""
        return f"""## {self._state.ticket_key}

### Changes
{self._state.developer_result}

### Review
Reviewer verdict: {self._state.reviewer_verdict}

### Testing
Tester verdict: {self._state.tester_verdict}

---
*Auto-generated by EngMemory Pipeline*
"""

    def _do_merge(self) -> str:
        """Merge via tester agent (user approved)."""
        self._state.stage = PipelineStage.DONE
        self._state.completed_at = datetime.now(timezone.utc).isoformat()
        self._state.add_message(
            ConversationRole.ORCHESTRATOR,
            "User approved merge. Pipeline complete."
        )
        self._state._save()
        return "done"

    def _run_git(self, args: list[str]) -> dict:
        """Run a git command."""
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=self.repo_path,
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return {"output": result.stdout.strip(), "success": True}
            else:
                return {"output": result.stdout.strip(), "error": result.stderr.strip(), "success": False}
        except Exception as exc:
            return {"error": str(exc), "success": False}

    def get_conversation_log(self) -> list[dict]:
        """Get the full conversation log for display in the extension."""
        if not self._state:
            return []
        return [m.to_dict() for m in self._state.conversation]

    def get_status(self) -> dict:
        """Get current pipeline status."""
        if not self._state:
            return {"stage": "no_pipeline", "ticket_key": None}
        return {
            "ticket_key": self._state.ticket_key,
            "stage": self._state.stage.value,
            "iteration": self._state.iteration,
            "reviewer_verdict": self._state.reviewer_verdict,
            "tester_verdict": self._state.tester_verdict,
            "pr_url": self._state.pr_url,
            "messages": len(self._state.conversation),
        }
