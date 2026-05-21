from __future__ import annotations

import argparse
import json
import time
from typing import Any, Dict

from promptvc.core.repo import PromptRepo
from promptvc.utils.config import get_config_value
from promptvc.providers.mock import MockProvider
from promptvc.providers.openai import OpenAIProvider
from promptvc.providers.gemini import GeminiProvider
from promptvc.providers.anthropic import AnthropicProvider
from promptvc.providers.ollama import OllamaProvider
from promptvc.providers.registry import register_provider, get_provider
from promptvc.utils.template import render_template, find_unused_variables
from promptvc.utils.console import (
    safe_print, print_table, print_box, badge,
    success, warning, dim, bold, spinner, print_error_panel,
)
from promptvc.utils.cost import estimate_cost, format_cost, format_latency

for _name, _cls in [
    ("mock", MockProvider), ("openai", OpenAIProvider),
    ("gemini", GeminiProvider), ("anthropic", AnthropicProvider),
    ("ollama", OllamaProvider),
]:
    try:
        register_provider(_name, _cls)
    except ValueError:
        pass


def eval_command(args: argparse.Namespace) -> None:
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

    # Resolve 'latest' alias
    version = args.version
    if version.lower() == "latest":
        try:
            space   = repo.storage.load_space(args.name)
            version = space.get("latest") or version
        except Exception:
            pass

    try:
        prompt_data = repo.get_version_meta(args.name, version)
    except Exception:
        print_error_panel(
            f"Prompt '{args.name} @ {version}' not found.",
            hint_cmd=f"promptvc log {args.name}",
        )
        return

    raw_prompt = prompt_data.get("prompt")
    if raw_prompt is None:
        print_error_panel(f"'{args.name}@{version}' has no prompt text.")
        return

    try:
        with open(args.dataset, "r", encoding="utf-8") as f:
            dataset = json.load(f)
    except Exception as exc:
        print_error_panel(
            f"Failed to load dataset: {exc}",
            tips=["Ensure the file exists and is valid JSON",
                  "Dataset must be a list of objects with at least an 'input' field"],
        )
        return

    if not isinstance(dataset, list):
        print_error_panel("Dataset must be a JSON array of objects.")
        return

    model_used = model or provider_name
    results = []
    total_tokens = 0
    total_cost = 0.0
    total_latency = 0.0

    safe_print()
    safe_print(bold(f"  Evaluating {args.name} @ {args.version}"))
    safe_print(dim(f"  Provider : {provider_name}" + (f" / {model}" if model else "")))
    safe_print(dim(f"  Dataset  : {args.dataset}  ({len(dataset)} cases)"))
    safe_print()

    for i, row in enumerate(dataset, start=1):
        if not isinstance(row, dict):
            safe_print(warning(f"  ⚠  Skipping row {i}: not a JSON object"))
            continue

        variables: Dict[str, Any] = row
        try:
            rendered_prompt = render_template(raw_prompt, variables)
        except Exception as exc:
            safe_print(warning(f"  ⚠  Row {i} template error: {exc}"))
            continue

        unused = find_unused_variables(raw_prompt, variables)
        if unused:
            safe_print(warning(f"  ⚠  Row {i}: unused vars: {', '.join(sorted(unused))}"))

        t0 = time.monotonic()
        try:
            with spinner(f"  [{i}/{len(dataset)}] Running case {i}…"):
                result = provider.run(rendered_prompt, **provider_kwargs)
        except Exception as exc:
            safe_print(warning(f"  ✗  Case {i} failed: {exc}"))
            continue
        latency_ms = (time.monotonic() - t0) * 1000

        output = result.get("output") or ""
        tokens = result.get("tokens")
        actual_model = result.get("model_used") or model_used

        cost = None
        if tokens:
            cost = estimate_cost(actual_model, int(tokens * 0.8), int(tokens * 0.2))
            total_tokens += tokens
            if cost is not None:
                total_cost += cost
        total_latency += latency_ms

        results.append({
            "case":      i,
            "input":     row,
            "output":    output,
            "tokens":    tokens,
            "latency_ms": round(latency_ms),
            "cost_usd":  cost,
            "model_used": actual_model,
        })

    if not results:
        print_error_panel("No results produced. Check your dataset and provider.")
        return

    # ── Results table ──────────────────────────────────────────────────────────
    safe_print()
    headers = ["#", "Tokens", "Latency", "Cost", "Output (preview)"]
    rows = []
    for r in results:
        preview = (r["output"] or "")[:60].replace("\n", " ")
        if len(r["output"] or "") > 60:
            preview += "…"
        rows.append([
            str(r["case"]),
            str(r["tokens"] or "—"),
            format_latency(r["latency_ms"]),
            format_cost(r["cost_usd"]),
            preview,
        ])
    print_table(headers, rows, title=f"Eval: {args.name} @ {args.version}")

    # ── Summary box ────────────────────────────────────────────────────────────
    avg_latency = total_latency / len(results) if results else 0
    summary_lines = [
        badge("Cases    ", f"{len(results)} / {len(dataset)}"),
        badge("Total tokens", str(total_tokens) if total_tokens else "—"),
        badge("Total cost  ", format_cost(total_cost) if total_cost else "—"),
        badge("Avg latency ", format_latency(avg_latency)),
    ]
    safe_print()
    print_box("Evaluation Summary", summary_lines)

    # ── Store evaluation ──────────────────────────────────────────────────────
    repo.log_evaluation(
        name=args.name,
        version=version,
        dataset=args.dataset,
        results=results,
    )
    safe_print(success(f"\n✓ Evaluation complete — {len(results)} cases stored"))