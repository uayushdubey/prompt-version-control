from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CheckResult:
    check_type: str
    passed: bool
    score: float  # 0.0 to 1.0
    message: str
    expected: Optional[Any] = None
    actual: Optional[Any] = None


@dataclass
class ScoreResult:
    score: float  # 0.0 to 1.0
    checks: List[CheckResult]
    method: str  # "rule", "llm", "composite"
    feedback: Optional[str] = None


def _word_similarity(a: str, b: str) -> float:
    """Jaccard similarity on word sets."""
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa and not wb:
        return 1.0
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


class RuleScorer:
    """Evaluate output against check definitions."""

    SUPPORTED_CHECKS = {
        "exact_match",
        "contains",
        "not_contains",
        "regex",
        "starts_with",
        "ends_with",
        "json_valid",
        "max_tokens",
        "min_tokens",
        "max_length",
        "similarity",
    }

    def score(
        self,
        output: str,
        checks: List[Dict[str, Any]],
        tokens: Optional[int] = None,
    ) -> ScoreResult:
        results: List[CheckResult] = []
        if not checks:
            return ScoreResult(score=1.0, checks=[], method="rule")

        total_score = 0.0
        for check in checks:
            ctype = check.get("type", "").lower()
            if ctype not in self.SUPPORTED_CHECKS:
                results.append(
                    CheckResult(
                        check_type=ctype,
                        passed=False,
                        score=0.0,
                        message=f"Unsupported check type: '{ctype}'",
                    )
                )
                continue

            passed = False
            score = 0.0
            msg = ""
            expected = check.get("expected") or check.get("value") or check.get("reference")

            if ctype == "exact_match":
                passed = output == str(expected)
                score = 1.0 if passed else 0.0
                msg = f"Output {'matches' if passed else 'does not match'} expected value"

            elif ctype == "contains":
                passed = str(expected) in output
                score = 1.0 if passed else 0.0
                msg = f"Output {'contains' if passed else 'does not contain'} '{expected}'"

            elif ctype == "not_contains":
                passed = str(expected) not in output
                score = 1.0 if passed else 0.0
                msg = f"Output {'correctly omits' if passed else 'unexpectedly contains'} '{expected}'"

            elif ctype == "regex":
                try:
                    m = re.search(str(expected), output, re.DOTALL)
                    passed = m is not None
                    score = 1.0 if passed else 0.0
                    msg = f"Regex '{expected}' {'matched' if passed else 'did not match'}"
                except re.error as exc:
                    passed = False
                    score = 0.0
                    msg = f"Invalid regex '{expected}': {exc}"

            elif ctype == "starts_with":
                passed = output.strip().startswith(str(expected))
                score = 1.0 if passed else 0.0
                msg = f"Output {'starts with' if passed else 'does not start with'} '{expected}'"

            elif ctype == "ends_with":
                passed = output.strip().endswith(str(expected))
                score = 1.0 if passed else 0.0
                msg = f"Output {'ends with' if passed else 'does not end with'} '{expected}'"

            elif ctype == "json_valid":
                try:
                    json.loads(output)
                    passed = True
                    score = 1.0
                    msg = "Output is valid JSON"
                except json.JSONDecodeError as exc:
                    passed = False
                    score = 0.0
                    msg = f"Output is not valid JSON: {exc}"

            elif ctype == "max_tokens":
                if tokens is None:
                    passed = True
                    score = 1.0
                    msg = "Token count unavailable - skipped"
                else:
                    passed = tokens <= int(expected)
                    score = 1.0 if passed else 0.0
                    msg = f"Tokens {tokens} {'≤' if passed else '>'} max {expected}"

            elif ctype == "min_tokens":
                if tokens is None:
                    passed = True
                    score = 1.0
                    msg = "Token count unavailable - skipped"
                else:
                    passed = tokens >= int(expected)
                    score = 1.0 if passed else 0.0
                    msg = f"Tokens {tokens} {'≥' if passed else '<'} min {expected}"

            elif ctype == "max_length":
                max_len = int(expected)
                passed = len(output) <= max_len
                score = 1.0 if passed else 0.0
                msg = f"Output length {len(output)} {'≤' if passed else '>'} max {max_len}"

            elif ctype == "similarity":
                ref = str(expected)
                threshold = float(check.get("threshold", 0.8))
                sim = _word_similarity(ref, output)
                passed = sim >= threshold
                score = sim
                msg = f"Similarity {sim:.2f} {'≥' if passed else '<'} threshold {threshold}"

            results.append(
                CheckResult(
                    check_type=ctype,
                    passed=passed,
                    score=score,
                    message=msg,
                    expected=expected,
                    actual=output[:120] if ctype in ("exact_match", "contains", "not_contains", "regex", "starts_with", "ends_with", "similarity") else str(tokens if "tokens" in ctype else len(output)),
                )
            )
            total_score += score

        return ScoreResult(
            score=total_score / len(checks),
            checks=results,
            method="rule",
        )


