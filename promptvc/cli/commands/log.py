from __future__ import annotations

from promptvc.core import PromptVCError
from promptvc.cli.utils import get_repo, require_arg


def handle(args) -> None:
    """Handle `promptvc log <name>` — display all versions of a prompt space."""
    repo = get_repo()
    if repo is None:
        return

    try:
        name = require_arg(args, "name")
        if name is None:
            return

        versions = repo.log(name)

        if not versions:
            print(f"No versions found for '{name}'.")
            return

        latest_id = versions[0]["id"]
        print(f"\n{name}\n")

        for v in versions:
            _print_version(v, is_latest=(v["id"] == latest_id))

    except PromptVCError as exc:
        print(f"✗ {exc}")
    except ValueError as exc:
        print(f"✗ {exc}")


def _print_version(v: dict, *, is_latest: bool) -> None:
    """Render a single version entry to stdout."""
    vid         = v["id"]
    locked      = v.get("locked", False)
    latest_marker = "  ← latest" if is_latest else ""
    lock_marker   = "🔒 locked"  if locked     else "○  unlocked"
    date          = _format_date(v.get("timestamp", ""))

    print(f"  {vid}{latest_marker}")
    print(f"  message : {v.get('message', '')}")
    print(f"  tokens  : {v.get('tokens', 0)}")
    print(f"  status  : {lock_marker}")
    print(f"  date    : {date}")
    print()


def _format_date(timestamp: str) -> str:
    """Return the date portion of an ISO 8601 timestamp, or '-' if absent."""
    if not timestamp:
        return "-"
    return timestamp.split("T")[0]