"""
promptvc/core/budget.py

Cost budget guard for PromptVC.

Prevents runaway API spend by:
  1. Pre-run cost estimation before executing a prompt
  2. Session-level cumulative cost tracking
  3. Configurable hard stop when budget is exceeded

Usage:
    from promptvc.core.budget import BudgetGuard, BudgetExceededError

    guard = BudgetGuard(max_cost_per_run=0.05, max_session_cost=1.00)
    guard.check_pre_run(model="gpt-4o", estimated_input_tokens=2000)
    # ... run the prompt ...
    guard.record_usage(model="gpt-4o", input_tokens=2000, output_tokens=500)
    print(guard.session_cost)  # 0.0065
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional

from promptvc.utils.cost import compute_cost_breakdown, format_cost, CostBreakdown


class BudgetExceededError(Exception):
    """Raised when a budget limit would be exceeded."""

    def __init__(
        self,
        limit_type: str,
        limit_usd: float,
        current_usd: float,
        estimated_usd: float,
    ):
        self.limit_type = limit_type
        self.limit_usd = limit_usd
        self.current_usd = current_usd
        self.estimated_usd = estimated_usd
        super().__init__(
            f"Budget exceeded: {limit_type} limit is {format_cost(limit_usd)}, "
            f"current session total is {format_cost(current_usd)}, "
            f"estimated run cost is {format_cost(estimated_usd)}. "
            f"Increase limit with: promptvc config set budget.max_session_cost <amount>"
        )


class BudgetWarning(UserWarning):
    """Issued when usage reaches 80% of a budget limit."""


@dataclass
class UsageRecord:
    """A single API call's token usage for budget tracking."""
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: Optional[float]
    timestamp: str


@dataclass
class BudgetGuard:
    """
    Session-scoped cost budget guard.

    Tracks cumulative API spend and enforces configurable limits.

    Args:
        max_cost_per_run: Maximum USD cost allowed for a single run. Default: None (no limit)
        max_session_cost: Maximum cumulative USD cost for this session. Default: None (no limit)
        warn_at_fraction: Issue warning when this fraction of budget is used. Default: 0.8
        enabled: If False, all checks are bypassed. Default: True
    """
    max_cost_per_run: Optional[float] = None
    max_session_cost: Optional[float] = None
    warn_at_fraction: float = 0.8
    enabled: bool = True

    _session_records: List[UsageRecord] = field(default_factory=list, init=False)
    _session_cost: float = field(default=0.0, init=False)

    @classmethod
    def from_config(cls, config_fn) -> "BudgetGuard":
        """Create a BudgetGuard from CLI config values."""
        max_run = config_fn("budget.max_cost_per_run")
        max_session = config_fn("budget.max_session_cost")
        enabled = config_fn("budget.enabled")

        return cls(
            max_cost_per_run=float(max_run) if max_run else None,
            max_session_cost=float(max_session) if max_session else None,
            enabled=enabled != "false",
        )

    @property
    def session_cost(self) -> float:
        """Total USD cost accumulated in this session."""
        return self._session_cost

    @property
    def session_records(self) -> List[UsageRecord]:
        """All usage records in this session."""
        return list(self._session_records)

    def estimate_run_cost(
        self,
        model: str,
        estimated_input_tokens: int,
        estimated_output_tokens: int = 0,
    ) -> Optional[float]:
        """
        Estimate cost for an upcoming run without executing it.

        Uses input token count (which is known pre-run) plus an estimated
        output token count (default 0 for conservative estimate).

        Returns None if model pricing is unknown.
        """
        bd = compute_cost_breakdown(model, estimated_input_tokens, estimated_output_tokens)
        return bd.total_cost_usd

    def check_pre_run(
        self,
        model: str,
        estimated_input_tokens: int,
        estimated_output_tokens: int = 0,
    ) -> None:
        """
        Check if an upcoming run would exceed budget limits.

        Call this BEFORE executing a prompt.

        Args:
            model: Model to be used.
            estimated_input_tokens: Known input token count.
            estimated_output_tokens: Estimated output tokens (conservative: 0).

        Raises:
            BudgetExceededError: If the estimated cost would exceed any limit.

        Warns:
            BudgetWarning: If usage would reach warn_at_fraction of any limit.
        """
        if not self.enabled:
            return

        bd = compute_cost_breakdown(model, estimated_input_tokens, estimated_output_tokens)
        estimated = bd.total_cost_usd

        if estimated is None:
            return  # Unknown model, can't enforce budget

        import warnings

        # Check per-run limit
        if self.max_cost_per_run is not None and estimated > self.max_cost_per_run:
            raise BudgetExceededError(
                limit_type="per-run",
                limit_usd=self.max_cost_per_run,
                current_usd=0.0,
                estimated_usd=estimated,
            )

        # Check session limit
        if self.max_session_cost is not None:
            projected = self._session_cost + estimated
            if projected > self.max_session_cost:
                raise BudgetExceededError(
                    limit_type="session",
                    limit_usd=self.max_session_cost,
                    current_usd=self._session_cost,
                    estimated_usd=estimated,
                )

            # Warn at threshold
            if (self._session_cost / self.max_session_cost) >= self.warn_at_fraction:
                warnings.warn(
                    f"Budget warning: {self._session_cost / self.max_session_cost * 100:.0f}% "
                    f"of session budget used ({format_cost(self._session_cost)} / "
                    f"{format_cost(self.max_session_cost)})",
                    BudgetWarning,
                    stacklevel=3,
                )

    def record_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        timestamp: Optional[str] = None,
    ) -> CostBreakdown:
        """
        Record actual token usage after a run completes.

        Call this AFTER executing a prompt to update session totals.

        Args:
            model: Model used.
            input_tokens: Actual input tokens consumed.
            output_tokens: Actual output tokens generated.
            timestamp: ISO timestamp (defaults to now).

        Returns:
            CostBreakdown for this individual run.
        """
        if not timestamp:
            from datetime import datetime, timezone
            timestamp = datetime.now(timezone.utc).isoformat()

        bd = compute_cost_breakdown(model, input_tokens, output_tokens)

        record = UsageRecord(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=bd.total_cost_usd,
            timestamp=timestamp,
        )
        self._session_records.append(record)

        if bd.total_cost_usd is not None:
            self._session_cost += bd.total_cost_usd

        return bd

    def reset_session(self) -> None:
        """Reset session cost tracking (e.g., at start of new CLI invocation)."""
        self._session_records.clear()
        self._session_cost = 0.0

    def summary(self) -> str:
        """Return a human-readable session budget summary."""
        lines = [f"Session cost: {format_cost(self._session_cost)}"]
        if self.max_session_cost:
            pct = self._session_cost / self.max_session_cost * 100
            lines.append(f"Budget used : {pct:.1f}% of {format_cost(self.max_session_cost)}")
        lines.append(f"Runs this session: {len(self._session_records)}")
        return "\n".join(lines)


# Global session-scoped guard instance (lazily initialized per CLI invocation)
_session_guard: Optional[BudgetGuard] = None


def get_session_guard(config_fn=None) -> BudgetGuard:
    """Return (or initialize) the global session budget guard."""
    global _session_guard
    if _session_guard is None:
        if config_fn:
            _session_guard = BudgetGuard.from_config(config_fn)
        else:
            _session_guard = BudgetGuard()
    return _session_guard


def reset_session_guard() -> None:
    """Reset the global session guard (useful in tests)."""
    global _session_guard
    _session_guard = None
