from __future__ import annotations

import argparse

from promptvc.core.repo import PromptRepo
from promptvc.core.compare import compare_versions
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


def compare_command(args: argparse.Namespace) -> None:
    # Resolve provider (CLI > config > default)
    provider_name = (
        getattr(args, "provider", None)
        or get_config_value("provider")
        or "mock"
    )

    provider = _resolve_provider(provider_name)

    repo = PromptRepo()

    # Run comparison
    result = compare_versions(
        repo=repo,
        name=args.name,
        v1=args.v1,
        v2=args.v2,
        dataset_path=args.dataset,
        provider=provider,
    )

    comparisons = result.get("comparisons", [])

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