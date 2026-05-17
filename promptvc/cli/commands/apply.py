from __future__ import annotations
import argparse
from typing import Dict, List, Optional, Set

from promptvc.core.repo import PromptRepo
from promptvc.providers.mock import MockProvider
from promptvc.providers.openai import OpenAIProvider
from promptvc.providers.gemini import GeminiProvider
from promptvc.providers.anthropic import AnthropicProvider
from promptvc.providers.ollama import OllamaProvider
from promptvc.providers.registry import register_provider, get_provider
from promptvc.utils.config import get_config_value
from promptvc.utils.diff_apply import apply_unified_diff
from promptvc.utils.template import render_template, find_unused_variables, extract_variables
from promptvc.utils.console import (
    success,
    error,
    warning,
    section,
    pretty_diff,
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

try:
    register_provider("anthropic", AnthropicProvider)
except ValueError:
    pass

try:
    register_provider("ollama", OllamaProvider)
except ValueError:
    pass


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


# -------------------------
# NEW: schema-aware handling
# -------------------------
def _collect_schema_variables(
    schema_vars: Dict[str, Dict],
    provided_vars: Dict[str, str],
) -> Dict[str, str]:
    collected: Dict[str, str] = {}

    print(section("Using Schema Variables"))

    for var_name, spec in schema_vars.items():
        if var_name in provided_vars:
            continue

        required = spec.get("required", False)
        default = spec.get("default")

        if default is not None:
            collected[var_name] = str(default)
            continue

        if required:
            value = input(dim(f"  {var_name}: ")).strip()
            collected[var_name] = value

    return collected


def _collect_template_variables(
    required_vars: Set[str],
    provided_vars: Dict[str, str],
) -> Dict[str, str]:
    missing = required_vars - set(provided_vars.keys())
    if not missing:
        return {}

    print(section("Missing Variables"))

    collected: Dict[str, str] = {}
    for var in sorted(missing):
        value = input(f"  {var}: ").strip()
        collected[var] = value

    return collected


def apply_command(args: argparse.Namespace) -> None:
    is_dry_run = getattr(args, "dry_run", False)

    provider_name = (
        getattr(args, "provider", None)
        or get_config_value("provider")
        or "mock"
    )

    provider = get_provider(provider_name)
    print("\n--- Provider ---")
    print(provider_name)

    model = (
        getattr(args, "model", None)
        or get_config_value(f"models.{provider_name}")
    )
    if model:
        print(dim(f"Model: {model}"))

    repo = PromptRepo()
    prompt_data = repo.get_version_meta(args.name, args.version)

    if prompt_data is None:
        raise ValueError(f"Prompt '{args.name}@{args.version}' not found.")

    raw_prompt = prompt_data.get("prompt")
    if raw_prompt is None:
        raise ValueError(f"Prompt '{args.name}@{args.version}' has no 'prompt' field.")

    schema = repo.get_schema(args.name, args.version)
    schema_vars = schema.get("variables", {}) if schema else {}

    variables = _parse_vars(getattr(args, "var", None))

    if schema_vars:
        required_vars = {
            var_name
            for var_name, spec in schema_vars.items()
            if spec.get("required", False) and spec.get("default") is None
        }
    else:
        required_vars = extract_variables(raw_prompt)

    try:
        with open(args.file, "r", encoding="utf-8") as f:
            file_content = f.read()
    except OSError as e:
        raise RuntimeError(f"Failed to read file '{args.file}': {e}") from e

    if is_dry_run:
        missing = required_vars - set(variables.keys())

        if missing:
            print(section("Missing Required Variables (dry-run)"))
            for var in sorted(missing):
                print(f"  {var}")

        try:
            rendered_prompt = render_template(raw_prompt, variables)
        except Exception:
            rendered_prompt = raw_prompt

        print(section("Rendered Prompt"))
        print(rendered_prompt)

        MAX_LINES = 200
        lines = file_content.splitlines()

        print(section("File Content"))
        if len(lines) > MAX_LINES:
            preview = "\n".join(lines[:MAX_LINES])
            print(preview)
            print(f"\n... ({len(lines) - MAX_LINES} more lines)")
        else:
            print(file_content)
        return

    # -------------------------
    # Schema-aware flow
    # -------------------------
    if schema_vars:
        interactive_vars = _collect_schema_variables(schema_vars, variables)
    else:
        interactive_vars = _collect_template_variables(required_vars, variables)

    variables = {**interactive_vars, **variables}

    rendered_prompt = render_template(raw_prompt, variables)

    unused = find_unused_variables(raw_prompt, variables)
    if unused:
        unused_list = ", ".join(sorted(unused))
        print(warning(f"Unused variable(s): {unused_list}"))

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

    try:
        result = provider.run(combined_input, model=model)
    except Exception as e:
        print(f"Error: {e}")
        return

    if not isinstance(result, dict):
        raise ValueError("Provider returned invalid response format.")

    output = result.get("output") or ""
    output = output.strip()

    if not output:
        raise ValueError("Provider returned empty output.")

    if output == "NO_CHANGES":
        print(success("No changes required."))
        return

    if not output.startswith("---"):
        print(error("Invalid diff format received."))
        return

    print(section("Proposed Changes"))
    print(pretty_diff(output))

    answer = input(dim("\nApply changes? (y/n): ")).strip().lower()

    if answer == "y":
        try:
            new_content = apply_unified_diff(file_content, output)
        except ValueError as e:
            print(error(f"Failed to apply diff: {e}"))
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

        print(success(f"Changes applied to '{args.file}'"))

    else:
        print(dim("Aborted. No changes made."))
