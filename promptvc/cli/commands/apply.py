from __future__ import annotations
import argparse
from typing import Dict, List, Optional

from promptvc.core.repo import PromptRepo
from promptvc.providers.mock import MockProvider
from promptvc.providers.openai import OpenAIProvider
from promptvc.utils.config import get_config_value
from promptvc.utils.diff_apply import apply_unified_diff
from promptvc.utils.template import render_template, find_unused_variables

# Store classes, NOT instances
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

    # Lazy instantiation (fixes API key crash)
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


def apply_command(args: argparse.Namespace) -> None:
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
        raise ValueError(f"Prompt '{args.name}@{args.version}' has no 'prompt' field.")

    variables = _parse_vars(getattr(args, "var", None))

    rendered_prompt = render_template(raw_prompt, variables)

    unused = find_unused_variables(raw_prompt, variables)
    if unused:
        unused_list = ", ".join(sorted(unused))
        print(f"Warning: Unused variable(s): {unused_list}")

    try:
        with open(args.file, "r", encoding="utf-8") as f:
            file_content = f.read()
    except OSError as e:
        raise RuntimeError(f"Failed to read file '{args.file}': {e}") from e

    combined_input = f"""
You are a senior software engineer.

Your task is to modify the given file according to the instruction.

INSTRUCTION:
{rendered_prompt}

FILE PATH:
{args.file}

FILE CONTENT:
{file_content}

IMPORTANT:
- Return ONLY a unified diff
- Do NOT return full file
- Do NOT explain anything
- Do NOT include markdown
- Use this exact format:

--- {args.file}
+++ {args.file}
@@
- old line
+ new line

If no changes are needed, return:
NO_CHANGES
"""

    result = provider.run(combined_input)

    if not isinstance(result, dict):
        raise ValueError("Provider returned invalid response format.")

    output = result.get("output")
    if output is None:
        raise ValueError("Provider returned no output.")

    output = output.strip()

    if not output:
        raise ValueError("Provider returned empty output.")

    if output == "NO_CHANGES":
        print("✓ No changes required.")
        return

    # Optional safety check (recommended)
    if not output.startswith("---"):
        print("✗ Invalid diff format received.")
        return

    print("\n--- Proposed changes ---")
    print(output)

    answer = input("\nApply changes? (y/n): ").strip().lower()

    if answer == "y":
        try:
            new_content = apply_unified_diff(file_content, output)
        except ValueError as e:
            print(f"✗ Failed to apply diff: {e}")
            return

        try:
            with open(args.file, "w", encoding="utf-8") as f:
                f.write(new_content)
        except OSError as e:
            raise RuntimeError(f"Failed to write file '{args.file}': {e}") from e
        repo.log_file_change(
            name=args.name,
            version=args.version,
            file_path=args.file,
            diff=output,
        )

        print(f"✓ Changes applied to '{args.file}'")

    else:
        print("Aborted. No changes made.")