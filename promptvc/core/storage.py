from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, TypedDict


# =========================
# Exceptions
# =========================

class PromptVCError(Exception):
    """Base exception for PromptVC."""


class PromptSpaceNotFoundError(PromptVCError):
    """Raised when a prompt space does not exist."""


class VersionNotFoundError(PromptVCError):
    """Raised when a version is not found."""


class RepoNotInitializedError(PromptVCError):
    """Raised when .promptvc directory is not initialized."""


# =========================
# TypedDict Schemas
# =========================

class VersionData(TypedDict):
    id: str
    prompt: str
    message: str
    timestamp: str
    tokens: int
    locked: bool
    hash: str


class PromptSpace(TypedDict):
    versions: Dict[str, VersionData]
    latest: Optional[str]  # Empty string or None before first commit


# =========================
# Storage Engine
# =========================

class StorageEngine:
    """
    Handles persistence and retrieval of prompt spaces.

    - In-memory cache for O(1) repeated reads
    - Atomic JSON writes via temp file + replace
    - Strict name validation
    """

    _SPACE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")

    def __init__(self, root: Optional[Path] = None) -> None:
        self._root: Path = root or Path.cwd() / ".promptvc"
        self._cache: Dict[str, PromptSpace] = {}

    # -------------------------
    # Initialization
    # -------------------------

    def initialize(self) -> None:
        """Create the storage directory if it does not exist."""
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def is_initialized(self) -> bool:
        """Return True if the storage directory exists."""
        return self._root.exists() and self._root.is_dir()

    def _ensure_initialized(self) -> None:
        if not self.is_initialized:
            raise RepoNotInitializedError(
                "Repository not initialized. Run `promptvc init` first."
            )

    # -------------------------
    # Validation
    # -------------------------

    def _validate_name(self, name: str) -> None:
        if not self._SPACE_NAME_PATTERN.match(name):
            raise ValueError(
                f"Invalid prompt space name '{name}'. "
                "Only alphanumeric characters, hyphens, and underscores are allowed."
            )

    def _space_path(self, name: str) -> Path:
        return self._root / f"{name}.json"

    # -------------------------
    # Cache
    # -------------------------
    def invalidate_cache(self, name: Optional[str] = None) -> None:
        """
        Invalidate cache for a specific space, or all spaces if name is None.

        Useful in tests and when external writes are expected.
        """
        if name is None:
            self._cache.clear()
        else:
            self._cache.pop(name, None)

    # -------------------------
    # Core I/O
    # -------------------------

    def load_space(self, name: str) -> PromptSpace:
        """
        Load a prompt space from cache or disk.

        Raises:
            PromptSpaceNotFoundError: If no file exists for this space.
            PromptVCError: If stored JSON is corrupted.
        """
        import copy

        self._ensure_initialized()
        self._validate_name(name)

        # Return from cache (safe copy)
        if name in self._cache:
            return copy.deepcopy(self._cache[name])

        file_path = self._space_path(name)
        if not file_path.exists():
            raise PromptSpaceNotFoundError(
                f"Prompt space '{name}' does not exist. "
                "Use `commit` to create it."
            )

        try:
            with file_path.open("r", encoding="utf-8") as f:
                data: PromptSpace = json.load(f)
        except json.JSONDecodeError as e:
            raise PromptVCError(
                f"Corrupted data in prompt space '{name}'."
            ) from e

        # Store safe copy in cache
        self._cache[name] = data

        return copy.deepcopy(data)

    def save_space(self, name: str, data: PromptSpace) -> None:
        """
        Atomically persist a prompt space to disk and update cache.

        Uses a temp file + replace for crash safety.

        Raises:
            PromptVCError: If persistence fails.
        """
        import copy
        import os

        self._ensure_initialized()
        self._validate_name(name)

        file_path = self._space_path(name)
        temp_path: Optional[Path] = None

        try:
            # Ensure directory exists (handles deletion mid-run)
            self._root.mkdir(parents=True, exist_ok=True)

            with tempfile.NamedTemporaryFile(
                    mode="w",
                    delete=False,
                    dir=self._root,
                    suffix=".tmp",
                    encoding="utf-8",
            ) as tmp:
                json.dump(data, tmp, indent=2)
                tmp.flush()
                os.fsync(tmp.fileno())
                temp_path = Path(tmp.name)

            # Atomic replace
            temp_path.replace(file_path)

        except Exception as e:
            # Cleanup temp file if it exists
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass  # best-effort cleanup

            raise PromptVCError(
                f"Failed to persist prompt space '{name}'."
            ) from e

        # Update cache only after successful write
        self._cache[name] = copy.deepcopy(data)

    def load_or_create_space(self, name: str) -> PromptSpace:
        """
        Return an existing space, or return a fresh in-memory space.

        Does NOT write to disk — the caller (commit) persists on first save.
        This avoids creating empty .json files for uncommitted spaces.
        """
        try:
            return self.load_space(name)
        except PromptSpaceNotFoundError:
            return {"versions": {}, "latest": None}

    # Version Access
    # -------------------------

    def get_version(self, name: str, version: str) -> VersionData:
        """
        Return a specific version from a space.

        Raises:
            VersionNotFoundError: If the version ID does not exist.
        """
        space = self.load_space(name)

        if version not in space["versions"]:
            raise VersionNotFoundError(
                f"Version '{version}' not found in space '{name}'."
            )

        return space["versions"][version]

    def append_run(self, name: str, run_data: dict) -> None:
        """
        Append a run record to a prompt space.

        Ensures backward compatibility by creating 'runs' if missing.
        """
        space = self.load_space(name)

        runs = space.setdefault("runs", [])
        runs.append(run_data)

        self.save_space(name, space)

    def next_version_id(self, space: PromptSpace) -> str:
        """
        Generate the next sequential version ID (v1, v2, v3, ...).

        Derives the next ID from the highest existing numeric suffix.
        """
        versions = space.get("versions", {})
        nums = [self._version_num(v) for v in versions if self._version_num(v) is not None]
        next_num = (max(nums) + 1) if nums else 1  # type: ignore[arg-type]
        return f"v{next_num}"

    def list_space_names(self) -> List[str]:
        """Return the names of all persisted prompt spaces."""
        self._ensure_initialized()
        return [f.stem for f in self._root.glob("*.json")]

    # -------------------------
    # Helpers
    # -------------------------

    @staticmethod
    def _version_num(version_id: str) -> Optional[int]:
        """
        Parse the numeric suffix from a version ID string (e.g. 'v3' → 3).

        Returns None for malformed IDs.
        """
        if version_id.startswith("v") and version_id[1:].isdigit():
            return int(version_id[1:])
        return None