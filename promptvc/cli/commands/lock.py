from __future__ import annotations

import argparse

from promptvc.core import PromptVCError
from promptvc.cli.utils import get_repo, require_arg
from promptvc.utils.console import safe_print, success, warning, print_error_panel, _colorize, Color


def handle(args: argparse.Namespace) -> None:
    """Handle `promptvc lock <name> <version>` — lock a version."""
    repo = get_repo()
    if repo is None:
        return

    try:
        name    = require_arg(args, "name")
        version = require_arg(args, "version")

        if not all([name, version]):
            return

        # Resolve 'latest' alias
        if version.lower() == "latest":
            space   = repo.storage.load_space(name)
            version = space.get("latest") or version

        repo.lock(name, version)
        safe_print(success(f"✓ Locked {name} @ {version}"))
        safe_print(_colorize(
            f"  This version is now read-only. No further operations can be performed on it.",
            Color.DIM,
        ))

    except PromptVCError as exc:
        safe_print(f"✗ {exc}")
    except ValueError as exc:
        safe_print(f"✗ Invalid input: {exc}")