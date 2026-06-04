# Azure Integration Guide

Complete guide to integrate engmemory with Azure AI Search and Blob Storage for RAG-powered commit search.

## Quick Start

```bash
# 1. Install Azure dependencies
pip install -e .

# 2. Configure environment
cp docs/engmemory.env.example ~/engmemory.env
# Edit ~/engmemory.env with your Azure credentials

# 3. Create Azure Search index
engmemory azure-setup

# 4. Index your commits
engmemory index --limit 20 --analyze

# 5. Ask questions!
engmemory ask "How was the authentication bug fixed?"
```

---

## Prerequisites

### 1. Azure Account
Sign up at https://azure.microsoft.com/free (includes $200 free credit)

### 2. OpenRouter Account (for AI responses)
Sign up at https://openrouter.ai (free tier available)
- Go to https://openrouter.ai/keys
- Create a key named `engmemory-key`
- Copy the key (starts with `sk-or-...`)

### 3. Azure CLI
**Windows:**
```powershell
winget install Microsoft.AzureCLI
```

**macOS:**
```bash
brew install azure-cli
```

**Linux:**
```bash
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
```

Verify installation:
```bash
az version
```

---

## Step 1: Azure Login

```bash
az logout
az account clear
az login --use-device-code
```

When prompted:
1. Go to https://login.microsoft.com/device
2. Enter the code shown in your terminal
3. Sign in with your Azure account

Set your subscription:
```bash
az account set --subscription "YOUR_SUBSCRIPTION_ID"
```

Find your subscription ID:
```bash
az account list --output table
```

---

## Step 2: Register Resource Providers

```bash
az provider register --namespace Microsoft.Storage
az provider register --namespace Microsoft.Search
az provider register --namespace Microsoft.CognitiveServices
```

Wait ~60 seconds, then verify:
```bash
az provider show --namespace Microsoft.Storage --query "registrationState"
az provider show --namespace Microsoft.Search --query "registrationState"
```

Both should return `"Registered"`.

---

## Step 3: Create Azure Resources

### Resource Group
```bash
az group create --name engmemory-rg --location eastus
```

### Azure AI Search (Free Tier)
```bash
az search service create \
  --name engmemory-search \
  --resource-group engmemory-rg \
  --sku free
```

### Azure Blob Storage
```bash
az storage account create \
  --name engmemorystorage001 \
  --resource-group engmemory-rg \
  --location eastus \
  --sku Standard_LRS
```

### Storage Container
```bash
az storage container create \
  --name commits \
  --account-name engmemorystorage001 \
  --auth-mode login
```

---

## Step 4: Set Permissions

### Get Your Azure Object ID
```bash
az ad signed-in-user show --query id --output tsv
```
Copy the UUID (looks like `9a0534db-62c5-4f19-...`)

### Assign Blob Storage Permission
```bash
az role assignment create \
  --assignee-object-id YOUR_OBJECT_ID \
  --assignee-principal-type User \
  --role "Storage Blob Data Contributor" \
  --scope /subscriptions/YOUR_SUBSCRIPTION_ID/resourceGroups/engmemory-rg/providers/Microsoft.Storage/storageAccounts/engmemorystorage001
```

### Get Azure Search Admin Key
```bash
az search admin-key show \
  --service-name engmemory-search \
  --resource-group engmemory-rg
```
Copy the `primaryKey` value.

**⚠️ Wait 5-10 minutes** for permissions to propagate before proceeding.

---

## Step 5: Configure Environment

Create `~/engmemory.env` (or `C:\Users\USERNAME\engmemory.env` on Windows):

```env
# Azure
AZURE_SUBSCRIPTION_ID=your-subscription-id-here
AZURE_RESOURCE_GROUP=engmemory-rg
AZURE_LOCATION=eastus

# Azure AI Search
AZURE_SEARCH_ENDPOINT=https://engmemory-search.search.windows.net
AZURE_SEARCH_INDEX=commits
AZURE_SEARCH_ADMIN_KEY=your-admin-key-from-step-4

# Azure Blob Storage
AZURE_STORAGE_ACCOUNT=engmemorystorage001
AZURE_STORAGE_ENDPOINT=https://engmemorystorage001.blob.core.windows.net/
AZURE_STORAGE_CONTAINER=commits

# OpenRouter (AI)
OPENROUTER_API_KEY=sk-or-your-key-here
OPENROUTER_MODEL=openrouter/auto
```

