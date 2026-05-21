from __future__ import annotations

import argparse

from promptvc.core import PromptVCError
from promptvc.cli.utils import get_repo
from promptvc.utils.console import safe_print, print_table, dim, bold, warning


def handle(args: argparse.Namespace) -> None:
    """Handle `promptvc list` — display all prompt space names as a table."""
    repo = get_repo()
    if repo is None:
        return

    try:
        spaces = repo.list_spaces()

        if not spaces:
            safe_print(dim("\n  No prompt spaces found. Run: promptvc commit <name>"))
            return

        safe_print()
        headers = ["Space", "Latest", "Versions"]
        rows = []
        for name in sorted(spaces):
            try:
                space = repo.storage.load_space(name)
                latest    = space.get("latest", "—")
                ver_count = len(space.get("versions", {}))
            except Exception:
                latest    = "—"
                ver_count = "?"
            rows.append([name, str(latest), str(ver_count)])

        print_table(headers, rows, title="Prompt Spaces")
        safe_print()

    except PromptVCError as exc:
        safe_print(f"✗ {exc}")