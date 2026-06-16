"""
promptrepo/core/analytics.py

Analytics engine for PromptVC.

Computes per-space and global statistics from trace records:
- Total cost, total tokens, run count
- Latency percentiles (p50, p90, p95)
- Per-model usage breakdown
- Per-version score history
- Cost trend over time

Usage:
    from promptrepo.core.analytics import compute_space_analytics, compute_global_analytics
    stats = compute_space_analytics("summarizer", trace_store, storage)
    print(stats.summary())
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from promptrepo.utils.cost import compute_cost_breakdown, format_cost


@dataclass
class LatencyStats:
    """Latency statistics across multiple runs."""
    p50_ms: float
    p90_ms: float
    p95_ms: float
    mean_ms: float
    min_ms: float
    max_ms: float
    sample_count: int


@dataclass
class ModelUsage:
    """Usage stats for a single model."""
    model: str
    run_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_usd: Optional[float]


@dataclass
class VersionAnalytics:
    """Analytics for a single prompt version."""
    version: str
    run_count: int
    avg_score: Optional[float]
    avg_tokens: Optional[float]
    avg_latency_ms: Optional[float]
    total_cost_usd: Optional[float]
    last_run: Optional[str]


@dataclass
class SpaceAnalytics:
    """Full analytics for a prompt space."""
    name: str
    total_runs: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_cost_usd: Optional[float]
    latency: Optional[LatencyStats]
    model_breakdown: List[ModelUsage]
    version_breakdown: List[VersionAnalytics]
    avg_score: Optional[float]
    first_run: Optional[str]
    last_run: Optional[str]

    def summary(self) -> str:
        lines = [
            f"Space: {self.name}",
            f"Total runs    : {self.total_runs}",
            f"Total tokens  : {self.total_tokens:,}",
            f"Total cost    : {format_cost(self.total_cost_usd)}",
        ]
        if self.latency:
            lines.append(f"Latency p50   : {self.latency.p50_ms:.0f}ms")
            lines.append(f"Latency p95   : {self.latency.p95_ms:.0f}ms")
        if self.avg_score is not None:
            lines.append(f"Avg score     : {self.avg_score:.3f}")
        return "\n".join(lines)


@dataclass
class GlobalAnalytics:
    """Aggregate analytics across all prompt spaces."""
    total_spaces: int
    total_versions: int
    total_runs: int
    total_tokens: int
    total_cost_usd: Optional[float]
    top_spaces_by_runs: List[Tuple[str, int]]       # (space_name, run_count)
    top_spaces_by_cost: List[Tuple[str, Optional[float]]]
    model_breakdown: List[ModelUsage]
    avg_latency_ms: Optional[float]
    last_activity: Optional[str]

    def summary(self) -> str:
        lines = [
            f"Total spaces  : {self.total_spaces}",
            f"Total versions: {self.total_versions}",
            f"Total runs    : {self.total_runs}",
            f"Total tokens  : {self.total_tokens:,}",
            f"Total cost    : {format_cost(self.total_cost_usd)}",
        ]
        if self.avg_latency_ms is not None:
            lines.append(f"Avg latency   : {self.avg_latency_ms:.0f}ms")
        return "\n".join(lines)


def _percentile(data: List[float], p: float) -> float:
    """Compute p-th percentile of a sorted list."""
    if not data:
        return 0.0
    idx = (len(data) - 1) * p / 100.0
    lo = int(idx)
    hi = min(lo + 1, len(data) - 1)
    frac = idx - lo
    return data[lo] * (1 - frac) + data[hi] * frac


def _compute_latency_stats(latencies_ms: List[float]) -> Optional[LatencyStats]:
    if not latencies_ms:
        return None
    sorted_lats = sorted(latencies_ms)
    return LatencyStats(
        p50_ms=round(_percentile(sorted_lats, 50), 1),
        p90_ms=round(_percentile(sorted_lats, 90), 1),
        p95_ms=round(_percentile(sorted_lats, 95), 1),
        mean_ms=round(sum(sorted_lats) / len(sorted_lats), 1),
        min_ms=sorted_lats[0],
        max_ms=sorted_lats[-1],
        sample_count=len(sorted_lats),
    )


def _load_traces(root: Path) -> List[Dict[str, Any]]:
    """Load all trace records from traces.jsonl."""
    traces_path = root / "traces.jsonl"
    if not traces_path.exists():
        return []

    records = []
    with open(traces_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    return records


def compute_space_analytics(
    name: str,
    root: Path,
    space_data: Optional[Dict[str, Any]] = None,
) -> SpaceAnalytics:
    """
    Compute full analytics for a single prompt space.

    Args:
        name: Prompt space name.
        root: Path to .promptrepo directory.
        space_data: Pre-loaded space dict (optional, avoids re-reading disk).

    Returns:
        SpaceAnalytics dataclass.
    """
    # Load traces filtered to this space
    all_traces = _load_traces(root)
    traces = [t for t in all_traces if t.get("prompt_name") == name]

    # Load run records from space data as fallback
    run_records: List[Dict[str, Any]] = []
    if space_data:
        run_records = space_data.get("runs", [])

    total_runs = len(traces) or len(run_records)

    # --- Aggregate from traces (preferred — richer data) ---
    model_data: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "run_count": 0, "input_tokens": 0, "output_tokens": 0,
        "tokens": 0, "cost": 0.0, "cost_known": False,
    })
    version_data: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "run_count": 0, "scores": [], "tokens": [], "latencies": [], "cost": 0.0,
        "last_run": None,
    })

    all_latencies: List[float] = []
    all_scores: List[float] = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_tokens = 0
    total_cost: float = 0.0
    cost_known = False
    first_run: Optional[str] = None
    last_run: Optional[str] = None

    for t in traces:
        model = t.get("model", t.get("provider", "unknown"))
        version = t.get("version", "?")
        it = t.get("input_tokens") or 0
        ot = t.get("output_tokens") or 0
        tok = t.get("tokens") or (it + ot)
        lat = t.get("latency_ms", 0.0)
        score = t.get("score")
        ts = t.get("timestamp", "")
        cost_usd = t.get("cost_usd")

        total_input_tokens += it
        total_output_tokens += ot
        total_tokens += tok

        if it > 0 or ot > 0:
            bd = compute_cost_breakdown(model, it, ot)
            if bd.total_cost_usd is not None:
                total_cost += bd.total_cost_usd
                cost_known = True
                model_data[model]["cost"] += bd.total_cost_usd
                model_data[model]["cost_known"] = True

        model_data[model]["run_count"] += 1
        model_data[model]["input_tokens"] += it
        model_data[model]["output_tokens"] += ot
        model_data[model]["tokens"] += tok

        if lat:
            all_latencies.append(lat)
            version_data[version]["latencies"].append(lat)

        if score is not None:
            all_scores.append(float(score))
            version_data[version]["scores"].append(float(score))

        version_data[version]["run_count"] += 1
        if tok:
            version_data[version]["tokens"].append(tok)
        if ts:
            version_data[version]["last_run"] = ts
            if not first_run or ts < first_run:
                first_run = ts
            if not last_run or ts > last_run:
                last_run = ts

    # Fallback to run_records if no traces
    if not traces and run_records:
        for r in run_records:
            tok = r.get("tokens") or 0
            total_tokens += tok

    model_breakdown = [
        ModelUsage(
            model=m,
            run_count=d["run_count"],
            total_input_tokens=d["input_tokens"],
            total_output_tokens=d["output_tokens"],
            total_tokens=d["tokens"],
            total_cost_usd=d["cost"] if d["cost_known"] else None,
        )
        for m, d in sorted(model_data.items(), key=lambda x: -x[1]["run_count"])
    ]

    version_breakdown = [
        VersionAnalytics(
            version=v,
            run_count=d["run_count"],
            avg_score=round(sum(d["scores"]) / len(d["scores"]), 4) if d["scores"] else None,
            avg_tokens=round(sum(d["tokens"]) / len(d["tokens"]), 1) if d["tokens"] else None,
            avg_latency_ms=round(sum(d["latencies"]) / len(d["latencies"]), 1) if d["latencies"] else None,
            total_cost_usd=None,
            last_run=d["last_run"],
        )
        for v, d in sorted(version_data.items())
    ]

    return SpaceAnalytics(
        name=name,
        total_runs=total_runs,
        total_input_tokens=total_input_tokens,
        total_output_tokens=total_output_tokens,
        total_tokens=total_tokens,
        total_cost_usd=total_cost if cost_known else None,
        latency=_compute_latency_stats(all_latencies),
        model_breakdown=model_breakdown,
        version_breakdown=version_breakdown,
        avg_score=round(sum(all_scores) / len(all_scores), 4) if all_scores else None,
        first_run=first_run,
        last_run=last_run,
    )


def compute_global_analytics(
    root: Path,
    storage: Any,
) -> GlobalAnalytics:
    """
    Compute aggregate analytics across all prompt spaces.

    Args:
        root: Path to .promptrepo directory.
        storage: StorageEngine instance.

    Returns:
        GlobalAnalytics dataclass.
    """
    all_traces = _load_traces(root)
    space_names = storage.list_space_names()
    total_versions = 0
    space_run_counts: Dict[str, int] = defaultdict(int)
    space_costs: Dict[str, float] = defaultdict(float)
    space_cost_known: Dict[str, bool] = defaultdict(bool)

    model_data: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "run_count": 0, "input_tokens": 0, "output_tokens": 0,
        "tokens": 0, "cost": 0.0, "cost_known": False,
    })

    all_latencies: List[float] = []
    total_tokens = 0
    total_cost = 0.0
    cost_known_global = False
    last_activity: Optional[str] = None

    for name in space_names:
        try:
            space_data = storage.load_space(name)
            total_versions += len(space_data.get("versions", {}))
        except Exception:
            continue

    for t in all_traces:
        name = t.get("prompt_name", "")
        model = t.get("model", t.get("provider", "unknown"))
        it = t.get("input_tokens") or 0
        ot = t.get("output_tokens") or 0
        tok = t.get("tokens") or (it + ot)
        lat = t.get("latency_ms", 0.0)
        ts = t.get("timestamp", "")

        space_run_counts[name] += 1
        total_tokens += tok

        if it > 0 or ot > 0:
            bd = compute_cost_breakdown(model, it, ot)
            if bd.total_cost_usd is not None:
                total_cost += bd.total_cost_usd
                space_costs[name] += bd.total_cost_usd
                space_cost_known[name] = True
                cost_known_global = True
                model_data[model]["cost"] += bd.total_cost_usd
                model_data[model]["cost_known"] = True

        model_data[model]["run_count"] += 1
        model_data[model]["input_tokens"] += it
        model_data[model]["output_tokens"] += ot
        model_data[model]["tokens"] += tok

        if lat:
            all_latencies.append(lat)

        if ts and (not last_activity or ts > last_activity):
            last_activity = ts

    top_by_runs = sorted(space_run_counts.items(), key=lambda x: -x[1])[:5]
    top_by_cost = sorted(
        [(n, space_costs.get(n)) for n in space_names],
        key=lambda x: -(x[1] or 0.0)
    )[:5]

    model_breakdown = [
        ModelUsage(
            model=m,
            run_count=d["run_count"],
            total_input_tokens=d["input_tokens"],
            total_output_tokens=d["output_tokens"],
            total_tokens=d["tokens"],
            total_cost_usd=d["cost"] if d["cost_known"] else None,
        )
        for m, d in sorted(model_data.items(), key=lambda x: -x[1]["run_count"])
    ]

    avg_latency = round(sum(all_latencies) / len(all_latencies), 1) if all_latencies else None

    return GlobalAnalytics(
        total_spaces=len(space_names),
        total_versions=total_versions,
        total_runs=len(all_traces),
        total_tokens=total_tokens,
        total_cost_usd=total_cost if cost_known_global else None,
        top_spaces_by_runs=top_by_runs,
        top_spaces_by_cost=top_by_cost,
        model_breakdown=model_breakdown,
        avg_latency_ms=avg_latency,
        last_activity=last_activity,
    )
