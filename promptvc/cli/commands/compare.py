from __future__ import annotations

import argparse
import json
from typing import Dict, Any

from promptvc.core.repo import PromptRepo
from promptvc.utils.config import get_config_value
from promptvc.providers.mock import MockProvider
from promptvc.providers.openai import OpenAIProvider
from promptvc.providers.gemini import GeminiProvider
from promptvc.providers.anthropic import AnthropicProvider
from promptvc.providers.ollama import OllamaProvider
from promptvc.providers.registry import register_provider, get_provider
from promptvc.utils.template import render_template, find_unused_variables


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


def compare_command(args: argparse.Namespace) -> None:
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
    
    provider_kwargs = {}
    if model:
        provider_kwargs["model"] = model
        print(f"Model: {model}")

    timeout = (
        getattr(args, "timeout", None)
        or get_config_value("defaults.timeout")
    )

    if timeout:
        provider_kwargs["timeout"] = timeout

    max_tokens = getattr(args, "max_tokens", None)
    if max_tokens:
        provider_kwargs["max_tokens"] = max_tokens

    stream = getattr(args, "stream", False)
    if stream:
        provider_kwargs["stream"] = True

    repo = PromptRepo()

    # Load prompts
    prompt_v1_data = repo.get(args.name, args.v1)
    prompt_v2_data = repo.get(args.name, args.v2)

    if prompt_v1_data is None:
        raise ValueError(f"Prompt '{args.name}@{args.v1}' not found.")
    if prompt_v2_data is None:
        raise ValueError(f"Prompt '{args.name}@{args.v2}' not found.")

    prompt_v1 = prompt_v1_data.get("prompt")
    prompt_v2 = prompt_v2_data.get("prompt")

    if prompt_v1 is None:
        raise ValueError(f"Prompt '{args.name}@{args.v1}' has no 'prompt' field.")
    if prompt_v2 is None:
        raise ValueError(f"Prompt '{args.name}@{args.v2}' has no 'prompt' field.")

    # Load dataset
    try:
        with open(args.dataset, "r", encoding="utf-8") as f:
            dataset = json.load(f)
    except Exception as e:
        raise RuntimeError(f"Failed to load dataset: {e}") from e

    if not isinstance(dataset, list):
        raise ValueError("Dataset must be a list of objects.")

    comparisons = []

    # Run comparison loop
    for i, row in enumerate(dataset, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Dataset row {i} is not an object.")

        variables: Dict[str, Any] = row

        # Render both prompts
        rendered_v1 = render_template(prompt_v1, variables)
        rendered_v2 = render_template(prompt_v2, variables)

        # Warn unused variables (non-blocking)
        unused_v1 = find_unused_variables(prompt_v1, variables)
        unused_v2 = find_unused_variables(prompt_v2, variables)

        if unused_v1:
            unused_list = ", ".join(sorted(unused_v1))
            print(f"Warning (case {i}, {args.v1}): Unused variable(s): {unused_list}")

        if unused_v2:
            unused_list = ", ".join(sorted(unused_v2))
            print(f"Warning (case {i}, {args.v2}): Unused variable(s): {unused_list}")

        # Run both versions
        try:
            result_v1 = provider.run(rendered_v1, **provider_kwargs)
            result_v2 = provider.run(rendered_v2, **provider_kwargs)
        except Exception as e:
            print(f"Error in case {i}: {e}")
            continue
        if not isinstance(result_v1, dict):
            raise ValueError(f"Invalid provider response for {args.v1} at case {i}")
        if not isinstance(result_v2, dict):
            raise ValueError(f"Invalid provider response for {args.v2} at case {i}")

        output_v1 = result_v1.get("output") or ""
        output_v2 = result_v2.get("output") or ""

        comparisons.append({
            "input": row,
            "v1_output": output_v1,
            "v2_output": output_v2,
        })

    # Print results
    for i, case in enumerate(comparisons, start=1):
        print(f"Case {i}:")
        print(f"Input: {case.get('input')}")
        print()

        print(f"{args.v1} Output:")
        print(case.get("v1_output"))
        print()

        print(f"{args.v2} Output:")
        print(case.get("v2_output"))
        print()

        print("-" * 40)
        print()

    print(f"✓ Compared {args.v1} vs {args.v2} ({len(comparisons)} cases)")