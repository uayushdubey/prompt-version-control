from __future__ import annotations

import argparse
from typing import Optional

from promptvc.core.repo import PromptRepo
from promptvc.utils.console import safe_print, print_error_panel


def get_repo() -> Optional[PromptRepo]:
    """
    Instantiate PromptRepo, printing a clean error if it fails.

    Returns None on failure so handlers can exit early with a simple
    `if repo is None: return` guard.
    """
    try:
        return PromptRepo()
    except Exception as exc:  # noqa: BLE001
        print_error_panel(f"Failed to load repository: {exc}")
        return None


def require_arg(args: argparse.Namespace, attr: str) -> Optional[str]:
    """
    Return a stripped CLI argument value, or print an error and return None.

    Handles missing attributes (AttributeError) and empty strings uniformly.
    """
    value = getattr(args, attr, None)
    if not value or not value.strip():
        print_error_panel(f"Missing required argument: <{attr}>")
        return None
    return value.strip()