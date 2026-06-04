"""
rag.py

RAG (Retrieval-Augmented Generation) queries over commit history.
Uses Azure AI Search to find relevant commits, then uses LLM to answer questions.
"""

from __future__ import annotations

import logging
from typing import Optional

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from .azure_search import search_commits
from ..utils.config import config

log = logging.getLogger(__name__)


def ask_question(question: str, top_k: int = 5, repo_path: str = ".") -> str:
    """
    Answer a question using RAG over commit history + AI session context + Jira.
    
    Args:
        question: The question to answer
        top_k: Number of commits to retrieve for context
        repo_path: Path to git repo root
    
    Returns:
        The AI-generated answer
    """
    # 1. Search AI session summaries first (developer intent)
    ai_context = _load_ai_sessions(repo_path, question)

    # 2. Retrieve relevant commits
    commits = search_commits(question, top_k=top_k)

    # 3. Fetch Jira tickets if question is about tickets/issues
    jira_context = _load_jira_context(question)
    
    if not commits and not ai_context and not jira_context:
        return "No relevant commits found. Make sure commits are indexed in Azure AI Search."
    
    # 4. Build context from commits + AI sessions + Jira
    context = _build_context(commits)
    if ai_context:
        context = f"=== Developer AI Session Notes ===\n{ai_context}\n\n{context}"
    if jira_context:
        context = f"=== Jira Tickets ===\n{jira_context}\n\n{context}"
    
    # 5. Generate answer using LLM
    answer = _generate_answer(question, context)
    
    return answer


def _load_jira_context(question: str) -> str:
    """Fetch Jira tickets when question is about tickets/issues/tasks."""
    # Keywords that suggest the user wants Jira info
    jira_keywords = ['ticket', 'jira', 'issue', 'task', 'story', 'bug', 'sprint',
                     'backlog', 'todo', 'to do', 'assigned', 'kan-', 'eng-', 'proj-',
                     'solved', 'pending', 'status', 'board']
    question_lower = question.lower()

    if not any(kw in question_lower for kw in jira_keywords):
        return ""

    try:
        import re
        import requests as req
        from requests.auth import HTTPBasicAuth
        from ..utils.config import config

        if not all([config.jira_domain, config.jira_email, config.jira_api_token]):
            return ""

        # Check if question asks about a specific ticket
        ticket_match = re.search(r'([A-Z][A-Z0-9]+-\d+)', question.upper())
        if ticket_match:
            from ..utils.jira import get_issue_full_context
            try:
                data = get_issue_full_context(ticket_match.group(1), max_depth=2)
                return data["context_summary"]
            except Exception:
                # Fallback to simple fetch
                from ..utils.jira import get_issue_details
                details = get_issue_details(ticket_match.group(1))
                comments_text = ""
                if details.get('comments'):
                    comments_text = "\n  Comments:\n" + "\n".join(
                        f"    - {c['author']}: {c['text']}" for c in details['comments']
                    )
                return (
                    f"Ticket: {details['key']}\n"
                    f"  Summary: {details['summary']}\n"
                    f"  Status: {details['status']}\n"
                    f"  Type: {details['issue_type']} | Priority: {details['priority']}\n"
                    f"  Assignee: {details['assignee']}\n"
                    f"  Description: {details['description']}"
                    f"{comments_text}"
                )

        # Otherwise fetch all recent tickets
        url = f"https://{config.jira_domain}/rest/api/3/search/jql"
        headers = {"Accept": "application/json"}
        auth = HTTPBasicAuth(config.jira_email, config.jira_api_token)
        params = {
            "jql": "project is not EMPTY ORDER BY updated DESC",
            "maxResults": 20,
            "fields": "summary,status,assignee,priority,issuetype,description"
        }

        response = req.get(url, headers=headers, auth=auth, params=params)
        if response.status_code != 200:
            return ""

        data = response.json()
        issues = data.get("issues", [])
        if not issues:
            return ""

        parts = []
        for issue in issues:
            fields = issue.get("fields", {})
            status = fields.get("status", {}).get("name", "Unknown")
            assignee_obj = fields.get("assignee")
            assignee = assignee_obj.get("displayName", "Unassigned") if assignee_obj else "Unassigned"
            priority = fields.get("priority", {}).get("name", "None") if fields.get("priority") else "None"
            issue_type = fields.get("issuetype", {}).get("name", "Task")
            parts.append(
                f"- {issue['key']}: {fields.get('summary', '')} "
                f"[{status}] ({issue_type}, {priority}, Assignee: {assignee})"
            )

        return "\n".join(parts)

    except Exception as exc:
        log.warning(f"Could not load Jira context: {exc}")
        return ""


