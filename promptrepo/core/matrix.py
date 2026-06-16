"""
promptrepo/core/matrix.py

Matrix Evaluation Engine for PromptVC.

Runs N prompt versions × M test cases and produces a comparative score matrix.
This is the core A/B testing feature.

Usage:
    from promptrepo.core.matrix import MatrixConfig, run_matrix_eval, format_matrix_table

    config = MatrixConfig(
        name="summarizer",
        versions=["v1", "v2", "v3"],
        dataset_path="tests/data.json",
    )
    result = run_matrix_eval(config, provider=openai_provider, repo=repo)
    print(format_matrix_table(result))
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from promptrepo.core.evaluator import run_case_assertions, CaseResult
from promptrepo.utils.template import render_template


@dataclass
class MatrixCell:
    """Result for one (version, test_case) combination."""
    version: str
    case_id: str
    score: float            # 0.0 - 1.0
    passed: bool
    output: str
    tokens: Optional[int]
    latency_ms: float
    error: Optional[str] = None


@dataclass
class VersionStats:
    """Aggregate statistics for one prompt version across all test cases."""
    version: str
    mean_score: float
    std_dev: float
    pass_rate: float          # fraction of cases that passed
    total_cases: int
    passed_cases: int
    avg_tokens: Optional[float]
    avg_latency_ms: float
    total_cost_usd: Optional[float] = None

    @property
    def rank_score(self) -> float:
        """Combined ranking metric: weighted mean of score and pass_rate."""
        return 0.7 * self.mean_score + 0.3 * self.pass_rate


@dataclass
class MatrixResult:
    """Full N×M evaluation matrix result."""
    name: str                               # Prompt space name
    versions: List[str]                     # Evaluated versions
    case_ids: List[str]                     # Test case IDs
    cells: List[MatrixCell]                 # All N×M results
    version_stats: List[VersionStats]       # Per-version aggregate stats
    winner: Optional[str]                   # Version with highest rank_score
    dataset_path: str
    provider_name: str
    total_duration_ms: float

    def get_cell(self, version: str, case_id: str) -> Optional[MatrixCell]:
        for cell in self.cells:
            if cell.version == version and cell.case_id == case_id:
                return cell
        return None

    def get_stats(self, version: str) -> Optional[VersionStats]:
        for s in self.version_stats:
            if s.version == version:
                return s
        return None


@dataclass
class MatrixConfig:
    """Configuration for a matrix evaluation run."""
    name: str                               # Prompt space name
    versions: List[str]                     # Versions to evaluate
    dataset_path: str                       # Path to test dataset JSON
    provider_name: str = "mock"             # Provider to use
    model: Optional[str] = None             # Override model
    deterministic: bool = True              # Disable LLM judge for reproducibility
    max_workers: int = 1                    # Parallel execution (>1 = concurrent)
    stop_on_error: bool = False             # Abort if any cell errors


def _load_dataset(path: str) -> List[Dict[str, Any]]:
    """Load and validate a test dataset from JSON file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Dataset file not found: {path}")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in dataset file '{path}': {e}") from e

    if not isinstance(data, list):
        raise ValueError(f"Dataset must be a JSON array, got {type(data).__name__}.")

    if not data:
        raise ValueError("Dataset is empty.")

    return data


def _run_single_cell(
    version: str,
    case: Dict[str, Any],
    raw_prompt: str,
    provider: Any,
    provider_kwargs: Dict[str, Any],
    deterministic: bool,
) -> MatrixCell:
    """Execute one (version, case) combination and return a MatrixCell."""
    case_id = case.get("id", "unnamed")
    input_vars: Dict[str, str] = case.get("input", {})

    # Render template
    try:
        rendered = render_template(raw_prompt, {k: str(v) for k, v in input_vars.items()})
    except Exception as exc:
        return MatrixCell(
            version=version,
            case_id=case_id,
            score=0.0,
            passed=False,
            output="",
            tokens=None,
            latency_ms=0.0,
            error=f"Template error: {exc}",
        )

    # Run provider
    t0 = time.monotonic()
    try:
        result = provider.run(rendered, **provider_kwargs)
        latency_ms = (time.monotonic() - t0) * 1000
    except Exception as exc:
        return MatrixCell(
            version=version,
            case_id=case_id,
            score=0.0,
            passed=False,
            output="",
            tokens=None,
            latency_ms=(time.monotonic() - t0) * 1000,
            error=f"Provider error: {exc}",
        )

    output = result.get("output", "")
    tokens = result.get("tokens")

    # Run assertions / checks / scoring
    try:
        case_result: CaseResult = run_case_assertions(
            case=case,
            output=output,
            tokens=tokens,
            provider=provider,
            deterministic=deterministic,
        )
        score = case_result.score
        passed = case_result.passed
    except Exception:
        score = 1.0 if output else 0.0
        passed = bool(output)

    return MatrixCell(
        version=version,
        case_id=case_id,
        score=score,
        passed=passed,
        output=output,
        tokens=tokens,
        latency_ms=round(latency_ms, 1),
        error=None,
    )


