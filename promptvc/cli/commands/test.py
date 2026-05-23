"""
promptvc/cli/commands/test.py

Prompt unit testing CLI — `promptvc test run` and `promptvc test golden`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from promptvc.core.repo import PromptRepo
from promptvc.core.testing import run_case_assertions, CaseResult
from promptvc.utils.config import get_config_value
from promptvc.providers.registry import get_provider

from promptvc.utils.template import render_template
from promptvc.utils.console import (
    safe_print, print_table, print_box, print_error_panel,
    badge, bold, dim, success, warning, spinner,
    _colorize, Color,
)

# ── test run ──────────────────────────────────────────────────────────────────

def test_run_command(args: argparse.Namespace) -> None:
    """Run a test suite against a prompt version."""
    provider_name = (
        getattr(args, "provider", None)
        or get_config_value("provider")
        or "mock"
    )
    provider = get_provider(provider_name)
    model = getattr(args, "model", None) or get_config_value(f"models.{provider_name}")

    provider_kwargs = {}
    if model:
        provider_kwargs["model"] = model

    repo = PromptRepo()

    try:
        prompt_data = repo.get_version_meta(args.name, args.version)
    except Exception:
        print_error_panel(
            f"Prompt '{args.name} @ {args.version}' not found.",
            hint_cmd=f"promptvc log {args.name}",
        )
        sys.exit(1)

    raw_prompt = prompt_data.get("prompt", "")

    # Load test suite
    suite_path = args.suite
    try:
        with open(suite_path, "r", encoding="utf-8") as f:
            suite = json.load(f)
    except Exception as exc:
        print_error_panel(f"Failed to load test suite: {exc}")
        sys.exit(1)

    if not isinstance(suite, list):
        print_error_panel("Test suite must be a JSON array of test case objects.")
        sys.exit(1)

    golden_dir = os.path.dirname(os.path.abspath(suite_path))

    safe_print()
    safe_print(bold(f"  promptvc test  ·  {args.name} @ {args.version}"))
    safe_print(dim(f"  Suite    : {suite_path}  ({len(suite)} cases)"))
    safe_print(dim(f"  Provider : {provider_name}" + (f" / {model}" if model else "")))
    safe_print()

    case_results: list[CaseResult] = []
    failed_count = 0

    for i, case in enumerate(suite, start=1):
        case_id   = case.get("id", f"case-{i}")
        input_vars = case.get("input", {})

        # Render prompt
        try:
            rendered = render_template(raw_prompt, input_vars)
        except Exception as exc:
            safe_print(warning(f"  ⚠  {case_id}: template error — {exc}"))
            continue

        # Run
        try:
            with spinner(f"  [{i}/{len(suite)}] {case_id}…"):
                result = provider.run(rendered, **provider_kwargs)
        except Exception as exc:
            safe_print(warning(f"  ✗  {case_id}: provider failed — {exc}"))
            continue

        output = result.get("output") or ""
        tokens = result.get("tokens")

        deterministic = getattr(args, "deterministic", False)
        cr = run_case_assertions(
            case,
            output,
            tokens,
            golden_dir,
            provider=provider,
            deterministic=deterministic,
        )
        case_results.append(cr)

        if cr.passed:
            safe_print(_colorize(f"  ✓  {case_id}  (Score: {cr.score:.2f})", Color.BOLD_GREEN))
        else:
            failed_count += 1
            safe_print(_colorize(f"  ✗  {case_id}  (Score: {cr.score:.2f})", Color.BOLD_RED))
            for a in cr.failed_assertions:
                safe_print(dim(f"       [assertion: {a.assertion_type}] {a.message}"))
                if a.expected:
                    safe_print(dim(f"         expected: {a.expected}"))
                if a.actual:
                    safe_print(dim(f"         actual  : {a.actual}"))
            for c in cr.failed_checks:
                safe_print(dim(f"       [check: {c.check_type}] {c.message}"))
                if c.expected:
                    safe_print(dim(f"         expected: {c.expected}"))
                if c.actual:
                    safe_print(dim(f"         actual  : {c.actual}"))
            if cr.score_feedback:
                safe_print(dim(f"       [feedback] {cr.score_feedback.strip()}"))

    # ── Summary ────────────────────────────────────────────────────────────────
    safe_print()
    total_assertions = sum(len(cr.assertions) for cr in case_results)
    passed_assertions = sum(
        sum(1 for a in cr.assertions if a.passed) for cr in case_results
    )
    total_checks = sum(len(cr.checks) for cr in case_results)
    passed_checks = sum(
        sum(1 for c in cr.checks if c.passed) for cr in case_results
    )
    passed_cases  = sum(1 for cr in case_results if cr.passed)
    total_cases   = len(case_results)
    avg_score     = sum(cr.score for cr in case_results) / total_cases if total_cases > 0 else 0.0

    headers = ["Case", "Assertions", "Checks", "Score", "Result"]
    rows = []
    for cr in case_results:
        total_a  = len(cr.assertions)
        passed_a = sum(1 for a in cr.assertions if a.passed)
        total_c  = len(cr.checks)
        passed_c = sum(1 for c in cr.checks if c.passed)
        result_label = (
            _colorize("PASS", Color.BOLD_GREEN)
            if cr.passed
            else _colorize("FAIL", Color.BOLD_RED)
        )
        rows.append([
            cr.case_id,
            f"{passed_a}/{total_a}",
            f"{passed_c}/{total_c}",
            f"{cr.score:.2f}",
            result_label
        ])

    print_table(headers, rows, title="Test Results")

    summary_lines = [
        badge("Cases     ", f"{passed_cases}/{total_cases} passed"),
        badge("Assertions", f"{passed_assertions}/{total_assertions} passed"),
        badge("Checks    ", f"{passed_checks}/{total_checks} passed"),
        badge("Avg Score ", f"{avg_score:.2f}"),
    ]
    
    threshold = getattr(args, "threshold", None)
    if threshold is not None:
        threshold = float(threshold)

    failed = False
    fail_reasons = []

    if passed_cases < total_cases:
        failed = True
        fail_reasons.append(f"{total_cases - passed_cases} case(s) failed assertions or checks")

    if threshold is not None and avg_score < threshold:
        failed = True
        fail_reasons.append(f"Average score {avg_score:.2f} is below threshold {threshold:.2f}")

    safe_print()
    if not failed:
        print_box("All tests passed ✓", summary_lines)
        safe_print(success("\n✓ Test suite complete"))
    else:
        print_box("Test suite failed", summary_lines, color=Color.BOLD_RED)
        for reason in fail_reasons:
            safe_print(_colorize(f"\n✗ {reason}", Color.BOLD_RED))
        sys.exit(1)


# ── test golden ───────────────────────────────────────────────────────────────

def test_golden_command(args: argparse.Namespace) -> None:
    """Update golden files from current model output."""
    provider_name = (
        getattr(args, "provider", None)
        or get_config_value("provider")
        or "mock"
    )
    provider = get_provider(provider_name)
    model = getattr(args, "model", None) or get_config_value(f"models.{provider_name}")

    provider_kwargs = {}
    if model:
        provider_kwargs["model"] = model

    repo = PromptRepo()
    try:
        prompt_data = repo.get_version_meta(args.name, args.version)
    except Exception:
        print_error_panel(f"Prompt '{args.name} @ {args.version}' not found.")
        sys.exit(1)

    raw_prompt = prompt_data.get("prompt", "")

    suite_path = args.suite
    try:
        with open(suite_path, "r", encoding="utf-8") as f:
            suite = json.load(f)
    except Exception as exc:
        print_error_panel(f"Failed to load test suite: {exc}")
        sys.exit(1)

    golden_dir = os.path.dirname(os.path.abspath(suite_path))
    updated = 0

    safe_print()
    safe_print(bold(f"  Updating golden files for {args.name} @ {args.version}"))
    safe_print()

    for i, case in enumerate(suite, start=1):
        case_id    = case.get("id", f"case-{i}")
        input_vars = case.get("input", {})

        # Find golden assertions
        golden_assertions = [
            a for a in case.get("assertions", [])
            if a.get("type") == "golden" and a.get("file")
        ]
        if not golden_assertions:
            continue

        try:
            rendered = render_template(raw_prompt, input_vars)
        except Exception as exc:
            safe_print(warning(f"  ⚠  {case_id}: template error — {exc}"))
            continue

        try:
            with spinner(f"  [{i}/{len(suite)}] Running {case_id}…"):
                result = provider.run(rendered, **provider_kwargs)
        except Exception as exc:
            safe_print(warning(f"  ✗  {case_id}: failed — {exc}"))
            continue

        output = result.get("output") or ""

        for ga in golden_assertions:
            golden_file = os.path.join(golden_dir, ga["file"])
            os.makedirs(os.path.dirname(golden_file), exist_ok=True)
            with open(golden_file, "w", encoding="utf-8") as f:
                f.write(output)
            safe_print(success(f"  ✓  Updated: {ga['file']}"))
            updated += 1

    safe_print()
    safe_print(success(f"✓ {updated} golden file(s) updated"))


# ── test list ─────────────────────────────────────────────────────────────────

def test_list_command(args: argparse.Namespace) -> None:
    """List all .json test suites in the current directory tree."""
    import glob
    pattern = getattr(args, "dir", ".") + "/**/*.json"
    files   = glob.glob(pattern, recursive=True)
    suites  = []

    for f in sorted(files):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list) and data and isinstance(data[0], dict):
                has_assertions = any("assertions" in c for c in data)
                if has_assertions:
                    suites.append((f, str(len(data))))
        except Exception:
            pass

    if not suites:
        safe_print(dim("  No test suites found."))
        return

    safe_print()
    print_table(["Suite File", "Cases"], suites, title="Test Suites")


# ── Dispatcher ────────────────────────────────────────────────────────────────

def test_command(args: argparse.Namespace) -> None:
    sub = getattr(args, "test_subcommand", None)
    if sub == "run":
        test_run_command(args)
    elif sub == "golden":
        test_golden_command(args)
    elif sub == "list":
        test_list_command(args)
    else:
        print_error_panel(
            "Unknown test subcommand.",
            tips=["Usage: promptvc test run <name> <version> --suite <file>",
                  "       promptvc test golden <name> <version> --suite <file>",
                  "       promptvc test list"],
        )
        sys.exit(1)