---

## Step 6: Setup and Index

### Create Azure Search Index
```bash
engmemory azure-setup
```

Expected output:
```
Setting up Azure AI Search...
Endpoint: https://engmemory-search.search.windows.net
Index: commits

✓ Index 'commits' created successfully!
```

### Index Your Commits
```bash
# Index last 20 commits with AI analysis
engmemory index --limit 20 --analyze

# Index without analysis (faster)
engmemory index --limit 50
```

---

## Step 7: Ask Questions!

### Interactive Mode
```bash
engmemory ask
```

### Direct Question
```bash
engmemory ask "How was the authentication bug fixed?"
engmemory ask "What changes were made to the database?"
engmemory ask "Who worked on the API rate limiting?"
```

### Example Output
```
Ask a question about your commit history:
> How was the authentication bug fixed?

Searching commit history...

================================================================================
ANSWER
================================================================================

The authentication bug was fixed in commit 447ff855 by Sahithi on May 19, 2026.
The fix involved adding JWT validation and token expiry checks to the auth.py
file. This prevented null pointer exceptions in the login handler and improved
security by validating tokens before granting access.

Key changes:
- Added null check in login handler
- Implemented JWT token validation
- Added token expiry verification
```

---

## Commands Reference

| Command | Description |
|---|---|
| `engmemory azure-setup` | Create Azure AI Search index |
| `engmemory index` | Index commits into Azure Search |
| `engmemory index --analyze` | Index with AI analysis |
| `engmemory ask <question>` | Ask a question (RAG query) |
| `engmemory ask` | Interactive question mode |

---

## Troubleshooting

### `AuthorizationPermissionMismatch`
You don't have blob storage permissions.
- Re-run the role assignment from Step 4
- Wait 5-10 minutes for propagation
- Try again

### `Forbidden` on Azure Search
The admin key is wrong or missing.
- Re-run: `az search admin-key show --service-name engmemory-search --resource-group engmemory-rg`
- Copy `primaryKey` to `AZURE_SEARCH_ADMIN_KEY` in `.env`

### `404 Not Found` from OpenRouter
Model ID doesn't exist or unavailable.
- Use `openrouter/auto` (recommended)
- Check https://openrouter.ai/models for available free models

### `SubscriptionNotFound`
Provider not registered.
- Run: `az provider register --namespace Microsoft.Storage`
- Wait 60 seconds and verify

### `.env` not loading
- Save file as `engmemory.env` (not `.env.txt`)
- Place in home directory: `~/engmemory.env`
- No spaces around `=` signs

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Git Commit                                             │
└────────────────┬────────────────────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────────────────────┐
│  engmemory captures commit data                         │
│  (hook.py → runner.py → capture.py)                     │
└────────────────┬────────────────────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────────────────────┐
│  Local Storage (.ai_memory/commits/)                    │
└────────────────┬────────────────────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────────────────────┐
│  engmemory index --analyze                              │
│  • Reads local commits                                  │
│  • Analyzes with LLM                                    │
│  • Uploads to Azure Blob Storage                        │
│  • Indexes in Azure AI Search                           │
└────────────────┬────────────────────────────────────────┘
                 │
                 v
┌─────────────────────────────────────────────────────────┐
│  engmemory ask "question"                               │
│  • Searches Azure AI Search                             │
│  • Retrieves relevant commits                           │
│  • Generates answer with LLM (RAG)                      │
└─────────────────────────────────────────────────────────┘
```

---

## Cost Estimate

| Service | Tier | Cost |
|---|---|---|
| Azure AI Search | Free | $0/month (1 index, 50MB) |
| Azure Blob Storage | Standard_LRS | ~$0.02/month (first GB) |
| OpenRouter | Free tier | $0 (rate limited) |

**Total: < $1/month** for typical usage.

---

## Next Steps

1. ✅ Set up Azure (this guide)
2. 🚀 Index your commits
3. 💡 Try RAG queries
4. 📊 Build dashboards
5. 🤖 Train custom models

See `docs/advanced_features.md` for more!
