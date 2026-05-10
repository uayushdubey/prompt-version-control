from __future__ import annotations

import argparse
from typing import Dict, List, Optional, Set

from promptvc.core.repo import PromptRepo
from promptvc.providers.mock import MockProvider
from promptvc.providers.openai import OpenAIProvider
from promptvc.utils.config import get_config_value
from promptvc.utils.template import (
    render_template,
    find_unused_variables,
    extract_variables,
)


_PROVIDER_REGISTRY = {
    "mock": MockProvider,
    "openai": OpenAIProvider,
}


def _resolve_provider(name: str):
    provider_cls = _PROVIDER_REGISTRY.get(name)
    if provider_cls is None:
        available = ", ".join(f"'{k}'" for k in _PROVIDER_REGISTRY)
        raise ValueError(
            f"Provider '{name}' not found. Available providers: {available}"
        )
    return provider_cls()


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
            value = input(f"  {var_name}: ").strip()
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

    print("\nMissing variables detected. Please provide values:")

    collected: Dict[str, str] = {}
    for var in sorted(missing):
        value = input(f"  {var}: ").strip()
        collected[var] = value

    return collected


def run_command(args: argparse.Namespace) -> None:
    provider_name = (
        getattr(args, "provider", None)
        or get_config_value("provider")
        or "mock"
    )

    provider = _resolve_provider(provider_name)
    repo = PromptRepo()

    prompt_data = repo.get(args.name, args.version)
    if prompt_data is None:
        raise ValueError(f"Prompt '{args.name}@{args.version}' not found.")

    raw_prompt = prompt_data.get("prompt")
    if raw_prompt is None:
        raise ValueError(
            f"Prompt '{args.name}@{args.version}' has no 'prompt' field."
        )

    schema = repo.get_schema(args.name, args.version)
    schema_vars = schema.get("variables", {}) if schema else {}

    variables = _parse_vars(getattr(args, "var", None))

    # -------------------------
    # Schema-aware flow
    # -------------------------
    if schema_vars:
        print("\nUsing schema-defined variables:")
        interactive_vars = _collect_schema_variables(schema_vars, variables)

    # -------------------------
    # Fallback (no schema)
    # -------------------------
    else:
        required_vars = extract_variables(raw_prompt)
        interactive_vars = _collect_template_variables(required_vars, variables)

    variables = {**interactive_vars, **variables}

    rendered_prompt = render_template(raw_prompt, variables)

    unused = find_unused_variables(raw_prompt, variables)
    if unused:
        unused_list = ", ".join(sorted(unused))
        print(f"Warning: Unused variable(s): {unused_list}")

    result = provider.run(rendered_prompt)

    if not isinstance(result, dict):
        raise ValueError("Provider returned invalid response format.")

    output = result.get("output")
    if output is None:
        raise ValueError("Provider returned no output.")

    tokens = result.get("tokens")

    print(f"\n✓ Ran {args.name}@{args.version}")
    print(f"\nOutput:\n{output}")

    if tokens is not None:
        print(f"\nTokens: {tokens}")