from __future__ import annotations

import argparse
import time
from typing import Dict, List, Optional, Set

from promptvc.core.repo import PromptRepo
from promptvc.providers.mock import MockProvider
from promptvc.providers.openai import OpenAIProvider
from promptvc.providers.gemini import GeminiProvider
from promptvc.providers.anthropic import AnthropicProvider
from promptvc.providers.ollama import OllamaProvider
from promptvc.providers.registry import register_provider, get_provider
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

for _name, _cls in [
    ("mock", MockProvider), ("openai", OpenAIProvider),
    ("gemini", GeminiProvider), ("anthropic", AnthropicProvider),
    ("ollama", OllamaProvider),
]:
    try:
        register_provider(_name, _cls)
    except ValueError:
        pass


def _parse_vars(var_args: Optional[List[str]]) -> Dict[str, str]:
    if not var_args:
        return {}
    variables: Dict[str, str] = {}
    for entry in var_args:
        if "=" not in entry:
            raise ValueError(f"Invalid --var format: '{entry}'. Expected 'key=value'.")
        key, value = entry.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid --var format: '{entry}'. Key must not be empty.")
        variables[key] = value.strip()
    return variables


def _collect_schema_variables(
    schema_vars: Dict,
    provided_vars: Dict[str, str],
    is_non_interactive: bool = False,
) -> Dict[str, str]:
    collected: Dict[str, str] = {}
    for var_name, spec in schema_vars.items():
        if var_name in provided_vars:
            continue
        required = spec.get("required", False)
        default = spec.get("default")
        if default is not None:
            collected[var_name] = str(default)
            continue
        if required:
            if is_non_interactive:
                raise RuntimeError(
                    f"Missing required variable '{var_name}' in non-interactive mode."
                )
            value = input(dim(f"  {var_name}: ")).strip()
            collected[var_name] = value
    return collected


def _collect_template_variables(
    required_vars: Set[str],
    provided_vars: Dict[str, str],
    is_non_interactive: bool = False,
) -> Dict[str, str]:
    missing = required_vars - set(provided_vars.keys())
    if not missing:
        return {}
    if is_non_interactive:
        first_missing = sorted(missing)[0]
        raise RuntimeError(
            f"Missing required variable '{first_missing}' in non-interactive mode."
        )
    safe_print(bold("\n  Variables needed:"))
    collected: Dict[str, str] = {}
    for var in sorted(missing):
        value = input(dim(f"  {var}: ")).strip()
        collected[var] = value
    return collected


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

    try:
        prompt_data = repo.get_version_meta(args.name, args.version)
    except Exception:
        print_error_panel(
            f"Prompt version not found: '{args.name} @ {args.version}'",
            tips=[f"Run: promptvc log {args.name}  to see available versions"],
        )
        return

    raw_prompt = prompt_data.get("prompt")
    if raw_prompt is None:
        print_error_panel(f"'{args.name}@{args.version}' has no prompt text.")
        return

    schema = repo.get_schema(args.name, args.version)
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
        with spinner(f"Running {args.name} @ {args.version} via {provider_name}…"):
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
        space = repo.storage.load_space(args.name)
        run_record = {
            "version": args.version,
            "output": output,
            "tokens": tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": round(latency_ms),
            "cost_usd": cost,
            "model_used": model_used,
            "timestamp": repo._utc_now_iso(),
        }
        if "runs" not in space:
            space["runs"] = []
        space["runs"].append(run_record)
        repo.storage.save_space(args.name, space)
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
    print_box(f"{args.name} @ {args.version}", info_lines)

    safe_print()
    safe_print(dim("── Output ───────────────────────────────────────────"))
    safe_print(output)
    safe_print(dim("─────────────────────────────────────────────────────"))
    safe_print(success(f"\n✓ Run complete"))
