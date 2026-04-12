"""
promptvc.core.repo
~~~~~~~~~~~~~~~~~~
Public-facing repository API — the single entry-point for consumers.

Usage::

    from promptvc.core.repo import PromptRepo

    repo = PromptRepo()
    repo.init_repo()

    repo.commit(
        name="summarizer",
        prompt="Summarize the following text in 3 bullet points: {text}",
        message="Initial summarizer prompt",
    )

    for version in repo.log("summarizer"):
        print(version["id"], version["message"])

    text = repo.get("summarizer", "v1")
    repo.lock("summarizer", "v1")

Design
------
:class:`PromptRepo` is an *orchestrator*: it delegates storage to
:class:`~promptvc.core.storage.StorageEngine`, token counting to a
:class:`~promptvc.core.tokenizer.BaseTokenizer`, and lock enforcement to
:class:`~promptvc.core.lock.LockGuard`.

None of those collaborators know about each other — all wiring lives here.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from promptvc.core.lock import LockGuard, VersionLockedError  # noqa: F401 (re-export)
from promptvc.core.storage import (
    PromptSpaceData,
    PromptSpaceNotFoundError,  # noqa: F401 (re-export)
    RepoNotInitializedError,   # noqa: F401 (re-export)
    StorageEngine,
    VersionData,
    VersionNotFoundError,       # noqa: F401 (re-export)
)
from promptvc.core.tokenizer import BaseTokenizer, get_tokenizer


# ---------------------------------------------------------------------------
# Exceptions specific to repo-level logic
# ---------------------------------------------------------------------------

class PromptVCError(Exception):
    """Root exception for all promptvc errors."""


class CommitError(PromptVCError):
    """Raised when a commit operation fails for a business-logic reason."""


# ---------------------------------------------------------------------------
# Commit result — rich return type avoids magic tuples
# ---------------------------------------------------------------------------

class CommitResult:
    """
    Returned by :meth:`PromptRepo.commit`.

    Attributes:
        name:    Prompt space name.
        version: The newly created version id (e.g. ``"v3"``).
        tokens:  Estimated token count for the committed prompt.
        hash:    SHA-256 hex digest of the prompt text.
    """

    __slots__ = ("name", "version", "tokens", "hash")

    def __init__(self, name: str, version: str, tokens: int, hash: str) -> None:
        self.name = name
        self.version = version
        self.tokens = tokens
        self.hash = hash

    def __repr__(self) -> str:
        return (
            f"CommitResult(name={self.name!r}, version={self.version!r}, "
            f"tokens={self.tokens}, hash={self.hash[:8]}…)"
        )


# ---------------------------------------------------------------------------
# PromptRepo
# ---------------------------------------------------------------------------

class PromptRepo:
    """
    Git-inspired version control for LLM prompts.

    Parameters
    ----------
    root:
        Project root directory.  Defaults to the current working directory.
        The repository is stored in ``<root>/.promptvc/``.
    tokenizer_name:
        Which built-in tokenizer to use for token counting.
        One of ``"whitespace"`` (default), ``"wordpunct"``, ``"character"``.
    tokenizer:
        Pass a custom :class:`~promptvc.core.tokenizer.BaseTokenizer` instance
        directly.  Takes precedence over *tokenizer_name* if both are given.

    Thread safety
    -------------
    The in-memory cache inside :class:`~promptvc.core.storage.StorageEngine`
    is **not** thread-safe.  For concurrent workloads, create one
    :class:`PromptRepo` instance per thread/process.
    """

    def __init__(
        self,
        root: Optional[Path | str] = None,
        tokenizer_name: str = "whitespace",
        tokenizer: Optional[BaseTokenizer] = None,
    ) -> None:
        self._storage = StorageEngine(root=Path(root) if root else None)
        self._tokenizer: BaseTokenizer = tokenizer or get_tokenizer(tokenizer_name)
        self._lock_guard = LockGuard()

    # ------------------------------------------------------------------
    # Repo lifecycle
    # ------------------------------------------------------------------

    def init_repo(self) -> bool:
        """
        Initialize the repository by creating the ``.promptvc`` directory.

        Idempotent — safe to call multiple times.

        Returns:
            ``True`` if the directory was created, ``False`` if it already existed.

        Example::

            repo = PromptRepo()
            repo.init_repo()  # creates .promptvc/
        """
        created = self._storage.initialize()
        return created

    @property
    def is_initialized(self) -> bool:
        """``True`` if the repository has been initialized."""
        return self._storage.is_initialized

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def commit(
        self,
        name: str,
        prompt: str,
        message: str,
    ) -> CommitResult:
        """
        Record a new version of a prompt.

        Creates the prompt space if it does not exist.  Versions are always
        appended — existing versions are **never** modified.

        Args:
            name:    Prompt space name (e.g. ``"summarizer"``).
            prompt:  The raw prompt text.
            message: A short description of what changed (like a git commit message).

        Returns:
            A :class:`CommitResult` describing the created version.

        Raises:
            RepoNotInitializedError: If :meth:`init_repo` has not been called.
            ValueError:              If *name* or *prompt* are empty.
            CommitError:             For other commit-level failures.

        Example::

            result = repo.commit(
                name="classifier",
                prompt="Classify the sentiment of: {text}",
                message="Add sentiment classifier",
            )
            print(result.version)  # "v1"
        """
        self._assert_initialized()
        self._validate_commit_args(name, prompt, message)

        space_data = self._storage.load_or_create_space(name)
        version_id = self._storage.next_version_id(space_data)

        version: VersionData = {
            "id": version_id,
            "prompt": prompt,
            "message": message.strip(),
            "timestamp": _utc_now_iso(),
            "tokens": self._tokenizer.count(prompt),
            "locked": False,
            "hash": _sha256(prompt),
        }

        # Defensive: ensure we never overwrite (belt-and-suspenders guard)
        if version_id in space_data["versions"]:
            raise CommitError(
                f"Version id '{version_id}' already exists in space '{name}'. "
                "This is a bug — please report it."
            )

        space_data["versions"][version_id] = version
        space_data["latest"] = version_id

        self._storage.save_space(name, space_data)

        return CommitResult(
            name=name,
            version=version_id,
            tokens=version["tokens"],
            hash=version["hash"],
        )

    def log(self, name: str) -> list[VersionData]:
        """
        Return all versions of a prompt space, sorted latest → oldest.

        Args:
            name: Prompt space name.

        Returns:
            List of :class:`~promptvc.core.storage.VersionData` dicts,
            ordered by descending version number.

        Raises:
            RepoNotInitializedError: If the repo is not initialized.
            PromptSpaceNotFoundError: If *name* does not exist.

        Example::

            for v in repo.log("summarizer"):
                print(f"{v['id']}  {v['timestamp']}  {v['message']}")
        """
        self._assert_initialized()
        space_data = self._storage.load_space(name)
        versions = list(space_data["versions"].values())
        return _sort_versions_desc(versions)

    def get(self, name: str, version: str) -> str:
        """
        Retrieve the prompt text for a specific version.

        Args:
            name:    Prompt space name.
            version: Version id (e.g. ``"v2"``). Case-insensitive.

        Returns:
            The raw prompt string.

        Raises:
            RepoNotInitializedError:  If the repo is not initialized.
            PromptSpaceNotFoundError: If *name* does not exist.
            VersionNotFoundError:     If *version* does not exist.

        Example::

            prompt_text = repo.get("summarizer", "v1")
        """
        self._assert_initialized()
        version_norm = version.lower().strip()
        version_data = self._storage.get_version(name, version_norm)
        return version_data["prompt"]

    def get_version_meta(self, name: str, version: str) -> VersionData:
        """
        Return the full metadata dict for a specific version.

        Useful when you need token counts, hash, lock status, etc.

        Args:
            name:    Prompt space name.
            version: Version id.

        Returns:
            A :class:`~promptvc.core.storage.VersionData` dict.
        """
        self._assert_initialized()
        version_norm = version.lower().strip()
        return self._storage.get_version(name, version_norm)

    def list_spaces(self) -> list[str]:
        """
        Return a sorted list of all prompt space names in the repository.

        Returns:
            List of strings, e.g. ``["classifier", "summarizer"]``.

        Raises:
            RepoNotInitializedError: If the repo is not initialized.

        Example::

            spaces = repo.list_spaces()
        """
        self._assert_initialized()
        return self._storage.list_space_names()

    def lock(self, name: str, version: str) -> None:
        """
        Mark a specific version as locked (immutable).

        Once locked, a version's prompt and metadata **cannot** be changed.
        Attempting to overwrite a locked version raises
        :class:`~promptvc.core.lock.VersionLockedError`.

        Args:
            name:    Prompt space name.
            version: Version id to lock.

        Raises:
            RepoNotInitializedError:  If the repo is not initialized.
            PromptSpaceNotFoundError: If *name* does not exist.
            VersionNotFoundError:     If *version* does not exist.
            AlreadyLockedError:       If *version* is already locked.

        Example::

            repo.lock("summarizer", "v1")
        """
        self._assert_initialized()
        version_norm = version.lower().strip()
        space_data = self._storage.load_space(name)

        if version_norm not in space_data["versions"]:
            raise VersionNotFoundError(name, version_norm)

        existing = space_data["versions"][version_norm]

        # Guard: raise if already locked
        self._lock_guard.assert_not_already_locked(existing, name, version_norm)

        # Apply lock (returns a new dict — never mutates in place)
        locked_version = self._lock_guard.apply_lock(existing)
        space_data["versions"][version_norm] = locked_version

        self._storage.save_space(name, space_data)

    # ------------------------------------------------------------------
    # Convenience / introspection
    # ------------------------------------------------------------------

    def latest(self, name: str) -> Optional[VersionData]:
        """
        Return the metadata for the latest version, or ``None`` if the space is empty.

        Args:
            name: Prompt space name.
        """
        self._assert_initialized()
        space_data = self._storage.load_space(name)
        latest_id = space_data.get("latest")
        if latest_id is None:
            return None
        return space_data["versions"].get(latest_id)

    def diff_tokens(self, name: str, v1: str, v2: str) -> int:
        """
        Return the token count difference between two versions.

        Args:
            name: Prompt space name.
            v1:   Earlier version id.
            v2:   Later version id.

        Returns:
            ``tokens(v2) - tokens(v1)``  (negative means v2 is shorter).
        """
        self._assert_initialized()
        meta1 = self._storage.get_version(name, v1.lower().strip())
        meta2 = self._storage.get_version(name, v2.lower().strip())
        return meta2["tokens"] - meta1["tokens"]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _assert_initialized(self) -> None:
        """Delegate initialization check to storage engine."""
        if not self._storage.is_initialized:
            raise RepoNotInitializedError(self._storage.repo_dir)

    @staticmethod
    def _validate_commit_args(name: str, prompt: str, message: str) -> None:
        if not name or not name.strip():
            raise ValueError("Prompt space 'name' must not be empty.")
        if not prompt:
            raise ValueError("'prompt' text must not be empty.")
        if not message or not message.strip():
            raise ValueError("Commit 'message' must not be empty.")

    def __repr__(self) -> str:
        return (
            f"PromptRepo(root={self._storage.repo_dir.parent!r}, "
            f"initialized={self.is_initialized}, "
            f"tokenizer={self._tokenizer!r})"
        )


# ---------------------------------------------------------------------------
# Module-level pure helpers
# ---------------------------------------------------------------------------

def _sha256(text: str) -> str:
    """Return the SHA-256 hex digest of *text* (UTF-8 encoded)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with timezone info."""
    return datetime.now(tz=timezone.utc).isoformat()


def _sort_versions_desc(versions: list[VersionData]) -> list[VersionData]:
    """
    Sort *versions* by descending version number.

    Extracts the numeric suffix from version ids (``"v3"`` → ``3``) for
    sorting.  Non-standard ids (no numeric suffix) are sorted last.
    """

    def _sort_key(v: VersionData) -> int:
        vid = v.get("id", "v0")
        try:
            return int(vid.lstrip("v"))
        except ValueError:
            return -1

    return sorted(versions, key=_sort_key, reverse=True)