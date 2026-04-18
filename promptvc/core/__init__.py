"""
promptvc.core — version control engine for LLM prompts.

Public surface:
    PromptRepo              – main entry point
    StorageEngine           – low-level persistence
    get_tokenizer           – retrieve tokenizer by name
    register_tokenizer      – add custom tokenizer
    unregister_tokenizer    – remove custom tokenizer
    list_tokenizers         – list registered tokenizers
    compute_diff            – word-level diff between prompts
    format_diff             – format diff lines for display
    LockGuard               – version lock enforcement
    Exceptions              – PromptVCError, LockError, and subclasses
"""

from promptvc.core.repo import PromptRepo
from promptvc.core.storage import (
    StorageEngine,
    PromptVCError,
    PromptSpaceNotFoundError,
    VersionNotFoundError,
    RepoNotInitializedError,
)
from promptvc.core.lock import (
    LockGuard,
    LockError,
    VersionLockedError,
    AlreadyLockedError,
)
from promptvc.core.diff import compute_diff, format_diff
from promptvc.core.tokenizer import (
    get_tokenizer,
    register_tokenizer,
    unregister_tokenizer,
    list_tokenizers,
    get_tokenizer_info,
)

__all__ = [
    # Main interface
    "PromptRepo",
    # Storage
    "StorageEngine",
    # Tokenizer
    "get_tokenizer",
    "register_tokenizer",
    "unregister_tokenizer",
    "list_tokenizers",
    "get_tokenizer_info",
    # Diff
    "compute_diff",
    "format_diff",
    # Locking
    "LockGuard",
    # Exceptions — grouped for discoverability
    "PromptVCError",
    "PromptSpaceNotFoundError",
    "VersionNotFoundError",
    "RepoNotInitializedError",
    "LockError",
    "VersionLockedError",
    "AlreadyLockedError",
]