"""
llm_analyzer.py

Uses an LLM to analyze commit data and generate insights:
- How the issue was fixed
- What changes were made and why
- Technical summary
- Key learnings

Supports OpenRouter (recommended), OpenAI, or any OpenAI-compatible API.
"""

from __future__ import annotations

import json
import os       
from typing import Optional

try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from ..utils.config import config


# ---------------------------------------------------------------------------
# LLM Analysis
# ---------------------------------------------------------------------------

def analyze_commit(commit_data: dict, ai_context: str = "") -> Optional[dict]:
    """
    Analyze a commit using an LLM and return insights.
    Combines code diff + AI session context for full development narrative.
    
    Args:
        commit_data: The commit payload dict (from CommitPayload.to_dict())
        ai_context: Optional developer AI session summary
    
    Returns:
        Dict with analysis results, or None if LLM is not configured
    """
    # Fetch Jira context if ticket ID is present and not already fetched
    ticket_id = commit_data.get('ticket_id')
    if ticket_id and not commit_data.get('jira_context'):
        try:
            from ..utils.jira import get_issue_details
            print(f"  Fetching Jira context for {ticket_id}...")
            jira_context = get_issue_details(ticket_id)
            if jira_context:
                commit_data['jira_context'] = jira_context
                print(f"  ✓ Jira context fetched: {jira_context.get('summary', '')}")
        except Exception as e:
            print(f"  ⚠ Could not fetch Jira context: {e}")

    # Store AI context in commit_data for prompt building
    if ai_context:
        commit_data['_ai_context'] = ai_context
    
    # Try OpenRouter first (recommended - has free tier)
    if config.openrouter_api_key:
        return _analyze_with_openrouter(commit_data)
    
    # Fallback to OpenAI
    if config.openai_api_key:
        return _analyze_with_openai(commit_data)
    
    return None


def _analyze_with_openrouter(commit_data: dict) -> Optional[dict]:
    """Analyze using OpenRouter API."""
    if not HAS_REQUESTS:
        return {
            "error": "requests library not installed. Run: pip install requests",
            "commit_sha": commit_data["sha"],
        }
    
    prompt = _build_analysis_prompt(commit_data)
    
    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {config.openrouter_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.openrouter_model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a senior software engineer analyzing git commits. "
                            "Provide clear, concise analysis of how issues were fixed based on "
                            "commit messages and code diffs. Focus on the problem, solution, and key changes."
                        )
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.3,
                "max_tokens": 1000,
            },
            timeout=30
        )
        response.raise_for_status()
        
        result = response.json()
        analysis_text = result["choices"][0]["message"]["content"]
        
        return {
            "analysis": analysis_text,
            "model": result.get("model", config.openrouter_model),
            "tokens_used": result.get("usage", {}).get("total_tokens", 0),
            "commit_sha": commit_data["sha"],
        }
    
    except Exception as exc:
        return {
            "error": str(exc),
            "commit_sha": commit_data["sha"],
        }


def _analyze_with_openai(commit_data: dict) -> Optional[dict]:
    """Analyze using OpenAI API."""
    if not HAS_OPENAI:
        return {
            "error": "OpenAI library not installed. Run: pip install openai",
            "commit_sha": commit_data["sha"],
        }
    
    # Build the prompt
    prompt = _build_analysis_prompt(commit_data, ai_context)
    
    # Call the LLM
    try:
        client = openai.OpenAI(api_key=config.openai_api_key)
        response = client.chat.completions.create(
            model=config.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior software engineer analyzing git commits. "
                        "Provide clear, concise analysis of how issues were fixed based on "
                        "commit messages, code diffs, and developer AI session context. "
                        "Focus on the problem, approaches discussed, solution chosen, and key changes."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,
            max_tokens=1000,
        )
        
        analysis_text = response.choices[0].message.content
        
        return {
            "analysis": analysis_text,
            "model": response.model,
            "tokens_used": response.usage.total_tokens,
            "commit_sha": commit_data["sha"],
        }
    
    except Exception as exc:
        return {
            "error": str(exc),
            "commit_sha": commit_data["sha"],
        }


