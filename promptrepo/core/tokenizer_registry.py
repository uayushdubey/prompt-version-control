"""
promptrepo/core/tokenizer_registry.py

Production-grade tokenizer registry with model-aware BPE tokenization.

Hierarchy:
  1. tiktoken (real BPE) — if installed: `pip install promptrepo[tiktoken]`
  2. WordPunct (regex) — always available, ~10% off
  3. Character estimate (4 chars/token) — always available, rough

Usage:
    from promptrepo.core.tokenizer_registry import get_tokenizer_for_model, TokenizerRegistry
    tok = get_tokenizer_for_model("gpt-4o")
    count = tok.count("Hello, world!")
"""
from __future__ import annotations

import re
from typing import Dict, Optional, Type

from promptrepo.core.repo import (
    BaseTokenizer,
    WhitespaceTokenizer,
    WordPunctTokenizer,
    CharacterEstimateTokenizer,
    _TOKENIZER_REGISTRY,
    _BUILTIN_TOKENIZER_NAMES,
)


# ---------------------------------------------------------------------------
# Tiktoken BPE tokenizer (optional dependency)
# ---------------------------------------------------------------------------

class TiktokenTokenizer(BaseTokenizer):
    """
    Real BPE tokenizer using OpenAI's tiktoken library.

    Supports all OpenAI model encodings:
    - cl100k_base  : GPT-4, GPT-3.5-turbo, text-embedding-ada-002
    - o200k_base   : GPT-4o, o1, o3, o4 family
    - p50k_base    : Older GPT-3 models

    Falls back to WordPunctTokenizer if tiktoken is not installed.
    """

    # Encoding families by model prefix
    _ENCODING_MAP: Dict[str, str] = {
        # o200k_base family
        "gpt-4o":           "o200k_base",
        "gpt-4.1":          "o200k_base",
        "gpt-4.1-mini":     "o200k_base",
        "gpt-4.1-nano":     "o200k_base",
        "o1":               "o200k_base",
        "o1-mini":          "o200k_base",
        "o1-preview":       "o200k_base",
        "o3":               "o200k_base",
        "o3-mini":          "o200k_base",
        "o4-mini":          "o200k_base",
        # cl100k_base family
        "gpt-4":            "cl100k_base",
        "gpt-4-turbo":      "cl100k_base",
        "gpt-3.5-turbo":    "cl100k_base",
        "claude":           "cl100k_base",  # Claude uses same vocabulary approx
        # p50k_base — legacy
        "text-davinci":     "p50k_base",
    }
    _DEFAULT_ENCODING = "cl100k_base"

    def __init__(self, encoding: str = "cl100k_base"):
        self._encoding_name = encoding
        self._enc = None
        self._fallback = WordPunctTokenizer()
        self._available = self._try_load(encoding)

    def _try_load(self, encoding: str) -> bool:
        try:
            import tiktoken
            self._enc = tiktoken.get_encoding(encoding)
            return True
        except ImportError:
            return False
        except Exception:
            return False

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self._available and self._enc is not None:
            try:
                return len(self._enc.encode(text))
            except Exception:
                pass
        return self._fallback.count(text)

    @property
    def is_using_bpe(self) -> bool:
        """True if real tiktoken BPE is active, False if using fallback."""
        return self._available

    @classmethod
    def for_model(cls, model: str) -> "TiktokenTokenizer":
        """Return a TiktokenTokenizer configured for the given model."""
        model_lower = model.strip().lower()
        encoding = cls._DEFAULT_ENCODING
        for prefix, enc in cls._ENCODING_MAP.items():
            if model_lower.startswith(prefix):
                encoding = enc
                break
        return cls(encoding)


# ---------------------------------------------------------------------------
# Register TiktokenTokenizer in the global registry
# ---------------------------------------------------------------------------

def _register_tiktoken() -> None:
    """Register tiktoken tokenizer if not already registered."""
    if "tiktoken" not in _TOKENIZER_REGISTRY:
        _TOKENIZER_REGISTRY["tiktoken"] = TiktokenTokenizer


_register_tiktoken()


# ---------------------------------------------------------------------------
# Model-aware tokenizer selection
# ---------------------------------------------------------------------------

_MODEL_TOKENIZER_MAP: Dict[str, str] = {
    # OpenAI — real BPE
    "gpt-4o": "tiktoken",
    "gpt-4.1": "tiktoken",
    "gpt-4.1-mini": "tiktoken",
    "gpt-4.1-nano": "tiktoken",
    "gpt-4": "tiktoken",
    "gpt-4-turbo": "tiktoken",
    "gpt-3.5-turbo": "tiktoken",
    "o1": "tiktoken",
    "o1-mini": "tiktoken",
    "o3": "tiktoken",
    "o3-mini": "tiktoken",
    "o4-mini": "tiktoken",
    # Anthropic Claude — approximation (tiktoken cl100k close enough)
    "claude": "tiktoken",
    # Gemini — character estimate is most reliable
    "gemini": "character",
    # Local models
    "llama": "wordpunct",
    "mistral": "wordpunct",
    "phi": "wordpunct",
    "gemma": "wordpunct",
    "qwen": "wordpunct",
    "deepseek": "wordpunct",
}


def get_tokenizer_for_model(model: str) -> BaseTokenizer:
    """
    Return the best available tokenizer for the given model.

    For OpenAI/Claude models: uses TiktokenTokenizer (real BPE) if tiktoken
    is installed, otherwise falls back to WordPunctTokenizer.

    For Gemini models: uses CharacterEstimateTokenizer.

    For local models: uses WordPunctTokenizer.

    Args:
        model: Model identifier string (e.g. "gpt-4o", "claude-sonnet-4")

    Returns:
        A BaseTokenizer instance appropriate for the model.
    """
    model_lower = model.strip().lower()
    tokenizer_name = "wordpunct"  # default

    for prefix, tok_name in _MODEL_TOKENIZER_MAP.items():
        if model_lower.startswith(prefix):
            tokenizer_name = tok_name
            break

    if tokenizer_name == "tiktoken":
        return TiktokenTokenizer.for_model(model_lower)
    elif tokenizer_name == "character":
        return CharacterEstimateTokenizer()
    elif tokenizer_name == "wordpunct":
        return WordPunctTokenizer()
    else:
        return WordPunctTokenizer()


class TokenizerRegistry:
    """
    Convenience class for tokenizer registration and discovery.
    Wraps the module-level functions from repo.py.
    """

    @staticmethod
    def list_all() -> list:
        return sorted(_TOKENIZER_REGISTRY.keys())

    @staticmethod
    def get(name: str) -> BaseTokenizer:
        from promptrepo.core.repo import get_tokenizer
        return get_tokenizer(name)

    @staticmethod
    def for_model(model: str) -> BaseTokenizer:
        return get_tokenizer_for_model(model)

    @staticmethod
    def tiktoken_available() -> bool:
        """Return True if the tiktoken library is installed."""
        try:
            import tiktoken  # noqa: F401
            return True
        except ImportError:
            return False
