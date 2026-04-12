"""
promptvc.core.storage
~~~~~~~~~~~~~~~~~~~~~
Dual-layer storage engine: in-memory dict (O(1) access) + JSON persistence.

Architecture
------------
::

    ┌─────────────────────────────────┐
    │           PromptRepo            │  ← orchestration / public API
    └────────────────┬────────────────┘
                     │ uses
    ┌────────────────▼────────────────┐
    │         StorageEngine           │  ← THIS MODULE
    │  ┌──────────────────────────┐   │
    │  │  in-memory cache (dict)  │   │  O(1) reads after first load
    │  └──────────┬───────────────┘   │
    │             │ write-through      │
    │  ┌──────────▼───────────────┐   │
    │  │   .promptvc/<name>.json  │   │  durable persistence
    │  └──────────────────────────┘   │
    └─────────────────────────────────┘

All file I/O is funnelled through :class:`StorageEngine`.  The rest of the
codebase never touches ``open()`` or ``json`` directly.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Type aliases & TypedDicts — act as the schema contract
# ---------------------------------------------------------------------------

class VersionData(TypedDict):
    """Schema for a single stored version."""

    id: str              # "v1", "v2", …
    prompt: str          # raw prompt text
    message: str         # commit message
    timestamp: str       # ISO-8601 datetime string
    tokens: int          # estimated token count
    locked: bool         # immutability flag
    hash: str            # SHA-256 hex digest of the prompt


class PromptSpaceData(TypedDict):
    """Schema for the JSON file of a single prompt space."""

    versions: dict[str, VersionData]   # keyed by version id
    latest: Optional[str]              # e.g. "v3", or None if empty


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class StorageError(Exception):
    """Base for all storage-layer exceptions."""


class PromptSpaceNotFoundError(StorageError):
    """Raised when referencing a prompt space that does not exist on disk."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(
            f"Prompt space '{name}' does not exist. "
            "Use repo.commit() to create it."
        )


class VersionNotFoundError(StorageError):
    """Raised when referencing a version that does not exist."""

    def __init__(self, name: str, version: str) -> None:
        self.name = name
        self.version = version
        super().__init__(
            f"Version '{version}' does not exist in prompt space '{name}'."
        )


class RepoNotInitializedError(StorageError):
    """Raised when trying to use the repo before :meth:`init_repo` is called."""

    def __init__(self, repo_dir: Path) -> None:
        self.repo_dir = repo_dir
        super().__init__(
            f"Repository not initialized at '{repo_dir}'. "
            "Call repo.init_repo() first."
        )


# ---------------------------------------------------------------------------
# Storage engine
# ---------------------------------------------------------------------------

REPO_DIR_NAME: str = ".promptvc"
FILE_SUFFIX: str = ".json"
_JSON_INDENT: int = 2


