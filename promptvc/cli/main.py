from __future__ import annotations

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

import argparse
import sys
from typing import Callable, Dict

from promptvc.cli.commands.apply import apply_command
from promptvc.cli.commands.commit import handle as commit_handler
from promptvc.cli.commands.config import config_command
from promptvc.cli.commands.diff import handle as diff_handler
from promptvc.cli.commands.get import handle as get_handler
from promptvc.cli.commands.inspect import inspect_command
from promptvc.cli.commands.list import handle as list_handler
from promptvc.cli.commands.lock import handle as lock_handler
from promptvc.cli.commands.log import handle as log_handler
from promptvc.cli.commands.run import run_command
from promptvc.cli.commands.changes import changes_command
from promptvc.cli.commands.eval import eval_command
from promptvc.cli.commands.compare import compare_command
from promptvc.cli.commands.test import test_command
from promptvc.cli.commands.status import status_command
from promptvc.cli.commands.shell import shell_command
from promptvc.cli.commands.pipe import pipe_command

from promptvc.core import PromptVCError
from promptvc.core.repo import PromptRepo
from promptvc.utils.console import safe_print, print_error_panel, success, _colorize, Color

Handler = Callable[[argparse.Namespace], None]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="promptvc",
        description="Prompt Version Control — git for LLM prompts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  promptvc init
  promptvc commit summarize --message "v1" --prompt "Summarize: {{text}}"
  promptvc run summarize v1 --provider openai
  promptvc test run summarize v1 --suite tests/summarize.json
  promptvc shell
  promptvc pipe run pipeline.json --var code="$(cat src/main.py)"
  promptvc status
