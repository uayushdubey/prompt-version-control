from __future__ import annotations

import argparse
import dataclasses
import json
import sys

from promptvc.core.repo import PromptRepo
from promptvc.core.trace import TraceStore
from promptvc.utils.console import (
    Color,
    _colorize,
    bold,
    dim,
    print_error_panel,
    print_table,
    safe_print,
)


def trace_command(args: argparse.Namespace) -> None:
    """CLI handler for viewing execution traces."""
    repo = PromptRepo()
    if not repo.storage.is_initialized:
        print_error_panel("Repository not initialized.", tips=["Run 'promptvc init' first."])
        sys.exit(1)

    store = TraceStore(repo.storage._root)

    name = args.name
    version = getattr(args, "version", None)
    limit = getattr(args, "last", 20) or 20

    try:
        limit = int(limit)
    except (ValueError, TypeError):
        limit = 20

    records = store.query(name, version, limit=limit)

    if getattr(args, "json", False):
        safe_print(json.dumps([dataclasses.asdict(r) for r in records], indent=2))
        return

    if not records:
        safe_print(dim(f"  No traces found for prompt '{name}'" + (f" @ {version}" if version else "")))
        return

    safe_print()
    safe_print(bold(f"  Execution Traces for: {name}" + (f" @ {version}" if version else "")))
    safe_print()

    headers = ["Timestamp", "Ver", "Provider", "Model", "Tokens", "Latency", "Score", "Result"]
    rows = []

    for r in records:
        lat = f"{r.latency_ms:.0f}ms" if r.latency_ms else "—"
        tok = str(r.tokens) if r.tokens is not None else "—"
        score = f"{r.score:.2f}" if r.score is not None else "—"

        if r.error:
            result_label = _colorize("ERROR", Color.BOLD_RED)
        else:
            result_label = _colorize("OK", Color.BOLD_GREEN)

        rows.append([
            r.timestamp[:19].replace("T", " "),
            r.version,
            r.provider,
            r.model,
            tok,
            lat,
            score,
            result_label,
        ])

    print_table(headers, rows, title=f"Recent Traces (Last {len(records)})")

    if records:
        last = records[-1]
        safe_print()
        safe_print(bold("  [Latest Trace Details]"))
        safe_print(dim(f"  Trace ID : {last.trace_id}"))
        safe_print(dim(f"  Inputs   : {json.dumps(last.variables)}"))
        if last.error:
            safe_print(_colorize(f"  Error    : {last.error}", Color.BOLD_RED))
        else:
            safe_print(dim("  Output   :"))
            output_lines = last.output.splitlines()
            indented_output = "\n".join(f"    {l}" for l in output_lines[:10])
            safe_print(indented_output)
            if len(output_lines) > 10:
                safe_print(dim("    ... (truncated)"))
        safe_print()
