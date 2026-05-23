from __future__ import annotations

import argparse
import time
from typing import Dict, List, Optional, Set

from promptvc.core.repo import PromptRepo
from promptvc.providers.registry import get_provider
from promptvc.cli.helpers import (
    _parse_vars,
    _collect_schema_variables,
    _collect_template_variables,
)
from promptvc.utils.config import get_config_value
from promptvc.utils.template import (
    render_template,
    find_unused_variables,
    extract_variables,
)
from promptvc.utils.console import (
    success, error, warning, dim, bold, muted,
    safe_print, print_box, badge, print_error_panel, spinner,
)
from promptvc.utils.cost import estimate_cost, format_cost, format_latency



def run_command(args: argparse.Namespace) -> None:
    provider_name = (
        getattr(args, "provider", None)
        or get_config_value("provider")
        or "mock"
    )

    try:
        provider = get_provider(provider_name)
    except Exception:
        print_error_panel(
            f"Unknown provider '{provider_name}'",
            tips=[
                "Available: openai, anthropic, gemini, ollama, mock",
                f"Set default with: promptvc config set provider openai",
            ],
        )
        return

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

    stream = getattr(args, "stream", False)
    if stream:
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
            f"Prompt version not found: '{args.name} @ {args.version}'",
            tips=[f"Run: promptvc log {args.name}  to see available versions"],
        )
        return

    raw_prompt = prompt_data.get("prompt")
    if raw_prompt is None:
        print_error_panel(f"'{args.name}@{version}' has no prompt text.")
        return

    schema = repo.get_schema(args.name, version)
    schema_vars = schema.get("variables", {}) if schema else {}

    variables = _parse_vars(getattr(args, "var", None))
    is_dry_run = getattr(args, "dry_run", False)
    is_non_interactive = getattr(args, "non_interactive", False)

    if schema_vars:
        required_vars = {
            n for n, s in schema_vars.items()
            if s.get("required", False) and s.get("default") is None
        }
    else:
        required_vars = extract_variables(raw_prompt)

    # ── Dry-run ───────────────────────────────────────────────────────────────
    if is_dry_run:
        missing = required_vars - set(variables.keys())
        try:
            rendered_prompt = render_template(raw_prompt, variables)
        except Exception:
            rendered_prompt = raw_prompt
        info_lines = [
            badge("Prompt",  f"{args.name} @ {args.version}"),
            badge("Provider", f"{provider_name}" + (f" / {model}" if model else "")),
        ]
        if missing:
            info_lines.append(warning(f"Missing vars: {', '.join(sorted(missing))}"))
        from promptvc.utils.console import print_box
        print_box("Dry Run Preview", info_lines)
        safe_print()
        safe_print(dim("── Rendered Prompt ──────────────────────────────"))
        safe_print(rendered_prompt)
        safe_print(dim("─────────────────────────────────────────────────"))
        return

    # ── Variable collection ───────────────────────────────────────────────────
    try:
        if schema_vars:
            interactive_vars = _collect_schema_variables(
                schema_vars, variables, is_non_interactive
            )
        else:
            interactive_vars = _collect_template_variables(
                required_vars, variables, is_non_interactive
            )
    except RuntimeError as exc:
        var_name = str(exc).split("'")[1] if "'" in str(exc) else "unknown"
        print_error_panel(
            str(exc),
            where=f"{args.name} @ {args.version}",
            tips=[
                f'Supply it with --var {var_name}="<value>"',
                "Or run without --non-interactive for interactive input",
            ],
            hint_cmd=f"promptvc inspect {args.name} {args.version}",
        )
        return

    variables = {**interactive_vars, **variables}
    rendered_prompt = render_template(raw_prompt, variables)

    unused = find_unused_variables(raw_prompt, variables)
    if unused:
        safe_print(warning(f"⚠  Unused variable(s): {', '.join(sorted(unused))}"))

    # ── Execute ───────────────────────────────────────────────────────────────
    t_start = time.monotonic()
    try:
        with spinner(f"Running {args.name} @ {version} via {provider_name}…"):
            result = provider.run(rendered_prompt, **provider_kwargs)
    except Exception as exc:
        print_error_panel(
            f"Provider call failed: {exc}",
            where=f"{provider_name}" + (f" / {model}" if model else ""),
            tips=["Check your API key and network connection",
                  f"Try the mock provider: --provider mock"],
        )
        return

    latency_ms = (time.monotonic() - t_start) * 1000

    if not isinstance(result, dict):
        print_error_panel("Provider returned invalid response format.")
        return

    output = result.get("output") or ""
    if not output:
        print_error_panel("Provider returned empty output.")
        return

    tokens       = result.get("tokens")
    model_used   = result.get("model_used") or model or provider_name
    # Try to split input/output tokens if provider returns them
    input_tokens  = result.get("input_tokens")
    output_tokens = result.get("output_tokens")
    cost = None
    if model_used:
        if input_tokens is not None and output_tokens is not None:
            cost = estimate_cost(model_used, input_tokens, output_tokens)
        elif tokens is not None:
            # Rough estimate: assume 80% input, 20% output
            cost = estimate_cost(model_used, int(tokens * 0.8), int(tokens * 0.2))

    # ── Persist ───────────────────────────────────────────────────────────────
    try:
        run_record = {
            "version":      version,
            "output":       output,
            "tokens":       tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms":   round(latency_ms),
            "cost_usd":     cost,
            "model_used":   model_used,
            "timestamp":    repo._utc_now_iso(),
        }
        # Use append_run for validated, atomic storage
        repo.storage.append_run(args.name, run_record)
    except Exception:
        pass  # never fail a run due to storage error

    # ── Output ────────────────────────────────────────────────────────────────
    token_str = (
        f"{input_tokens} in + {output_tokens} out = {tokens} total"
        if (input_tokens is not None and output_tokens is not None)
        else str(tokens) if tokens is not None else "—"
    )

    info_lines = [
        badge("Provider", f"{provider_name} / {model_used}"),
        badge("Latency ", format_latency(latency_ms)),
        badge("Tokens  ", token_str),
        badge("Cost    ", format_cost(cost)),
    ]
    safe_print()
    from promptvc.utils.console import print_box, Color
    print_box(f"{args.name} @ {version}", info_lines)

    safe_print()
    safe_print(dim("── Output ───────────────────────────────────────────"))
    safe_print(output)
    safe_print(dim("─────────────────────────────────────────────────────"))
    safe_print(success(f"\n✓ Run complete"))
