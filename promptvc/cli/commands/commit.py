from __future__ import annotations

from promptvc.core import PromptVCError
from promptvc.cli.utils import get_repo, require_arg


def handle(args) -> None:
    """Handle `promptvc commit <name>` — supports inline args or interactive fallback."""
    repo = get_repo()
    if repo is None:
        return

    try:
        name = require_arg(args, "name")
        if name is None:
            return

        prompt = getattr(args, "prompt", None) or _read_input("Enter prompt:")
        if prompt is None:
            return

        message = getattr(args, "message", None) or _read_input("Enter commit message:")
        if message is None:
            return

        result = repo.commit(name, prompt, message)
        print(f"\n✓ Committed {result['id']}  [{result['tokens']} tokens]")

    except PromptVCError as exc:
        print(f"✗ {exc}")
    except ValueError as exc:
        print(f"✗ Invalid input: {exc}")


def _read_input(prompt_label: str) -> str | None:
    """Prompt user for non-empty input. Returns None if empty."""
    print(f"\n{prompt_label}\n")
    value = input("> ").strip()
    if not value:
        print(f"✗ {prompt_label.rstrip(':').lower()} cannot be empty.")
        return None
    return value