from __future__ import annotations

from typing import Mapping, Any, Dict

from promptvc.core.storage import PromptVCError


# =========================
# Exceptions
# =========================

class LockError(PromptVCError):
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

    # -------------------------
    # Internal helpers
    # -------------------------

    @staticmethod
    def _is_locked(version_data: Mapping[str, Any]) -> bool:
        return bool(version_data.get("locked", False))

    # -------------------------
    # Public API
    # -------------------------

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
        # Defensive copy to ensure immutability
        new_data = dict(version_data)
        new_data["locked"] = True
        return new_data

    @classmethod
    def is_locked(cls, version_data: Mapping[str, Any]) -> bool:
        """
        Check if version is locked.
        """
        return cls._is_locked(version_data)