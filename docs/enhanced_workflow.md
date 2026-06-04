# Enhanced Post-Commit Workflow

## Overview

The enhanced post-commit hook now automatically:
1. **Captures** the commit diff
2. **Extracts** Jira ticket ID from commit message
3. **Fetches** Jira issue details for additional context
4. **Analyzes** the commit using LLM with Jira context
5. **Stores** everything to Azure Blob Storage

## Workflow Diagram

```
Git Commit
    ↓
Post-Commit Hook Triggered
    ↓
┌─────────────────────────────────────────┐
│ 1. Capture Commit                       │
│    - Get diff, metadata, files changed  │
│    - Extract Jira ticket ID             │
└────────────┬────────────────────────────┘
             ↓
┌─────────────────────────────────────────┐
│ 2. Save Locally                         │
│    - Write to .ai_memory/commits/       │
│    - Update index.jsonl                 │
└────────────┬────────────────────────────┘
             ↓
┌─────────────────────────────────────────┐
│ 3. Fetch Jira Context (if ticket ID)   │
│    - Call get_issue_details(ticket_id)  │
│    - Get summary, description, status   │
│    - Get comments, priority, type       │
└────────────┬────────────────────────────┘
             ↓
┌─────────────────────────────────────────┐
│ 4. Analyze with LLM                     │
│    - Build prompt with:                 │
│      * Commit message & diff            │
│      * Jira issue context               │
│    - Get AI analysis                    │
└────────────┬────────────────────────────┘
             ↓
┌─────────────────────────────────────────┐
│ 5. Upload to Azure Blob                 │
│    - Bundle: commit + analysis + jira   │
│    - Upload as JSON blob                │
└─────────────────────────────────────────┘
```

## Configuration

### Required Environment Variables

```bash
# For LLM Analysis
export OPENAI_API_KEY="sk-..."
# OR
export OPENROUTER_API_KEY="sk-or-..."

# For Jira Integration
export JIRA_DOMAIN="your-company.atlassian.net"
export JIRA_EMAIL="your-email@company.com"
export JIRA_API_TOKEN="your-api-token"

# For Azure Storage
export AZURE_STORAGE_ENDPOINT="https://youraccount.blob.core.windows.net"
# Azure authentication via DefaultAzureCredential
```

### Optional Variables

```bash
export OPENAI_MODEL="gpt-4"  # Default model
export OPENROUTER_MODEL="anthropic/claude-3-sonnet"  # OpenRouter model
export AZURE_STORAGE_CONTAINER="commits"  # Container name
```

## Commit Message Format

To enable Jira integration, include the ticket ID in your commit message:

### Supported Formats

```bash
# Format 1: Ticket at the start
git commit -m "PROJ-123: Add user authentication"

# Format 2: Ticket in square brackets
git commit -m "[PROJ-123] Fix login bug"

# Format 3: Ticket at the end
git commit -m "Update documentation (PROJ-123)"

# Format 4: Azure DevOps style
git commit -m "AB#456: Implement feature X"
```

The system automatically extracts ticket IDs matching these patterns:
- `JIRA-123`, `PROJ-456` (Jira style)
- `AB#123` (Azure DevOps style)
- Any `[A-Z]+-\d+` or `[A-Z]+#\d+` pattern

## What Gets Captured

### Commit Data
- SHA, message, author, timestamp
- Branch name
- File changes (insertions/deletions)
- Full unified diffs
- Extracted ticket ID

### Jira Context (if ticket ID found)
- Issue key, summary, description
- Status, priority, issue type
- Assignee, reporter
- Labels
- Comments with authors and timestamps

### LLM Analysis
- Problem identification (enhanced with Jira context)
- Solution explanation
- Key code changes
- Impact assessment
- Model used and tokens consumed

## Example Enhanced Analysis

With Jira context, the LLM receives richer information:

```
**Commit Information:**
- Message: "PROJ-123: Fix authentication timeout bug"
- Files changed: auth.py, config.py

**Jira Issue Context:**
- Issue Key: PROJ-123
- Type: Bug
- Priority: High
- Status: In Progress
- Summary: Users experiencing session timeout after 30 minutes
- Description: Multiple users report being logged out unexpectedly...

**Code Changes:**
### auth.py
- Updated session timeout from 1800 to 7200 seconds
- Added refresh token logic
...
```

This allows the LLM to provide more accurate analysis by understanding:
- The original issue being addressed
- The expected behavior from Jira description
- Priority and business impact
- Related discussions from comments

## Storage Structure

### Local Storage
```
.ai_memory/
├── commits/
│   └── 2026-05-24T10-30-00_abc123ef.json  # Commit data only
└── index.jsonl  # Quick index
```

### Azure Blob Storage
```json
{
  "commit": {
    "sha": "abc123ef",
    "message": "PROJ-123: Fix bug",
    "file_diffs": [...],
    ...
  },
  "analysis": {
    "analysis": "**Problem**: Users experiencing...",
    "model": "gpt-4",
    "tokens_used": 542
  },
  "jira_context": {
    "issue_key": "PROJ-123",
    "summary": "Fix authentication timeout",
    "description": "...",
    "status": "In Progress",
    ...
  },
  "uploaded_at": "2026-05-24T10-30-00"
}
```

