from __future__ import annotations
import argparse

from promptvc.core.repo import PromptRepo
from promptvc.providers.mock import MockProvider
from promptvc.providers.openai import OpenAIProvider
from promptvc.utils.config import get_config_value
from promptvc.utils.diff_apply import apply_unified_diff

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


def apply_command(args: argparse.Namespace) -> None:
    provider_name = (
        getattr(args, "provider", None)
        or get_config_value("provider")
        or "mock"
    )

    provider = _resolve_provider(provider_name)

    repo = PromptRepo()
    prompt_text = repo.get(args.name, args.version)

    try:
        with open(args.file, "r", encoding="utf-8") as f:
            file_content = f.read()
    except OSError as e:
        raise RuntimeError(f"Failed to read file '{args.file}': {e}") from e

    combined_input = f"""
You are a senior software engineer.

Your task is to modify the given file according to the instruction.

INSTRUCTION:
{prompt_text}

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
    output = result.get("output")

    if output is None:
        raise ValueError("Provider returned no output.")

    if output.strip() == "NO_CHANGES":
        print("✓ No changes required.")
        return

    # Optional safety check (recommended)
    if not output.strip().startswith("---"):
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