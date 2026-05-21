from __future__ import annotations
import argparse

from promptvc.core.repo import PromptRepo
from promptvc.utils.console import (
    safe_print, print_table, print_error_panel,
    bold, dim, _colorize, Color,
)


def changes_command(args: argparse.Namespace) -> None:
    repo = PromptRepo()

    try:
        space = repo.storage.load_space(args.name)
    except Exception as exc:
        print_error_panel(
            f"Prompt space '{args.name}' not found.",
            hint_cmd=f"promptvc list",
        )
        return

    file_changes = space.get("file_changes") or []

    if not file_changes:
        safe_print(dim(f"\n  No file changes recorded for '{args.name}'."))
        return

    safe_print()
    safe_print(bold(f"  File changes for: {args.name}"))
    safe_print()

    headers = ["Timestamp", "Version", "File"]
    rows = []
    for change in reversed(file_changes):
        ts      = change.get("timestamp", "—")
        date    = ts.split("T")[0] if "T" in ts else ts
        time_   = ts.split("T")[1][:8] if "T" in ts else ""
        ver     = change.get("version", "—")
        fpath   = change.get("file", "—")
        rows.append([f"{date} {time_}".strip(), _colorize(ver, Color.CYAN), fpath])

    print_table(headers, rows, title=f"Changes  {args.name}")
    safe_print()