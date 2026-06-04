"""
engmemory.agent — Autonomous AI Agent

Transforms engmemory from a library into an autonomous agent that:
1. Watches for triggers (Jira ticket, new branch, manual invoke)
2. Gathers context (Jira, commits, AI sessions, discussions)
3. Plans a solution
4. Executes code changes via tools (git, file ops, Copilot)
5. Self-corrects on failure with retry logic
6. Multi-agent loop: Context → Code → Review → (iterate)
7. Background daemon: auto-process new Jira tickets
8. Learns from developer feedback

Usage:
    from engmemory.agent import Agent
    agent = Agent(repo_path=".")
    agent.run(trigger="jira", issue_key="ENG-456")

    # Or multi-agent mode:
    from engmemory.agent.multi_agent import MultiAgentOrchestrator
    orchestrator = MultiAgentOrchestrator(repo_path=".")
    orchestrator.run(issue_key="ENG-456")
"""

from .engine import Agent
from .context_builder import ContextBuilder
from .watcher import Watcher

__all__ = ["Agent", "ContextBuilder", "Watcher"]
