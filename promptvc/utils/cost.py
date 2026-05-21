"""
promptvc/utils/cost.py

Static cost estimation for known LLM models.
Prices are per 1M tokens (input/output), in USD.
Updated to reflect mid-2025 public pricing.
"""
from __future__ import annotations

from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# Price table  (USD per 1_000_000 tokens)
# format: { model_id: (input_price, output_price) }
# ---------------------------------------------------------------------------
_PRICES: dict[str, Tuple[float, float]] = {
    # ── OpenAI ──────────────────────────────────────────────────────────────
    "gpt-4o":                  (2.50,  10.00),
    "gpt-4o-mini":             (0.15,   0.60),
    "gpt-4-turbo":             (10.00, 30.00),
    "gpt-4":                   (30.00, 60.00),
    "gpt-3.5-turbo":           (0.50,  1.50),

    # ── Anthropic ───────────────────────────────────────────────────────────
    "claude-opus-4-20250514":      (15.00, 75.00),
    "claude-sonnet-4-20250514":    (3.00,  15.00),
    "claude-3-5-sonnet-20241022":  (3.00,  15.00),
    "claude-3-5-haiku-20241022":   (0.80,   4.00),
    "claude-3-opus-20240229":      (15.00, 75.00),
    "claude-3-haiku-20240307":     (0.25,  1.25),

    # ── Google Gemini ────────────────────────────────────────────────────────
    "gemini-1.5-pro":          (3.50,  10.50),
    "gemini-1.5-flash":        (0.075,  0.30),
    "gemini-1.0-pro":          (0.50,   1.50),
    "gemini-2.0-flash":        (0.10,   0.40),

    # ── Meta / Ollama (local — free) ─────────────────────────────────────────
    "llama3":                  (0.0,   0.0),
    "llama3.1":                (0.0,   0.0),
    "llama3.2":                (0.0,   0.0),
    "codellama":               (0.0,   0.0),
    "mistral":                 (0.0,   0.0),
    "phi3":                    (0.0,   0.0),
    "gemma2":                  (0.0,   0.0),
}

# Normalise model names: strip common prefixes/suffixes
_ALIASES: dict[str, str] = {
    "gpt4o":         "gpt-4o",
    "gpt4o-mini":    "gpt-4o-mini",
    "gpt4":          "gpt-4",
    "claude-3-sonnet": "claude-3-5-sonnet-20241022",
}


def _resolve(model: str) -> Optional[Tuple[float, float]]:
    m = model.strip().lower()
    m = _ALIASES.get(m, m)
    if m in _PRICES:
        return _PRICES[m]
    # Prefix match — e.g. "gpt-4o-2024-11-20" → "gpt-4o"
    for key, prices in _PRICES.items():
        if m.startswith(key):
            return prices
    return None


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> Optional[float]:
    """
    Return estimated USD cost for a single call.
    Returns None if the model is unknown (cost not tracked).

    Args:
        model:         Model identifier string (e.g. "gpt-4o")
        input_tokens:  Number of prompt/input tokens
        output_tokens: Number of completion/output tokens
    """
    prices = _resolve(model)
    if prices is None:
        return None
    in_price, out_price = prices
    cost = (input_tokens * in_price + output_tokens * out_price) / 1_000_000
    return cost


def format_cost(usd: Optional[float]) -> str:
    """
    Format a cost value for display.
    Returns '—' if cost is None (unknown model).
    """
    if usd is None:
        return "—"
    if usd == 0.0:
        return "free (local)"
    if usd < 0.001:
        return f"~${usd:.6f}"
    if usd < 0.01:
        return f"~${usd:.4f}"
    return f"~${usd:.4f}"


def format_latency(ms: Optional[float]) -> str:
    """Format a latency value in ms for display."""
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.2f}s"


def known_models() -> list[str]:
    """Return sorted list of all models with known pricing."""
    return sorted(_PRICES.keys())
