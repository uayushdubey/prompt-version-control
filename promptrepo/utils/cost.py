"""
promptrepo/utils/cost.py

Production-grade cost estimation for LLM providers.
Prices are USD per 1,000,000 tokens (input / output).
Updated: June 2025 public pricing.

Usage:
    breakdown = compute_cost_breakdown("gpt-4o", input_tokens=500, output_tokens=200)
    print(format_cost_breakdown(breakdown))
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Price table  (USD per 1_000_000 tokens)
# format: { model_id: (input_price, output_price) }
# ---------------------------------------------------------------------------
_PRICES: Dict[str, Tuple[float, float]] = {
    # ── OpenAI ──────────────────────────────────────────────────────────────
    "gpt-4.1":                     (2.00,   8.00),
    "gpt-4.1-mini":                (0.40,   1.60),
    "gpt-4.1-nano":                (0.10,   0.40),
    "gpt-4o":                      (2.50,  10.00),
    "gpt-4o-mini":                 (0.15,   0.60),
    "gpt-4o-audio-preview":        (2.50,  10.00),
    "gpt-4-turbo":                 (10.00, 30.00),
    "gpt-4":                       (30.00, 60.00),
    "gpt-3.5-turbo":               (0.50,   1.50),
    "o3":                          (10.00, 40.00),
    "o3-mini":                     (1.10,   4.40),
    "o4-mini":                     (1.10,   4.40),
    "o1":                          (15.00, 60.00),
    "o1-mini":                     (3.00,  12.00),
    "o1-preview":                  (15.00, 60.00),

    # ── Anthropic ───────────────────────────────────────────────────────────
    "claude-opus-4-20250514":          (15.00, 75.00),
    "claude-sonnet-4-20250514":        (3.00,  15.00),
    "claude-3-5-sonnet-20241022":      (3.00,  15.00),
    "claude-3-5-haiku-20241022":       (0.80,   4.00),
    "claude-3-opus-20240229":          (15.00, 75.00),
    "claude-3-haiku-20240307":         (0.25,   1.25),
    "claude-3-sonnet-20240229":        (3.00,  15.00),

    # ── Google Gemini ────────────────────────────────────────────────────────
    "gemini-2.5-pro":              (1.25,  10.00),  # <= 200k ctx
    "gemini-2.5-flash":            (0.15,   0.60),
    "gemini-2.0-flash":            (0.10,   0.40),
    "gemini-2.0-flash-lite":       (0.075,  0.30),
    "gemini-1.5-pro":              (1.25,   5.00),  # <= 128k ctx
    "gemini-1.5-flash":            (0.075,  0.30),
    "gemini-1.5-flash-8b":         (0.0375, 0.15),
    "gemini-1.0-pro":              (0.50,   1.50),

    # ── Meta / Ollama (local — free) ─────────────────────────────────────────
    "llama3":                      (0.0, 0.0),
    "llama3.1":                    (0.0, 0.0),
    "llama3.2":                    (0.0, 0.0),
    "llama3.3":                    (0.0, 0.0),
    "llama4":                      (0.0, 0.0),
    "codellama":                   (0.0, 0.0),
    "mistral":                     (0.0, 0.0),
    "mistral-nemo":                (0.0, 0.0),
    "phi3":                        (0.0, 0.0),
    "phi4":                        (0.0, 0.0),
    "gemma2":                      (0.0, 0.0),
    "gemma3":                      (0.0, 0.0),
    "qwen2.5":                     (0.0, 0.0),
    "deepseek-r1":                 (0.0, 0.0),
}

# Aliases: map shorthand to canonical model name
_ALIASES: Dict[str, str] = {
    "gpt4o":               "gpt-4o",
    "gpt4o-mini":          "gpt-4o-mini",
    "gpt4":                "gpt-4",
    "gpt4.1":              "gpt-4.1",
    "claude-opus-4":       "claude-opus-4-20250514",
    "claude-sonnet-4":     "claude-sonnet-4-20250514",
    "claude-3-sonnet":     "claude-3-5-sonnet-20241022",
    "claude-3-haiku":      "claude-3-haiku-20240307",
    "gemini-pro":          "gemini-1.5-pro",
    "gemini-flash":        "gemini-2.0-flash",
    "gemini-2.5":          "gemini-2.5-pro",
}


@dataclass
class CostBreakdown:
    """Full cost breakdown for a single LLM call or aggregate of calls."""
    model: str
    input_tokens: int
    output_tokens: int
    input_cost_usd: Optional[float]
    output_cost_usd: Optional[float]
    total_cost_usd: Optional[float]
    is_known_model: bool

    @property
    def is_free(self) -> bool:
        return self.total_cost_usd is not None and self.total_cost_usd == 0.0

    def __add__(self, other: "CostBreakdown") -> "CostBreakdown":
        """Aggregate two breakdowns (for cumulative cost tracking)."""
        def _add_optional(a: Optional[float], b: Optional[float]) -> Optional[float]:
            if a is None and b is None:
                return None
            return (a or 0.0) + (b or 0.0)

        return CostBreakdown(
            model=self.model if self.model == other.model else f"{self.model}+{other.model}",
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            input_cost_usd=_add_optional(self.input_cost_usd, other.input_cost_usd),
            output_cost_usd=_add_optional(self.output_cost_usd, other.output_cost_usd),
            total_cost_usd=_add_optional(self.total_cost_usd, other.total_cost_usd),
            is_known_model=self.is_known_model and other.is_known_model,
        )


def _resolve_model(model: str) -> Tuple[str, Optional[Tuple[float, float]]]:
    """
    Resolve a model name to its canonical form and price tuple.
    Returns (canonical_name, (input_price, output_price)) or (model, None) if unknown.
    """
    m = model.strip().lower()
    m = _ALIASES.get(m, m)

    if m in _PRICES:
        return m, _PRICES[m]

    # Prefix match — e.g. "gpt-4o-2024-11-20" → "gpt-4o"
    for key, prices in _PRICES.items():
        if m.startswith(key):
            return key, prices

    return model, None


def compute_cost_breakdown(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> CostBreakdown:
    """
    Compute a full cost breakdown for an LLM call.

    Args:
        model: Model identifier string (e.g. "gpt-4o", "claude-sonnet-4")
        input_tokens: Number of prompt/input tokens consumed
        output_tokens: Number of completion/output tokens generated

    Returns:
        CostBreakdown with per-direction costs and total.
        If model is unknown, cost fields will be None.
    """
    canonical, prices = _resolve_model(model)

    if prices is None:
        return CostBreakdown(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_cost_usd=None,
            output_cost_usd=None,
            total_cost_usd=None,
            is_known_model=False,
        )

    in_price, out_price = prices
    input_cost = (input_tokens * in_price) / 1_000_000
    output_cost = (output_tokens * out_price) / 1_000_000

    return CostBreakdown(
        model=canonical,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_cost_usd=input_cost,
        output_cost_usd=output_cost,
        total_cost_usd=input_cost + output_cost,
        is_known_model=True,
    )


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> Optional[float]:
    """
    Return estimated USD total cost for a single call.
    Returns None if the model is unknown.

    For detailed breakdown, use compute_cost_breakdown() instead.
    """
    breakdown = compute_cost_breakdown(model, input_tokens, output_tokens)
    return breakdown.total_cost_usd


def cumulative_cost(
    calls: List[Tuple[str, int, int]],
) -> CostBreakdown:
    """
    Compute total cost across multiple calls.

    Args:
        calls: List of (model, input_tokens, output_tokens) tuples.

    Returns:
        Aggregated CostBreakdown.
    """
    if not calls:
        return CostBreakdown(
            model="(none)",
            input_tokens=0,
            output_tokens=0,
            input_cost_usd=0.0,
            output_cost_usd=0.0,
            total_cost_usd=0.0,
            is_known_model=True,
        )

    result = compute_cost_breakdown(*calls[0])
    for call in calls[1:]:
        result = result + compute_cost_breakdown(*call)
    return result


def format_cost(usd: Optional[float]) -> str:
    """Format a cost value for display. Returns '—' if cost is None."""
    if usd is None:
        return "—"
    if usd == 0.0:
        return "free (local)"
    if usd < 0.000001:
        return f"~${usd:.8f}"
    if usd < 0.001:
        return f"~${usd:.6f}"
    if usd < 0.01:
        return f"~${usd:.4f}"
    return f"~${usd:.4f}"


def format_cost_breakdown(breakdown: CostBreakdown) -> str:
    """
    Format a CostBreakdown into a human-readable multi-line string.

    Example:
        Model       : gpt-4o
        Input tokens: 1,200 → ~$0.0030
        Output tokens: 350  → ~$0.0035
        Total cost  : ~$0.0065
    """
    if not breakdown.is_known_model:
        return (
            f"Model       : {breakdown.model} (unknown — cost not tracked)\n"
            f"Input tokens: {breakdown.input_tokens:,}\n"
            f"Output tokens: {breakdown.output_tokens:,}"
        )

    lines = [
        f"Model        : {breakdown.model}",
        f"Input tokens : {breakdown.input_tokens:,}  → {format_cost(breakdown.input_cost_usd)}",
        f"Output tokens: {breakdown.output_tokens:,}  → {format_cost(breakdown.output_cost_usd)}",
        f"Total cost   : {format_cost(breakdown.total_cost_usd)}",
    ]
    if breakdown.is_free:
        lines.append("               (local model — no API cost)")
    return "\n".join(lines)


def format_latency(ms: Optional[float]) -> str:
    """Format a latency value in ms for display."""
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.2f}s"


def known_models() -> List[str]:
    """Return sorted list of all models with known pricing."""
    return sorted(_PRICES.keys())


def get_model_pricing(model: str) -> Optional[Tuple[float, float]]:
    """
    Return (input_price, output_price) per 1M tokens for a model.
    Returns None if model is unknown.
    """
    _, prices = _resolve_model(model)
    return prices
