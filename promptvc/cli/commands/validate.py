from __future__ import annotations

import argparse
import sys

from promptvc.core.repo import PromptRepo
from promptvc.core.validator import validate_dataset, validate_prompt
from promptvc.utils.console import (
    bold,
    dim,
    print_error_panel,
    safe_print,
    success,
    warning,
)


def validate_command(args: argparse.Namespace) -> None:
    sub = getattr(args, "validate_subcommand", None)
    if sub == "dataset":
        if not getattr(args, "file", None):
            print_error_panel("Missing dataset file path.", tips=["Usage: promptvc validate dataset <file>"])
            sys.exit(1)
        res = validate_dataset(args.file)
        _print_result(res, f"dataset file: {args.file}")
    elif sub == "prompt":
        if not getattr(args, "name", None) or not getattr(args, "version", None):
            print_error_panel("Missing prompt name or version.", tips=["Usage: promptvc validate prompt <name> <version>"])
            sys.exit(1)
        repo = PromptRepo()
        res = validate_prompt(repo, args.name, args.version)
        _print_result(res, f"prompt '{args.name} @ {args.version}'")
    else:
        print_error_panel(
            "Unknown validate subcommand.",
            tips=[
                "Usage: promptvc validate dataset <file>",
                "       promptvc validate prompt <name> <version>",
            ],
        )
        sys.exit(1)


def _print_result(res, target_label: str) -> None:
    safe_print()
    safe_print(bold(f"  Validation for {target_label}"))
    safe_print()

    if res.valid:
        safe_print(success("  ✓ Validation passed successfully!"))
        if res.warnings:
            safe_print()
            safe_print(warning("  Warnings:"))
            for w in res.warnings:
                safe_print(dim(f"    - {w}"))
        safe_print()
    else:
        print_error_panel("Validation failed.", tips=res.errors)
        if res.warnings:
            safe_print(warning("  Warnings:"))
            for w in res.warnings:
                safe_print(dim(f"    - {w}"))
        sys.exit(1)
