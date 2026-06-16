"""
promptvc — Prompt Version Control library.

Top-level package that re-exports the full SDK surface so users can simply:

    import promptvc

    result = promptvc.run("my-prompt", "v1", provider="openai", text="Hello")
    print(result.output)

    @promptvc.prompt("summarizer", version="latest", provider="openai")
    def summarize(text: str): ...

    with promptvc.run_context("classifier", "v2", provider="gemini") as ctx:
        result = ctx.run(category="food")
"""
from promptvc.version import __version__

# ── SDK (primary developer interface) ─────────────────────────────────────
from promptvc.sdk import (
    run,
    batch_run,
    prompt,
    run_context,
    RunResult,
    BatchResult,
    RunContext,
    PromptDecorator,
)

# ── Core ──────────────────────────────────────────────────────────────────
from promptvc.core.repo import PromptRepo

# ── Utilities ─────────────────────────────────────────────────────────────
from promptvc.utils.cost import format_cost, compute_cost_breakdown, CostBreakdown

__all__ = [
    "__version__",
    # SDK
    "run",
    "batch_run",
    "prompt",
    "run_context",
    "RunResult",
    "BatchResult",
    "RunContext",
    "PromptDecorator",
    # Core
    "PromptRepo",
    # Utils
    "format_cost",
    "compute_cost_breakdown",
    "CostBreakdown",
]
