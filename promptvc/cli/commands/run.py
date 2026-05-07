from __future__ import annotations

import argparse

from promptvc.core.repo import PromptRepo
from promptvc.providers.mock import MockProvider
from promptvc.providers.openai import OpenAIProvider
from promptvc.utils.config import get_config_value

# Provider registry — add new providers here as they become available
_PROVIDER_REGISTRY = {
    "mock": MockProvider(),
    "openai": OpenAIProvider(),
}


def _resolve_provider(name: str):
    """
    Return the provider instance for the given name.

    Raises:
        ValueError: If the provider is not registered.
    """
    provider = _PROVIDER_REGISTRY.get(name)
    if provider is None:
        available = ", ".join(f"'{k}'" for k in _PROVIDER_REGISTRY)
        raise ValueError(
            f"Provider '{name}' not found. Available providers: {available}"
        )
    return provider


def run_command(args: argparse.Namespace) -> None:
    provider_name = (
        getattr(args, "provider", None)
        or get_config_value("provider")
        or "mock"
    )
    provider = _resolve_provider(provider_name)

    repo = PromptRepo()
    result = repo.run(args.name, args.version, provider)

    output = result.get("output")
    if output is None:
        raise ValueError("Provider returned no output.")

    tokens = result.get("tokens")

    print(f"\n✓ Ran {args.name}@{args.version}")
    print(f"\nOutput:\n{output}")
    if tokens is not None:
        print(f"\nTokens: {tokens}")