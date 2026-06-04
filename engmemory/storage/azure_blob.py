"""
azure_blob.py

Upload commit data to Azure Blob Storage.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

try:
    from azure.storage.blob import BlobServiceClient
    from azure.identity import DefaultAzureCredential
    HAS_AZURE_STORAGE = True
except ImportError:
    HAS_AZURE_STORAGE = False

from ..utils.config import config

log = logging.getLogger(__name__)


def _get_blob_service_client() -> Optional[BlobServiceClient]:
    """
    Get BlobServiceClient with appropriate authentication.
    Uses storage key if available, otherwise DefaultAzureCredential.
    """
    if not HAS_AZURE_STORAGE:
        return None
    
    if not config.azure_storage_endpoint:
        return None
    
    try:
        # Use storage key if available (simpler and more reliable)
        if config.azure_storage_key:
            return BlobServiceClient(
                account_url=config.azure_storage_endpoint,
                credential=config.azure_storage_key
            )
        else:
            # Fall back to DefaultAzureCredential (requires az login)
            return BlobServiceClient(
                account_url=config.azure_storage_endpoint,
                credential=DefaultAzureCredential()
            )
    except Exception as exc:
        log.error(f"Failed to create BlobServiceClient: {exc}")
        return None


def upload_commit_to_blob(commit_data: dict, analysis: Optional[dict] = None) -> Optional[str]:
    """
    Upload commit + analysis to Azure Blob Storage.
    
    Args:
        commit_data: The commit payload dict
        analysis: Optional LLM analysis result
    
    Returns:
        Blob name if successful, None otherwise
    """
    blob_service = _get_blob_service_client()
    if not blob_service:
        return None
    
    try:
        container = blob_service.get_container_client(config.azure_storage_container)
        
        # Create blob name
        blob_name = f"{commit_data['timestamp'].replace(':', '-').split('.')[0]}_{commit_data['short_sha']}.json"
        
        # Combine commit + analysis
        payload = {
            "commit": commit_data,
            "analysis": analysis or {},
        }
        
        # Upload
        blob_client = container.get_blob_client(blob_name)
        blob_client.upload_blob(json.dumps(payload, indent=2), overwrite=True)
        
        log.info(f"Uploaded to Azure Blob: {blob_name}")
        return blob_name
    
    except Exception as exc:
        log.error(f"Failed to upload to Azure Blob: {exc}")
        return None


def list_blobs(limit: int = 20) -> list[str]:
    """List blob names in the commits container."""
    blob_service = _get_blob_service_client()
    if not blob_service:
        return []
    
    try:
        container = blob_service.get_container_client(config.azure_storage_container)
        
        blobs = []
        for blob in container.list_blobs():
            blobs.append(blob.name)
            if len(blobs) >= limit:
                break
        
        return blobs
    except Exception as exc:
        log.error(f"Failed to list blobs: {exc}")
        return []


def download_blob(blob_name: str) -> Optional[dict]:
    """Download a commit blob by name."""
    blob_service = _get_blob_service_client()
    if not blob_service:
        return None
    
    try:
        container = blob_service.get_container_client(config.azure_storage_container)
        blob_client = container.get_blob_client(blob_name)
        
        data = blob_client.download_blob().readall()
        return json.loads(data)
    except Exception as exc:
        log.error(f"Failed to download blob: {exc}")
        return None


def upload_commit(commit_data: dict, analysis: Optional[dict] = None, jira_context: Optional[dict] = None) -> Optional[str]:
    """
    Enhanced upload function that includes commit, analysis, and Jira context.
    
    Args:
        commit_data: The commit payload dict
        analysis: Optional LLM analysis result
        jira_context: Optional Jira issue details
    
    Returns:
        Blob name if successful, None otherwise
    """
    blob_service = _get_blob_service_client()
    if not blob_service:
        return None
    
    try:
        container = blob_service.get_container_client(config.azure_storage_container)
        
        # Create blob name
        timestamp = commit_data.get('timestamp', '').replace(':', '-').split('.')[0]
        short_sha = commit_data.get('short_sha', 'unknown')
        blob_name = f"{timestamp}_{short_sha}.json"
        
        # Combine commit + analysis + jira context
        payload = {
            "commit": commit_data,
            "analysis": analysis or {},
            "jira_context": jira_context or {},
            "uploaded_at": timestamp,
        }
        
        # Upload
        blob_client = container.get_blob_client(blob_name)
        blob_client.upload_blob(json.dumps(payload, indent=2), overwrite=True)
        
        log.info(f"Uploaded to Azure Blob: {blob_name}")
        return blob_name
    
    except Exception as exc:
        log.error(f"Failed to upload to Azure Blob: {exc}")
        return None
