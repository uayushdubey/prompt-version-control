"""
promptrepo/sdk.py

Production-grade Python SDK for PromptVC.

Provides convenient developer-facing wrappers for using versioned prompts
directly in application code without writing CLI commands.

Quick Start:
    import promptrepo

    # Decorator: wrap a function to be powered by a versioned prompt
    @promptrepo.prompt("summarizer", version="latest", provider="openai")
    def summarize(text: str) -> str:
        \"\"\"This docstring is ignored — the prompt is used instead.\"\"\"

    result = summarize(text="The quick brown fox...")
    print(result.output)
    print(result.cost)       # CostBreakdown
    print(result.tokens)     # int
    print(result.latency_ms) # float

    # Context manager: full control with auto-tracing
    with promptrepo.run_context("classifier", "v2", provider="gemini") as ctx:
        result = ctx.run(category="food")
        print(ctx.cost)

    # Batch runner: parallel execution over a list of inputs
    results = promptrepo.batch_run(
        "summarizer", "v1",
        inputs=[{"text": "..."}, {"text": "..."}],
        provider="openai",
        max_workers=4,
    )
"""
from __future__ import annotations

import functools
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, TypeVar, Union

from promptrepo.core.repo import PromptRepo
from promptrepo.providers import get_provider
from promptrepo.utils.cost import compute_cost_breakdown, format_cost, CostBreakdown
from promptrepo.utils.template import render_template
from promptrepo.core.prompt_format import render_prompt


F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class RunResult:
    """
    Result of a single prompt run via the SDK.

    Attributes:
        output:      Generated text from the LLM.
        tokens:      Total token count (input + output).
        input_tokens: Prompt token count.
        output_tokens: Completion token count.
        latency_ms:  Wall-clock time for the API call in milliseconds.
        cost:        Full cost breakdown (or None if model unknown).
        model:       Model ID actually used.
        trace_id:    Unique identifier for this run.
        prompt_name: Prompt space name.
        version:     Prompt version used.
        variables:   Template variables that were substituted.
    """
    output: str
    tokens: Optional[int]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    latency_ms: float
    cost: Optional[CostBreakdown]
    model: str
    trace_id: str
    prompt_name: str
    version: str
    variables: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def cost_usd(self) -> Optional[float]:
        """Convenience: total cost in USD."""
        return self.cost.total_cost_usd if self.cost else None

    @property
    def ok(self) -> bool:
        """True if the run completed without error."""
        return self.error is None


@dataclass
class BatchResult:
    """Result of a batch_run() call."""
    results: List[RunResult]
    total_tokens: int
    total_cost_usd: Optional[float]
    total_latency_ms: float
    success_count: int
    error_count: int

    @property
    def success_rate(self) -> float:
        total = len(self.results)
        return self.success_count / total if total else 0.0


def _resolve_repo(root: Optional[str] = None) -> PromptRepo:
    """Create or load a PromptRepo instance."""
    repo = PromptRepo()
    if not repo.storage.is_initialized:
        raise RuntimeError(
            "PromptVC repository not initialized. "
            "Run `promptrepo init` or PromptRepo().init_repo() first."
        )
    return repo


def _resolve_version(repo: PromptRepo, name: str, version: str) -> str:
    """Resolve 'latest' version alias to the actual version ID."""
    if version.lower() == "latest":
        try:
            meta = repo.latest(name)
            return meta["id"]
        except Exception:
            return version
    return version


def _execute_run(
    repo: PromptRepo,
    name: str,
    version: str,
    variables: Dict[str, str],
    provider_name: str,
    provider_kwargs: Dict[str, Any],
) -> RunResult:
    """Core execution logic shared by decorator, context manager, and batch runner."""

    trace_id = str(uuid.uuid4())
    resolved_version = _resolve_version(repo, name, version)

    try:
        version_meta = repo.get_version_meta(name, resolved_version)
        raw_prompt = version_meta.get("prompt", "")
        fmt = version_meta.get("format", "raw")
    except Exception as e:
        return RunResult(
            output="", tokens=None, input_tokens=None, output_tokens=None,
            latency_ms=0.0, cost=None, model=provider_name,
            trace_id=trace_id, prompt_name=name, version=resolved_version,
            variables=variables, error=f"Prompt load error: {e}",
        )

    try:
        rendered = render_prompt(raw_prompt, {k: str(v) for k, v in variables.items()}, fmt)
    except Exception as e:
        return RunResult(
            output="", tokens=None, input_tokens=None, output_tokens=None,
            latency_ms=0.0, cost=None, model=provider_name,
            trace_id=trace_id, prompt_name=name, version=resolved_version,
            variables=variables, error=f"Template error: {e}",
        )

    try:
        provider = get_provider(provider_name)
    except Exception as e:
        return RunResult(
            output="", tokens=None, input_tokens=None, output_tokens=None,
            latency_ms=0.0, cost=None, model=provider_name,
            trace_id=trace_id, prompt_name=name, version=resolved_version,
            variables=variables, error=f"Provider error: {e}",
        )

    provider_kwargs_copy = dict(provider_kwargs)
    if isinstance(rendered, list):
        provider_kwargs_copy["messages"] = rendered
        prompt_param = ""
    else:
        prompt_param = rendered

    t0 = time.monotonic()
    try:
        result = provider.run(prompt_param, **provider_kwargs_copy)
        latency_ms = round((time.monotonic() - t0) * 1000, 1)
    except Exception as e:
        return RunResult(
            output="", tokens=None, input_tokens=None, output_tokens=None,
            latency_ms=round((time.monotonic() - t0) * 1000, 1),
            cost=None, model=provider_name,
            trace_id=trace_id, prompt_name=name, version=resolved_version,
            variables=variables, error=f"Provider run failed: {e}",
        )

    output = result.get("output", "")
    tokens = result.get("tokens")
    input_tokens = result.get("input_tokens")
    output_tokens = result.get("output_tokens")
    model_used = result.get("model_used", provider_name)

    cost: Optional[CostBreakdown] = None
    if model_used and input_tokens is not None and output_tokens is not None:
        cost = compute_cost_breakdown(model_used, input_tokens, output_tokens)

    return RunResult(
        output=output,
        tokens=tokens,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        cost=cost,
        model=model_used,
        trace_id=trace_id,
        prompt_name=name,
        version=resolved_version,
        variables=variables,
    )


