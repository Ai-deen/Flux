"""
AI Intelligence Module - Powers the "smart" features of EngMemory.

- Ticket progress summaries
- Blocker detection
- Next step suggestions
- Risk assessment
"""

from __future__ import annotations

import logging
from typing import Optional

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from ..utils.config import config
from ..orchestrator.session import DevSession

log = logging.getLogger(__name__)


def _get_llm_response(system_prompt: str, user_prompt: str) -> Optional[str]:
    """Call LLM (OpenRouter or OpenAI) and return text response."""
    if not HAS_HTTPX:
        return None

    # Try OpenRouter first
    if config.openrouter_api_key:
        import requests
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {config.openrouter_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.openrouter_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 800,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        log.warning("OpenRouter error: %s", resp.text[:200])
        return None

    # Fallback to OpenAI
    if config.openai_api_key:
        import requests
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {config.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.openai_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 800,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        log.warning("OpenAI error: %s", resp.text[:200])
        return None

    return None


def generate_ticket_summary(session: DevSession) -> dict:
    """
    Generate an AI-powered summary of a ticket's progress.
    
    Returns:
        {
            "summary": "...",
            "status_assessment": "on_track | at_risk | blocked",
            "what_done": "...",
            "blockers": ["..."],
            "next_steps": ["..."],
            "confidence": 0.0-1.0
        }
    """
    system_prompt = """You are an engineering manager's AI assistant. Given context about a development ticket 
(Jira details, Slack discussions, commits, AI agent interactions), produce a concise status report.

Output EXACTLY this JSON format (no markdown, no code fences):
{
  "summary": "2-3 sentence overview of what this ticket is about and where it stands",
  "status_assessment": "on_track or at_risk or blocked",
  "what_done": "What work has been completed so far (1-2 sentences)",
  "blockers": ["List of blockers or empty array"],
  "next_steps": ["Suggested next actions"],
  "confidence": 0.8
}"""

    # Build context from session
    context_parts = []
    context_parts.append(f"Ticket: [{session.ticket_key}] {session.summary}")
    context_parts.append(f"Type: {session.issue_type} | Priority: {session.priority}")
    context_parts.append(f"Status: {session.status}")
    context_parts.append(f"Assignee: {session.assignee_email or 'Unassigned'}")
    context_parts.append(f"Branch: {session.branch_name}")

    if session.context.jira_description:
        context_parts.append(f"\nJira Description:\n{session.context.jira_description[:500]}")

    if session.context.jira_comments:
        context_parts.append(f"\nJira Comments ({len(session.context.jira_comments)}):")
        for c in session.context.jira_comments[-5:]:
            context_parts.append(f"  - {c[:150]}")

    if session.context.slack_messages:
        context_parts.append(f"\nSlack Discussion ({len(session.context.slack_messages)} messages):")
        for m in session.context.slack_messages[-5:]:
            context_parts.append(f"  - {m[:150]}")

    if session.context.related_commits:
        context_parts.append(f"\nRelated Commits:")
        for c in session.context.related_commits[:5]:
            context_parts.append(f"  - {c}")

    if session.pending_questions:
        context_parts.append(f"\nPending Questions (AI is blocked on these):")
        for q in session.pending_questions:
            context_parts.append(f"  - {q}")

    if session.updates_since_last_check:
        context_parts.append(f"\nRecent Updates:")
        for u in session.updates_since_last_check[-5:]:
            context_parts.append(f"  - {u}")

    user_prompt = "\n".join(context_parts)

    # Call LLM
    response = _get_llm_response(system_prompt, user_prompt)

    if response:
        try:
            import json
            # Clean response (remove markdown fences if present)
            clean = response.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1]
                clean = clean.rsplit("```", 1)[0]
            return json.loads(clean)
        except Exception as e:
            log.warning("Failed to parse AI summary: %s", e)
            return {
                "summary": response[:300],
                "status_assessment": "unknown",
                "what_done": "",
                "blockers": [],
                "next_steps": [],
                "confidence": 0.5,
            }

    # Fallback: generate rule-based summary
    return _generate_fallback_summary(session)


def _generate_fallback_summary(session: DevSession) -> dict:
    """Generate a basic summary without LLM."""
    blockers = session.pending_questions if session.pending_questions else []

    if session.status == "blocked":
        assessment = "blocked"
    elif blockers:
        assessment = "at_risk"
    else:
        assessment = "on_track"

    what_done = []
    if session.context.related_commits:
        what_done.append(f"{len(session.context.related_commits)} related commits found")
    if session.context.slack_messages:
        what_done.append(f"{len(session.context.slack_messages)} Slack messages captured")
    if session.context.jira_comments:
        what_done.append(f"{len(session.context.jira_comments)} Jira comments tracked")

    return {
        "summary": f"[{session.ticket_key}] {session.summary} — Status: {session.status}",
        "status_assessment": assessment,
        "what_done": "; ".join(what_done) if what_done else "Session initialized, gathering context",
        "blockers": blockers,
        "next_steps": ["Continue development", "Check for new updates"],
        "confidence": 0.6,
    }


def detect_risks(sessions: list[DevSession]) -> list[dict]:
    """Detect risks across all active sessions."""
    risks = []
    for s in sessions:
        if s.status == "blocked":
            risks.append({
                "ticket_key": s.ticket_key,
                "risk": "blocked",
                "detail": f"AI agent is blocked waiting for answers: {s.pending_questions[:2]}",
                "severity": "high",
            })
        elif s.status == "waiting" and s.pending_questions:
            risks.append({
                "ticket_key": s.ticket_key,
                "risk": "waiting_on_input",
                "detail": f"Needs clarification: {s.pending_questions[0][:80]}",
                "severity": "medium",
            })
    return risks
