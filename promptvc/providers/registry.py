from typing import Any, Dict, List, Optional, Type

from promptvc.providers.base import BaseProvider

_REGISTRY: Dict[str, Type[BaseProvider]] = {}


def register_provider(name: str, provider_cls: Type[BaseProvider]) -> None:
    name = name.lower()

    if not name:
        raise ValueError("Provider name cannot be empty.")

    if name in _REGISTRY:
        raise ValueError(f"Provider '{name}' is already registered.")

    if not issubclass(provider_cls, BaseProvider):
        raise TypeError("Provider class must be a subclass of BaseProvider.")

    _REGISTRY[name] = provider_cls


def get_provider(name: str, config: Optional[Dict[str, Any]] = None) -> BaseProvider:
    name = name.lower()

    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY.keys())) or "none"
        raise ValueError(
            f"Provider '{name}' not found. Available providers: {available}"
        )

    return _REGISTRY[name](config)


def list_providers() -> List[str]:
    return sorted(_REGISTRY.keys())