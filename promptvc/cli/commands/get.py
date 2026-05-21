from __future__ import annotations

import argparse

from promptvc.core import PromptVCError
from promptvc.cli.utils import get_repo, require_arg
from promptvc.utils.console import safe_print, bold, dim, _colorize, Color


def handle(args: argparse.Namespace) -> None:
    """Handle `promptvc get <name> <version>` — print raw prompt text."""
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

        prompt = repo.get(name, version)

        safe_print()
        safe_print(bold(f"  {name} @ {version}"))
        safe_print(dim("  ─────────────────────────────────────────────────────"))
        for line in prompt.splitlines():
            safe_print(f"  {line}")
        safe_print(dim("  ─────────────────────────────────────────────────────"))
        safe_print()

    except PromptVCError as exc:
        safe_print(f"✗ {exc}")
    except ValueError as exc:
        safe_print(f"✗ {exc}")