def _compute_version_stats(
    version: str,
    cells: List[MatrixCell],
) -> VersionStats:
    """Compute aggregate statistics for a single version's cells."""
    scores = [c.score for c in cells if c.error is None]
    passed_count = sum(1 for c in cells if c.passed and c.error is None)
    total = len(cells)

    if not scores:
        return VersionStats(
            version=version,
            mean_score=0.0,
            std_dev=0.0,
            pass_rate=0.0,
            total_cases=total,
            passed_cases=0,
            avg_tokens=None,
            avg_latency_ms=0.0,
        )

    mean = sum(scores) / len(scores)
    variance = sum((s - mean) ** 2 for s in scores) / max(len(scores) - 1, 1)
    std_dev = math.sqrt(variance)

    token_counts = [c.tokens for c in cells if c.tokens is not None]
    avg_tokens = sum(token_counts) / len(token_counts) if token_counts else None
    avg_latency = sum(c.latency_ms for c in cells) / max(len(cells), 1)

    return VersionStats(
        version=version,
        mean_score=round(mean, 4),
        std_dev=round(std_dev, 4),
        pass_rate=round(passed_count / total, 4),
        total_cases=total,
        passed_cases=passed_count,
        avg_tokens=round(avg_tokens, 1) if avg_tokens is not None else None,
        avg_latency_ms=round(avg_latency, 1),
    )


def run_matrix_eval(
    config: MatrixConfig,
    provider: Any,
    repo: Any,
) -> MatrixResult:
    """
    Run N versions × M test cases evaluation matrix.

    Args:
        config: MatrixConfig specifying versions, dataset, provider settings.
        provider: A provider instance (must implement run()).
        repo: PromptRepo instance.

    Returns:
        MatrixResult with full N×M grid and aggregate stats.

    Raises:
        ValueError: If dataset is invalid or versions not found.
        FileNotFoundError: If dataset file doesn't exist.
    """
    t_start = time.monotonic()

    dataset = _load_dataset(config.dataset_path)
    case_ids = [case.get("id", f"case-{i+1}") for i, case in enumerate(dataset)]

    provider_kwargs: Dict[str, Any] = {}
    if config.model:
        provider_kwargs["model"] = config.model

    # Determine provider name for reporting
    provider_name = config.provider_name
    if hasattr(provider, "__class__"):
        provider_name = provider.__class__.__name__.replace("Provider", "").lower()

    all_cells: List[MatrixCell] = []

    for version in config.versions:
        # Load prompt for this version
        try:
            raw_prompt = repo.get(config.name, version)
        except Exception as exc:
            # Create error cells for all cases in this version
            for case in dataset:
                case_id = case.get("id", "unnamed")
                all_cells.append(MatrixCell(
                    version=version,
                    case_id=case_id,
                    score=0.0,
                    passed=False,
                    output="",
                    tokens=None,
                    latency_ms=0.0,
                    error=f"Version load error: {exc}",
                ))
            continue

        # Run each test case for this version
        for case in dataset:
            cell = _run_single_cell(
                version=version,
                case=case,
                raw_prompt=raw_prompt,
                provider=provider,
                provider_kwargs=provider_kwargs,
                deterministic=config.deterministic,
            )
            all_cells.append(cell)

            if config.stop_on_error and cell.error:
                break

    # Compute per-version statistics
    version_stats: List[VersionStats] = []
    for version in config.versions:
        v_cells = [c for c in all_cells if c.version == version]
        stats = _compute_version_stats(version, v_cells)
        version_stats.append(stats)

    # Determine winner
    winner: Optional[str] = None
    if version_stats:
        best = max(version_stats, key=lambda s: s.rank_score)
        winner = best.version

    total_duration_ms = round((time.monotonic() - t_start) * 1000, 1)

    return MatrixResult(
        name=config.name,
        versions=config.versions,
        case_ids=case_ids,
        cells=all_cells,
        version_stats=version_stats,
        winner=winner,
        dataset_path=config.dataset_path,
        provider_name=provider_name,
        total_duration_ms=total_duration_ms,
    )


