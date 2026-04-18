from __future__ import annotations

from promptvc.core.diff import compute_diff
from promptvc.core import PromptVCError
from promptvc.cli.utils import get_repo, require_arg


def handle(args) -> None:
    """Handle `promptvc diff <name> <v1> <v2>` — show word-level diff."""
    repo = get_repo()
    if repo is None:
        return

    try:
        name = require_arg(args, "name")
        v1   = require_arg(args, "v1")
        v2   = require_arg(args, "v2")

        if not all([name, v1, v2]):
            return

        text1 = repo.get(name, v1)
        text2 = repo.get(name, v2)

        diff_lines = compute_diff(text1, text2)
        changes = [line for line in diff_lines if not line.startswith("  ")]

        print(f"\nDiff  {v1} → {v2}\n")

        if not changes:
            print("  No differences found.")
            return

        for line in changes:
            print(line)

        added   = sum(1 for l in changes if l.startswith("+"))
        removed = sum(1 for l in changes if l.startswith("-"))
        print(f"\n  +{added} added  -{removed} removed")

    except PromptVCError as exc:
        print(f"✗ {exc}")
    except ValueError as exc:
        print(f"✗ {exc}")