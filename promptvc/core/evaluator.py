from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from promptvc.core.scorer import CompositeScorer, RuleScorer
from promptvc.utils.template import render_template

# ── Assertion & Testing classes (from testing.py) ───────────────────────────────────

@dataclass
class AssertionResult:
    assertion_type: str
    passed: bool
    message: str
    expected: Optional[str] = None
    actual: Optional[str]   = None


@dataclass
class CaseResult:
    case_id: str
    input_vars: Dict[str, Any]
    output: str
    tokens: Optional[int]
    assertions: List[AssertionResult] = field(default_factory=list)
    score: float = 1.0
    checks: List[Any] = field(default_factory=list)
    score_feedback: Optional[str] = None

    @property
    def passed(self) -> bool:
        assertions_passed = all(a.passed for a in self.assertions)
        checks_passed = all(c.passed for c in self.checks)
        return assertions_passed and checks_passed

    @property
    def failed_assertions(self) -> List[AssertionResult]:
        return [a for a in self.assertions if not a.passed]

    @property
    def failed_checks(self) -> List[Any]:
        return [c for c in self.checks if not c.passed]


def _word_similarity(a: str, b: str) -> float:
    """Jaccard similarity on word sets — fast, no deps."""
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa and not wb:
        return 1.0
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


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

    import warnings
    warnings.warn(f"Unknown assertion type '{atype}' - skipping.")
    return AssertionResult(
        assertion_type=atype, passed=True,
        message=f"Unknown assertion type '{atype}' was skipped",
    )


def run_case_assertions(
    case: Dict[str, Any],
    output: str,
    tokens: Optional[int],
    golden_dir: str = ".",
    provider: Any = None,
    deterministic: bool = False,
) -> CaseResult:
    """Run all assertions and checks/llm judge for a single test case."""
    assertions_cfg = case.get("assertions", [])
    case_id   = case.get("id", "unnamed")
    input_vars = case.get("input", {})

    results = [
        run_assertion(a, output, tokens, golden_dir)
        for a in assertions_cfg
    ]

    checks_cfg = case.get("checks", [])
    llm_judge_cfg = case.get("llm_judge")

    scorer = CompositeScorer()
    score_res = scorer.score(
        output=output,
        checks=checks_cfg,
        llm_judge_cfg=llm_judge_cfg,
        provider=provider,
        tokens=tokens,
        deterministic=deterministic,
    )

    if checks_cfg or llm_judge_cfg:
        score = score_res.score
    else:
        # Fallback to assertions
        if not assertions_cfg:
            score = 1.0
        else:
            passed_count = sum(1 for r in results if r.passed)
            score = passed_count / len(assertions_cfg)

    return CaseResult(
        case_id=case_id,
        input_vars=input_vars,
        output=output,
        tokens=tokens,
        assertions=results,
        score=score,
        checks=score_res.checks,
        score_feedback=score_res.feedback,
    )


# ── Pipeline classes & executor (from pipeline.py) ───────────────────────────────────

@dataclass
class PipelineStep:
    id: str
    prompt_name: str
    version: str
    vars: Dict[str, str] = field(default_factory=dict)
    provider: Optional[str] = None
    model: Optional[str] = None


@dataclass
class Pipeline:
    name: str
    steps: List[PipelineStep]
    description: str = ""


