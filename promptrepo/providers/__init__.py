import importlib
import warnings
from typing import Any, Dict, List, Optional, Type
from promptrepo.providers.base import BaseProvider

_REGISTRY: Dict[str, Type[BaseProvider]] = {}

_PROVIDER_SPECS = [
    ("mock", "promptrepo.providers.mock", "MockProvider"),
    ("openai", "promptrepo.providers.openai", "OpenAIProvider"),
    ("gemini", "promptrepo.providers.gemini", "GeminiProvider"),
    ("anthropic", "promptrepo.providers.anthropic", "AnthropicProvider"),
    ("ollama", "promptrepo.providers.ollama", "OllamaProvider"),
]


def register_provider(name: str, provider_cls: Type[BaseProvider]) -> None:
    name = name.lower()

    if not name:
        raise ValueError("Provider name cannot be empty.")

    if name in _REGISTRY:
        raise ValueError(f"Provider '{name}' is already registered.")

    if not issubclass(provider_cls, BaseProvider):
        raise TypeError("Provider class must be a subclass of BaseProvider.")

    _REGISTRY[name] = provider_cls


def ensure_providers_registered() -> None:
    """Register all available providers, warning on missing dependencies."""
    for name, module_path, class_name in _PROVIDER_SPECS:
        try:
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            register_provider(name, cls)
        except ImportError:
            # Dependency not installed — provider simply unavailable
            pass
        except ValueError:
            # Already registered, register_provider raises ValueError if already registered
            pass
        except Exception as exc:
            warnings.warn(f"Failed to register provider '{name}': {exc}")


def get_provider(name: str, config: Optional[Dict[str, Any]] = None) -> BaseProvider:
    name = name.lower()
    ensure_providers_registered()

    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY.keys())) or "none"
        raise ValueError(
            f"Provider '{name}' not found. Available providers: {available}"
        )

    return _REGISTRY[name](config)


def list_providers() -> List[str]:
    ensure_providers_registered()
    return sorted(_REGISTRY.keys())
