from __future__ import annotations

import argparse

from promptvc.core import PromptVCError
from promptvc.cli.utils import get_repo, require_arg
from promptvc.utils.console import (
    safe_print, print_table, bold, dim, success,
    warning, _colorize, Color,
)


def handle(args: argparse.Namespace) -> None:
    """Handle `promptvc log <name>` — display version history as a table."""
    repo = get_repo()
    if repo is None:
        return

    try:
        name = require_arg(args, "name")
        if name is None:
            return

        versions = repo.log(name)

        if not versions:
            safe_print(warning(f"  No versions found for '{name}'."))
            return

        latest_id = versions[0]["id"]
        safe_print()
        safe_print(bold(f"  {name}"))
        safe_print(dim(f"  {len(versions)} version(s)\n"))

        headers = ["Version", "Message", "Tokens", "Status", "Date"]
        rows = []
        for v in versions:
            vid     = v["id"]
            locked  = v.get("locked", False)
            is_latest = vid == latest_id

            ver_label = vid
            if is_latest:
                ver_label += _colorize("  ← latest", Color.BOLD_GREEN)

            status = _colorize("🔒 locked", Color.YELLOW) if locked else _colorize("○  active", Color.GREEN)
            date   = v.get("timestamp", "")
            date   = date.split("T")[0] if date else "—"
            msg    = v.get("message", "")[:52] + ("…" if len(v.get("message","")) > 52 else "")

            rows.append([ver_label, msg, str(v.get("tokens", 0)), status, date])

        print_table(headers, rows, title=name)
        safe_print()

    except PromptVCError as exc:
        safe_print(f"✗ {exc}")
    except ValueError as exc:
        safe_print(f"✗ {exc}")