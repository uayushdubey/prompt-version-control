from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from promptvc.core.storage import (
    StorageEngine,
    VersionNotFoundError,
)
from promptvc.core.lock import LockGuard
from promptvc.core.tokenizer import Tokenizer


@runtime_checkable
class Provider(Protocol):
    """Protocol for prompt execution providers."""

    def run(self, prompt: str) -> Dict[str, Any]:
        ...


class PromptRepo:
    """
    Main interface for Prompt Version Control.

    Orchestrates storage, tokenization, and locking.
    Accepts injected tokenizer/lock_guard for future extensibility.
    """

    def __init__(
        self,
        tokenizer: Optional[Tokenizer] = None,
        lock_guard: Optional[LockGuard] = None,
    ) -> None:
        self.storage = StorageEngine()
        self.tokenizer = tokenizer or Tokenizer()
        self.lock_guard = lock_guard or LockGuard()

    # -------------------------
    # Initialization
    # -------------------------

    def init_repo(self) -> None:
        """Initialize the repository storage."""
        self.storage.initialize()

    # -------------------------
    # Internal Hooks (extensibility points)
    # -------------------------

    def _on_commit(self, version_data: Dict[str, Any]) -> None:
        """Called after a successful commit. Reserved for future analytics/logging."""
        pass

    def _on_run(self, run_record: Dict[str, Any]) -> None:
        """Called after a successful run. Reserved for future analytics/logging."""
        pass

    # -------------------------
    # Normalization & Validation
    # -------------------------

    def _normalize_name(self, name: str) -> str:
        if not name or not name.strip():
            raise ValueError("name must be a non-empty string.")
        return name.strip().lower()

    def _normalize_version(self, version: str) -> str:
        if not version or not version.strip():
            raise ValueError("version must be a non-empty string.")
        return version.strip().lower()

    def _validate_non_empty(self, **kwargs: str) -> None:
        for field, value in kwargs.items():
            if value is None or not value.strip():
                raise ValueError(f"{field} must be a non-empty string.")

    def _validate_provider(self, provider: Any) -> None:
        """Ensure provider conforms to the Provider protocol."""
        if not isinstance(provider, Provider):
            raise TypeError(
                "provider must implement a `run(prompt: str) -> dict` method."
            )

    # -------------------------
    # Commit
    # -------------------------

    def _build_version(
        self,
        version_id: str,
        prompt: str,
        message: str,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "id": version_id,
            "prompt": prompt,
            "message": message,
            "timestamp": self._utc_now_iso(),
            "tokens": self.tokenizer.count(prompt),
            "locked": False,
            "hash": self._sha256(prompt),
            "schema": schema or {},
        }

    def commit(
            self,
            name: str,
            prompt: str,
            message: str,
            schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create a new immutable version of a prompt.

        Returns:
            Dict[str, Any]: Metadata of the created version.

        Raises:
            ValueError: If inputs are invalid.
        """
        self._validate_non_empty(name=name, prompt=prompt, message=message)

        name = self._normalize_name(name)
        prompt = prompt.strip()
        message = message.strip()

        # Validate schema after normalization
        if schema is not None:
            self._validate_schema(schema)

        space = self.storage.load_or_create_space(name)
        version_id = self.storage.next_version_id(space)

        version_data = self._build_version(
            version_id=version_id,
            prompt=prompt,
            message=message,
            schema=schema,
        )

        space["versions"][version_id] = version_data
        space["latest"] = version_id

        self.storage.save_space(name, space)

        self._on_commit(version_data)

        return version_data
    # -------------------------
    # Log
    # -------------------------

    def log(self, name: str) -> List[Dict[str, Any]]:
        """Return all versions for a space, sorted latest → oldest."""
        name = self._normalize_name(name)
        space = self.storage.load_space(name)
        return self._sort_versions_desc(list(space["versions"].values()))

    # -------------------------
    # Getters
    # -------------------------

    def get(self, name: str, version: str) -> str:
        """
        Return the prompt text for a specific version.

        Raises:
            ValueError: If inputs are invalid.
            VersionNotFoundError: If version does not exist.
        """
        name = self._normalize_name(name)
        version = self._normalize_version(version)

        data = self.storage.get_version(name, version)
        return data["prompt"]

    def get_version_meta(self, name: str, version: str) -> Dict[str, Any]:
        """
        Return full metadata for a specific version.

        Raises:
            ValueError: If inputs are invalid.
            VersionNotFoundError: If version does not exist.
        """
        name = self._normalize_name(name)
        version = self._normalize_version(version)

        return self.storage.get_version(name, version)

    def get_schema(self, name: str, version: str) -> Dict[str, Any]:
        """
        Return schema for a given prompt version.
        Returns empty dict if no schema exists.
        """
        name = self._normalize_name(name)
        version = self._normalize_version(version)

        data = self.storage.get_version(name, version)
        return data.get("schema", {})

    def latest(self, name: str) -> Dict[str, Any]:
        """
        Return metadata for the latest version of a space.

        Raises:
            ValueError: If name is invalid.
            VersionNotFoundError: If no versions exist.
        """
        name = self._normalize_name(name)

        space = self.storage.load_space(name)
        latest_id: Optional[str] = space.get("latest")

        if not latest_id:
            raise VersionNotFoundError(
                f"No versions found in space '{name}'."
            )

        return self.storage.get_version(name, latest_id)

    # Helpers

    def log_file_change(
            self,
            name: str,
            version: str,
            file_path: str,
            diff: str,
    ) -> None:
        """
        Log a file change triggered by a prompt version.

        Stores:
        - version
        - file path
        - diff
        - timestamp
        """
        name = self._normalize_name(name)
        version = self._normalize_version(version)

        space = self.storage.load_space(name)

        record = {
            "version": version,
            "file": file_path,
            "diff": diff,
            "timestamp": self._utc_now_iso(),
        }

        if "file_changes" not in space:
            space["file_changes"] = []

        space["file_changes"].append(record)

        self.storage.save_space(name, space)

    def log_evaluation(
            self,
            name: str,
            version: str,
            dataset: str,
            results: list,
    ) -> None:
        """
        Log an evaluation run for a prompt version.

        Stores:
        - version
        - dataset path
        - results
        - timestamp
        """
        name = self._normalize_name(name)
        version = self._normalize_version(version)

        space = self.storage.load_space(name)

        record = {
            "version": version,
            "dataset": dataset,
            "results": results,
            "timestamp": self._utc_now_iso(),
        }

        if "evaluations" not in space:
            space["evaluations"] = []

        space["evaluations"].append(record)

        self.storage.save_space(name, space)

    # -------------------------
    # Run
    # -------------------------

    def _build_run_record(
        self,
        version: str,
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build a run record from a provider result.

        Structured to accommodate future fields (latency, cost, model, etc.)
        without breaking existing callers.
        """
        return {
            "version": version,
            "output": result.get("output"),
            "tokens": result.get("tokens"),
            "timestamp": self._utc_now_iso(),
            # Future fields can be added here:
            # "latency_ms": result.get("latency_ms"),
            # "cost": result.get("cost"),
            # "model": result.get("model"),
        }

    def run(self, name: str, version: str, provider: Any) -> Dict[str, Any]:
        """
        Execute a prompt version using a provider and record the result.

        Raises:
            TypeError: If provider does not implement the Provider protocol.
            ValueError: If inputs are invalid or provider output is missing.
            VersionNotFoundError: If version does not exist.
        """
        self._validate_provider(provider)

        name = self._normalize_name(name)
        version = self._normalize_version(version)

        prompt = self.get(name, version)
        result = provider.run(prompt)

        if not isinstance(result, dict):
            raise ValueError("Provider must return a dict.")

        output = result.get("output")
        if output is None:
            raise ValueError("Provider must return 'output'.")

        run_record = self._build_run_record(version=version, result=result)

        self.storage.append_run(name, run_record)

        self._on_run(run_record)

        return result

    # -------------------------
    # List
    # -------------------------

    def list_spaces(self) -> List[str]:
        """Return names of all prompt spaces."""
        return self.storage.list_space_names()

    # -------------------------
    # Locking
    # -------------------------

    def lock(self, name: str, version: str) -> None:
        """
        Lock a version to prevent future modifications.

        Raises:
            ValueError: If inputs are invalid.
            VersionNotFoundError: If version does not exist.
            AlreadyLockedError: If version is already locked.
        """
        name = self._normalize_name(name)
        version = self._normalize_version(version)

        version_data = self.storage.get_version(name, version)

        self.lock_guard.assert_not_already_locked(version_data, name, version)

        updated_version = self.lock_guard.apply_lock(version_data)

        space = self.storage.load_space(name)
        space["versions"][version] = updated_version
        self.storage.save_space(name, space)

    # -------------------------
    # Diff
    # -------------------------

    def token_diff(self, name: str, v1: str, v2: str) -> int:
        """
        Return the token count difference between two versions (v2 - v1).

        Positive → v2 is longer; negative → v2 is shorter.
        """
        name = self._normalize_name(name)
        version1 = self.storage.get_version(name, v1.lower())
        version2 = self.storage.get_version(name, v2.lower())
        return version2["tokens"] - version1["tokens"]

    # -------------------------
    # Helpers
    # -------------------------

    def _sha256(self, text: str) -> str:
        """Return SHA-256 hex digest of UTF-8 encoded text."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _utc_now_iso(self) -> str:
        """Return current UTC time as ISO 8601 string."""
        return datetime.now(timezone.utc).isoformat()

    def _sort_versions_desc(
        self, versions: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Sort versions newest-first by numeric ID suffix (e.g. 'v3' → 3)."""
        def version_order(v: Dict[str, Any]) -> int:
            try:
                return int(v["id"][1:])
            except (KeyError, ValueError, IndexError):
                return -1

        return sorted(versions, key=version_order, reverse=True)

    def _validate_schema(self, schema: Dict[str, Any]) -> None:
        if not isinstance(schema, dict):
            raise ValueError("schema must be a dictionary.")

        variables = schema.get("variables")
        if variables is None:
            return  # allow empty schema

        if not isinstance(variables, dict):
            raise ValueError("schema.variables must be a dictionary.")

        for name, spec in variables.items():
            if not isinstance(name, str) or not name:
                raise ValueError("variable names must be non-empty strings.")

            if not isinstance(spec, dict):
                raise ValueError(f"schema for '{name}' must be a dictionary.")

            if "type" in spec and not isinstance(spec["type"], str):
                raise ValueError(f"'type' for '{name}' must be a string.")

            if "required" in spec and not isinstance(spec["required"], bool):
                raise ValueError(f"'required' for '{name}' must be a boolean.")

            if "description" in spec and not isinstance(spec["description"], str):
                raise ValueError(f"'description' for '{name}' must be a string.")