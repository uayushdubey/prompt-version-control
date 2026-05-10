from __future__ import annotations

import argparse
from typing import Dict, List, Optional, Set

from promptvc.core.repo import PromptRepo
from promptvc.providers.mock import MockProvider
from promptvc.providers.openai import OpenAIProvider
from promptvc.utils.config import get_config_value
from promptvc.utils.template import render_template, find_unused_variables, extract_variables


_PROVIDER_REGISTRY = {
    "mock": MockProvider,
    "openai": OpenAIProvider,
}


def _resolve_provider(name: str):
    """
    Return the provider instance for the given name.

    Raises:
        ValueError: If the provider is not registered.
    """
    provider_cls = _PROVIDER_REGISTRY.get(name)
    if provider_cls is None:
        available = ", ".join(f"'{k}'" for k in _PROVIDER_REGISTRY)
        raise ValueError(
            f"Provider '{name}' not found. Available providers: {available}"
        )

    return provider_cls()


def _parse_vars(var_args: Optional[List[str]]) -> Dict[str, str]:
    """
    Parse a list of 'key=value' strings into a dictionary.

    Args:
        var_args: List of strings in 'key=value' format, or None.

    Returns:
        A dictionary mapping variable names to their values.

    Raises:
        ValueError: If any entry does not contain '=' or has an empty key.
    """
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


def _collect_missing_variables(
    required_vars: Set[str], provided_vars: Dict[str, str]
) -> Dict[str, str]:
    """
    Interactively prompt the user for any required variables not already provided.

    Args:
        required_vars: Set of variable names required by the template.
        provided_vars: Variables already supplied via --var flags.

    Returns:
        A dictionary of variable names to user-supplied values for any
        that were missing from provided_vars. Empty dict if none are missing.
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

    variables = _parse_vars(getattr(args, "var", None))

    required_vars = extract_variables(raw_prompt)
    interactive_vars = _collect_missing_variables(required_vars, variables)
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