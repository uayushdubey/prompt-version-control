"""
promptvc/core/pipeline.py

Pipeline loader and executor for `promptvc pipe`.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── Pipeline schema ────────────────────────────────────────────────────────────

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


# ── Loader (JSON or simple dict) ───────────────────────────────────────────────

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


# ── Template interpolation for pipeline vars ───────────────────────────────────

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


# ── Executor ──────────────────────────────────────────────────────────────────

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
    from promptvc.utils.template import render_template

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
