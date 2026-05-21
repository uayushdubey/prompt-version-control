"""
promptvc/core/testing.py

Prompt unit-testing assertion engine.
Zero external dependencies.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Assertion result ───────────────────────────────────────────────────────────

@dataclass
class AssertionResult:
    assertion_type: str
    passed: bool
    message: str
    expected: Optional[str] = None
    actual: Optional[str]   = None


# ── Test case result ───────────────────────────────────────────────────────────

@dataclass
class CaseResult:
    case_id: str
    input_vars: Dict[str, Any]
    output: str
    tokens: Optional[int]
    assertions: List[AssertionResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(a.passed for a in self.assertions)

    @property
    def failed_assertions(self) -> List[AssertionResult]:
        return [a for a in self.assertions if not a.passed]


# ── Similarity helper (for golden comparison) ─────────────────────────────────

def _word_similarity(a: str, b: str) -> float:
    """Jaccard similarity on word sets — fast, no deps."""
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa and not wb:
        return 1.0
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


# ── Assertion engine ───────────────────────────────────────────────────────────

def run_assertion(
    assertion: Dict[str, Any],
    output: str,
    tokens: Optional[int],
    golden_dir: str = ".",
) -> AssertionResult:
    """
    Evaluate a single assertion dict against an LLM output string.

    Supported assertion types:
      contains       value: str
      not_contains   value: str
      regex          value: str  (Python regex)
      starts_with    value: str
      ends_with      value: str
      max_tokens     value: int
      min_tokens     value: int
      json_valid     (no value needed)
      golden         file: str, threshold: float (0–1, default 0.8)
    """
    atype = assertion.get("type", "").lower()
    value = assertion.get("value")

    if atype == "contains":
        passed = str(value) in output
        return AssertionResult(
            assertion_type=atype,
            passed=passed,
            message=f"Output {'contains' if passed else 'does NOT contain'} '{value}'",
            expected=str(value),
            actual=output[:120],
        )

    if atype == "not_contains":
        passed = str(value) not in output
        return AssertionResult(
            assertion_type=atype,
            passed=passed,
            message=f"Output {'correctly omits' if passed else 'unexpectedly contains'} '{value}'",
            expected=f"not '{value}'",
            actual=output[:120],
        )

    if atype == "regex":
        try:
            m = re.search(str(value), output, re.DOTALL)
            passed = m is not None
        except re.error as exc:
            return AssertionResult(
                assertion_type=atype, passed=False,
                message=f"Invalid regex '{value}': {exc}",
            )
        return AssertionResult(
            assertion_type=atype,
            passed=passed,
            message=f"Regex '{value}' {'matched' if passed else 'did NOT match'}",
            expected=str(value),
            actual=output[:120],
        )

    if atype == "starts_with":
        passed = output.strip().startswith(str(value))
        return AssertionResult(
            assertion_type=atype,
            passed=passed,
            message=f"Output {'starts with' if passed else 'does NOT start with'} '{value}'",
        )

    if atype == "ends_with":
        passed = output.strip().endswith(str(value))
        return AssertionResult(
            assertion_type=atype,
            passed=passed,
            message=f"Output {'ends with' if passed else 'does NOT end with'} '{value}'",
        )

    if atype == "max_tokens":
        if tokens is None:
            return AssertionResult(
                assertion_type=atype, passed=True,
                message="Token count not available — skipped",
            )
        passed = tokens <= int(value)
        return AssertionResult(
            assertion_type=atype,
            passed=passed,
            message=f"Tokens {tokens} {'≤' if passed else '>'} max {value}",
            expected=f"≤ {value}",
            actual=str(tokens),
        )

    if atype == "min_tokens":
        if tokens is None:
            return AssertionResult(
                assertion_type=atype, passed=True,
                message="Token count not available — skipped",
            )
        passed = tokens >= int(value)
        return AssertionResult(
            assertion_type=atype,
            passed=passed,
            message=f"Tokens {tokens} {'≥' if passed else '<'} min {value}",
            expected=f"≥ {value}",
            actual=str(tokens),
        )

    if atype == "json_valid":
        try:
            json.loads(output)
            passed = True
            msg = "Output is valid JSON"
        except json.JSONDecodeError as exc:
            passed = False
            msg = f"Output is NOT valid JSON: {exc}"
        return AssertionResult(assertion_type=atype, passed=passed, message=msg)

    if atype == "golden":
        import os
        golden_file = assertion.get("file", "")
        threshold   = float(assertion.get("threshold", 0.8))
        full_path   = os.path.join(golden_dir, golden_file)

        if not os.path.exists(full_path):
            return AssertionResult(
                assertion_type=atype, passed=False,
                message=f"Golden file not found: {full_path}",
            )
        with open(full_path, "r", encoding="utf-8") as f:
            golden_text = f.read()

        sim = _word_similarity(golden_text, output)
        passed = sim >= threshold
        return AssertionResult(
            assertion_type=atype,
            passed=passed,
            message=f"Similarity {sim:.2f} {'≥' if passed else '<'} threshold {threshold}",
            expected=f"≥ {threshold}",
            actual=f"{sim:.2f}",
        )

    return AssertionResult(
        assertion_type=atype, passed=False,
        message=f"Unknown assertion type: '{atype}'",
    )


def run_case_assertions(
    case: Dict[str, Any],
    output: str,
    tokens: Optional[int],
    golden_dir: str = ".",
) -> CaseResult:
    """Run all assertions for a single test case."""
    assertions_cfg = case.get("assertions", [])
    case_id   = case.get("id", "unnamed")
    input_vars = case.get("input", {})

    results = [
        run_assertion(a, output, tokens, golden_dir)
        for a in assertions_cfg
    ]

    return CaseResult(
        case_id=case_id,
        input_vars=input_vars,
        output=output,
        tokens=tokens,
        assertions=results,
    )
