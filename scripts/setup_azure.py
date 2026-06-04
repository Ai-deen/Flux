"""
EngMemory - Automated Azure Setup Script

Run this ONCE to set up all Azure resources needed:
  - Resource Group
  - Storage Account + Container
  - Azure AI Search Service + Index

Usage:
    python scripts/setup_azure.py

Prerequisites:
    pip install azure-identity azure-mgmt-resource azure-mgmt-storage azure-mgmt-search azure-storage-blob azure-search-documents

    You must be logged in:
        az login
"""

import os
import sys
import time
import secrets
import string

try:
    from azure.identity import DefaultAzureCredential, InteractiveBrowserCredential
    from azure.mgmt.resource import ResourceManagementClient
    from azure.mgmt.storage import StorageManagementClient
    from azure.mgmt.search import SearchManagementClient
    from azure.storage.blob import BlobServiceClient
    from azure.search.documents.indexes import SearchIndexClient
    from azure.search.documents.indexes.models import (
        SearchIndex,
        SimpleField,
        SearchableField,
        SearchFieldDataType,
    )
except ImportError:
    print("Missing Azure SDK packages. Install with:")
    print("  pip install azure-identity azure-mgmt-resource azure-mgmt-storage azure-mgmt-search azure-storage-blob azure-search-documents")
    sys.exit(1)


# ─── Configuration ────────────────────────────────────────────────────────

RESOURCE_GROUP = os.getenv("AZURE_RESOURCE_GROUP", "engmemory-rg")
LOCATION = os.getenv("AZURE_LOCATION", "eastus")
STORAGE_ACCOUNT = os.getenv("AZURE_STORAGE_ACCOUNT", f"engmemory{''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))}")
CONTAINER_NAME = "engmemory"
SEARCH_SERVICE = os.getenv("AZURE_SEARCH_SERVICE", f"engmemory-search-{''.join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(4))}")
SEARCH_INDEX = "engmemory-commits"


