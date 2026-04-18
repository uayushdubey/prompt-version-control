from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from promptvc.core.storage import (
    StorageEngine,
    VersionNotFoundError,
)
from promptvc.core.lock import LockGuard
from promptvc.core.tokenizer import Tokenizer


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
    # Commit
    # -------------------------

    def _validate_non_empty(self, **kwargs: str) -> None:
        for field, value in kwargs.items():
            if value is None or not value.strip():
                raise ValueError(f"{field} must be a non-empty string.")

    # Name Normalization

    def _normalize_name(self, name: str) -> str:
        return name.strip().lower()

    def _build_version(self, version_id: str, prompt: str, message: str) -> Dict[str, Any]:
        return {
            "id": version_id,
            "prompt": prompt,
            "message": message,
            "timestamp": self._utc_now_iso(),
            "tokens": self.tokenizer.count(prompt),
            "locked": False,
            "hash": self._sha256(prompt),
        }

    def commit(self, name: str, prompt: str, message: str) -> Dict[str, Any]:
        """
        Create a new immutable version of a prompt.

        Returns:
            Dict[str, Any]: Metadata of the created version.

        Raises:
            ValueError: If inputs are invalid.
        """
        # Validate inputs
        self._validate_non_empty(name=name, prompt=prompt, message=message)

        # Normalize inputs
        name = self._normalize_name(name)
        prompt = prompt.strip()
        message = message.strip()

        # Load or create prompt space
        space = self.storage.load_or_create_space(name)

        # Generate next version ID
        version_id = self.storage.next_version_id(space)

        # Build version data
        version_data = self._build_version(
            version_id=version_id,
            prompt=prompt,
            message=message,
        )

        # Persist
        space["versions"][version_id] = version_data
        space["latest"] = version_id

        self.storage.save_space(name, space)

        return version_data

    # -------------------------
    # Log
    # -------------------------

    def log(self, name: str) -> List[Dict[str, Any]]:
        """Return all versions for a space, sorted latest → oldest."""
        space = self.storage.load_space(name)
        return self._sort_versions_desc(list(space["versions"].values()))

    # -------------------------
    # Getters
    # -------------------------

    def _normalize_version(self, version: str) -> str:
        if not version or not version.strip():
            raise ValueError("version must be a non-empty string.")
        return version.strip().lower()

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

    # -------------------------
    #Run
    # -------------------------

    def run(self, name: str, version: str, provider) -> dict:
        name = self._normalize_name(name)
        version = self._normalize_version(version)

        prompt = self.get(name, version)
        result = provider.run(prompt)

        output = result.get("output")
        if output is None:
            raise ValueError("Provider must return 'output'.")

        run_record = {
            "version": version,
            "output": output,
            "tokens": result.get("tokens"),
            "timestamp": self._utc_now_iso(),
        }

        self.storage.append_run(name, run_record)

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

        # Fetch version (delegates existence check to storage)
        version_data = self.storage.get_version(name, version)

        # Ensure it's not already locked
        self.lock_guard.assert_not_already_locked(version_data, name, version)

        # Apply lock
        updated_version = self.lock_guard.apply_lock(version_data)

        # Persist
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