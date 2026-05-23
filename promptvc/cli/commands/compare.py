from __future__ import annotations

import argparse
import json
import time
from typing import Any, Dict

from promptvc.core.repo import PromptRepo
from promptvc.utils.config import get_config_value
from promptvc.providers.registry import get_provider
from promptvc.utils.template import render_template, find_unused_variables
from promptvc.utils.console import (
    safe_print, print_table, print_box, badge,
    success, warning, dim, bold, spinner, print_error_panel,
    pretty_diff, Color, _colorize,
)
from promptvc.utils.cost import estimate_cost, format_cost, format_latency



def compare_command(args: argparse.Namespace) -> None:
    provider_name = (
        getattr(args, "provider", None)
        or get_config_value("provider")
        or "mock"
    )
    provider = get_provider(provider_name)

    model = (
        getattr(args, "model", None)
        or get_config_value(f"models.{provider_name}")
    )
    provider_kwargs: Dict = {}
    if model:
        provider_kwargs["model"] = model

    timeout = getattr(args, "timeout", None) or get_config_value("defaults.timeout")
    if timeout:
        provider_kwargs["timeout"] = timeout

    max_tokens = getattr(args, "max_tokens", None)
    if max_tokens:
        provider_kwargs["max_tokens"] = max_tokens

    if getattr(args, "stream", False):
        provider_kwargs["stream"] = True

    repo = PromptRepo()

    for ver in [args.v1, args.v2]:
        try:
            repo.get_version_meta(args.name, ver)
        except Exception:
            print_error_panel(
                f"Version '{args.name} @ {ver}' not found.",
                hint_cmd=f"promptvc log {args.name}",
            )
            return

    prompt_v1 = repo.get_version_meta(args.name, args.v1).get("prompt", "")
    prompt_v2 = repo.get_version_meta(args.name, args.v2).get("prompt", "")

    try:
        with open(args.dataset, "r", encoding="utf-8") as f:
            dataset = json.load(f)
    except Exception as exc:
        print_error_panel(f"Failed to load dataset: {exc}")
        return

    if not isinstance(dataset, list):
        print_error_panel("Dataset must be a JSON array.")
        return

    safe_print()
    safe_print(bold(f"  Comparing {args.name}: {args.v1} vs {args.v2}"))
    safe_print(dim(f"  Provider : {provider_name}" + (f" / {model}" if model else "")))
    safe_print(dim(f"  Dataset  : {args.dataset}  ({len(dataset)} cases)"))
    safe_print()

    comparisons = []
    for i, row in enumerate(dataset, start=1):
        if not isinstance(row, dict):
            safe_print(warning(f"  ⚠  Skipping row {i}: not a JSON object"))
            continue

        variables: Dict[str, Any] = row

        try:
            rendered_v1 = render_template(prompt_v1, variables)
            rendered_v2 = render_template(prompt_v2, variables)
        except Exception as exc:
            safe_print(warning(f"  ⚠  Row {i} template error: {exc}"))
            continue

        try:
            with spinner(f"  [{i}/{len(dataset)}] Running case {i} ({args.v1})…"):
                t0 = time.monotonic()
                result_v1 = provider.run(rendered_v1, **provider_kwargs)
                lat_v1 = (time.monotonic() - t0) * 1000

            with spinner(f"  [{i}/{len(dataset)}] Running case {i} ({args.v2})…"):
                t0 = time.monotonic()
                result_v2 = provider.run(rendered_v2, **provider_kwargs)
                lat_v2 = (time.monotonic() - t0) * 1000
        except Exception as exc:
            safe_print(warning(f"  ✗  Case {i} failed: {exc}"))
            continue

        out_v1 = result_v1.get("output") or ""
        out_v2 = result_v2.get("output") or ""
        tok_v1 = result_v1.get("tokens")
        tok_v2 = result_v2.get("tokens")

        comparisons.append({
            "case":    i,
            "input":   row,
            "v1_output":   out_v1,
            "v2_output":   out_v2,
            "v1_tokens":   tok_v1,
            "v2_tokens":   tok_v2,
            "v1_latency":  round(lat_v1),
            "v2_latency":  round(lat_v2),
        })

    if not comparisons:
        print_error_panel("No comparison results. Check dataset and provider.")
        return

    # ── Summary table ──────────────────────────────────────────────────────────
    headers = ["#", f"{args.v1} tokens", f"{args.v1} latency",
               f"{args.v2} tokens", f"{args.v2} latency", "Δ tokens"]
    rows = []
    for c in comparisons:
        t1 = c["v1_tokens"] or 0
        t2 = c["v2_tokens"] or 0
        delta = t2 - t1
        delta_str = (f"+{delta}" if delta > 0 else str(delta)) if (t1 and t2) else "—"
        rows.append([
            str(c["case"]),
            str(c["v1_tokens"] or "—"),
            format_latency(c["v1_latency"]),
            str(c["v2_tokens"] or "—"),
            format_latency(c["v2_latency"]),
            delta_str,
        ])

    safe_print()
    print_table(headers, rows, title=f"Compare: {args.name}  {args.v1} vs {args.v2}")

    # ── Per-case outputs ───────────────────────────────────────────────────────
    safe_print()
    for c in comparisons:
        safe_print(_colorize(f"  ── Case {c['case']} ──────────────────────────────", Color.DIM))
        input_preview = str(c["input"])[:120]
        safe_print(dim(f"  Input: {input_preview}"))
        safe_print()

        v1_label = _colorize(f"  {args.v1}", Color.BOLD_CYAN)
        v2_label = _colorize(f"  {args.v2}", Color.BOLD_MAGENTA)
        safe_print(v1_label)
        for line in (c["v1_output"] or "").splitlines()[:10]:
            safe_print(f"    {line}")

        safe_print()
        safe_print(v2_label)
        for line in (c["v2_output"] or "").splitlines()[:10]:
            safe_print(f"    {line}")
        safe_print()

    safe_print(success(f"✓ Compared {args.v1} vs {args.v2}  ({len(comparisons)} cases)"))