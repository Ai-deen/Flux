"""
Orchestrator module - Reactive development automation.

Watches Jira, Slack, and Git for changes, maintains development sessions,
and feeds context to the AI agent.
"""

from engmemory.orchestrator.session import DevSession, SessionContext
from engmemory.orchestrator.poller import Poller
from engmemory.orchestrator.context_builder import ContextBuilder
from engmemory.orchestrator.git_automation import GitAutomation

__all__ = ["DevSession", "SessionContext", "Poller", "ContextBuilder", "GitAutomation"]
