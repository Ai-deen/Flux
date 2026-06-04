"""
Flux - AI-powered developer lifecycle automation

Automatically capture, store, and analyze your Git commit history.
From ticket to code, automatically.
"""

__version__ = "0.1.0"

# Expose commonly used functions at package level
from engmemory.core import capture_commit, install, uninstall, status
from engmemory.storage import write_commit, read_recent, read_commit

__all__ = [
    "__version__",
    "capture_commit",
    "write_commit",
    "read_recent",
    "read_commit",
    "install",
    "uninstall",
    "status",
]
