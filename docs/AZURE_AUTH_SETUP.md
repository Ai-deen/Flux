# Azure Storage Authentication Setup

## Problem
Your commit was captured locally but failed to upload to Azure Blob because authentication is not configured.

Error: `DefaultAzureCredential` tries multiple auth methods (Environment variables, Azure CLI, etc.) but none are available.

## Solutions

### Option 1: Use Storage Account Key (Recommended - Simplest)

1. **Get your storage account key:**

   **Via Azure Portal:**
   - Go to https://portal.azure.com
   - Navigate to Storage Accounts → `engmemorystorage001`
   - Click "Access keys" in the left sidebar
   - Copy "key1" or "key2" value

   **Via Azure CLI:**
   ```bash
   az storage account keys list \
     --resource-group engmemory-rg \
     --account-name engmemorystorage001 \
     --query '[0].value' -o tsv
   ```

2. **Add to your `.env` file:**
   ```bash
   AZURE_STORAGE_KEY="<your-key-here>"
   ```

3. **Reload environment and test:**
   ```bash
   source .env
   git commit --allow-empty -m "TEST: Azure upload test"
   tail .ai_memory/engmemory.log
   ```

### Option 2: Use Azure CLI Authentication

1. **Install Azure CLI** (if not installed):
   ```bash
   # Ubuntu/Debian
   curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
   
   # macOS
   brew install azure-cli
   ```

2. **Login to Azure:**
   ```bash
   az login
   ```

3. **Test:**
   ```bash
   git commit --allow-empty -m "TEST: Azure upload test"
   ```

### Option 3: Use Service Principal (Recommended for Production/CI/CD)

**Why use Service Principal?**
- No need for `az login` or storing storage keys
- Better security with fine-grained permissions
- Perfect for automated environments and production deployments

1. **Create service principal:**
   ```bash
   az ad sp create-for-rbac --name engmemory-sp \
     --role "Storage Blob Data Contributor" \
     --scopes /subscriptions/c6971a88-4fa8-4c04-bc7e-f16f98b12a63/resourceGroups/engmemory-rg/providers/Microsoft.Storage/storageAccounts/engmemorystorage001
   ```

2. **Add credentials to `.env`:**
   ```bash
   AZURE_TENANT_ID="<tenant from output>"
   AZURE_CLIENT_ID="<appId from output>"
   AZURE_CLIENT_SECRET="<password from output>"
   ```

3. **Test:**
   ```bash
   git commit --allow-empty -m "TEST: Azure upload with Service Principal"
   tail .ai_memory/engmemory.log
   ```

**Note:** `DefaultAzureCredential()` automatically detects these environment variables and uses them for authentication. No code changes needed!

### Option 4: Disable Azure Upload (Temporary)

If you don't want to use Azure Blob Storage right now:

**Edit `.env` and comment out:**
```bash
# AZURE_STORAGE_ENDPOINT=https://engmemorystorage001.blob.core.windows.net/
```

Or unset in terminal:
```bash
unset AZURE_STORAGE_ENDPOINT
```

Everything will still work locally in `.ai_memory/commits/`!

## What Was Fixed

I've updated the code to support **Storage Account Key authentication**, which is simpler and more reliable than `DefaultAzureCredential`.

**Changes made:**
1. Added `AZURE_STORAGE_KEY` config property
2. Created `_get_blob_service_client()` helper that uses key if available
3. Falls back to `DefaultAzureCredential` if no key is set

## Verification

After setting up authentication, verify it works:

```bash
# 1. Check configuration
python -c "from engmemory.utils.config import config; print('Key set:', bool(config.azure_storage_key))"

# 2. Make a test commit
git commit --allow-empty -m "TEST: Azure Blob upload test"

# 3. Check logs
tail -20 .ai_memory/engmemory.log

# Look for this line:
# INFO Uploaded to Azure Blob: 2026-05-24T16-30-00_abc123.json
```

## Current Status

Your commit **WAS captured locally** ✅
- Location: `.ai_memory/commits/`
- Index: `.ai_memory/index.jsonl`

Your commit **DID NOT upload to Azure** ❌
- Reason: No authentication configured
- Fix: Choose one of the options above

## Recommended Next Steps

1. **Quick fix:** Use Storage Account Key (Option 1)
   - Fastest to set up
   - Works everywhere
   - Just add one line to `.env`

2. **For development:** Use Azure CLI (Option 2)
   - No need to manage keys
   - Works on your machine
   - Requires `az login`

3. **For production/CI:** Use Service Principal (Option 3)
   - Most secure
   - Works in automated environments
   - Requires setup

4. **Skip for now:** Disable Azure (Option 4)
   - Everything still works locally
   - Can enable later

Choose the option that works best for you!
