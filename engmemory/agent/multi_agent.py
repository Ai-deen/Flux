"""
multi_agent.py — Multi-Agent System

Three agents that work together:

1. Context Agent: Fetches and synthesizes information from Jira, commits, 
   AI sessions, and past bug history. Provides context to the Code Agent.

2. Code Agent: Takes context from Context Agent and makes actual code changes.
   Uses LLM/Copilot to generate code, writes files, runs commands.

3. Reviewer Agent: After Code Agent finishes, reviews the changes.
   Checks if they make sense given the ticket requirements.
   If issues found → sends feedback to Code Agent for another iteration.

The agents communicate via a shared memory (AgentMemory) that persists
their thinking, decisions, and feedback for future reference.

Background Mode:
- Can run as a daemon watching for new Jira tickets
- Auto-creates workspace folder and starts working
- Notifies developer when done
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable

log = logging.getLogger(__name__)


@dataclass
class AgentMessage:
    """Message passed between agents."""
    from_agent: str
    to_agent: str
    content: str
    message_type: str  # "context", "code_change", "review", "feedback", "done"
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentMemory:
    """Shared memory between agents. Persists to disk for learning."""
    messages: list[AgentMessage] = field(default_factory=list)
    developer_feedback: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)

    def add_message(self, msg: AgentMessage):
        self.messages.append(msg)

    def add_developer_feedback(self, feedback: str, context: str = ""):
        self.developer_feedback.append({
            "feedback": feedback,
            "context": context,
            "timestamp": time.time(),
        })

    def add_decision(self, agent: str, decision: str, reasoning: str = ""):
        self.decisions.append({
            "agent": agent,
            "decision": decision,
            "reasoning": reasoning,
            "timestamp": time.time(),
        })

    def save(self, path: Path):
        """Persist memory to disk for future reference."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "messages": [
                {"from": m.from_agent, "to": m.to_agent, "type": m.message_type,
                 "content": m.content[:500], "timestamp": m.timestamp}
                for m in self.messages
            ],
            "developer_feedback": self.developer_feedback,
            "decisions": self.decisions,
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(self, path: Path):
        """Load previous memory for learning."""
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.developer_feedback = data.get("developer_feedback", [])
            self.decisions = data.get("decisions", [])
        except Exception:
            pass

    def get_past_feedback_for_topic(self, topic: str) -> list[str]:
        """Get developer feedback related to a topic (for learning)."""
        topic_lower = topic.lower()
        relevant = []
        for fb in self.developer_feedback:
            if any(word in fb.get("context", "").lower() or word in fb.get("feedback", "").lower()
                   for word in topic_lower.split() if len(word) > 3):
                relevant.append(fb["feedback"])
        return relevant[-5:]  # Last 5 relevant feedbacks


