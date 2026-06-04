# Project Structure

This document explains the reorganized folder structure of the engmemory project.

## Directory Layout

```
hackathon/
├── engmemory/                    # Main package
│   ├── __init__.py               # Package initialization & exports
│   ├── cli.py                    # CLI entry point
│   │
│   ├── core/                     # Core commit capture functionality
│   │   ├── __init__.py
│   │   ├── capture.py            # Git commit capture logic
│   │   ├── hook.py               # Git hook installation/management
│   │   └── runner.py             # Post-commit hook entry point
│   │
│   ├── storage/                  # Data persistence
│   │   ├── __init__.py
│   │   └── local.py              # Local JSON storage
│   │   └── azure_blob.py         # [TODO] Azure Blob Storage
│   │
│   ├── analysis/                 # AI/ML analysis
│   │   ├── __init__.py
│   │   ├── llm_analyzer.py       # LLM-based commit analysis
│   │   └── categorizer.py        # [TODO] Commit categorization
│   │
│   ├── search/                   # Search & indexing
│   │   ├── __init__.py
│   │   ├── azure_search.py       # [TODO] Azure AI Search
│   │   └── rag.py                # [TODO] RAG queries
│   │
│   └── utils/                    # Utilities
│       ├── __init__.py
│       ├── config.py             # [TODO] Configuration
│       └── logging.py            # [TODO] Logging setup
│
├── test/                         # Tests
│   └── test_capture_storage.py
│
├── .ai_memory/                   # Generated (gitignored)
│   ├── commits/                  # Captured commit JSONs
│   ├── index.jsonl               # Commit index
│   └── engmemory.log             # Debug logs
│
├── .gitignore
├── pyproject.toml
└── README.md
```

## Module Responsibilities

### 📦 `core/` - Core Functionality
- **`capture.py`**: Reads commit metadata and diffs from Git
- **`hook.py`**: Installs/uninstalls the post-commit hook
- **`runner.py`**: Entry point called by the post-commit hook

### 💾 `storage/` - Data Persistence
- **`local.py`**: Writes commit data to `.ai_memory/commits/` as JSON
- **`azure_blob.py`** [TODO]: Upload to Azure Blob Storage

### 🤖 `analysis/` - AI/ML Processing
- **`llm_analyzer.py`**: Uses OpenAI to analyze commits
- **`categorizer.py`** [TODO]: Categorize commits (bug/feature/refactor)

### 🔍 `search/` - Search & Retrieval
- **`azure_search.py`** [TODO]: Index commits in Azure AI Search
- **`rag.py`** [TODO]: RAG-based search queries

### 🛠️ `utils/` - Utilities
- Configuration management
- Logging setup
- Helper functions

## Import Paths

### Old (flat structure):
```python
from engmemory.capture import capture_commit
from engmemory.storage import write_commit
from engmemory.llm_analyzer import analyze_commit
```

### New (nested structure):
```python
from engmemory.core import capture_commit
from engmemory.storage import write_commit, read_recent
from engmemory.analysis import analyze_commit
```

### Package-level imports (recommended):
```python
from engmemory import capture_commit, write_commit
```

## Adding New Features

### Example: Adding Azure Blob Storage

1. Create `engmemory/storage/azure_blob.py`:
```python
from azure.storage.blob import BlobServiceClient

def upload_to_blob(commit_data: dict, analysis: dict) -> str:
    # Your Azure Blob upload logic
    pass
```

2. Export in `engmemory/storage/__init__.py`:
```python
from .local import write_commit, read_recent, read_commit
from .azure_blob import upload_to_blob

__all__ = [
    "write_commit",
    "read_recent",
    "read_commit",
    "upload_to_blob",
]
```

3. Use it:
```python
from engmemory.storage import upload_to_blob
```

## Benefits of This Structure

✅ **Separation of Concerns** - Each module has a single responsibility  
✅ **Scalability** - Easy to add new features without clutter  
✅ **Team-Friendly** - Multiple developers can work on different modules  
✅ **Testability** - Tests can mirror the source structure  
✅ **Import Clarity** - Clear, hierarchical imports  

## Migration Notes

All imports have been updated. Old files remain in the root `engmemory/` folder but are no longer used:
- `capture.py` → `core/capture.py`
- `hook.py` → `core/hook.py`
- `runner.py` → `core/runner.py`
- `storage.py` → `storage/local.py`
- `llm_analyzer.py` → `analysis/llm_analyzer.py`

You can safely delete the old files after testing:
```bash
rm engmemory/capture.py
rm engmemory/hook.py
rm engmemory/runner.py
rm engmemory/storage.py
rm engmemory/llm_analyzer.py
```