def format_matrix_table(result: MatrixResult, show_outputs: bool = False) -> str:
    """
    Format the matrix result as an ASCII table.

    Rows = test cases, Columns = versions.
    Cell values = score (0.00-1.00), with ✓/✗ pass indicator.

    Example:
        ┌─────────────────┬──────────┬──────────┬──────────┐
        │ Case            │   v1     │   v2     │   v3     │
        ├─────────────────┼──────────┼──────────┼──────────┤
        │ case-01         │ ✓ 1.00   │ ✓ 0.85   │ ✗ 0.30   │
        │ case-02         │ ✓ 0.90   │ ✓ 1.00   │ ✓ 0.95   │
        ├─────────────────┼──────────┼──────────┼──────────┤
        │ Mean Score      │  0.95    │  0.925   │  0.625   │
        │ Pass Rate       │ 100%     │ 100%     │  50%     │
        │ Winner          │ ★        │          │          │
        └─────────────────┴──────────┴──────────┴──────────┘
    """
    versions = result.versions
    case_ids = result.case_ids

    col_w = max(10, max((len(v) + 4 for v in versions), default=10))
    label_w = max(20, max((len(cid) for cid in case_ids), default=20))

    def _sep(left="┌", mid="┬", right="┐", fill="─") -> str:
        cols = mid.join(fill * (col_w + 2) for _ in versions)
        return f"{left}{fill * (label_w + 2)}{mid}{cols}{right}"

    def _row(label: str, cells: List[str]) -> str:
        label_part = f" {label:<{label_w}} "
        cell_parts = " │ ".join(f"{c:^{col_w}}" for c in cells)
        return f"│{label_part}│ {cell_parts} │"

    lines = [_sep("┌", "┬", "┐", "─")]
    lines.append(_row("Case", versions))
    lines.append(_sep("├", "┼", "┤", "─"))

    for case_id in case_ids:
        row_cells = []
        for version in versions:
            cell = result.get_cell(version, case_id)
            if cell is None:
                row_cells.append("  —  ")
            elif cell.error:
                row_cells.append("  ERR")
            else:
                mark = "✓" if cell.passed else "✗"
                row_cells.append(f"{mark} {cell.score:.2f}")
        lines.append(_row(case_id, row_cells))

    lines.append(_sep("├", "┼", "┤", "─"))

    # Summary rows
    mean_cells = []
    pass_cells = []
    lat_cells = []
    winner_cells = []
    for version in versions:
        stats = result.get_stats(version)
        if stats:
            mean_cells.append(f"{stats.mean_score:.3f}")
            pass_cells.append(f"{stats.pass_rate * 100:.0f}%")
            lat_cells.append(f"{stats.avg_latency_ms:.0f}ms")
            winner_cells.append("★ WINNER" if version == result.winner else "")
        else:
            mean_cells.append("—")
            pass_cells.append("—")
            lat_cells.append("—")
            winner_cells.append("")

    lines.append(_row("Mean Score", mean_cells))
    lines.append(_row("Pass Rate", pass_cells))
    lines.append(_row("Avg Latency", lat_cells))
    lines.append(_row("", winner_cells))
    lines.append(_sep("└", "┴", "┘", "─"))

    return "\n".join(lines)


def save_matrix_report(result: MatrixResult, output_path: str) -> None:
    """Save a matrix evaluation report to a JSON file."""
    import os
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    report = {
        "name": result.name,
        "versions": result.versions,
        "case_ids": result.case_ids,
        "winner": result.winner,
        "dataset_path": result.dataset_path,
        "provider": result.provider_name,
        "total_duration_ms": result.total_duration_ms,
        "version_stats": [
            {
                "version": s.version,
                "mean_score": s.mean_score,
                "std_dev": s.std_dev,
                "pass_rate": s.pass_rate,
                "total_cases": s.total_cases,
                "passed_cases": s.passed_cases,
                "avg_tokens": s.avg_tokens,
                "avg_latency_ms": s.avg_latency_ms,
            }
            for s in result.version_stats
        ],
        "cells": [
            {
                "version": c.version,
                "case_id": c.case_id,
                "score": c.score,
                "passed": c.passed,
                "tokens": c.tokens,
                "latency_ms": c.latency_ms,
                "error": c.error,
            }
            for c in result.cells
        ],
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