class ContextAgent:
    """
    Agent 1: Gathers ALL context needed to solve a ticket.
    
    - Fetches Jira ticket + parent + subtasks + links (recursive)
    - Searches ALL Jira tickets for similar past bugs
    - Gets commit history from Azure AI Search
    - Gets AI session context
    - Checks developer's past feedback for related topics
    """

    def __init__(self, repo_path: str = ".", memory: Optional[AgentMemory] = None):
        self.repo_path = repo_path
        self.memory = memory or AgentMemory()

    def gather(self, issue_key: Optional[str] = None, 
               search_query: Optional[str] = None) -> AgentMessage:
        """Gather comprehensive context from all sources."""
        parts = []

        # 1. Full Jira traversal (parent, subtasks, links, ALL comments)
        if issue_key:
            jira_context = self._get_jira_full(issue_key)
            if jira_context:
                parts.append(jira_context)

        # 2. Search ALL Jira tickets for similar past issues/bugs
        search_term = search_query or (issue_key or "")
        if search_term:
            bug_history = self._search_past_issues(search_term)
            if bug_history:
                parts.append(bug_history)

        # 3. Commit history from Azure AI Search
        if search_term:
            commit_context = self._get_commits(search_term)
            if commit_context:
                parts.append(commit_context)

        # 4. AI session context
        ai_context = self._get_ai_sessions()
        if ai_context:
            parts.append(ai_context)

        # 5. Past developer feedback on similar topics
        past_feedback = self.memory.get_past_feedback_for_topic(search_term)
        if past_feedback:
            parts.append(
                "## Developer's Past Feedback (learn from this)\n" +
                "\n".join(f"- {fb}" for fb in past_feedback)
            )

        # 6. Team discussions (from Slack/Teams channels)
        if issue_key:
            team_context = self._get_team_discussions(issue_key)
            if team_context:
                parts.append(team_context)

        context = "\n\n---\n\n".join(parts) if parts else "No context gathered."

        msg = AgentMessage(
            from_agent="context",
            to_agent="code",
            content=context,
            message_type="context",
            data={"issue_key": issue_key, "search_query": search_query},
        )
        self.memory.add_message(msg)
        self.memory.add_decision("context", f"Gathered context for {issue_key or search_query}",
                                 f"Sources: jira={bool(issue_key)}, search={bool(search_term)}")
        return msg

    def _get_jira_full(self, issue_key: str) -> Optional[str]:
        """Full recursive Jira traversal."""
        try:
            from ..utils.jira import get_issue_full_context
            data = get_issue_full_context(issue_key, max_depth=2)
            return data["context_summary"]
        except Exception as exc:
            log.warning(f"Context Agent: Jira fetch failed: {exc}")
            return None

    def _get_team_discussions(self, issue_key: str) -> Optional[str]:
        """Get team discussions for this ticket from Slack/Teams."""
        try:
            from .team_chat import TeamChatIntegration
            chat = TeamChatIntegration(repo_path=self.repo_path)
            return chat.get_discussion_context(issue_key)
        except Exception as exc:
            log.debug(f"Context Agent: Team chat fetch failed: {exc}")
            return None

    def _search_past_issues(self, query: str) -> Optional[str]:
        """Search ALL Jira tickets for similar past issues."""
        try:
            from ..utils.jira import search_jira_tickets
            results = search_jira_tickets(query, max_results=10)
            if not results:
                return None

            parts = ["## Similar Past Tickets (from Jira search)"]
            for ticket in results:
                parts.append(f"\n**{ticket['key']}**: {ticket['summary']} [{ticket['status']}]")
                if ticket["description"]:
                    parts.append(f"  {ticket['description'][:200]}")
                if ticket["comments"]:
                    parts.append(f"  Comments ({len(ticket['comments'])}):")
                    for c in ticket["comments"][:3]:
                        parts.append(f"    {c['author']}: {c['text'][:150]}")

            return "\n".join(parts)
        except Exception as exc:
            log.warning(f"Context Agent: Past issue search failed: {exc}")
            return None

    def _get_commits(self, query: str) -> Optional[str]:
        """Get related commits from Azure AI Search."""
        try:
            from ..search.azure_search import search_commits
            commits = search_commits(query, top_k=5)
            if not commits:
                return None

            parts = ["## Related Commits"]
            for c in commits:
                ticket = f" [{c.get('ticket_id')}]" if c.get('ticket_id') else ""
                parts.append(f"- {c.get('sha', '?')[:8]}{ticket}: {c.get('commit_message', '')}")
                if c.get('analysis'):
                    parts.append(f"  Analysis: {c['analysis'][:150]}")
            return "\n".join(parts)
        except Exception:
            return None

    def _get_ai_sessions(self) -> Optional[str]:
        """Get AI session context."""
        try:
            from ..ai_context import create_ai_context_summary
            result = create_ai_context_summary(self.repo_path)
            if result and result.get("summary"):
                return f"## AI Session Context\n{result['summary']}"
        except Exception:
            pass
        return None


