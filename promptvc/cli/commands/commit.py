from __future__ import annotations

import argparse

from promptvc.cli.utils import get_repo, require_arg


def handle(args: argparse.Namespace) -> None:
    """Handle `promptvc commit <name>` — supports inline args or interactive fallback."""
    repo = get_repo()
    if repo is None:
        return

    name = require_arg(args, "name")
    if name is None:
        return

    prompt = _resolve("prompt", getattr(args, "prompt", None), "Enter prompt:")
    if prompt is None:
        return

    message = _resolve("message", getattr(args, "message", None), "Enter commit message:")
    if message is None:
        return

    result = repo.commit(name, prompt, message)
    print(f"\n✓ Committed {result['id']}  [{result['tokens']} tokens]")


def _resolve(field: str, value: str | None, prompt_label: str) -> str | None:
    """
    Return value if provided, otherwise prompt interactively.

    Returns None if the value is empty or input is aborted.
    """
    if value and value.strip():
        return value.strip()
    return _read_input(field, prompt_label)


def _read_input(field: str, prompt_label: str) -> str | None:
    """
    Prompt user for non-empty input.

    Returns None on empty input, EOF, or keyboard interrupt.
    """
    print(f"\n{prompt_label}\n")
    try:
        value = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        print(f"\n✗ Input cancelled.")
        return None

    if not value:
        print(f"✗ {field} cannot be empty.")
        return None

    return value