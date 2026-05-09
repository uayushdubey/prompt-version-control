from __future__ import annotations

import argparse

from promptvc.core.repo import PromptRepo
from promptvc.core.eval import run_evaluation
from promptvc.utils.config import get_config_value
from promptvc.providers.mock import MockProvider
from promptvc.providers.openai import OpenAIProvider


# Provider registry (lazy instantiation)
_PROVIDER_REGISTRY = {
    "mock": MockProvider,
    "openai": OpenAIProvider,
}


def _resolve_provider(name: str):
    provider_cls = _PROVIDER_REGISTRY.get(name)
    if provider_cls is None:
        available = ", ".join(_PROVIDER_REGISTRY.keys())
        raise ValueError(
            f"Unknown provider '{name}'. Available providers: {available}."
        )
    return provider_cls()


def eval_command(args: argparse.Namespace) -> None:
    # Resolve provider (CLI > config > default)
    provider_name = (
        getattr(args, "provider", None)
        or get_config_value("provider")
        or "mock"
    )

    provider = _resolve_provider(provider_name)

    repo = PromptRepo()

    # Run evaluation
    result = run_evaluation(
        repo=repo,
        name=args.name,
        version=args.version,
        dataset_path=args.dataset,
        provider=provider,
    )

    results = result.get("results", [])

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