class StorageEngine:
    """
    Manages all persistence for a single ``promptvc`` repository.

    Parameters
    ----------
    root:
        Project root directory.  Defaults to the current working directory.

    The engine maintains a write-through in-memory cache so that repeated
    reads within a session never hit disk.  Each :meth:`save_space` call
    atomically writes to disk via a temp-file rename strategy to avoid
    leaving corrupt JSON on crash.
    """

    def __init__(self, root: Optional[Path] = None) -> None:
        self._root: Path = Path(root) if root else Path.cwd()
        self._repo_dir: Path = self._root / REPO_DIR_NAME

        # In-memory cache: space_name → PromptSpaceData
        self._cache: dict[str, PromptSpaceData] = {}

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def repo_dir(self) -> Path:
        """Absolute path to the ``.promptvc`` directory."""
        return self._repo_dir

    @property
    def is_initialized(self) -> bool:
        """``True`` if the ``.promptvc`` directory exists."""
        return self._repo_dir.is_dir()

    # ------------------------------------------------------------------
    # Repo lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> bool:
        """
        Create the ``.promptvc`` directory if it does not exist.

        Returns:
            ``True`` if the directory was created, ``False`` if it already existed.
        """
        if self._repo_dir.exists():
            return False
        self._repo_dir.mkdir(parents=True, exist_ok=True)
        return True

    def _assert_initialized(self) -> None:
        if not self.is_initialized:
            raise RepoNotInitializedError(self._repo_dir)

    # ------------------------------------------------------------------
    # Space discovery
    # ------------------------------------------------------------------

    def list_space_names(self) -> list[str]:
        """
        Return sorted list of all prompt space names in the repository.

        Reads directory listing; does NOT rely on the cache so that
        spaces created by other processes are visible.
        """
        self._assert_initialized()
        return sorted(
            p.stem
            for p in self._repo_dir.iterdir()
            if p.is_file() and p.suffix == FILE_SUFFIX
        )

    def space_exists(self, name: str) -> bool:
        """Return ``True`` if a JSON file exists for *name*."""
        return self._space_path(name).is_file()

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def load_space(self, name: str) -> PromptSpaceData:
        """
        Load a prompt space into the cache and return it.

        Cache-hit: returns immediately without disk I/O.
        Cache-miss: reads JSON from disk, populates cache, returns data.

        Raises:
            PromptSpaceNotFoundError: If no file exists for *name*.
        """
        self._assert_initialized()

        if name in self._cache:
            return self._cache[name]

        path = self._space_path(name)
        if not path.is_file():
            raise PromptSpaceNotFoundError(name)

        with path.open("r", encoding="utf-8") as fh:
            raw: dict = json.load(fh)

        data: PromptSpaceData = {
            "versions": raw.get("versions", {}),
            "latest": raw.get("latest", None),
        }
        self._cache[name] = data
        return data

    def save_space(self, name: str, data: PromptSpaceData) -> None:
        """
        Persist *data* to disk and update the in-memory cache.

        Uses an atomic write (write to ``<name>.tmp`` then rename) so a
        crash mid-write never corrupts the existing JSON file.

        Args:
            name: Prompt space name.
            data: Full space data to persist.
        """
        self._assert_initialized()

        path = self._space_path(name)
        tmp_path = path.with_suffix(".tmp")

        try:
            with tmp_path.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=_JSON_INDENT, ensure_ascii=False)
            # Atomic rename — on POSIX this is guaranteed atomic;
            # on Windows it replaces atomically since Python 3.3+.
            os.replace(tmp_path, path)
        except Exception:
            # Clean up temp file on failure
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

        # Update cache *after* successful disk write
        self._cache[name] = data

    def load_or_create_space(self, name: str) -> PromptSpaceData:
        """
        Return existing space data or return a fresh empty space.

        Does NOT write to disk — the caller must call :meth:`save_space`.
        """
        if self.space_exists(name):
            return self.load_space(name)
        return {"versions": {}, "latest": None}

    # ------------------------------------------------------------------
    # Version helpers
    # ------------------------------------------------------------------

    def get_version(self, name: str, version: str) -> VersionData:
        """
        Retrieve a specific version from *name*.

        Args:
            name:    Prompt space name.
            version: Version id (e.g. ``"v1"``).

        Raises:
            PromptSpaceNotFoundError: If the space does not exist.
            VersionNotFoundError:     If *version* does not exist in the space.
        """
        data = self.load_space(name)
        if version not in data["versions"]:
            raise VersionNotFoundError(name, version)
        return data["versions"][version]

    def next_version_id(self, data: PromptSpaceData) -> str:
        """
        Compute the next sequential version id.

        Parses existing numeric suffixes (``v1`` → ``1``) and returns
        ``v{max + 1}``.  Returns ``"v1"`` for an empty space.

        Args:
            data: The current space data (may have zero versions).

        Returns:
            A version string like ``"v1"``, ``"v2"``, etc.
        """
        if not data["versions"]:
            return "v1"

        indices: list[int] = []
        for vid in data["versions"]:
            try:
                indices.append(int(vid.lstrip("v")))
            except ValueError:
                pass  # skip non-standard ids — future-proof

        return f"v{max(indices) + 1}" if indices else "v1"

    def invalidate_cache(self, name: Optional[str] = None) -> None:
        """
        Evict entries from the in-memory cache.

        Args:
            name: If given, evict only that space.  If ``None``, flush all.
        """
        if name is None:
            self._cache.clear()
        else:
            self._cache.pop(name, None)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _space_path(self, name: str) -> Path:
        """Return the absolute path for *name*'s JSON file."""
        safe_name = self._sanitize_name(name)
        return self._repo_dir / f"{safe_name}{FILE_SUFFIX}"

    @staticmethod
    def _sanitize_name(name: str) -> str:
        """
        Validate and return a safe file-system name.

        Raises:
            ValueError: If *name* contains path separators or is empty.
        """
        stripped = name.strip()
        if not stripped:
            raise ValueError("Prompt space name must not be empty.")
        forbidden = set("/\\:*?\"<>|")
        bad = forbidden.intersection(stripped)
        if bad:
            raise ValueError(
                f"Prompt space name '{stripped}' contains forbidden characters: "
                f"{', '.join(sorted(bad))}."
            )
        return stripped

    def __repr__(self) -> str:
        return (
            f"StorageEngine(root={self._root!r}, "
            f"initialized={self.is_initialized}, "
            f"cached_spaces={list(self._cache)})"
        )