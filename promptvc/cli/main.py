from __future__ import annotations

import argparse
import sys
from typing import Callable, Dict

from promptvc.cli.commands.commit import handle as commit_handler
from promptvc.cli.commands.diff import handle as diff_handler
from promptvc.cli.commands.get import handle as get_handler
from promptvc.cli.commands.list import handle as list_handler
from promptvc.cli.commands.lock import handle as lock_handler
from promptvc.cli.commands.log import handle as log_handler
from promptvc.core import PromptVCError
from promptvc.core.repo import PromptRepo

from promptvc.cli.commands.run import run_command

# Type alias for all CLI command handlers
Handler = Callable[[argparse.Namespace], None]


def build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="promptvc",
        description="Prompt Version Control (promptvc) CLI",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    subparsers.add_parser("init", help="Initialize a promptvc repository")

    # commit
    # commit
    commit_p = subparsers.add_parser("commit", help="Commit a new prompt version")
    commit_p.add_argument("name", type=str, help="Prompt space name")
    commit_p.add_argument("--prompt", type=str, default=None,
                          help="Prompt text (optional, prompts interactively if omitted)")
    commit_p.add_argument("--message", type=str, default=None,
                          help="Commit message (optional, prompts interactively if omitted)")

    # log
    log_p = subparsers.add_parser("log", help="Show version history for a space")
    log_p.add_argument("name", type=str, help="Prompt space name")

    # get
    get_p = subparsers.add_parser("get", help="Print a specific prompt version")
    get_p.add_argument("name", type=str, help="Prompt space name")
    get_p.add_argument("version", type=str, help="Version ID (e.g. v1)")

    # diff
    diff_p = subparsers.add_parser("diff", help="Diff two prompt versions")
    diff_p.add_argument("name", type=str, help="Prompt space name")
    diff_p.add_argument("v1", type=str, help="First version ID")
    diff_p.add_argument("v2", type=str, help="Second version ID")

    # lock
    lock_p = subparsers.add_parser("lock", help="Lock a version against modification")
    lock_p.add_argument("name", type=str, help="Prompt space name")
    lock_p.add_argument("version", type=str, help="Version ID to lock")

    # list
    subparsers.add_parser("list", help="List all prompt spaces")

    # run
    run_p = subparsers.add_parser("run", help="Run a prompt version")
    run_p.add_argument("name", type=str, help="Prompt space name")
    run_p.add_argument("version", type=str, help="Version ID (e.g. v1)")

    return parser


def handle_init(_: argparse.Namespace) -> None:
    """Handle `promptvc init` — initialize the repository."""
    try:
        repo = PromptRepo()
        repo.init_repo()
        print("✓ Repository initialized.")
    except PromptVCError as exc:
        print(f"✗ {exc}")


def _resolve_handler(args: argparse.Namespace) -> Handler:
    """Return the handler function for the parsed command."""
    mapping: Dict[str, Handler] = {
        "init":   handle_init,
        "commit": commit_handler,
        "log":    log_handler,
        "get":    get_handler,
        "diff":   diff_handler,
        "lock":   lock_handler,
        "list":   list_handler,
        "run": run_command,
    }
    return mapping[args.command]


def main() -> None:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        handler = _resolve_handler(args)
    except KeyError:
        print(f"✗ Unknown command: '{args.command}'")
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()