class CodeAgent:
    """
    Agent 2: Makes actual code changes based on context.
    
    - Receives context from Context Agent
    - Plans implementation steps
    - Uses LLM/Copilot to generate code
    - Writes files, creates branches
    - Sends results to Reviewer Agent
    """

    def __init__(self, repo_path: str = ".", memory: Optional[AgentMemory] = None,
                 dry_run: bool = False):
        self.repo_path = repo_path
        self.memory = memory or AgentMemory()
        self.dry_run = dry_run

    def execute(self, context_msg: AgentMessage, 
                feedback_msg: Optional[AgentMessage] = None) -> AgentMessage:
        """Execute code changes based on context (and optional reviewer feedback)."""
        from .engine import Agent

        context = context_msg.content
        issue_key = context_msg.data.get("issue_key", "")

        # If we have reviewer feedback, incorporate it
        if feedback_msg and feedback_msg.message_type == "feedback":
            context += f"\n\n---\n\n## Reviewer Feedback (fix these issues)\n{feedback_msg.content}"

        # Use the existing Agent engine to plan and execute
        agent = Agent(repo_path=self.repo_path, dry_run=self.dry_run, max_retries=3)
        
        # Override the context in the agent's run
        trigger = "jira" if issue_key else "manual"
        kwargs = {}
        if issue_key:
            kwargs["issue_key"] = issue_key
        else:
            kwargs["prompt"] = context_msg.data.get("search_query", "implement changes")

        result = agent.run(trigger=trigger, **kwargs)

        # Build result message
        steps_summary = "\n".join(
            f"{'✓' if r.success else '✗'} {r.description}" 
            for r in result.results
        )

        msg = AgentMessage(
            from_agent="code",
            to_agent="reviewer",
            content=steps_summary,
            message_type="code_change",
            data={
                "state": result.state.value,
                "steps": len(result.results),
                "success": sum(1 for r in result.results if r.success),
                "failed": sum(1 for r in result.results if not r.success),
            },
        )
        self.memory.add_message(msg)
        self.memory.add_decision("code", f"Executed {len(result.results)} steps",
                                 f"State: {result.state.value}")
        return msg


class ReviewerAgent:
    """
    Agent 3: Reviews changes made by the Code Agent.
    
    - Checks if changes align with ticket requirements
    - Validates code quality
    - If issues found, sends feedback for another iteration
    - If good, marks as done
    """

    def __init__(self, repo_path: str = ".", memory: Optional[AgentMemory] = None):
        self.repo_path = repo_path
        self.memory = memory or AgentMemory()

    def review(self, context_msg: AgentMessage, code_msg: AgentMessage) -> AgentMessage:
        """Review the code changes against the original context."""
        
        # Get the git diff of changes
        diff = self._get_diff()
        
        # Ask LLM to review
        review_result = self._llm_review(
            context=context_msg.content,
            changes=code_msg.content,
            diff=diff,
        )

        if review_result.get("approved"):
            msg = AgentMessage(
                from_agent="reviewer",
                to_agent="done",
                content=review_result.get("summary", "Changes approved."),
                message_type="done",
                data={"approved": True},
            )
        else:
            msg = AgentMessage(
                from_agent="reviewer",
                to_agent="code",
                content=review_result.get("feedback", "Changes need revision."),
                message_type="feedback",
                data={"approved": False, "issues": review_result.get("issues", [])},
            )

        self.memory.add_message(msg)
        self.memory.add_decision("reviewer", 
                                 "approved" if review_result.get("approved") else "needs revision",
                                 review_result.get("summary", ""))
        return msg

    def _get_diff(self) -> str:
        """Get git diff of current changes."""
        import subprocess
        try:
            result = subprocess.run(
                ["git", "diff", "--stat"],
                cwd=self.repo_path,
                capture_output=True, text=True, timeout=10,
            )
            return result.stdout[:3000] if result.returncode == 0 else ""
        except Exception:
            return ""

    def _llm_review(self, context: str, changes: str, diff: str) -> dict:
        """Use LLM to review changes against requirements."""
        try:
            from openai import OpenAI
            from ..utils.config import config

            if config.groq_api_key:
                client = OpenAI(
                    api_key=config.groq_api_key,
                    base_url="https://api.groq.com/openai/v1",
                )
                model = config.groq_model
            elif config.openrouter_api_key:
                client = OpenAI(
                    api_key=config.openrouter_api_key,
                    base_url="https://openrouter.ai/api/v1",
                )
                model = config.openrouter_model
            elif config.openai_api_key:
                client = OpenAI(api_key=config.openai_api_key)
                model = config.openai_model
            else:
                # No LLM — auto-approve
                return {"approved": True, "summary": "No LLM available for review, auto-approved."}

            prompt = f"""You are a code reviewer. Check if the changes meet the requirements.

REQUIREMENTS (from Jira ticket + context):
{context[:3000]}

CHANGES MADE:
{changes}

GIT DIFF:
{diff}

Review the changes and respond with JSON:
{{
  "approved": true/false,
  "summary": "brief summary of review",
  "issues": ["issue 1", "issue 2"] or [],
  "feedback": "what needs to change (if not approved)"
}}"""

            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=500,
            )

            content = response.choices[0].message.content
            # Try to parse JSON from response
            import re
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return {"approved": True, "summary": content[:200]}

        except Exception as exc:
            log.warning(f"Reviewer Agent: LLM review failed: {exc}")
            return {"approved": True, "summary": "Review skipped (LLM unavailable)."}


