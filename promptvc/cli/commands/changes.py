from __future__ import annotations
import argparse

from promptvc.core.repo import PromptRepo


def changes_command(args: argparse.Namespace) -> None:
    repo = PromptRepo()

    name = args.name
    space = repo.storage.load_space(name)

    file_changes = space.get("file_changes")

    if not file_changes:
        print("No file changes recorded.")
        return

    for change in reversed(file_changes):
        timestamp = change.get("timestamp", "unknown")
        version = change.get("version", "unknown")
        file_path = change.get("file", "unknown")
        print(f"[{timestamp}] {version} → {file_path}")