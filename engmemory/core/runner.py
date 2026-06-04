"""
runner.py

The entry point the post-commit hook calls after every git commit:

    python -m engmemory.core.runner --repo /path/to/repo

Steps:
  1. Capture the commit (capture.py)
  2. Write raw JSON to .ai_memory/commits/ (storage.py)
  3. POST the payload to the ingest endpoint (if ENGMEMORY_API_URL is set)
  4. Log what happened

Runs in the background (the hook appends & to the call) so it never
slows down the git commit itself.
"""

from __future__ import annotations

import warnings
warnings.filterwarnings("ignore", category=RuntimeWarning, module="runpy")

import argparse
import json
import logging
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

from .capture import capture_commit
from ..storage import write_commit


# ---------------------------------------------------------------------------
# Logging — write to .ai_memory/engmemory.log so developers can debug
# ---------------------------------------------------------------------------

def _setup_logging(repo_path: str) -> None:
    log_dir = Path(repo_path) / ".ai_memory"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "engmemory.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


def _load_env_file(repo_path: str) -> None:
    """Load env vars from engmemory.env.txt or .env in repo or parent dirs."""
    search_dirs = [
        Path(repo_path),
        Path(repo_path).parent,
    ]
    for d in search_dirs:
        for name in ['engmemory.env.txt', '.env']:
            env_file = d / name
            if env_file.exists():
                try:
                    for line in env_file.read_text(encoding='utf-8').splitlines():
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, val = line.split('=', 1)
                            os.environ.setdefault(key.strip(), val.strip())
                except Exception:
                    pass
                return


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def _fetch_jira_context(ticket_id: str) -> dict | None:
    """
    Fetch Jira issue details for the given ticket ID.
    Returns None if Jira is not configured or fetch fails.
    """
    try:
        from ..utils.jira import get_issue_details
        from ..utils.config import config
        
        # Check if Jira is configured
        if not all([config.jira_domain, config.jira_email, config.jira_api_token]):
            log.info("Jira not configured — skipping Jira context")
            return None
        
        log.info("Fetching Jira issue details for %s", ticket_id)
        issue = get_issue_details(ticket_id)
        return issue
    
    except Exception as exc:
        log.warning("Failed to fetch Jira context for %s: %s", ticket_id, exc)
        return None


def _analyze_commit_with_context(payload, jira_context: dict | None) -> dict | None:
    """
    Analyze commit using LLM with optional Jira context.
    Returns analysis dict or None if analysis fails.
    """
    try:
        from ..analysis import analyze_commit
        
        # Convert payload to dict if needed
        commit_data = payload.to_dict() if hasattr(payload, 'to_dict') else payload
        
        # If we have Jira context, enhance the commit data
        if jira_context:
            commit_data['jira_context'] = {
                'issue_key': jira_context.get('key'),
                'summary': jira_context.get('summary'),
                'description': jira_context.get('description'),
                'status': jira_context.get('status'),
                'issue_type': jira_context.get('issue_type'),
                'priority': jira_context.get('priority'),
            }
        
        analysis = analyze_commit(commit_data)
        return analysis
    
    except Exception as exc:
        log.warning("Failed to analyze commit: %s", exc)
        return {"error": str(exc)}