class RunContext:
    """
    Context manager for a prompt run with automatic cost and latency tracking.

    Usage:
        with promptrepo.run_context("summarizer", "v2", provider="openai") as ctx:
            result = ctx.run(text="Hello world")
            print(ctx.cost)
            print(ctx.latency_ms)
    """

    def __init__(
        self,
        name: str,
        version: str,
        provider: str = "mock",
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
    ):
        self.name = name
        self.version = version
        self._provider_name = provider
        self._provider_kwargs: Dict[str, Any] = {}
        if model:
            self._provider_kwargs["model"] = model
        if system_prompt:
            self._provider_kwargs["system_prompt"] = system_prompt
        if temperature is not None:
            self._provider_kwargs["temperature"] = temperature

        self._repo: Optional[PromptRepo] = None
        self._last_result: Optional[RunResult] = None

    def __enter__(self) -> "RunContext":
        self._repo = _resolve_repo()
        return self

    def __exit__(self, *args) -> None:
        pass  # Cleanup if needed

    def run(self, **variables) -> RunResult:
        """Execute the prompt with the given template variables."""
        if self._repo is None:
            raise RuntimeError("RunContext must be used as a context manager.")

        result = _execute_run(
            repo=self._repo,
            name=self.name,
            version=self.version,
            variables=variables,
            provider_name=self._provider_name,
            provider_kwargs=self._provider_kwargs,
        )
        self._last_result = result
        return result

    @property
    def cost(self) -> Optional[CostBreakdown]:
        """Cost breakdown of the last run."""
        return self._last_result.cost if self._last_result else None

    @property
    def latency_ms(self) -> float:
        """Latency of the last run in milliseconds."""
        return self._last_result.latency_ms if self._last_result else 0.0

    @property
    def output(self) -> str:
        """Output text of the last run."""
        return self._last_result.output if self._last_result else ""


class PromptDecorator:
    """
    Decorator factory that wraps a function to run a versioned prompt.

    The decorated function's keyword arguments are used as template variables.

    Usage:
        @promptrepo.prompt("summarizer", version="v2", provider="openai")
        def summarize(text: str) -> RunResult: ...

        result = summarize(text="Hello world!")
        print(result.output)
        print(result.cost_usd)
    """

    def __init__(
        self,
        name: str,
        version: str = "latest",
        provider: str = "mock",
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
    ):
        self.name = name
        self.version = version
        self._provider_name = provider
        self._provider_kwargs: Dict[str, Any] = {}
        if model:
            self._provider_kwargs["model"] = model
        if system_prompt:
            self._provider_kwargs["system_prompt"] = system_prompt
        if temperature is not None:
            self._provider_kwargs["temperature"] = temperature

    def __call__(self, func: F) -> Callable[..., RunResult]:
        decorator = self

        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> RunResult:
            repo = _resolve_repo()
            return _execute_run(
                repo=repo,
                name=decorator.name,
                version=decorator.version,
                variables={k: str(v) for k, v in kwargs.items()},
                provider_name=decorator._provider_name,
                provider_kwargs=decorator._provider_kwargs,
            )

        # Attach metadata for introspection
        wrapper.prompt_name = self.name  # type: ignore[attr-defined]
        wrapper.prompt_version = self.version  # type: ignore[attr-defined]
        wrapper.provider = self._provider_name  # type: ignore[attr-defined]
        return wrapper


