from __future__ import annotations

from promptvc.core import PromptVCError
from promptvc.cli.utils import get_repo, require_arg


def handle(args) -> None:
    """Handle `promptvc get <name> <version>` — print prompt text for a version."""
    repo = get_repo()
    if repo is None:
        return

    try:
        name    = require_arg(args, "name")
        version = require_arg(args, "version")

        if not all([name, version]):
            return

        prompt = repo.get(name, version)

        print(f"\nPrompt  {name}@{version}\n")
        print(prompt)

    except PromptVCError as exc:
        print(f"✗ {exc}")
    except ValueError as exc:
        print(f"✗ {exc}")