def get_subscription_id():
    """Get Azure subscription ID from environment or az CLI."""
    sub_id = os.getenv("AZURE_SUBSCRIPTION_ID")
    if sub_id:
        return sub_id
    
    # Try to get from az CLI
    import subprocess
    result = subprocess.run(
        ["az", "account", "show", "--query", "id", "-o", "tsv"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        return result.stdout.strip()
    
    print("ERROR: Cannot determine Azure subscription ID.")
    print("  Set AZURE_SUBSCRIPTION_ID env var, or run: az login")
    sys.exit(1)


def main():
    print("=" * 60)
    print("  EngMemory - Azure Infrastructure Setup")
    print("=" * 60)
    print()

    subscription_id = get_subscription_id()
    print(f"  Subscription: {subscription_id[:8]}...")
    print(f"  Resource Group: {RESOURCE_GROUP}")
    print(f"  Location: {LOCATION}")
    print(f"  Storage Account: {STORAGE_ACCOUNT}")
    print(f"  Search Service: {SEARCH_SERVICE}")
    print()

    # Authenticate
    print("[1/6] Authenticating...")
    try:
        credential = DefaultAzureCredential()
        # Test the credential
        credential.get_token("https://management.azure.com/.default")
    except Exception:
        print("  Default credential failed, trying browser login...")
        credential = InteractiveBrowserCredential()
    print("  ✓ Authenticated")

    # Create Resource Group
    print(f"\n[2/6] Creating Resource Group: {RESOURCE_GROUP}...")
    resource_client = ResourceManagementClient(credential, subscription_id)
    resource_client.resource_groups.create_or_update(
        RESOURCE_GROUP,
        {"location": LOCATION}
    )
    print(f"  ✓ Resource Group ready")

    # Create Storage Account
    print(f"\n[3/6] Creating Storage Account: {STORAGE_ACCOUNT}...")
    storage_client = StorageManagementClient(credential, subscription_id)
    
    poller = storage_client.storage_accounts.begin_create(
        RESOURCE_GROUP,
        STORAGE_ACCOUNT,
        {
            "location": LOCATION,
            "kind": "StorageV2",
            "sku": {"name": "Standard_LRS"},
        }
    )
    poller.result()  # Wait for completion
    print(f"  ✓ Storage Account created")

    # Get Storage Key
    keys = storage_client.storage_accounts.list_keys(RESOURCE_GROUP, STORAGE_ACCOUNT)
    storage_key = keys.keys[0].value
    connection_string = (
        f"DefaultEndpointsProtocol=https;"
        f"AccountName={STORAGE_ACCOUNT};"
        f"AccountKey={storage_key};"
        f"EndpointSuffix=core.windows.net"
    )

    # Create Blob Container
    print(f"\n[4/6] Creating Blob Container: {CONTAINER_NAME}...")
    blob_service = BlobServiceClient.from_connection_string(connection_string)
    try:
        blob_service.create_container(CONTAINER_NAME)
        print(f"  ✓ Container created")
    except Exception as e:
        if "ContainerAlreadyExists" in str(e):
            print(f"  ✓ Container already exists")
        else:
            raise

    # Create Search Service
    print(f"\n[5/6] Creating Azure AI Search Service: {SEARCH_SERVICE}...")
    search_mgmt_client = SearchManagementClient(credential, subscription_id)
    
    poller = search_mgmt_client.services.begin_create_or_update(
        RESOURCE_GROUP,
        SEARCH_SERVICE,
        {
            "location": LOCATION,
            "sku": {"name": "free"},  # Free tier
            "replica_count": 1,
            "partition_count": 1,
        }
    )
    search_service = poller.result()
    print(f"  ✓ Search Service created")

    # Get Search Admin Key
    admin_keys = search_mgmt_client.admin_keys.get(RESOURCE_GROUP, SEARCH_SERVICE)
    search_key = admin_keys.primary_key
    search_endpoint = f"https://{SEARCH_SERVICE}.search.windows.net"

    # Create Search Index
    print(f"\n[6/6] Creating Search Index: {SEARCH_INDEX}...")
    index_client = SearchIndexClient(
        endpoint=search_endpoint,
        credential=credential,
    )
    
    index = SearchIndex(
        name=SEARCH_INDEX,
        fields=[
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SearchableField(name="commit_sha", type=SearchFieldDataType.String),
            SearchableField(name="message", type=SearchFieldDataType.String),
            SearchableField(name="author", type=SearchFieldDataType.String),
            SearchableField(name="diff_summary", type=SearchFieldDataType.String),
            SearchableField(name="analysis", type=SearchFieldDataType.String),
            SearchableField(name="ticket_id", type=SearchFieldDataType.String, filterable=True),
            SearchableField(name="jira_summary", type=SearchFieldDataType.String),
            SimpleField(name="timestamp", type=SearchFieldDataType.DateTimeOffset, filterable=True, sortable=True),
        ],
    )
    
    try:
        index_client.create_or_update_index(index)
        print(f"  ✓ Search Index created")
    except Exception as e:
        print(f"  ⚠ Index creation note: {e}")

    # Output .env values
    print("\n" + "=" * 60)
    print("  SETUP COMPLETE! Add these to your .env file:")
    print("=" * 60)
    print()
    print(f"AZURE_STORAGE_CONNECTION_STRING={connection_string}")
    print(f"AZURE_STORAGE_CONTAINER={CONTAINER_NAME}")
    print(f"AZURE_SEARCH_ENDPOINT={search_endpoint}")
    print(f"AZURE_SEARCH_KEY={search_key}")
    print(f"AZURE_SEARCH_INDEX={SEARCH_INDEX}")
    print()
    print("─" * 60)
    print("  Total cost: $0/month (free tier for both services)")
    print("  Storage: 5GB free, Search: 50MB free")
    print("─" * 60)

    # Also write to .env if it exists
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(env_path):
        print(f"\n  Auto-updating {env_path}...")
        with open(env_path, "a") as f:
            f.write(f"\n# Azure (auto-generated by setup_azure.py)\n")
            f.write(f"AZURE_STORAGE_CONNECTION_STRING={connection_string}\n")
            f.write(f"AZURE_STORAGE_CONTAINER={CONTAINER_NAME}\n")
            f.write(f"AZURE_SEARCH_ENDPOINT={search_endpoint}\n")
            f.write(f"AZURE_SEARCH_KEY={search_key}\n")
            f.write(f"AZURE_SEARCH_INDEX={SEARCH_INDEX}\n")
        print("  ✓ .env updated")


if __name__ == "__main__":
    main()