def load_pipeline(path: str) -> Pipeline:
    """Load a pipeline definition from a JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("Pipeline file must be a JSON object.")

    name        = data.get("name", "pipeline")
    description = data.get("description", "")
    steps_raw   = data.get("steps", [])

    if not steps_raw:
        raise ValueError("Pipeline must have at least one step.")

    steps: List[PipelineStep] = []
    for i, s in enumerate(steps_raw, 1):
        if not isinstance(s, dict):
            raise ValueError(f"Step {i} must be a JSON object.")
        step_id = s.get("id") or f"step{i}"
        pname   = s.get("prompt")
        ver     = s.get("version")
        if not pname or not ver:
            raise ValueError(f"Step '{step_id}' must have 'prompt' and 'version' fields.")
        steps.append(PipelineStep(
            id           = step_id,
            prompt_name  = pname,
            version      = ver,
            vars         = s.get("vars", {}),
            provider     = s.get("provider"),
            model        = s.get("model"),
        ))

    return Pipeline(name=name, steps=steps, description=description)


def validate_pipeline(pipeline: Pipeline) -> List[str]:
    """Return a list of validation errors (empty = valid)."""
    errors: List[str] = []
    seen_ids = set()
    for step in pipeline.steps:
        if step.id in seen_ids:
            errors.append(f"Duplicate step id: '{step.id}'")
        seen_ids.add(step.id)
    return errors


_PIPE_VAR_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def _resolve_value(
    expr: str,
    global_vars: Dict[str, Any],
    step_outputs: Dict[str, str],
) -> str:
    """
    Resolve {{ input.key }} and {{ steps.stepid.output }} references.
    Leaves unknown references as-is.
    """
    def _sub(m: re.Match) -> str:
        key = m.group(1)
        parts = key.split(".")

        if parts[0] == "input" and len(parts) >= 2:
            return str(global_vars.get(parts[1], m.group(0)))

        if parts[0] == "steps" and len(parts) >= 3:
            step_id = parts[1]
            field   = parts[2]
            if step_id in step_outputs and field == "output":
                return step_outputs[step_id]
            return m.group(0)

        # Flat key reference
        return str(global_vars.get(key, m.group(0)))

    return _PIPE_VAR_RE.sub(_sub, expr)


def _resolve_step_vars(
    step: PipelineStep,
    global_vars: Dict[str, Any],
    step_outputs: Dict[str, str],
) -> Dict[str, str]:
    resolved: Dict[str, str] = {}
    for k, v in step.vars.items():
        resolved[k] = _resolve_value(v, global_vars, step_outputs)
    return resolved


@dataclass
class StepResult:
    step_id: str
    output: str
    tokens: Optional[int]
    latency_ms: float
    model_used: Optional[str]
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def execute_pipeline(
    pipeline: Pipeline,
    global_vars: Dict[str, Any],
    repo: Any,
    default_provider_name: str = "mock",
    default_model: Optional[str] = None,
    get_provider_fn: Any = None,
    get_config_fn: Any = None,
) -> List[StepResult]:
    """
    Execute all steps in a pipeline sequentially.
    Outputs from each step are available to subsequent steps.
    """
    step_outputs: Dict[str, str] = {}
    results: List[StepResult] = []

    for step in pipeline.steps:
        # Resolve provider
        provider_name = (
            step.provider
            or (get_config_fn("provider") if get_config_fn else None)
            or default_provider_name
        )
        model = (
            step.model
            or default_model
            or (get_config_fn(f"models.{provider_name}") if get_config_fn else None)
        )

        try:
            provider = get_provider_fn(provider_name)
        except Exception as exc:
            results.append(StepResult(
                step_id=step.id, output="", tokens=None,
                latency_ms=0, model_used=None,
                error=f"Provider error: {exc}",
            ))
            break  # stop on provider failure

        # Load prompt
        try:
            prompt_data = repo.get_version_meta(step.prompt_name, step.version)
            raw_prompt  = prompt_data.get("prompt", "")
        except Exception as exc:
            results.append(StepResult(
                step_id=step.id, output="", tokens=None,
                latency_ms=0, model_used=None,
                error=f"Prompt load error: {exc}",
            ))
            break

        # Resolve step vars
        resolved_vars = _resolve_step_vars(step, global_vars, step_outputs)
        # Merge global vars for simple {{key}} references
        all_vars = {**global_vars, **resolved_vars}

        try:
            rendered = render_template(raw_prompt, all_vars)
        except Exception as exc:
            results.append(StepResult(
                step_id=step.id, output="", tokens=None,
                latency_ms=0, model_used=None,
                error=f"Template error: {exc}",
            ))
            break

        # Execute
        kwargs: Dict[str, Any] = {}
        if model:
            kwargs["model"] = model

        t0 = time.monotonic()
        try:
            result = provider.run(rendered, **kwargs)
        except Exception as exc:
            results.append(StepResult(
                step_id=step.id, output="", tokens=None,
                latency_ms=round((time.monotonic() - t0) * 1000),
                model_used=model,
                error=f"Provider failed: {exc}",
            ))
            break

        latency_ms = (time.monotonic() - t0) * 1000
        output = result.get("output") or ""
        tokens = result.get("tokens")
        actual_model = result.get("model_used") or model or provider_name

        step_outputs[step.id] = output

        results.append(StepResult(
            step_id    = step.id,
            output     = output,
            tokens     = tokens,
            latency_ms = round(latency_ms),
            model_used = actual_model,
        ))

    return results


# ── Dataset Evaluation (from eval.py) ──────────────────────────────────────────────────

def run_evaluation(
    repo,
    name: str,
    version: str,
    dataset_path: str,
    provider,
) -> dict:
    try:
        with open(dataset_path, "r", encoding="utf-8") as f:
            dataset = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in dataset file '{dataset_path}': {e}") from e

    if not isinstance(dataset, list):
        raise ValueError(
            f"Dataset must be a JSON array, got {type(dataset).__name__}."
        )

    prompt_text = repo.get(name, version)

    results = []
    for index, item in enumerate(dataset):
        if not isinstance(item, dict) or "input" not in item:
            raise ValueError(
                f"Dataset item at index {index} is missing required 'input' field."
            )

        input_text = item["input"]
        full_prompt = f"{prompt_text}\n\n{input_text}"
        result = provider.run(full_prompt)

        output = result.get("output")
        if output is None:
            raise ValueError(
                f"Provider returned no output for dataset item at index {index}."
            )

        results.append(
            {
                "input": input_text,
                "output": output,
                "tokens": result.get("tokens"),
            }
        )

    return {
        "version": version,
        "dataset": dataset_path,
        "results": results,
    }