## Benefits

### 1. Complete Context
Every commit is enriched with the full story:
- What was changed (code diff)
- Why it was changed (Jira issue)
- How it was changed (AI analysis)

### 2. Better AI Analysis
The LLM has access to:
- Original issue description
- Expected behavior
- Business context
- Previous discussions

### 3. Searchable History
All data in Azure Blob Storage can be:
- Indexed for search
- Analyzed for patterns
- Used for team insights
- Fed to other AI tools

### 4. Automatic Documentation
No manual work needed:
- Commit → Automatic analysis
- Analysis includes Jira context
- Stored with full traceability

## Performance

The enhanced workflow runs **asynchronously** in the background:
- Does NOT slow down `git commit`
- Hook returns immediately
- Processing happens after commit completes

Typical processing time:
- Capture: < 1 second
- Jira fetch: 1-2 seconds
- LLM analysis: 2-5 seconds
- Azure upload: 1-2 seconds
- **Total: ~5-10 seconds** (in background)

## Error Handling

The system is designed to **never fail a commit**:

1. **Jira fetch fails**: Logs warning, continues without Jira context
2. **LLM API fails**: Logs error, continues without analysis
3. **Azure upload fails**: Logs error, data still saved locally
4. **Any error**: Commit still succeeds, error logged to `.ai_memory/engmemory.log`

## Usage

### Installation
```bash
# Install the hook
engmemory init

# Verify it's installed
engmemory status
```

### Making Commits
```bash
# Just commit normally with ticket ID
git commit -m "PROJ-123: Fix critical bug in auth module"

# Check the log to see what happened
tail .ai_memory/engmemory.log
```

### Viewing Results

#### Local Storage
```bash
# View recent commits
engmemory recent

# View specific commit
cat .ai_memory/commits/2026-05-24T10-30-00_abc123ef.json
```

#### Azure Storage
```bash
# List blobs (requires Python script)
python -c "from engmemory.storage.azure_blob import list_blobs; print(list_blobs())"
```

## CLI Commands

### Analyze Existing Commit
```bash
# Analyze without Jira context (old way)
engmemory analyze --sha abc123

# Re-run analysis with current Jira state
# (Would need to implement this)
```

### Manual Upload to Azure
```bash
# Index recent commits to Azure
engmemory index --limit 50 --analyze
```

## Logging

All activity is logged to `.ai_memory/engmemory.log`:

```
2026-05-24 10:30:15 INFO Captured commit abc123ef on branch main (ticket: PROJ-123, files: 3)
2026-05-24 10:30:15 INFO Written to .ai_memory/commits/...
2026-05-24 10:30:16 INFO Fetching Jira issue details for PROJ-123
2026-05-24 10:30:17 INFO Fetched Jira context for PROJ-123
2026-05-24 10:30:19 INFO Analysis completed with model: gpt-4
2026-05-24 10:30:21 INFO Uploaded to Azure Blob: 2026-05-24T10-30-15_abc123ef.json
```

## Disabling Features

You can disable individual features by not setting environment variables:

```bash
# Disable Jira integration
unset JIRA_DOMAIN JIRA_EMAIL JIRA_API_TOKEN

# Disable LLM analysis
unset OPENAI_API_KEY OPENROUTER_API_KEY

# Disable Azure upload
unset AZURE_STORAGE_ENDPOINT

# Hook will still capture and store locally
```

## Future Enhancements

Potential improvements:

1. **Caching**: Cache Jira issues to reduce API calls
2. **Batch Analysis**: Analyze multiple commits together
3. **Custom Prompts**: Configure analysis prompt per project
4. **Webhooks**: Trigger actions when analysis completes
5. **Rich Diff Analysis**: Better code change understanding
6. **Test Coverage**: Include test results in analysis
7. **PR Integration**: Fetch PR context if available

## Troubleshooting

### Jira Context Not Fetched
```bash
# Check Jira configuration
python -c "from engmemory.utils.config import config; print(config.jira_domain)"

# Test Jira connection
engmemory jira-issue PROJ-123
```

### Analysis Not Running
```bash
# Check API key
echo $OPENAI_API_KEY
# or
echo $OPENROUTER_API_KEY

# Test analysis manually
engmemory analyze --limit 1
```

### Azure Upload Failing
```bash
# Check Azure config
python -c "from engmemory.utils.config import config; print(config.azure_storage_endpoint)"

# Test Azure authentication
az login  # If using Azure CLI for DefaultAzureCredential
```

### View Logs
```bash
# Tail the log
tail -f .ai_memory/engmemory.log

# Search for errors
grep ERROR .ai_memory/engmemory.log
```

## See Also

- [Jira Integration Guide](jira_issue_details.md)
- [Azure Setup Guide](azure_setup.md)
- [LLM Analyzer](../engmemory/analysis/llm_analyzer.py)
- [Runner Implementation](../engmemory/core/runner.py)
