"""
promptvc.core.tokenizer
~~~~~~~~~~~~~~~~~~~~~~~
Token counting abstraction layer.

Designed to be swappable — plug in tiktoken, HuggingFace tokenizers,
or any other backend without touching the rest of the codebase.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Protocol — duck-typing friendly interface for external tokenizers
# ---------------------------------------------------------------------------

@runtime_checkable
class TokenizerProtocol(Protocol):
    """
    Structural protocol any tokenizer must satisfy.
    Allows drop-in replacement without inheritance.
    """

    def count(self, text: str) -> int:
        """Return the number of tokens in *text*."""
        ...


# ---------------------------------------------------------------------------
# Abstract base — for tokenizers that prefer inheritance
# ---------------------------------------------------------------------------

class BaseTokenizer(ABC):
    """Abstract base for inheritance-based tokenizer implementations."""

    @abstractmethod
    def count(self, text: str) -> int:
        """Return the number of tokens in *text*."""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"


# ---------------------------------------------------------------------------
# Built-in implementations
# ---------------------------------------------------------------------------

class WhitespaceTokenizer(BaseTokenizer):
    """
    Naïve whitespace-based tokenizer.

    Splits on any whitespace and filters empty strings.
    Suitable for quick estimates; ~30-50 % accurate vs. GPT-4 tokenizer.

    Complexity: O(n) time, O(n) space.
    """

    def count(self, text: str) -> int:
        if not text or not text.strip():
            return 0
        return len(text.split())


class WordPunctTokenizer(BaseTokenizer):
    """
    Slightly smarter tokenizer that splits on whitespace *and* punctuation,
    mimicking the word-piece behaviour of many LLM tokenizers more closely.

    Still O(n) — no external dependencies.
    """

    # Punctuation characters that typically become separate tokens
    _PUNCT_PATTERN = re.compile(r"(\s+|[.,!?;:\"'()\[\]{}<>/\\|@#$%^&*\-_+=`~])")

    def count(self, text: str) -> int:
        if not text or not text.strip():
            return 0
        tokens = [t for t in self._PUNCT_PATTERN.split(text) if t and not t.isspace()]
        return len(tokens)


class CharacterEstimateTokenizer(BaseTokenizer):
    """
    Character-ratio estimator.

    OpenAI's rule of thumb: ~4 characters per token for English text.
    Fast O(1) character count — no splitting required.
    """

    CHARS_PER_TOKEN: float = 4.0

    def count(self, text: str) -> int:
        if not text:
            return 0
        return max(1, round(len(text) / self.CHARS_PER_TOKEN))


# ---------------------------------------------------------------------------
# Registry — allows future plug-in tokenizers by name
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, type[BaseTokenizer]] = {
    "whitespace": WhitespaceTokenizer,
    "wordpunct": WordPunctTokenizer,
    "character": CharacterEstimateTokenizer,
}


def get_tokenizer(name: str = "whitespace") -> BaseTokenizer:
    """
    Retrieve a tokenizer instance by registered name.

    Args:
        name: One of ``"whitespace"``, ``"wordpunct"``, ``"character"``.

    Returns:
        A :class:`BaseTokenizer` instance.

    Raises:
        ValueError: If *name* is not registered.

    Example::

        tokenizer = get_tokenizer("wordpunct")
        token_count = tokenizer.count("Hello, world!")
    """
    key = name.lower().strip()
    if key not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY))
        raise ValueError(
            f"Unknown tokenizer '{name}'. Available: {available}. "
            "Register a custom tokenizer with register_tokenizer()."
        )
    return _REGISTRY[key]()


def register_tokenizer(name: str, cls: type[BaseTokenizer]) -> None:
    """
    Register a custom tokenizer class under *name*.

    This is the extension point for external tokenizers (e.g. tiktoken).

    Args:
        name:  Unique name for this tokenizer.
        cls:   A :class:`BaseTokenizer` subclass (not an instance).

    Raises:
        TypeError: If *cls* does not subclass :class:`BaseTokenizer`.
        ValueError: If *name* is already registered.

    Example::

        class TiktokenWrapper(BaseTokenizer):
            def count(self, text: str) -> int:
                import tiktoken
                enc = tiktoken.get_encoding("cl100k_base")
                return len(enc.encode(text))

        register_tokenizer("tiktoken", TiktokenWrapper)
    """
    if not (isinstance(cls, type) and issubclass(cls, BaseTokenizer)):
        raise TypeError(
            f"cls must be a subclass of BaseTokenizer, got {cls!r}."
        )
    if name in _REGISTRY:
        raise ValueError(
            f"A tokenizer named '{name}' is already registered. "
            "Use a different name or unregister it first."
        )
    _REGISTRY[name] = cls


def unregister_tokenizer(name: str) -> None:
    """Remove a previously registered tokenizer (useful in tests)."""
    built_ins = {"whitespace", "wordpunct", "character"}
    if name in built_ins:
        raise ValueError(f"Cannot unregister built-in tokenizer '{name}'.")
    _REGISTRY.pop(name, None)