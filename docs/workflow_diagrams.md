# Enhanced Workflow - Visual Guide

## Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Developer Makes Commit                          │
│                  git commit -m "PROJ-123: Fix bug"                      │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       Post-Commit Hook Triggers                          │
│                 .git/hooks/post-commit (runs async)                     │
└──────────────────────────────────┬──────────────────────────────────────┘
                                   │
                                   ▼
        ┌──────────────────────────────────────────────────────────┐
        │         STEP 1: CAPTURE COMMIT                            │
        │  ┌─────────────────────────────────────────────────────┐ │
        │  │ • Get SHA, message, author, timestamp               │ │
        │  │ • Get branch name                                   │ │
        │  │ • Extract ticket ID (PROJ-123)                      │ │
        │  │ • Get file diffs                                    │ │
        │  │ • Get insertions/deletions                          │ │
        │  └─────────────────────────────────────────────────────┘ │
        └──────────────────────────────────────────────────────────┘
                                   │
                                   ▼
        ┌──────────────────────────────────────────────────────────┐
        │         STEP 2: SAVE LOCALLY                              │
        │  ┌─────────────────────────────────────────────────────┐ │
        │  │ Write to:                                           │ │
        │  │ .ai_memory/commits/2026-05-24_abc123.json           │ │
        │  │                                                     │ │
        │  │ Update index:                                       │ │
        │  │ .ai_memory/index.jsonl                              │ │
        │  └─────────────────────────────────────────────────────┘ │
        └──────────────────────────────────────────────────────────┘
                                   │
                                   ▼
        ┌──────────────────────────────────────────────────────────┐
        │         STEP 3: FETCH JIRA CONTEXT                        │
        │  ┌─────────────────────────────────────────────────────┐ │
        │  │ IF ticket ID exists (PROJ-123):                     │ │
        │  │                                                     │ │
        │  │ Call Jira API:                                      │ │
        │  │ GET /rest/api/3/issue/PROJ-123                      │ │
        │  │                                                     │ │
        │  │ Fetch:                                              │ │
        │  │ • Summary, description                              │ │
        │  │ • Status, priority, type                            │ │
        │  │ • Assignee, reporter                                │ │
        │  │ • Labels, comments                                  │ │
        │  └─────────────────────────────────────────────────────┘ │
        └──────────────────────────────────────────────────────────┘
                                   │
                                   ▼
        ┌──────────────────────────────────────────────────────────┐
        │         STEP 4: AI ANALYSIS                               │
        │  ┌─────────────────────────────────────────────────────┐ │
        │  │ Build enhanced prompt:                              │ │
        │  │                                                     │ │
        │  │ ┌───────────────────────────────────────────────┐   │ │
        │  │ │ **Commit Info:**                              │   │ │
        │  │ │ - Message: "PROJ-123: Fix bug"                │   │ │
        │  │ │ - Files: auth.py, config.py                   │   │ │
        │  │ │ - Diff: [code changes...]                     │   │ │
        │  │ │                                               │   │ │
        │  │ │ **Jira Context:**                             │   │ │
        │  │ │ - Summary: "Auth timeout issue"               │   │ │
        │  │ │ - Description: "Users report..."              │   │ │
        │  │ │ - Priority: High                              │   │ │
        │  │ │ - Status: In Progress                         │   │ │
        │  │ └───────────────────────────────────────────────┘   │ │
        │  │                                                     │ │
        │  │ Send to LLM (GPT-4 or OpenRouter)                  │ │
        │  │                                                     │ │
        │  │ Receive:                                            │ │
        │  │ • Problem analysis                                  │ │
        │  │ • Solution explanation                              │ │
        │  │ • Key changes                                       │ │
        │  │ • Impact assessment                                 │ │
        │  └─────────────────────────────────────────────────────┘ │
        └──────────────────────────────────────────────────────────┘
                                   │
                                   ▼
        ┌──────────────────────────────────────────────────────────┐
        │         STEP 5: UPLOAD TO AZURE                           │
        │  ┌─────────────────────────────────────────────────────┐ │
        │  │ Create blob package:                                │ │
        │  │                                                     │ │
        │  │ {                                                   │ │
        │  │   "commit": {                                       │ │
        │  │     "sha": "abc123",                                │ │
        │  │     "message": "PROJ-123: Fix bug",                 │ │
        │  │     "file_diffs": [...]                             │ │
        │  │   },                                                │ │
        │  │   "jira_context": {                                 │ │
        │  │     "issue_key": "PROJ-123",                        │ │
        │  │     "summary": "Auth timeout issue",                │ │
        │  │     "description": "..."                            │ │
        │  │   },                                                │ │
        │  │   "analysis": {                                     │ │
        │  │     "analysis": "**Problem**: ...",                 │ │
        │  │     "model": "gpt-4",                               │ │
        │  │     "tokens_used": 542                              │ │
        │  │   }                                                 │ │
        │  │ }                                                   │ │
        │  │                                                     │ │
        │  │ Upload to:                                          │ │
        │  │ Azure Blob: 2026-05-24T10-30-00_abc123.json         │ │
        │  └─────────────────────────────────────────────────────┘ │
        └──────────────────────────────────────────────────────────┘
                                   │
                                   ▼
        ┌──────────────────────────────────────────────────────────┐
        │                     COMPLETE!                             │
        │  Everything stored locally AND in cloud                   │
        │  Developer can continue working immediately               │
        └──────────────────────────────────────────────────────────┘
