"""
promptvc/cli/commands/status.py

`promptvc status` — workspace at-a-glance overview.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from promptvc.core.repo import PromptRepo
from promptvc.utils.config import get_config_value
from promptvc.utils.console import (
    safe_print, print_table, print_box,
    badge, bold, dim, success, warning, _colorize, Color,
)


def _time_ago(ts: str) -> str:
    """Return a human-readable relative timestamp."""
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = now - dt
        secs = int(diff.total_seconds())
        if secs < 60:
            return f"{secs}s ago"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return ts.split("T")[0]


def status_command(args: argparse.Namespace) -> None:
    repo   = PromptRepo()
    spaces = repo.list_spaces()

    provider = get_config_value("provider") or "mock"
    model    = get_config_value(f"models.{provider}") or "—"

    cwd = os.path.basename(os.getcwd())

    # ── Collect activity ──────────────────────────────────────────────────────
    recent_activity: list[tuple[str, str, str, str]] = []
    total_spaces  = len(spaces)
    total_versions = 0
    total_runs    = 0

    for space_name in spaces:
        try:
            space_data = repo.storage.load_space(space_name)
        except Exception:
            continue

        versions = space_data.get("versions", {})
        total_versions += len(versions)

        runs = space_data.get("runs", [])
        total_runs += len(runs)
        if runs:
            last_run = runs[-1]
            recent_activity.append((
                space_name,
                last_run.get("version", "?"),
                "run",
                last_run.get("timestamp", ""),
            ))

        evals = space_data.get("evaluations", [])
        if evals:
            last_eval = evals[-1]
            recent_activity.append((
                space_name,
                last_eval.get("version", "?"),
                "eval",
                last_eval.get("timestamp", ""),
            ))

        changes = space_data.get("file_changes", [])
        if changes:
            last_change = changes[-1]
            recent_activity.append((
                space_name,
                last_change.get("version", "?"),
                "apply",
                last_change.get("timestamp", ""),
            ))

    # Sort by most recent
    recent_activity.sort(key=lambda x: x[3], reverse=True)
    recent_activity = recent_activity[:8]

    # ── Output ────────────────────────────────────────────────────────────────
    safe_print()
    summary_lines = [
        badge("Workspace", cwd),
        badge("Provider ", f"{provider} / {model}"),
        badge("Spaces   ", str(total_spaces)),
        badge("Versions ", str(total_versions)),
        badge("Runs     ", str(total_runs)),
    ]
    print_box("promptvc status", summary_lines)

    if spaces:
        safe_print()
        safe_print(bold("  Spaces"))
        space_rows = []
        for name in sorted(spaces):
            try:
                data = repo.storage.load_space(name)
                latest = data.get("latest", "—")
                ver_count = len(data.get("versions", {}))
                run_count = len(data.get("runs", []))
                space_rows.append([name, latest, str(ver_count), str(run_count)])
            except Exception:
                space_rows.append([name, "—", "—", "—"])
        print_table(["Space", "Latest", "Versions", "Runs"], space_rows)

    if recent_activity:
        safe_print()
        safe_print(bold("  Recent Activity"))
        activity_rows = []
        for (name, ver, action, ts) in recent_activity:
            action_colored = {
                "run":   _colorize("run",   Color.CYAN),
                "eval":  _colorize("eval",  Color.MAGENTA),
                "apply": _colorize("apply", Color.YELLOW),
            }.get(action, action)
            activity_rows.append([name, ver, action_colored, _time_ago(ts)])
        print_table(["Space", "Version", "Action", "When"], activity_rows)

    safe_print()
