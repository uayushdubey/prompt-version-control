"""
promptvc.core.lock
~~~~~~~~~~~~~~~~~~
Immutability enforcement for prompt versions.

The lock layer is intentionally kept thin and pure — it contains no I/O.
Storage persistence of the locked flag is handled by :mod:`storage`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from promptvc.core.storage import VersionData


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LockError(Exception):
    """Base exception for all lock-related violations."""


class VersionLockedError(LockError):
    """
    Raised when a mutation is attempted on a locked version.

    Attributes:
        name:    Prompt space name.
        version: Version identifier (e.g. ``"v3"``).
    """

    def __init__(self, name: str, version: str) -> None:
        self.name = name
        self.version = version
        super().__init__(
            f"Version '{version}' of prompt '{name}' is locked and cannot be modified. "
            "Locked versions are immutable — commit a new version instead."
        )


class AlreadyLockedError(LockError):
    """Raised when trying to lock a version that is already locked."""

    def __init__(self, name: str, version: str) -> None:
        self.name = name
        self.version = version
        super().__init__(
            f"Version '{version}' of prompt '{name}' is already locked."
        )


# ---------------------------------------------------------------------------
# Lock guard — pure validation, no I/O
# ---------------------------------------------------------------------------

class LockGuard:
    """
    Stateless guard that enforces immutability rules.

    This class contains *only* validation logic.
    It never reads from or writes to disk — that is the storage layer's job.

    Design note
    -----------
    Keeping lock enforcement pure (no side-effects) makes it trivially
    testable and composable. The repo layer wires guard + storage together.
    """

    @staticmethod
    def assert_mutable(version_data: "VersionData", name: str, version: str) -> None:
        """
        Assert that *version_data* is not locked.

        Args:
            version_data: The version dict loaded from storage.
            name:         Prompt space name (for error messages).
            version:      Version id (for error messages).

        Raises:
            VersionLockedError: If the version is locked.
        """
        if version_data.get("locked", False):
            raise VersionLockedError(name, version)

    @staticmethod
    def assert_not_already_locked(
        version_data: "VersionData", name: str, version: str
    ) -> None:
        """
        Assert that *version_data* is not already locked (prevents no-op locks).

        Args:
            version_data: The version dict loaded from storage.
            name:         Prompt space name (for error messages).
            version:      Version id (for error messages).

        Raises:
            AlreadyLockedError: If the version is already locked.
        """
        if version_data.get("locked", False):
            raise AlreadyLockedError(name, version)

    @staticmethod
    def apply_lock(version_data: "VersionData") -> "VersionData":
        """
        Return a *new* version dict with ``locked`` set to ``True``.

        This is intentionally immutable — the caller receives a new dict
        and must persist it via the storage layer.

        Args:
            version_data: Original version dict.

        Returns:
            A shallow copy with ``locked=True``.
        """
        return {**version_data, "locked": True}

    @staticmethod
    def is_locked(version_data: "VersionData") -> bool:
        """Return ``True`` if *version_data* represents a locked version."""
        return bool(version_data.get("locked", False))