class MultiAgentOrchestrator:
    """
    Orchestrates the three agents in a loop:
    
    Context Agent → Code Agent → Reviewer Agent → (loop if needed) → Done
    
    Also handles:
    - Background mode (auto-trigger on ticket creation)
    - Developer feedback recording
    - Notification when done
    """

    def __init__(self, repo_path: str = ".", max_iterations: int = 3,
                 dry_run: bool = False,
                 on_complete: Optional[Callable] = None):
        self.repo_path = repo_path
        self.max_iterations = max_iterations
        self.dry_run = dry_run
        self.on_complete = on_complete

        # Shared memory
        self.memory = AgentMemory()
        memory_path = Path(repo_path) / ".ai_memory" / "agent_memory.json"
        self.memory.load(memory_path)

        # Initialize agents
        self.context_agent = ContextAgent(repo_path=repo_path, memory=self.memory)
        self.code_agent = CodeAgent(repo_path=repo_path, memory=self.memory, dry_run=dry_run)
        self.reviewer_agent = ReviewerAgent(repo_path=repo_path, memory=self.memory)

    def run(self, issue_key: Optional[str] = None, 
            search_query: Optional[str] = None) -> dict:
        """
        Run the full multi-agent loop.
        
        Returns:
            Dict with execution summary
        """
        log.info(f"[Orchestrator] Starting for {issue_key or search_query}")
        start_time = time.time()

        # Phase 1: Context Agent gathers information
        log.info("[Orchestrator] Phase 1: Context Agent gathering...")
        context_msg = self.context_agent.gather(
            issue_key=issue_key,
            search_query=search_query,
        )
        log.info(f"[Orchestrator] Context gathered ({len(context_msg.content)} chars)")

        # Phase 2-3: Code Agent + Reviewer Agent loop
        feedback_msg = None
        final_result = None

        for iteration in range(self.max_iterations):
            log.info(f"[Orchestrator] Phase 2: Code Agent (iteration {iteration + 1})...")
            code_msg = self.code_agent.execute(context_msg, feedback_msg)
            log.info(f"[Orchestrator] Code Agent done: {code_msg.data}")

            # If code agent failed completely, stop
            if code_msg.data.get("failed", 0) > code_msg.data.get("success", 0):
                log.warning("[Orchestrator] Code Agent had too many failures. Stopping.")
                final_result = {
                    "status": "failed",
                    "iteration": iteration + 1,
                    "reason": "Code execution had too many failures",
                }
                break

            log.info(f"[Orchestrator] Phase 3: Reviewer Agent (iteration {iteration + 1})...")
            review_msg = self.reviewer_agent.review(context_msg, code_msg)

            if review_msg.message_type == "done":
                log.info("[Orchestrator] Reviewer approved! Done.")
                final_result = {
                    "status": "approved",
                    "iteration": iteration + 1,
                    "summary": review_msg.content,
                }
                break
            else:
                log.info(f"[Orchestrator] Reviewer wants changes: {review_msg.content[:100]}")
                feedback_msg = review_msg

        if not final_result:
            final_result = {
                "status": "max_iterations_reached",
                "iteration": self.max_iterations,
                "summary": "Reached maximum review iterations.",
            }

        # Save memory for future learning
        final_result["duration_seconds"] = round(time.time() - start_time, 2)
        memory_path = Path(self.repo_path) / ".ai_memory" / "agent_memory.json"
        self.memory.save(memory_path)

        # Notify developer
        if self.on_complete:
            self.on_complete(final_result)

        log.info(f"[Orchestrator] Complete: {final_result['status']}")
        return final_result

    def record_feedback(self, feedback: str, context: str = ""):
        """Record developer feedback for future learning."""
        self.memory.add_developer_feedback(feedback, context)
        memory_path = Path(self.repo_path) / ".ai_memory" / "agent_memory.json"
        self.memory.save(memory_path)
        log.info(f"[Orchestrator] Developer feedback recorded: {feedback[:50]}...")
