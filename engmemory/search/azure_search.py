"""
azure_search.py

Index and search commits using Azure AI Search.
"""

from __future__ import annotations

import logging
from typing import Optional

try:
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient
    from azure.search.documents.indexes import SearchIndexClient
    from azure.search.documents.indexes.models import (
        SearchIndex,
        SimpleField,
        SearchableField,
        SearchFieldDataType,
    )
    HAS_AZURE_SEARCH = True
except ImportError:
    HAS_AZURE_SEARCH = False

from ..utils.config import config

log = logging.getLogger(__name__)


def create_index() -> bool:
    """
    Create the Azure AI Search index for commits.
    Returns True if successful.
    """
    if not HAS_AZURE_SEARCH:
        log.error("Azure Search SDK not installed. Run: pip install azure-search-documents")
        return False
    
    if not config.azure_search_endpoint or not config.azure_search_admin_key:
        log.error("Azure AI Search not configured")
        return False
    
    try:
        client = SearchIndexClient(
            endpoint=config.azure_search_endpoint,
            credential=AzureKeyCredential(config.azure_search_admin_key)
        )
        
        index = SearchIndex(
            name=config.azure_search_index,
            fields=[
                SimpleField(name="id", type=SearchFieldDataType.String, key=True),
                SearchableField(name="commit_message", type=SearchFieldDataType.String),
                SearchableField(name="analysis", type=SearchFieldDataType.String),
                SimpleField(name="author", type=SearchFieldDataType.String, filterable=True),
                SimpleField(name="branch", type=SearchFieldDataType.String, filterable=True),
                SimpleField(name="ticket_id", type=SearchFieldDataType.String, filterable=True),
                SimpleField(name="file_name", type=SearchFieldDataType.String, filterable=True),
                SearchableField(name="code_diff", type=SearchFieldDataType.String),
                SimpleField(name="timestamp", type=SearchFieldDataType.String, filterable=True, sortable=True),
                SimpleField(name="sha", type=SearchFieldDataType.String),
            ]
        )
        
        client.create_or_update_index(index)
        log.info(f"Index '{config.azure_search_index}' created/updated successfully")
        return True
    
    except Exception as exc:
        log.error(f"Failed to create index: {exc}")
        return False


def index_commit(commit_data: dict, analysis: Optional[dict] = None) -> bool:
    """
    Index a commit in Azure AI Search.
    
    Args:
        commit_data: The commit payload dict
        analysis: Optional LLM analysis result
    
    Returns:
        True if successful
    """
    if not HAS_AZURE_SEARCH or not config.azure_search_endpoint:
        return False
    
    try:
        search_client = SearchClient(
            endpoint=config.azure_search_endpoint,
            index_name=config.azure_search_index,
            credential=AzureKeyCredential(config.azure_search_admin_key)
        )
        
        # Flatten file diffs into searchable text
        code_diff = ""
        file_names = []
        for file_diff in commit_data.get("file_diffs", [])[:10]:
            file_names.append(file_diff["path"])
            code_diff += f"\n### {file_diff['path']}\n{file_diff.get('diff_text', '')[:1000]}"
        
        document = {
            "id": commit_data["sha"],
            "commit_message": commit_data["message"],
            "analysis": analysis.get("analysis", "") if analysis else "",
            "author": commit_data["author_name"],
            "branch": commit_data["branch"],
            "ticket_id": commit_data.get("ticket_id") or "",
            "file_name": ", ".join(file_names[:5]),  # First 5 files
            "code_diff": code_diff[:10000],  # Limit size
            "timestamp": commit_data["timestamp"],
            "sha": commit_data["short_sha"],
        }
        
        search_client.upload_documents([document])
        log.info(f"Indexed commit {commit_data['short_sha']} in Azure AI Search")
        return True
    
    except Exception as exc:
        log.error(f"Failed to index commit: {exc}")
        return False


def search_commits(query: str, top_k: int = 5) -> list[dict]:
    """
    Search for commits in Azure AI Search.
    
    Args:
        query: Search query string
        top_k: Number of results to return
    
    Returns:
        List of matching commits
    """
    if not HAS_AZURE_SEARCH or not config.azure_search_endpoint:
        return []
    
    try:
        search_client = SearchClient(
            endpoint=config.azure_search_endpoint,
            index_name=config.azure_search_index,
            credential=AzureKeyCredential(config.azure_search_admin_key)
        )
        
        results = search_client.search(
            search_text=query,
            select=["sha", "commit_message", "analysis", "author", "file_name", "timestamp", "ticket_id"],
            top=top_k
        )
        
        commits = []
        for result in results:
            commits.append(dict(result))
        
        return commits
    
    except Exception as exc:
        log.error(f"Search failed: {exc}")
        return []
