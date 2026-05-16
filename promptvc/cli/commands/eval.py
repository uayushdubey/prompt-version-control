from __future__ import annotations

import argparse
import json
from typing import Dict, Any

from promptvc.core.repo import PromptRepo
from promptvc.utils.config import get_config_value
from promptvc.providers.mock import MockProvider
from promptvc.providers.openai import OpenAIProvider
from promptvc.providers.gemini import GeminiProvider
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

def _resolve_provider(name: str):
    return get_provider(name)


def eval_command(args: argparse.Namespace) -> None:
    provider_name = (
        getattr(args, "provider", None)
        or get_config_value("provider")
        or "mock"
    )

    provider = _resolve_provider(provider_name)
    repo = PromptRepo()

    # Load prompt
    prompt_data = repo.get(args.name, args.version)
    if prompt_data is None:
        raise ValueError(f"Prompt '{args.name}@{args.version}' not found.")

    raw_prompt = prompt_data.get("prompt")
    if raw_prompt is None:
        raise ValueError(f"Prompt '{args.name}@{args.version}' has no 'prompt' field.")

    # Load dataset
    try:
        with open(args.dataset, "r", encoding="utf-8") as f:
            dataset = json.load(f)
    except Exception as e:
        raise RuntimeError(f"Failed to load dataset: {e}") from e

    if not isinstance(dataset, list):
        raise ValueError("Dataset must be a list of objects.")

    results = []

    # Run evaluation loop
    for i, row in enumerate(dataset, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Dataset row {i} is not an object.")

        variables: Dict[str, Any] = row

        # Render prompt
        rendered_prompt = render_template(raw_prompt, variables)

        # Warn unused vars (optional but useful)
        unused = find_unused_variables(raw_prompt, variables)
        if unused:
            unused_list = ", ".join(sorted(unused))
            print(f"Warning (case {i}): Unused variable(s): {unused_list}")

        # Run provider
        result = provider.run(rendered_prompt)

        if not isinstance(result, dict):
            raise ValueError(f"Invalid provider response at case {i}")

        output = result.get("output")
        tokens = result.get("tokens")

        results.append({
            "input": row.get("input"),
            "output": output,
            "tokens": tokens,
        })

    # Print results
    for i, case in enumerate(results, start=1):
        print(f"Case {i}:")
        print(f"  Input:  {case.get('input')}")
        print(f"  Output: {case.get('output')}")
        print(f"  Tokens: {case.get('tokens')}")
        print()

    # Store evaluation
    repo.log_evaluation(
        name=args.name,
        version=args.version,
        dataset=args.dataset,
        results=results,
    )

    print(f"✓ Evaluation completed ({len(results)} cases)")