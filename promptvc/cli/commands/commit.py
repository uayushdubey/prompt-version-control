from __future__ import annotations

import argparse

from promptvc.cli.utils import get_repo, require_arg
from promptvc.utils.console import safe_print, success, warning, dim, bold, _colorize, Color


def handle(args: argparse.Namespace) -> None:
    """Handle `promptvc commit <name>` — supports inline args or interactive fallback."""
    repo = get_repo()
    if repo is None:
        return

    name = require_arg(args, "name")
    if name is None:
        return

    prompt = _resolve("prompt", getattr(args, "prompt", None), "Enter prompt text:")
    if prompt is None:
        return

    message = _resolve("message", getattr(args, "message", None), "Enter commit message:")
    if message is None:
        return

    result = repo.commit(name, prompt, message)

    safe_print()
    safe_print(success(f"✓ Committed {result['id']}"))
    safe_print(dim(f"  Space   : {name}"))
    safe_print(dim(f"  Message : {result['message']}"))
    safe_print(dim(f"  Tokens  : {result['tokens']}"))
    safe_print(dim(f"  Hash    : {result['hash'][:16]}…"))
    safe_print()
    safe_print(_colorize(
        f"  Run it: promptvc run {name} {result['id']}",
        Color.CYAN,
    ))
    safe_print()


def _resolve(field: str, value: str | None, prompt_label: str) -> str | None:
    if value and value.strip():
        return value.strip()
    return _read_input(field, prompt_label)


def _read_input(field: str, prompt_label: str) -> str | None:
    safe_print(f"\n  {prompt_label}")
    try:
        value = input(dim("  > ")).strip()
    except (EOFError, KeyboardInterrupt):
        safe_print(warning("\n  Input cancelled."))
        return None

    if not value:
        safe_print(warning(f"  ✗ {field} cannot be empty."))
        return None

    return value