def prompt(
    name: str,
    version: str = "latest",
    provider: str = "mock",
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    temperature: Optional[float] = None,
) -> PromptDecorator:
    """
    Decorator: run a versioned prompt when the decorated function is called.

    Args:
        name:          Prompt space name in the repository.
        version:       Version to use. Default: "latest".
        provider:      LLM provider name. Default: "mock".
        model:         Override model within the provider.
        system_prompt: Inject a system message.
        temperature:   Sampling temperature.

    Returns:
        A decorator that wraps any function.

    Example:
        @promptrepo.prompt("summarizer", version="v3", provider="openai")
        def summarize(text: str) -> RunResult: ...
    """
    return PromptDecorator(
        name=name,
        version=version,
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        temperature=temperature,
    )


def run_context(
    name: str,
    version: str = "latest",
    provider: str = "mock",
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    temperature: Optional[float] = None,
) -> RunContext:
    """
    Create a RunContext for use as a `with` statement.

    Example:
        with promptrepo.run_context("classifier", "v2", provider="gemini") as ctx:
            result = ctx.run(category="food")
            print(ctx.cost)
    """
    return RunContext(
        name=name,
        version=version,
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        temperature=temperature,
    )


def run(
    name: str,
    version: str = "latest",
    provider: str = "mock",
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    temperature: Optional[float] = None,
    **variables,
) -> RunResult:
    """
    Single-shot prompt execution.

    Args:
        name:       Prompt space name.
        version:    Version to use. Default: "latest".
        provider:   LLM provider name. Default: "mock".
        model:      Override model.
        system_prompt: System message.
        temperature: Sampling temperature.
        **variables: Template variables to inject into the prompt.

    Returns:
        RunResult with output, tokens, cost, latency.

    Example:
        result = promptrepo.run("summarizer", "v2", provider="openai", text="Hello world")
        print(result.output)
    """
    repo = _resolve_repo()
    kwargs: Dict[str, Any] = {}
    if model:
        kwargs["model"] = model
    if system_prompt:
        kwargs["system_prompt"] = system_prompt
    if temperature is not None:
        kwargs["temperature"] = temperature

    return _execute_run(
        repo=repo,
        name=name,
        version=version,
        variables={k: str(v) for k, v in variables.items()},
        provider_name=provider,
        provider_kwargs=kwargs,
    )


def batch_run(
    name: str,
    version: str = "latest",
    inputs: Optional[List[Dict[str, str]]] = None,
    provider: str = "mock",
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    temperature: Optional[float] = None,
    max_workers: int = 4,
) -> BatchResult:
    """
    Execute a prompt over multiple inputs in parallel.

    Args:
        name:        Prompt space name.
        version:     Version to use.
        inputs:      List of variable dicts, one per run.
        provider:    LLM provider name.
        model:       Override model.
        system_prompt: System message for all runs.
        temperature: Sampling temperature.
        max_workers: Number of parallel threads. Default: 4.

    Returns:
        BatchResult with all RunResults and aggregate stats.

    Example:
        results = promptrepo.batch_run(
            "summarizer", "v1",
            inputs=[{"text": "A"}, {"text": "B"}, {"text": "C"}],
            provider="openai",
            max_workers=3,
        )
        for r in results.results:
            print(r.output)
        print(f"Total cost: {promptrepo.format_cost(results.total_cost_usd)}")
    """
    if inputs is None:
        inputs = [{}]

    repo = _resolve_repo()
    provider_kwargs: Dict[str, Any] = {}
    if model:
        provider_kwargs["model"] = model
    if system_prompt:
        provider_kwargs["system_prompt"] = system_prompt
    if temperature is not None:
        provider_kwargs["temperature"] = temperature

    t0 = time.monotonic()

    def _run_one(vars_dict: Dict[str, str]) -> RunResult:
        return _execute_run(
            repo=repo,
            name=name,
            version=version,
            variables=vars_dict,
            provider_name=provider,
            provider_kwargs=provider_kwargs,
        )

    results: List[RunResult] = []
    if max_workers == 1:
        for vars_dict in inputs:
            results.append(_run_one(vars_dict))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_run_one, v): i for i, v in enumerate(inputs)}
            ordered = [None] * len(inputs)
            for future in as_completed(futures):
                idx = futures[future]
                ordered[idx] = future.result()
        results = [r for r in ordered if r is not None]

    total_latency_ms = round((time.monotonic() - t0) * 1000, 1)
    total_tokens = sum(r.tokens or 0 for r in results)
    total_cost: float = 0.0
    cost_known = False
    for r in results:
        if r.cost and r.cost.total_cost_usd is not None:
            total_cost += r.cost.total_cost_usd
            cost_known = True

    success_count = sum(1 for r in results if r.ok)

    return BatchResult(
        results=results,
        total_tokens=total_tokens,
        total_cost_usd=total_cost if cost_known else None,
        total_latency_ms=total_latency_ms,
        success_count=success_count,
        error_count=len(results) - success_count,
    )


# Re-export format_cost at sdk level for convenience: `from promptrepo.sdk import format_cost`
# (already imported at top of module from promptrepo.utils.cost)