""",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── init ──────────────────────────────────────────────────────────────────
    subparsers.add_parser("init", help="Initialize a promptvc repository")

    # ── status ────────────────────────────────────────────────────────────────
    subparsers.add_parser("status", help="Show workspace overview (spaces, runs, recent activity)")

    # ── commit ────────────────────────────────────────────────────────────────
    commit_p = subparsers.add_parser("commit", help="Commit a new prompt version")
    commit_p.add_argument("name", type=str, help="Prompt space name")
    commit_p.add_argument("--prompt", type=str, default=None,
                          help="Prompt text (interactive if omitted)")
    commit_p.add_argument("--message", type=str, default=None,
                          help="Commit message (interactive if omitted)")

    # ── log ───────────────────────────────────────────────────────────────────
    log_p = subparsers.add_parser("log", help="Show version history for a prompt space")
    log_p.add_argument("name", type=str, help="Prompt space name")

    # ── get ───────────────────────────────────────────────────────────────────
    get_p = subparsers.add_parser("get", help="Print raw prompt text for a version")
    get_p.add_argument("name", type=str, help="Prompt space name")
    get_p.add_argument("version", type=str, help="Version ID (e.g. v1)")

    # ── inspect ───────────────────────────────────────────────────────────────
    inspect_p = subparsers.add_parser("inspect", help="Show detailed metadata for a version")
    inspect_p.add_argument("name", type=str, help="Prompt space name")
    inspect_p.add_argument("version", type=str, help="Version ID (e.g. v1)")

    # ── diff ──────────────────────────────────────────────────────────────────
    diff_p = subparsers.add_parser("diff", help="Diff two prompt versions")
    diff_p.add_argument("name", type=str, help="Prompt space name")
    diff_p.add_argument("v1", type=str, help="First version ID")
    diff_p.add_argument("v2", type=str, help="Second version ID")
    diff_p.add_argument("--text", action="store_true",
                        help="Show full unified text diff (like git diff)")
    diff_p.add_argument("--stat", action="store_true",
                        help="Show word/char/token breakdown table")

    # ── lock ──────────────────────────────────────────────────────────────────
    lock_p = subparsers.add_parser("lock", help="Lock a version against modification")
    lock_p.add_argument("name", type=str, help="Prompt space name")
    lock_p.add_argument("version", type=str, help="Version ID to lock")

    # ── list ──────────────────────────────────────────────────────────────────
    subparsers.add_parser("list", help="List all prompt spaces")

    # ── run ───────────────────────────────────────────────────────────────────
    run_p = subparsers.add_parser("run", help="Execute a prompt version")
    run_p.add_argument("name", type=str, help="Prompt space name")
    run_p.add_argument("version", type=str, help="Version ID (e.g. v1)")
    run_p.add_argument("--provider", type=str, default=None)
    run_p.add_argument("--model", type=str)
    run_p.add_argument("--timeout", type=int)
    run_p.add_argument("--max-tokens", type=int)
    run_p.add_argument("--stream", action="store_true")
    run_p.add_argument("--var", action="append",
                       help="Template variable (key=value). Repeatable.")
    run_p.add_argument("--dry-run", action="store_true",
                       help="Preview rendered prompt without executing")
    run_p.add_argument("--non-interactive", action="store_true",
                       help="Fail fast if required variables are missing")

    # ── eval ──────────────────────────────────────────────────────────────────
    eval_p = subparsers.add_parser("eval", help="Evaluate a prompt version on a dataset")
    eval_p.add_argument("name", type=str)
    eval_p.add_argument("version", type=str)
    eval_p.add_argument("--dataset", type=str, required=True)
    eval_p.add_argument("--provider", type=str, default=None)
    eval_p.add_argument("--model", type=str)
    eval_p.add_argument("--timeout", type=int)
    eval_p.add_argument("--max-tokens", type=int)
    eval_p.add_argument("--stream", action="store_true")
    eval_p.add_argument("--non-interactive", action="store_true")

    # ── compare ───────────────────────────────────────────────────────────────
    compare_p = subparsers.add_parser("compare", help="Compare two prompt versions on a dataset")
    compare_p.add_argument("name", type=str)
    compare_p.add_argument("v1", type=str)
    compare_p.add_argument("v2", type=str)
    compare_p.add_argument("--dataset", type=str, required=True)
    compare_p.add_argument("--provider", type=str, default=None)
    compare_p.add_argument("--model", type=str)
    compare_p.add_argument("--timeout", type=int)
    compare_p.add_argument("--max-tokens", type=int)
    compare_p.add_argument("--stream", action="store_true")

    # ── apply ─────────────────────────────────────────────────────────────────
    apply_p = subparsers.add_parser("apply", help="Apply a prompt to a file using an LLM diff")
    apply_p.add_argument("name", type=str)
    apply_p.add_argument("version", type=str)
    apply_p.add_argument("--file", required=False, help="Target file to modify")
    apply_p.add_argument("--dir", type=str, default=None,
                         help="Target directory (apply to all matching files)")
    apply_p.add_argument("--glob", type=str, default="*",
                         help="Glob pattern when using --dir (default: *)")
    apply_p.add_argument("--provider", type=str, default=None)
    apply_p.add_argument("--model", type=str)
    apply_p.add_argument("--timeout", type=int)
    apply_p.add_argument("--max-tokens", type=int)
    apply_p.add_argument("--stream", action="store_true")
    apply_p.add_argument("--var", action="append")
    apply_p.add_argument("--dry-run", action="store_true")
    apply_p.add_argument("--non-interactive", action="store_true")

    # ── changes ───────────────────────────────────────────────────────────────
    changes_p = subparsers.add_parser("changes", help="Show file change history for a space")
    changes_p.add_argument("name", type=str)

    # ── config ────────────────────────────────────────────────────────────────
    config_p = subparsers.add_parser("config", help="Get or set configuration values")
    config_p.add_argument("action", type=str, choices=["set", "get", "list"])
    config_p.add_argument("key", type=str, nargs="?")
    config_p.add_argument("value", type=str, nargs="?")

    # ── test ──────────────────────────────────────────────────────────────────
    test_p = subparsers.add_parser("test", help="Run prompt unit tests")
    test_sub = test_p.add_subparsers(dest="test_subcommand")

    t_run = test_sub.add_parser("run", help="Run a test suite")
    t_run.add_argument("name", type=str, help="Prompt space name")
    t_run.add_argument("version", type=str, help="Version ID")
    t_run.add_argument("--suite", type=str, required=True, help="Path to test suite JSON")
    t_run.add_argument("--provider", type=str, default=None)
    t_run.add_argument("--model", type=str)

    t_golden = test_sub.add_parser("golden", help="Update golden files from current output")
    t_golden.add_argument("name", type=str)
    t_golden.add_argument("version", type=str)
    t_golden.add_argument("--suite", type=str, required=True)
    t_golden.add_argument("--provider", type=str, default=None)
    t_golden.add_argument("--model", type=str)

    t_list = test_sub.add_parser("list", help="List test suite files in the current project")
    t_list.add_argument("--dir", type=str, default=".", help="Root directory to search")

    # ── shell ─────────────────────────────────────────────────────────────────
    subparsers.add_parser("shell", help="Launch the interactive REPL")

    # ── pipe ──────────────────────────────────────────────────────────────────
    pipe_p = subparsers.add_parser("pipe", help="Run multi-step prompt pipelines")
    pipe_sub = pipe_p.add_subparsers(dest="pipe_subcommand")

    p_run = pipe_sub.add_parser("run", help="Execute a pipeline")
    p_run.add_argument("pipeline", type=str, help="Path to pipeline JSON file")
    p_run.add_argument("--var", action="append",
                       help="Global input variable (key=value). Repeatable.")
    p_run.add_argument("--provider", type=str, default=None,
                       help="Default provider for all steps")

    p_val = pipe_sub.add_parser("validate", help="Validate a pipeline file")
    p_val.add_argument("pipeline", type=str, help="Path to pipeline JSON file")

    return parser


def handle_init(_: argparse.Namespace) -> None:
    repo = PromptRepo()
    repo.init_repo()
    safe_print(success("✓ Repository initialized."))


def _build_handler_map() -> Dict[str, Handler]:
    return {
        "init":    handle_init,
        "status":  status_command,
        "commit":  commit_handler,
        "log":     log_handler,
        "get":     get_handler,
        "inspect": inspect_command,
        "diff":    diff_handler,
        "lock":    lock_handler,
        "list":    list_handler,
        "run":     run_command,
        "eval":    eval_command,
        "compare": compare_command,
        "apply":   apply_command,
        "changes": changes_command,
        "config":  config_command,
        "test":    test_command,
        "shell":   shell_command,
        "pipe":    pipe_command,
    }


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        handler = _build_handler_map()[args.command]
        handler(args)
    except KeyError:
        print_error_panel(
            f"Unknown command: '{args.command}'",
            tips=["Run: promptvc --help  to see available commands"],
        )
        sys.exit(1)
    except PromptVCError as exc:
        print_error_panel(str(exc))
        sys.exit(1)
    except ValueError as exc:
        print_error_panel(f"Validation error: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        safe_print(_colorize("\n  Interrupted.", Color.DIM))
        sys.exit(130)
    except Exception as exc:
        print_error_panel(
            f"Unexpected error: {exc}",
            tips=["This may be a bug. Please report it at github.com/uayushdubey/prompt-version-control"],
        )
        sys.exit(2)


if __name__ == "__main__":
    main()