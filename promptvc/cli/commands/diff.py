from __future__ import annotations

import difflib
import argparse

from promptvc.core.diff import compute_diff
from promptvc.core import PromptVCError
from promptvc.cli.utils import get_repo, require_arg
from promptvc.utils.console import (
    safe_print, print_table, print_box, pretty_diff,
    badge, bold, dim, success, warning, _colorize, Color,
)


def handle(args: argparse.Namespace) -> None:
    """
    Handle `promptvc diff <name> <v1> <v2>`.

    Modes:
      (default)  Word-level diff of prompt content with color
      --text     Unified text diff (like git diff)
      --stat     Word / char / token breakdown table
    """
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

        meta1 = repo.get_version_meta(name, v1)
        meta2 = repo.get_version_meta(name, v2)
        tok1  = meta1.get("tokens", 0)
        tok2  = meta2.get("tokens", 0)

        use_text = getattr(args, "text", False)
        use_stat = getattr(args, "stat", False)

        safe_print()
        safe_print(bold(f"  {name}  {v1} → {v2}"))
        safe_print()

        # ── --stat mode ──────────────────────────────────────────────────────
        if use_stat:
            words1 = len(text1.split())
            words2 = len(text2.split())
            chars1 = len(text1)
            chars2 = len(text2)
            tok_delta = tok2 - tok1

            def _delta(a: int, b: int) -> str:
                d = b - a
                if d > 0:
                    return _colorize(f"+{d}", Color.GREEN)
                elif d < 0:
                    return _colorize(str(d), Color.RED)
                return dim("±0")

            headers = ["Metric", v1, v2, "Δ"]
            rows = [
                ["Tokens", str(tok1), str(tok2), _delta(tok1, tok2)],
                ["Words",  str(words1), str(words2), _delta(words1, words2)],
                ["Chars",  str(chars1), str(chars2), _delta(chars1, chars2)],
            ]
            print_table(headers, rows, title="Diff Stats")
            return

        # ── --text mode (unified diff) ────────────────────────────────────────
        if use_text:
            lines1 = text1.splitlines(keepends=True)
            lines2 = text2.splitlines(keepends=True)
            diff = list(difflib.unified_diff(
                lines1, lines2,
                fromfile=f"{name}/{v1}",
                tofile=f"{name}/{v2}",
                lineterm="",
            ))
            if not diff:
                safe_print(dim("  No text differences found."))
            else:
                safe_print(pretty_diff("\n".join(diff)))
            tok_delta = tok2 - tok1
            tok_str = (_colorize(f"+{tok_delta}", Color.GREEN) if tok_delta > 0
                       else _colorize(str(tok_delta), Color.RED) if tok_delta < 0
                       else dim("±0"))
            safe_print()
            safe_print(dim(f"  Token delta: {tok_str}  ({tok1} → {tok2})"))
            return

        # ── Default: word-level diff ──────────────────────────────────────────
        diff_lines = compute_diff(text1, text2)
        changes    = [l for l in diff_lines if not l.startswith("  ")]

        if not changes:
            safe_print(dim("  No differences found."))
        else:
            for line in changes:
                if line.startswith("+"):
                    safe_print(_colorize(line, Color.GREEN))
                elif line.startswith("-"):
                    safe_print(_colorize(line, Color.RED))
                else:
                    safe_print(line)

        added   = sum(1 for l in changes if l.startswith("+"))
        removed = sum(1 for l in changes if l.startswith("-"))
        tok_delta = tok2 - tok1
        tok_str = (_colorize(f"+{tok_delta}", Color.GREEN) if tok_delta > 0
                   else _colorize(str(tok_delta), Color.RED) if tok_delta < 0
                   else dim("±0"))

        safe_print()
        info_lines = [
            badge("Lines added  ", _colorize(f"+{added}", Color.GREEN)),
            badge("Lines removed", _colorize(f"-{removed}", Color.RED)),
            badge("Token delta  ", tok_str),
        ]
        print_box(f"Diff  {v1} → {v2}", info_lines)

    except PromptVCError as exc:
        safe_print(f"✗ {exc}")
    except ValueError as exc:
        safe_print(f"✗ {exc}")