def _upload_to_azure(payload, analysis: dict | None, jira_context: dict | None) -> None:
    """
    Upload commit data, analysis, and Jira context to Azure Blob Storage.
    """
    try:
        from ..storage.azure_blob import upload_commit
        from ..utils.config import config
        
        # Check if Azure is configured
        if not config.is_azure_configured():
            log.info("Azure not fully configured — skipping upload")
            return
        
        # Build comprehensive data package
        data = payload.to_dict() if hasattr(payload, 'to_dict') else payload
        
        if analysis:
            data['analysis'] = analysis
        
        if jira_context:
            data['jira_context'] = jira_context
        
        # Upload to Azure
        blob_name = upload_commit(data)
        if blob_name:
            log.info("Uploaded to Azure Blob: %s", blob_name)
        else:
            log.warning("Failed to upload to Azure Blob")
    
    except Exception as exc:
        log.warning("Azure upload failed (non-blocking): %s", exc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(repo_path: str) -> None:
    _setup_logging(repo_path)
    _load_env_file(repo_path)
    log.info("EngMemory runner started for repo: %s", repo_path)

    # 1. Capture
    try:
        payload = capture_commit(repo_path)
        log.info(
            "Captured commit %s on branch %s (ticket: %s, files: %d)",
            payload.short_sha,
            payload.branch,
            payload.ticket_id or "none",
            payload.files_changed,
        )
    except Exception as exc:
        log.error("Failed to capture commit: %s", exc, exc_info=True)
        return

    # 2. Write locally
    try:
        json_path = write_commit(payload, repo_path)
        log.info("Written to %s", json_path)
    except Exception as exc:
        log.error("Failed to write local JSON: %s", exc, exc_info=True)
        return

    # 2.5. Capture AI context (Copilot chat summary)
    _capture_ai_context(payload, repo_path)

    # 3. Fetch Jira context if ticket ID exists
    jira_context = None
    if payload.ticket_id:
        jira_context = _fetch_jira_context(payload.ticket_id)
        if jira_context:
            log.info("Fetched Jira context for %s", payload.ticket_id)

    # 4. Analyze commit with LLM (with Jira context if available)
    analysis = None
    if os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY"):
        analysis = _analyze_commit_with_context(payload, jira_context)
        if analysis and "error" not in analysis:
            log.info("Analysis completed with model: %s", analysis.get("model", "unknown"))
        elif analysis:
            log.warning("Analysis failed: %s", analysis.get("error"))
    else:
        log.info("No LLM API key set — skipping analysis")

    # 5. Upload to Azure Blob Storage (if configured)
    if os.getenv("AZURE_STORAGE_ENDPOINT"):
        _upload_to_azure(payload, analysis, jira_context)
    else:
        log.info("Azure not configured — skipping cloud storage")

    # 6. POST to ingest endpoint (optional — skipped if env var not set)
    api_url = os.getenv("ENGMEMORY_API_URL")
    if api_url:
        _post_to_api(payload.to_dict(), api_url)
    else:
        log.info("ENGMEMORY_API_URL not set — skipping remote ingest (local only)")


def _capture_ai_context(payload, repo_path: str) -> None:
    """
    Capture and sanitize AI session context (Copilot chat).
    Saves to .ai_memory/ai_sessions/ as a separate file.
    Uses basic filter (no LLM) for speed — LLM runs during index.
    Never blocks the commit.
    """
    log.info("AI context: attempting capture for %s", payload.short_sha)
    try:
        from ..ai_context import create_ai_context_summary, save_message_marker

        result = create_ai_context_summary(repo_path)
        if not result:
            log.info("AI context: no new technical content since last commit")
            # Still save marker so next commit starts fresh
            save_message_marker(repo_path)
            return

        summary = result["summary"]

        context_data = {
            "commit_sha": payload.short_sha,
            "commit_message": payload.message,
            "ticket_id": payload.ticket_id,
            "timestamp": payload.timestamp,
            "ai_context": summary,
            "message_count": result["message_count"],
            "source": result["source"],
        }

        # Upload to Azure Blob Storage (permanent storage)
        _upload_ai_context_to_blob(context_data, payload)

        # Save marker so next commit only captures NEW messages
        save_message_marker(repo_path)

        log.info("AI context uploaded to blob for commit %s (%d new messages)",
                 payload.short_sha, result["message_count"])
    except Exception as exc:
        log.warning("AI context capture failed: %s", exc)


def _upload_ai_context_to_blob(context_data: dict, payload) -> None:
    """Upload AI context summary to a separate blob container using shared blob client."""
    try:
        from ..storage.azure_blob import _get_blob_service_client
        from ..utils.config import config

        blob_service = _get_blob_service_client()
        if not blob_service:
            return

        # Use a separate container for AI sessions
        container_name = "ai-sessions"
        container = blob_service.get_container_client(container_name)
        try:
            container.create_container()
        except Exception:
            pass  # Already exists

        blob_name = f"{payload.timestamp}_{payload.short_sha}_ai_context.json"
        blob_name = blob_name.replace(":", "-")
        container.upload_blob(
            name=blob_name,
            data=json.dumps(context_data, indent=2),
            overwrite=True,
        )
        log.info("AI context uploaded to blob: %s", blob_name)
    except Exception as exc:
        log.debug("AI context blob upload skipped: %s", exc)


def _auto_index(payload) -> None:
    """
    Auto-index the commit to Azure AI Search and Blob Storage.
    Runs silently — never blocks the commit.
    """
    try:
        from ..search.azure_search import index_commit
        from ..storage.azure_blob import upload_commit_to_blob
        from ..utils.config import config

        if not config.azure_search_endpoint:
            return

        commit_data = payload.to_dict()
        index_commit(commit_data)
        upload_commit_to_blob(commit_data)
        log.info("Auto-indexed commit %s to Azure", payload.short_sha)
    except Exception as exc:
        log.debug("Auto-index skipped: %s", exc)


def _post_to_api(data: dict, api_url: str) -> None:
    """
    Fire-and-forget POST to the ingest endpoint.
    Uses stdlib urllib so there are zero extra dependencies at hook time.
    """
    url = api_url.rstrip("/") + "/ingest"
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Api-Key": os.getenv("ENGMEMORY_API_KEY", ""),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            log.info("Ingest API responded %d for commit %s", resp.status, data["short_sha"])
    except urllib.error.HTTPError as exc:
        log.warning("Ingest API HTTP error %d: %s", exc.code, exc.read().decode())
    except Exception as exc:
        log.warning("Ingest API call failed (non-blocking): %s", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="EngMemory post-commit runner")
    parser.add_argument(
        "--repo",
        default=".",
        help="Path to the git repository root (default: current directory)",
    )
    args = parser.parse_args()
    run(args.repo)


if __name__ == "__main__":
    main()