def _analyze_with_openrouter(commit_data: dict, ai_context: str, api_key: str) -> Optional[dict]:
    """Analyze using OpenRouter API."""
    try:
        import requests
    except ImportError:
        return None

    prompt = _build_analysis_prompt(commit_data, ai_context)

    try:
        response = requests.post(
            url="https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "google/gemini-2.0-flash-001",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a senior software engineer analyzing git commits. "
                            "Provide clear, concise analysis based on commit diffs and "
                            "developer AI session context. Focus on what was discussed, "
                            "approaches tried, solution chosen, and implementation details."
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 1000,
                "temperature": 0.3,
            },
            timeout=30,
        )
        if response.status_code == 200:
            analysis_text = response.json()["choices"][0]["message"]["content"]
            return {
                "analysis": analysis_text,
                "model": "gemini-2.0-flash",
                "commit_sha": commit_data["sha"],
            }
    except Exception as exc:
        return {"error": str(exc), "commit_sha": commit_data["sha"]}


def _build_analysis_prompt(commit_data: dict, ai_context: str = "") -> str:
    """Build the prompt for LLM analysis."""
    
    # Format file changes summary
    file_summary = []
    for file_diff in commit_data.get("file_diffs", [])[:10]:
        file_summary.append(
            f"- {file_diff['path']} ({file_diff['change_type']}): "
            f"+{file_diff['insertions']} -{file_diff['deletions']}"
        )
    
    # Build the full diff text
    diff_text = ""
    for file_diff in commit_data.get("file_diffs", [])[:5]:
        diff_text += f"\n### {file_diff['path']}\n"
        diff_text += file_diff.get("diff_text", "")[:2000]
    
    # Build Jira context section if available
    jira_section = ""
    jira_context = commit_data.get('jira_context')
    if jira_context:
        jira_section = f"""
**Jira Issue Context:**
- Issue Key: {jira_context.get('issue_key', 'N/A')}
- Type: {jira_context.get('issue_type', 'N/A')}
- Priority: {jira_context.get('priority', 'N/A')}
- Status: {jira_context.get('status', 'N/A')}
- Summary: {jira_context.get('summary', 'N/A')}
- Description: {jira_context.get('description', 'N/A')[:500]}
"""

    # AI context section
    ai_section = ""
    ai_context = commit_data.get('_ai_context', '')
    if ai_context:
        ai_section = f"""
**Developer AI Session (what was discussed with Copilot before this commit):**
{ai_context}
"""

    prompt = f"""Analyze this git commit and create a full development narrative:

**Commit Information:**
- SHA: {commit_data['sha']}
- Message: {commit_data['message']}
- Author: {commit_data['author_name']}
- Branch: {commit_data['branch']}
- Ticket: {commit_data.get('ticket_id', 'N/A')}
- Files changed: {commit_data['files_changed']}
- Insertions: +{commit_data['total_insertions']}, Deletions: -{commit_data['total_deletions']}
{jira_section}{ai_section}
**Files Modified:**
{chr(10).join(file_summary)}

**Code Changes:**
{diff_text}

**Please provide a development narrative including:**
1. **What the developer was trying to do** (use Jira/AI session context if available)
2. **Approach discussed/chosen** (from AI session + code evidence)
3. **How it was implemented** (key code changes, patterns used)
4. **What files were changed and why**
5. **Any potential issues or edge cases** (from the diff)

Write as a concise technical story that a future developer can read to understand
not just WHAT changed, but WHY and HOW the developer reasoned about it."""
    
    return prompt


# ---------------------------------------------------------------------------
# Optional: Batch analysis
# ---------------------------------------------------------------------------

def analyze_recent_commits(repo_path: str = ".", limit: int = 5) -> list[dict]:
    """
    Analyze the most recent commits in bulk.
    Returns a list of analysis results.
    """
    from ..storage import read_recent, read_commit
    
    recent = read_recent(repo_path, limit=limit)
    results = []
    
    for entry in recent:
        commit_data = read_commit(entry["sha"], repo_path)
        if commit_data:
            analysis = analyze_commit(commit_data)
            if analysis:
                results.append({
                    "commit": entry,
                    "analysis": analysis,
                })
    
    return results
