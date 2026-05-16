from __future__ import annotations

import argparse
from typing import Dict, List, Optional, Set

from promptvc.core.repo import PromptRepo
from promptvc.providers.mock import MockProvider
from promptvc.providers.openai import OpenAIProvider
from promptvc.providers.gemini import GeminiProvider
from promptvc.providers.registry import register_provider, get_provider
from promptvc.utils.config import get_config_value
from promptvc.utils.template import (
    render_template,
    find_unused_variables,
    extract_variables,
)
from promptvc.utils.console import (
    success,
    error,
    warning,
    section,
    dim,
)

try:
    register_provider("mock", MockProvider)
except ValueError:
    pass

try:
    register_provider("openai", OpenAIProvider)
except ValueError:
    pass

try:
    register_provider("gemini", GeminiProvider)
except ValueError:
    pass

def _resolve_provider(name: str):
    return get_provider(name)


def _parse_vars(var_args: Optional[List[str]]) -> Dict[str, str]:
    if not var_args:
        return {}

    variables: Dict[str, str] = {}

    for entry in var_args:
        if "=" not in entry:
            raise ValueError(
                f"Invalid --var format: '{entry}'. Expected 'key=value'."
            )

        key, value = entry.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not key:
            raise ValueError(
                f"Invalid --var format: '{entry}'. Key must not be empty."
            )

        variables[key] = value

    return variables


def _collect_schema_variables(
    schema_vars: Dict[str, Dict],
    provided_vars: Dict[str, str],
) -> Dict[str, str]:
    """
    Handle schema-aware variable collection:
    - fill defaults
    - prompt only for required missing vars
    """
    collected: Dict[str, str] = {}

    for var_name, spec in schema_vars.items():
        if var_name in provided_vars:
            continue

        required = spec.get("required", False)
        default = spec.get("default")

        # Use default if available
        if default is not None:
            collected[var_name] = str(default)
            continue

        # Ask only if required
        if required:
            value = input(dim(f"  {var_name}: ")).strip()
            collected[var_name] = value

    return collected


def _collect_template_variables(
    required_vars: Set[str], provided_vars: Dict[str, str]
) -> Dict[str, str]:
    """
    Fallback for non-schema prompts (existing behavior)
    """
    missing = required_vars - set(provided_vars.keys())
    if not missing:
        return {}

    print(section("Missing Variables"))

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

    provider = _resolve_provider(provider_name)
    print(section("Provider"))
    print(dim(type(provider).__name__))
    repo = PromptRepo()

    prompt_data = repo.get_version_meta(args.name, args.version)

    raw_prompt = prompt_data.get("prompt")
    if raw_prompt is None:
        raise ValueError(
            f"Prompt '{args.name}@{args.version}' has no 'prompt' field."
        )

    schema = repo.get_schema(args.name, args.version)
    schema_vars = schema.get("variables", {}) if schema else {}

    variables = _parse_vars(getattr(args, "var", None))

    is_dry_run = getattr(args, "dry_run", False)

    # -------------------------
    # Determine required variables
    # -------------------------
    if schema_vars:
        required_vars = {
            name for name, spec in schema_vars.items()
            if spec.get("required", False) and spec.get("default") is None
        }
    else:
        required_vars = extract_variables(raw_prompt)

    # -------------------------
    # Dry-run mode (non-interactive)
    # -------------------------
    if is_dry_run:
        missing = required_vars - set(variables.keys())

        if missing:
            print(section("Missing Required Variables (dry-run)"))
            for var in sorted(missing):
                print(dim(f"  {var}"))

        try:
            rendered_prompt = render_template(raw_prompt, variables)
        except Exception:
            rendered_prompt = raw_prompt  # fallback for visibility

        print(section("Rendered Prompt"))
        print(rendered_prompt)
        return

    # -------------------------
    # Schema-aware flow
    # -------------------------
    if schema_vars:
        print(section("Using Schema Variables"))
        interactive_vars = _collect_schema_variables(schema_vars, variables)

    # -------------------------
    # Fallback (no schema)
    # -------------------------
    else:
        interactive_vars = _collect_template_variables(required_vars, variables)

    # CLI vars override interactive/defaults
    variables = {**interactive_vars, **variables}

    rendered_prompt = render_template(raw_prompt, variables)

    unused = find_unused_variables(raw_prompt, variables)
    if unused:
        unused_list = ", ".join(sorted(unused))
        print(warning(f"Unused variable(s): {unused_list}"))

    result = provider.run(rendered_prompt)

    if not isinstance(result, dict):
        raise ValueError("Provider returned invalid response format.")

    output = result.get("output")
    if output is None:
        raise ValueError("Provider returned no output.")

    tokens = result.get("tokens")

    print(success(f"\n✓ Ran {args.name}@{args.version}"))
    print(section("Output"))
    print(output)

    if tokens is not None:
        print(dim(f"\nTokens: {tokens}"))