```

## Data Flow

```
┌─────────────┐         ┌─────────────┐         ┌─────────────┐
│   Git       │         │   Jira      │         │  OpenAI/    │
│  Repository │         │     API     │         │ OpenRouter  │
└──────┬──────┘         └──────┬──────┘         └──────┬──────┘
       │                       │                        │
       │ commit                │                        │
       ▼                       │                        │
┌──────────────┐               │                        │
│ Post-Commit  │               │                        │
│    Hook      │───────────────┤                        │
└──────┬───────┘      fetch    │                        │
       │             issue     │                        │
       │                       ▼                        │
       │              ┌─────────────────┐               │
       │              │ Jira Context    │               │
       │              │ • Summary       │               │
       │              │ • Description   │               │
       │              │ • Status        │               │
       │              └────────┬────────┘               │
       │                       │                        │
       ├───────────────────────┴────────────────────────┤
       │           Build Enhanced Prompt                │
       │                                                 │
       └─────────────────────────────────────────────────┤
                                                  analyze│
                                                         ▼
                                               ┌──────────────────┐
                                               │  AI Analysis     │
                                               │  • Problem       │
                                               │  • Solution      │
                                               │  • Key Changes   │
                                               │  • Impact        │
                                               └────────┬─────────┘
                                                        │
       ┌────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│                  Storage (3 locations)                        │
├──────────────────────────────────────────────────────────────┤
│                                                               │
│  1. Local:          .ai_memory/commits/*.json                │
│     ├── Commit data only                                     │
│     └── Fast access                                          │
│                                                               │
│  2. Local Index:    .ai_memory/index.jsonl                   │
│     ├── Lightweight metadata                                 │
│     └── Quick lookups                                        │
│                                                               │
│  3. Azure Blob:     https://account.blob.core.windows.net    │
│     ├── Commit + Jira + Analysis                             │
│     ├── Durable storage                                      │
│     ├── Searchable                                           │
│     └── Shareable                                            │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

## Configuration Dependencies

```
┌─────────────────────────────────────────────────────────────┐
│                    Feature Dependencies                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Basic Capture (Always Works)                               │
│  ├── No env vars required                                   │
│  └── Saves to .ai_memory/commits/                           │
│                                                              │
│  Jira Enrichment (Optional)                                 │
│  ├── JIRA_DOMAIN                                            │
│  ├── JIRA_EMAIL                                             │
│  └── JIRA_API_TOKEN                                         │
│                                                              │
│  AI Analysis (Optional)                                     │
│  ├── OPENAI_API_KEY                                         │
│  │   OR                                                     │
│  └── OPENROUTER_API_KEY                                     │
│                                                              │
│  Azure Storage (Optional)                                   │
│  ├── AZURE_STORAGE_ENDPOINT                                 │
│  └── Azure authentication (az login / DefaultAzureCredential)│
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Error Handling Flow

```
Each step has independent error handling:

┌──────────────┐
│ Capture      │ ──── ❌ Error? → Log + Return (commit still succeeds)
└──────┬───────┘
       │ ✅ Success
       ▼
┌──────────────┐
│ Save Local   │ ──── ❌ Error? → Log + Return (commit still succeeds)
└──────┬───────┘
       │ ✅ Success
       ▼
┌──────────────┐
│ Fetch Jira   │ ──── ❌ Error? → Log warning + Continue (without Jira context)
└──────┬───────┘
       │ ✅ Success or Skipped
       ▼
┌──────────────┐
│ AI Analysis  │ ──── ❌ Error? → Log warning + Continue (without analysis)
└──────┬───────┘
       │ ✅ Success or Skipped
       ▼
┌──────────────┐
│ Azure Upload │ ──── ❌ Error? → Log warning + Continue (local still saved)
└──────────────┘

Result: Commits ALWAYS succeed, failures are non-blocking
```

## Timeline Example

```
Time    Action                              Status
─────────────────────────────────────────────────────────────────
00:00   git commit -m "PROJ-123: Fix bug"   
00:00   → Commit completes                  ✅ User can continue
00:00   → Hook starts (background)          
00:01   → Capture commit                    ✅
00:01   → Save to .ai_memory/               ✅
00:02   → Fetch PROJ-123 from Jira          ✅
00:04   → Send to LLM for analysis          ✅
00:07   → Receive AI analysis               ✅
00:08   → Upload to Azure Blob              ✅
00:08   → Hook complete                     

Total: ~8 seconds (in background, doesn't block user)
```

## Comparison: Before vs After

### Before (Original)
```
Commit → Capture → Save Local → [Optional API POST]
           ↓
    Just commit data
```

### After (Enhanced)
```
Commit → Capture → Save Local → Fetch Jira → AI Analysis → Azure Upload
           ↓          ↓            ↓             ↓              ↓
       Commit      Commit      +Jira        +AI          Complete
        data        data      context    analysis        Package
```

## Storage Comparison

### Local Only (.ai_memory/)
```json
{
  "sha": "abc123",
  "message": "PROJ-123: Fix bug",
  "file_diffs": [...]
}
```
**Size**: ~50KB per commit

### Azure Blob (Complete Package)
```json
{
  "commit": {...},           // 50KB
  "jira_context": {...},     // 2KB
  "analysis": {...}          // 1KB
}
```
**Size**: ~53KB per commit
**Benefit**: Full context in one place

## See Also

- [Enhanced Workflow Documentation](enhanced_workflow.md)
- [Implementation Summary](../ENHANCED_WORKFLOW_IMPLEMENTATION.md)
- [Jira Integration](jira_issue_details.md)
- [Azure Setup](azure_setup.md)
