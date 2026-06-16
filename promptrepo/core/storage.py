from __future__ import annotations

import copy
import json
import os
import re
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, TypedDict



# =========================
# Exceptions
# =========================

class PromptRepoError(Exception):
    """Base exception for PromptVC."""


class PromptSpaceNotFoundError(PromptRepoError):
    """Raised when a prompt space does not exist."""


class VersionNotFoundError(PromptRepoError):
    """Raised when a version is not found."""


class RepoNotInitializedError(PromptRepoError):
    """Raised when .promptrepo directory is not initialized."""


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
        self._root: Path = root or Path.cwd() / ".promptrepo"
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
                "Repository not initialized. Run `promptrepo init` first."
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
            PromptRepoError: If required fields are missing or have wrong types.
        """
        if not isinstance(data, dict):
            raise PromptRepoError(
                f"Corrupted data in prompt space '{name}': "
                "expected a JSON object at the top level."
            )

        versions = data.get("versions")
        if not isinstance(versions, dict):
            raise PromptRepoError(
                f"Corrupted data in prompt space '{name}': "
                "'versions' must be a dict."
            )

        latest = data.get("latest")
        if latest is not None and not isinstance(latest, str):
            raise PromptRepoError(
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
            PromptRepoError: If stored JSON is corrupted or structurally invalid.
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
            raise PromptRepoError(
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
            PromptRepoError: If persistence fails.
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

            raise PromptRepoError(
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
            PromptRepoError: If the space cannot be loaded or saved.
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
            raise PromptRepoError(
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
        """Return the names of all persisted prompt spaces (skips malformed files)."""
        self._ensure_initialized()
        names = []
        for f in self._root.glob("*.json"):
            try:
                with f.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                # Only include files that look like a prompt space
                if isinstance(data, dict) and "versions" in data:
                    names.append(f.stem)
            except Exception:
                pass
        return sorted(names)

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

    def record_applied_diff(self, file_path: str, diff_hash: str) -> None:
        """Record that a diff has been applied to a specific file."""
        self._ensure_initialized()
        path = self._root / "applied_diffs.json"

        data = {}
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass

        abs_path = os.path.abspath(file_path)
        hashes = data.setdefault(abs_path, [])
        if diff_hash not in hashes:
            hashes.append(diff_hash)

        # Atomic write
        temp_fd, temp_path = tempfile.mkstemp(dir=str(self._root), suffix=".tmp")
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(temp_fd)
            os.replace(temp_path, str(path))
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise PromptRepoError(f"Failed to save applied diffs: {e}")

    def is_diff_applied(self, file_path: str, diff_hash: str) -> bool:
        """Check if a diff has already been applied to a specific file."""
        self._ensure_initialized()
        path = self._root / "applied_diffs.json"
        if not path.exists():
            return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return False

        abs_path = os.path.abspath(file_path)
        hashes = data.get(abs_path, [])
        return diff_hash in hashes


# =========================
# Lock Exceptions
# =========================

class LockError(PromptRepoError):
    """Base exception for lock-related errors."""

    def __init__(self, name: str, version: str, message: str) -> None:
        self.name = name
        self.version = version
        super().__init__(f"[{name}:{version}] {message}")


class VersionLockedError(LockError):
    """Raised when attempting to modify a locked version."""

    def __init__(self, name: str, version: str) -> None:
        super().__init__(name, version, "Version is locked and cannot be modified.")


class AlreadyLockedError(LockError):
    """Raised when attempting to lock an already locked version."""

    def __init__(self, name: str, version: str) -> None:
        super().__init__(name, version, "Version is already locked.")


# =========================
# Lock Guard
# =========================

class LockGuard:
    """
    Stateless lock enforcement utility.

    Provides pure validation and immutable updates.
    """

    @staticmethod
    def _is_locked(version_data: Mapping[str, Any]) -> bool:
        return bool(version_data.get("locked", False))

    @classmethod
    def assert_mutable(
        cls,
        version_data: Mapping[str, Any],
        name: str,
        version: str,
    ) -> None:
        """
        Ensure version is not locked.

        Raises:
            VersionLockedError
        """
        if cls._is_locked(version_data):
            raise VersionLockedError(name, version)

    @classmethod
    def assert_not_already_locked(
        cls,
        version_data: Mapping[str, Any],
        name: str,
        version: str,
    ) -> None:
        """
        Ensure version is not already locked.

        Raises:
            AlreadyLockedError
        """
        if cls._is_locked(version_data):
            raise AlreadyLockedError(name, version)

    @staticmethod
    def apply_lock(version_data: Mapping[str, Any]) -> Dict[str, Any]:
        """
        Return a new version dict with lock applied.

        Does NOT mutate input.
        """
        new_data = dict(version_data)
        new_data["locked"] = True
        return new_data

    @classmethod
    def is_locked(cls, version_data: Mapping[str, Any]) -> bool:
        """
        Check if version is locked.
        """
        return cls._is_locked(version_data)


# =========================
# Execution Tracing
# =========================

@dataclass
class TraceRecord:
    trace_id: str  # UUID
    timestamp: str  # ISO format
    prompt_name: str
    version: str
    rendered_prompt: str
    variables: Dict[str, str]
    provider: str
    model: str
    output: str
    tokens: Optional[int] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    latency_ms: float = 0.0
    cost_usd: Optional[float] = None
    score: Optional[float] = None
    error: Optional[str] = None


class TraceStore:
    """Append-only trace log stored as JSONL for efficient querying."""

    def __init__(self, root: Path):
        self._path = root / "traces.jsonl"

    def append(self, record: TraceRecord) -> None:
        """Append a trace record to the JSONL log file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record)) + "\n")

    def query(
        self,
        name: str,
        version: str = None,
        limit: int = 20,
    ) -> List[TraceRecord]:
        """Query recent trace records matching name and optional version."""
        if not self._path.exists():
            return []

        records = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    if data.get("prompt_name") == name:
                        if version is None or data.get("version") == version:
                            records.append(TraceRecord(**data))
                except Exception:
                    continue

        return records[-limit:]
