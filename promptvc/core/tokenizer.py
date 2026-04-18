from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Type, Protocol


# =========================
# Protocol
# =========================

class TokenizerProtocol(Protocol):
    """Structural protocol for tokenizer duck-typing."""

    def count(self, text: str) -> int:
        ...


# =========================
# Base Class
# =========================

class BaseTokenizer(ABC):
    """Abstract base for all tokenizer implementations."""

    @abstractmethod
    def count(self, text: str) -> int:
        """Return the token count for the given text."""
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}>"


# =========================
# Built-in Tokenizers
# =========================

class WhitespaceTokenizer(BaseTokenizer):
    """Splits on whitespace. Fast and predictable."""

    def count(self, text: str) -> int:
        if not text:
            return 0
        return len(text.split())


class WordPunctTokenizer(BaseTokenizer):
    """
    Splits into words and punctuation tokens via regex.

    More granular than whitespace splitting; useful for
    prompts with heavy punctuation.
    """

    _pattern = re.compile(r"\w+|[^\w\s]", re.UNICODE)

    def count(self, text: str) -> int:
        if not text:
            return 0
        return len(self._pattern.findall(text))


class CharacterEstimateTokenizer(BaseTokenizer):
    """
    Approximates token count from character length.

    Heuristic: 1 token ≈ 4 characters (common LLM rule of thumb).
    Returns 0 for empty input.
    """

    _CHARS_PER_TOKEN = 4

    def count(self, text: str) -> int:
        if not text:
            return 0
        return len(text) // self._CHARS_PER_TOKEN


# =========================
# Registry
# =========================

_REGISTRY: Dict[str, Type[BaseTokenizer]] = {
    "whitespace": WhitespaceTokenizer,
    "wordpunct": WordPunctTokenizer,
    "character": CharacterEstimateTokenizer,
}

_BUILTIN_NAMES: frozenset[str] = frozenset(_REGISTRY.keys())

# Default alias used by PromptRepo when no tokenizer is specified
Tokenizer = WhitespaceTokenizer


# =========================
# Registry Functions
# =========================

def get_tokenizer(name: str) -> BaseTokenizer:
    """
    Return a tokenizer instance by registered name.

    Raises:
        ValueError: If name is empty or not registered.
    """
    if not name:
        raise ValueError("Tokenizer name cannot be empty.")

    key = name.strip().lower()

    if key not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY))
        raise ValueError(
            f"Tokenizer '{name}' is not registered. "
            f"Available: {available}"
        )

    return _REGISTRY[key]()


def register_tokenizer(
    name: str,
    cls: Type[BaseTokenizer],
    *,
    force: bool = False,
) -> None:
    """
    Register a custom tokenizer class.

    Args:
        name:  Unique identifier for the tokenizer.
        cls:   Class inheriting from BaseTokenizer.
        force: If True, overwrite an existing custom registration.
               Built-in tokenizers cannot be overwritten.

    Raises:
        ValueError: If name is invalid, already registered, or is a built-in.
        TypeError:  If cls does not inherit BaseTokenizer.
    """
    if not name:
        raise ValueError("Tokenizer name cannot be empty.")

    key = name.strip().lower()

    if key in _BUILTIN_NAMES:
        raise ValueError(
            f"Cannot overwrite built-in tokenizer '{name}'."
        )

    if key in _REGISTRY and not force:
        raise ValueError(
            f"Tokenizer '{name}' is already registered. "
            "Pass force=True to overwrite."
        )

    if not issubclass(cls, BaseTokenizer):
        raise TypeError(
            f"{cls.__name__} must inherit from BaseTokenizer."
        )

    _REGISTRY[key] = cls


def unregister_tokenizer(name: str) -> None:
    """
    Remove a custom tokenizer from the registry.

    Built-in tokenizers cannot be removed.

    Raises:
        ValueError: If name is a built-in or not registered.
    """
    if not name:
        raise ValueError("Tokenizer name cannot be empty.")

    key = name.strip().lower()

    if key in _BUILTIN_NAMES:
        raise ValueError(
            f"Cannot unregister built-in tokenizer '{name}'."
        )

    if key not in _REGISTRY:
        raise ValueError(
            f"Tokenizer '{name}' is not registered."
        )

    del _REGISTRY[key]


def list_tokenizers(*, include_builtins: bool = True) -> List[str]:
    """
    Return names of all registered tokenizers.

    Args:
        include_builtins: If False, only custom tokenizers are returned.
    """
    if include_builtins:
        return sorted(_REGISTRY.keys())

    return sorted(k for k in _REGISTRY if k not in _BUILTIN_NAMES)


def get_tokenizer_info(name: str) -> Dict[str, object]:
    """
    Return metadata about a registered tokenizer.

    Returns a dict with keys: name, class, builtin.
    Useful for CLI introspection and debugging.
    """
    if not name:
        raise ValueError("Tokenizer name cannot be empty.")

    key = name.strip().lower()

    if key not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY))
        raise ValueError(
            f"Tokenizer '{name}' not found. Available: {available}"
        )

    cls = _REGISTRY[key]
    return {
        "name": key,
        "class": cls.__name__,
        "builtin": key in _BUILTIN_NAMES,
        "doc": cls.__doc__ or "",
    }