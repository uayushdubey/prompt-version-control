from __future__ import annotations

import copy
import json
import os
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
    latest: Optional[str]


class RunRecord(TypedDict):
    version: str
    output: str
    tokens: Optional[int]
    timestamp: str


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

    def _validate_space_structure(self, name: str, data: object) -> PromptSpace:
        """
        Validate that loaded JSON conforms to the expected PromptSpace structure.

        Raises:
            PromptVCError: If required fields are missing or have wrong types.
        """
        if not isinstance(data, dict):
            raise PromptVCError(
                f"Corrupted data in prompt space '{name}': "
                "expected a JSON object at the top level."
            )

        versions = data.get("versions")
        if not isinstance(versions, dict):
            raise PromptVCError(
                f"Corrupted data in prompt space '{name}': "
                "'versions' must be a dict."
            )

        latest = data.get("latest")
        if latest is not None and not isinstance(latest, str):
            raise PromptVCError(
                f"Corrupted data in prompt space '{name}': "
                "'latest' must be a string or null."
            )

        return data  # type: ignore[return-value]

    def _space_path(self, name: str) -> Path:
        return self._root / f"{name}.json"

    # -------------------------
    # Internal Hooks (extensibility points)
    # -------------------------

    def _on_space_loaded(self, name: str, data: PromptSpace) -> None:
        """Called after a space is successfully loaded from disk. Reserved for future use."""
        pass

    def _on_space_saved(self, name: str, data: PromptSpace) -> None:
        """Called after a space is successfully persisted to disk. Reserved for future use."""
        pass

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
            PromptVCError: If stored JSON is corrupted or structurally invalid.
        """
        self._ensure_initialized()
        self._validate_name(name)

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
                raw: object = json.load(f)
        except json.JSONDecodeError as e:
            raise PromptVCError(
                f"Failed to parse prompt space '{name}': JSON is malformed."
            ) from e

        data = self._validate_space_structure(name, raw)

        self._cache[name] = copy.deepcopy(data)

        self._on_space_loaded(name, data)

        return copy.deepcopy(data)

    def save_space(self, name: str, data: PromptSpace) -> None:
        """
        Atomically persist a prompt space to disk and update cache.

        Uses a temp file + replace for crash safety.

        Raises:
            PromptVCError: If persistence fails.
        """
        self._ensure_initialized()
        self._validate_name(name)

        file_path = self._space_path(name)
        temp_path: Optional[Path] = None

        try:
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

            temp_path.replace(file_path)

        except Exception as e:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

            raise PromptVCError(
                f"Failed to persist prompt space '{name}': {e}"
            ) from e

        self._cache[name] = copy.deepcopy(data)

        self._on_space_saved(name, data)

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

    # -------------------------
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
                f"Version '{version}' not found in space '{name}'. "
                "Use `log` to list available versions."
            )

        return space["versions"][version]

    def append_run(self, name: str, run_data: RunRecord) -> None:
        """
        Append a run record to a prompt space.

        Validates required fields before appending.
        Ensures backward compatibility by creating 'runs' if missing.

        Raises:
            ValueError: If required fields are missing from run_data.
            PromptVCError: If the space cannot be loaded or saved.
        """
        version = run_data.get("version")  # type: ignore[typeddict-item]
        if not version:
            raise ValueError(
                f"run_data for space '{name}' must include a non-empty 'version' field."
            )

        output = run_data.get("output")  # type: ignore[typeddict-item]
        if output is None:
            raise ValueError(
                f"run_data for space '{name}' must include an 'output' field."
            )

        space = self.load_space(name)

        runs: list = space.setdefault("runs", [])  # type: ignore[typeddict-unknown-key]
        if not isinstance(runs, list):
            raise PromptVCError(
                f"Corrupted 'runs' field in prompt space '{name}': expected a list."
            )

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