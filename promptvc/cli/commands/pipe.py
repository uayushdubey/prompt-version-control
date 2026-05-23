"""
promptvc/cli/commands/pipe.py

`promptvc pipe run` and `promptvc pipe validate`.
"""
from __future__ import annotations

import argparse
import sys
from typing import Dict

from promptvc.core.pipeline import load_pipeline, validate_pipeline, execute_pipeline
from promptvc.core.repo import PromptRepo
from promptvc.utils.config import get_config_value
from promptvc.providers.registry import get_provider
from promptvc.cli.helpers import _parse_vars
from promptvc.utils.console import (
    safe_print, print_table, print_box, print_error_panel,
    badge, bold, dim, success, warning, spinner,
    _colorize, Color,
)
from promptvc.utils.cost import estimate_cost, format_cost, format_latency



# ── pipe run ──────────────────────────────────────────────────────────────────

def pipe_run_command(args: argparse.Namespace) -> None:
    pipeline_file = args.pipeline

    try:
        pipeline = load_pipeline(pipeline_file)
    except Exception as exc:
        print_error_panel(
            f"Failed to load pipeline: {exc}",
            tips=["Ensure the file exists and is valid JSON",
                  "See: promptvc pipe validate <file>"],
        )
        sys.exit(1)

    errors = validate_pipeline(pipeline)
    if errors:
        print_error_panel("Pipeline validation failed:", tips=errors)
        sys.exit(1)

    global_vars = _parse_vars(getattr(args, "var", None))
    provider_name = (
        getattr(args, "provider", None)
        or get_config_value("provider")
        or "mock"
    )

    safe_print()
    safe_print(bold(f"  Pipeline: {pipeline.name}"))
    if pipeline.description:
        safe_print(dim(f"  {pipeline.description}"))
    safe_print(dim(f"  Steps: {len(pipeline.steps)}"))
    safe_print()

    # Print step plan
    plan_rows = [
        [s.id, s.prompt_name, s.version, s.provider or provider_name]
        for s in pipeline.steps
    ]
    print_table(["Step", "Prompt", "Version", "Provider"], plan_rows, title="Pipeline Steps")
    safe_print()

    repo = PromptRepo()

    with spinner(f"Executing pipeline '{pipeline.name}'…"):
        results = execute_pipeline(
            pipeline      = pipeline,
            global_vars   = global_vars,
            repo          = repo,
            default_provider_name = provider_name,
            get_provider_fn = get_provider,
            get_config_fn   = get_config_value,
        )

    # ── Results ───────────────────────────────────────────────────────────────
    total_tokens = 0
    total_cost   = 0.0
    all_ok       = True

    result_rows = []
    for r in results:
        status = _colorize("✓ ok",   Color.BOLD_GREEN) if r.ok else _colorize("✗ failed", Color.BOLD_RED)
        tok    = str(r.tokens) if r.tokens else "—"
        cost   = None
        if r.tokens and r.model_used:
            cost = estimate_cost(r.model_used, int(r.tokens * 0.8), int(r.tokens * 0.2))
            if cost:
                total_cost += cost
        if r.tokens:
            total_tokens += r.tokens
        if not r.ok:
            all_ok = False
        result_rows.append([
            r.step_id,
            tok,
            format_latency(r.latency_ms),
            format_cost(cost),
            status,
        ])

    safe_print()
    print_table(
        ["Step", "Tokens", "Latency", "Cost", "Status"],
        result_rows,
        title=f"Pipeline Results: {pipeline.name}",
    )

    # ── Per-step outputs ──────────────────────────────────────────────────────
    safe_print()
    for r in results:
        if r.error:
            safe_print(_colorize(f"  ✗ [{r.step_id}] {r.error}", Color.BOLD_RED))
            continue
        safe_print(bold(f"  [{r.step_id}] output:"))
        for line in (r.output or "").splitlines()[:15]:
            safe_print(f"    {line}")
        if len((r.output or "").splitlines()) > 15:
            safe_print(dim("    … (truncated)"))
        safe_print()

    # ── Summary ───────────────────────────────────────────────────────────────
    summary_lines = [
        badge("Steps  ", f"{len(results)} completed"),
        badge("Tokens ", str(total_tokens) if total_tokens else "—"),
        badge("Cost   ", format_cost(total_cost) if total_cost else "—"),
    ]
    print_box("Pipeline complete" if all_ok else "Pipeline failed", summary_lines,
              color=Color.BOLD_GREEN if all_ok else Color.BOLD_RED)

    if not all_ok:
        sys.exit(1)

    safe_print(success("\n✓ Pipeline finished successfully"))


# ── pipe validate ─────────────────────────────────────────────────────────────

def pipe_validate_command(args: argparse.Namespace) -> None:
    pipeline_file = args.pipeline

    try:
        pipeline = load_pipeline(pipeline_file)
    except Exception as exc:
        print_error_panel(f"Failed to parse pipeline: {exc}")
        sys.exit(1)

    errors = validate_pipeline(pipeline)

    safe_print()
    safe_print(bold(f"  Pipeline: {pipeline.name}"))
    safe_print(dim(f"  Steps: {len(pipeline.steps)}"))
    safe_print()

    step_rows = [
        [s.id, s.prompt_name, s.version, s.provider or "—"]
        for s in pipeline.steps
    ]
    print_table(["Step", "Prompt", "Version", "Provider"], step_rows)

    if errors:
        safe_print()
        for e in errors:
            safe_print(_colorize(f"  ✗ {e}", Color.BOLD_RED))
        sys.exit(1)
    else:
        safe_print(success("\n✓ Pipeline is valid"))


# ── Dispatcher ────────────────────────────────────────────────────────────────

def pipe_command(args: argparse.Namespace) -> None:
    sub = getattr(args, "pipe_subcommand", None)
    if sub == "run":
        pipe_run_command(args)
    elif sub == "validate":
        pipe_validate_command(args)
    else:
        print_error_panel(
            "Unknown pipe subcommand.",
            tips=["Usage: promptvc pipe run <pipeline.json> [--var key=value]",
                  "       promptvc pipe validate <pipeline.json>"],
        )
        sys.exit(1)