def _load_ai_sessions(repo_path: str, question: str) -> str:
    """Load AI session summaries from Azure Blob Storage."""
    try:
        from ..storage.azure_blob import _get_blob_service_client

        import json

        blob_service = _get_blob_service_client()
        if not blob_service:
            return ""

        container = blob_service.get_container_client("ai-sessions")

        question_lower = question.lower()
        relevant = []

        # Get recent AI session blobs
        blobs = sorted(container.list_blobs(), key=lambda b: b.name, reverse=True)
        for blob in blobs[:20]:
            try:
                blob_data = container.get_blob_client(blob.name).download_blob().readall()
                data = json.loads(blob_data)
                summary = data.get("ai_context", "")
                if summary and (
                    any(word in summary.lower() for word in question_lower.split() if len(word) > 3)
                    or len(relevant) < 3
                ):
                    ticket = data.get("ticket_id", "")
                    relevant.append(
                        f"[Commit {data.get('commit_sha', '?')}]"
                        f"{' [' + ticket + ']' if ticket else ''}\n"
                        f"Developer was working on: {summary}"
                    )
            except Exception:
                continue

        return "\n\n".join(relevant[:5])
    except Exception:
        return ""
def _build_context(commits: list[dict]) -> str:
    """Build context string from search results."""
    context = ""
    for i, commit in enumerate(commits, 1):
        ticket = commit.get('ticket_id', '')
        ticket_line = f"Ticket: {ticket}\n" if ticket else ""
        context += f"""
--- Commit {i} ---
SHA: {commit.get('sha', 'N/A')}
Message: {commit.get('commit_message', 'N/A')}
Author: {commit.get('author', 'N/A')}
Branch: {commit.get('branch', 'N/A')}
{ticket_line}Timestamp: {commit.get('timestamp', 'N/A')}
Files: {commit.get('file_name', 'N/A')}
Code Changes: {commit.get('code_diff', 'N/A')[:2000]}
Analysis: {commit.get('analysis', 'N/A')}
"""
    return context


def _generate_answer(question: str, context: str) -> str:
    """Generate answer using LLM (Groq, OpenRouter, or OpenAI)."""
    
    # Try Groq first (fast + free tier)
    if config.groq_api_key:
        return _call_groq(question, context)
    
    # Try OpenRouter
    if config.openrouter_api_key:
        return _call_openrouter(question, context)
    
    # Fallback to OpenAI
    if config.openai_api_key:
        return _call_openai(question, context)
    
    # No LLM configured - return raw context
    return f"No LLM configured. Raw commits:\n{context}"


def _call_groq(question: str, context: str) -> str:
    """Call Groq API (OpenAI-compatible)."""
    if not HAS_REQUESTS:
        return f"requests library not installed. Raw commits:\n{context}"
    
    prompt = f"""You are an engineering memory assistant that helps developers understand their codebase history and project status.
Use the context below (commit history, Jira tickets, AI session notes) to answer the question.

Rules:
- Answer the question directly and concisely
- Reference specific commits (SHA, message) and Jira tickets when relevant
- If the question is about tickets/status, focus on ticket information
- If the question is about a bug, explain root cause and fix
- If tickets have associated commits, link them together
- Do NOT include sections that weren't asked for
- Keep responses focused — 5-15 lines max unless more detail is explicitly requested

Context:
{context}

Question:
{question}

Answer:"""
    
    try:
        response = requests.post(
            url="https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {config.groq_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.groq_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 800,
                "temperature": 0.3,
            },
            timeout=30
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    
    except Exception as exc:
        log.error(f"Groq API failed: {exc}")
        return f"AI temporarily unavailable. Raw commits:\n{context}"


def _call_openrouter(question: str, context: str) -> str:
    """Call OpenRouter API."""
    if not HAS_REQUESTS:
        return f"requests library not installed. Raw commits:\n{context}"
    
    prompt = f"""You are an engineering memory assistant that helps developers understand their codebase history and project status.
Use the context below (commit history, Jira tickets, AI session notes) to answer the question.

Rules:
- Answer the question directly and concisely
- Reference specific commits (SHA, message) and Jira tickets when relevant
- If the question is about tickets/status, focus on ticket information
- If the question is about a bug, explain root cause and fix
- If tickets have associated commits, link them together
- Do NOT include sections that weren't asked for (e.g., don't add "Bug Analysis" if user asked about ticket status)
- Keep responses focused — 5-15 lines max unless more detail is explicitly requested

Context:
{context}

Question:
{question}

Answer:"""
    
    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {config.openrouter_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.openrouter_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 800,
                "temperature": 0.3,
            },
            timeout=30
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    
    except Exception as exc:
        log.error(f"OpenRouter API failed: {exc}")
        return f"AI temporarily unavailable. Raw commits:\n{context}"


def _call_openai(question: str, context: str) -> str:
    """Call OpenAI API."""
    try:
        import openai
        
        client = openai.OpenAI(api_key=config.openai_api_key)
        
        prompt = f"""You are an engineering memory assistant.
Use the commit history below to answer the question.

Commit History:
{context}

Question:
{question}

Answer clearly and concisely."""
        
        response = client.chat.completions.create(
            model=config.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=512,
        )
        
        return response.choices[0].message.content
    
    except Exception as exc:
        log.error(f"OpenAI API failed: {exc}")
        return f"AI temporarily unavailable. Raw commits:\n{context}"