class LLMJudgeScorer:
    """Use an LLM to score output quality against criteria."""

    def score(
        self,
        output: str,
        criteria: str,
        provider: Any = None,
    ) -> ScoreResult:
        if not provider or not criteria:
            return ScoreResult(score=1.0, checks=[], method="llm", feedback="No provider or criteria provided.")

        prompt = f"""You are an expert AI evaluator. Rate the following output based on the criteria provided.

Output to evaluate:
---
{output}
---

Criteria:
{criteria}

Provide your evaluation as a score from 0 to 10 (where 10 is perfect and 0 is completely incorrect), followed by a brief explanation.
Your response MUST start with the score in the format "Score: <number>/10" on the first line.
"""
        try:
            res = provider.run(prompt)
            output_text = res.get("output", "").strip()
            match = re.search(r"Score:\s*(\d+(?:\.\d+)?)\s*(?:/\s*10)?", output_text, re.IGNORECASE)
            if match:
                raw_score = float(match.group(1))
                score = max(0.0, min(1.0, raw_score / 10.0))
                return ScoreResult(
                    score=score,
                    checks=[],
                    method="llm",
                    feedback=output_text,
                )
            else:
                return ScoreResult(
                    score=0.0,
                    checks=[],
                    method="llm",
                    feedback=f"Failed to parse score from response: {output_text}",
                )
        except Exception as e:
            return ScoreResult(
                score=0.0,
                checks=[],
                method="llm",
                feedback=f"LLM Judge call failed: {e}",
            )


class CompositeScorer:
    """Combine rule-based and LLM scores with configurable weights."""

    def score(
        self,
        output: str,
        checks: List[Dict[str, Any]],
        llm_judge_cfg: Optional[Dict[str, Any]] = None,
        provider: Any = None,
        tokens: Optional[int] = None,
        deterministic: bool = False,
    ) -> ScoreResult:
        rule_scorer = RuleScorer()
        rule_res = rule_scorer.score(output, checks, tokens)

        if deterministic or not llm_judge_cfg or not provider:
            return rule_res

        criteria = llm_judge_cfg.get("criteria", "")
        weight = float(llm_judge_cfg.get("weight", 0.3))
        # Ensure weight is within valid bounds
        weight = max(0.0, min(1.0, weight))

        judge_scorer = LLMJudgeScorer()
        llm_res = judge_scorer.score(output, criteria, provider)

        # If LLM Judge failed completely or wasn't run, use rule score
        if "failed" in (llm_res.feedback or "").lower() or llm_res.score == 0.0 and "failed" in (llm_res.feedback or "").lower():
            return rule_res

        composite_score = (rule_res.score * (1.0 - weight)) + (llm_res.score * weight)
        return ScoreResult(
            score=composite_score,
            checks=rule_res.checks,
            method="composite",
            feedback=llm_res.feedback,
        )
