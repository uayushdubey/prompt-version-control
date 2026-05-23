import importlib
import warnings
from typing import Dict, Type
from promptvc.providers.registry import register_provider

_PROVIDER_SPECS = [
    ("mock", "promptvc.providers.mock", "MockProvider"),
    ("openai", "promptvc.providers.openai", "OpenAIProvider"),
    ("gemini", "promptvc.providers.gemini", "GeminiProvider"),
    ("anthropic", "promptvc.providers.anthropic", "AnthropicProvider"),
    ("ollama", "promptvc.providers.ollama", "OllamaProvider"),
]

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
