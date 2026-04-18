from __future__ import annotations

from promptvc.core import PromptVCError
from promptvc.cli.utils import get_repo


def handle(args) -> None:
    """Handle `promptvc list` — display all prompt space names."""
    repo = get_repo()
    if repo is None:
        return

    try:
        spaces = repo.list_spaces()

        if not spaces:
            print("No prompt spaces found.")
            return

        print("\nPrompt spaces:\n")
        for name in sorted(spaces):
            print(f"  • {name}")

    except PromptVCError as exc:
        print(f"✗ {exc}")