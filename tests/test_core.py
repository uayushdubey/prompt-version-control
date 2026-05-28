import json
import os
import uuid
from datetime import datetime, timezone
import pytest

from promptvc.core.storage import StorageEngine, TraceRecord, TraceStore
from promptvc.core.evaluator import run_assertion, CaseResult
from promptvc.core.validator import validate_dataset, validate_prompt
from promptvc.utils.diff import compute_diff, apply_unified_diff, validate_unified_diff


# ── Diff Computation & Application Tests ──────────────────────────────────────────

def test_compute_diff_basic():
    result = compute_diff("Hello world", "Hello AI world")
    assert isinstance(result, list)
    assert "+ AI" in result or any("AI" in r for r in result)


def test_apply_diff_basic():
    original = "line 1\nline 2\nline 3\n"
    diff = """--- original
+++ updated
@@
 line 1
-line 2
+line two
 line 3
"""
    result = apply_unified_diff(original, diff)
    assert result == "line 1\nline two\nline 3\n"


def test_apply_diff_context_mismatch():
    original = "line 1\nline 2\nline 3\n"
    diff = """--- original
+++ updated
@@
 line wrong
-line 2
+line two
 line 3
"""
    with pytest.raises(ValueError) as exc:
        apply_unified_diff(original, diff)
    assert "Mismatch in context line" in str(exc.value)


def test_apply_diff_invalid_format():
    diff = "invalid line\n+ new line"
    errors = validate_unified_diff(diff)
    assert len(errors) > 0
    assert any("does not start with" in e for e in errors)


def test_apply_diff_add_remove():
    original = "a\nb\nc\n"
    diff = """@@
-a
+hello
+world
 b
-c
"""
    result = apply_unified_diff(original, diff)
    assert result == "hello\nworld\nb\n"


# ── Storage Applied Diffs Tests ───────────────────────────────────────────────

def test_storage_applied_diffs(tmp_path):
    storage = StorageEngine(root=tmp_path)
    storage.initialize()

    file_path = "src/main.py"
    diff_hash = "some_sha256_hash"

    assert not storage.is_diff_applied(file_path, diff_hash)

    storage.record_applied_diff(file_path, diff_hash)
    assert storage.is_diff_applied(file_path, diff_hash)

    assert not storage.is_diff_applied(file_path, "other_hash")


# ── Trace Logging Tests ─────────────────────────────────────────────────────────

def test_trace_store(tmp_path):
    store = TraceStore(tmp_path)
    trace_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    rec = TraceRecord(
        trace_id=trace_id,
        timestamp=timestamp,
        prompt_name="summarize",
        version="v1",
        rendered_prompt="Summarize this",
        variables={"text": "this"},
        provider="mock",
        model="mock",
        output="siht ezirammus",
        tokens=2,
        latency_ms=12.5,
    )

    store.append(rec)

    # Query matching name and version
    results = store.query("summarize", "v1")
    assert len(results) == 1
    assert results[0].trace_id == trace_id
    assert results[0].output == "siht ezirammus"

    # Query matching name, any version
    results_any = store.query("summarize")
    assert len(results_any) == 1

    # Query non-matching name
    results_none = store.query("other_prompt")
    assert len(results_none) == 0


# ── Validator Tests ─────────────────────────────────────────────────────────────

def test_validate_dataset_nonexistent():
    res = validate_dataset("nonexistent_file.json")
    assert not res.valid
    assert "does not exist" in res.errors[0]


def test_validate_dataset_invalid_json(tmp_path):
    f = tmp_path / "invalid.json"
    f.write_text("{invalid")
    res = validate_dataset(str(f))
    assert not res.valid
    assert "Invalid JSON" in res.errors[0]


def test_validate_dataset_valid(tmp_path):
    f = tmp_path / "valid.json"
    data = [
        {
            "id": "case-1",
            "input": {"text": "hello"},
            "assertions": [
                {"type": "contains", "value": "hello"}
            ],
            "checks": [
                {"type": "exact_match", "expected": "hello"}
            ],
            "llm_judge": {
                "criteria": "be polite",
                "weight": 0.5
            }
        }
    ]
    f.write_text(json.dumps(data))
    res = validate_dataset(str(f))
    assert res.valid
    assert not res.errors


def test_validate_dataset_invalid_fields(tmp_path):
    f = tmp_path / "invalid_fields.json"
    data = [
        {
            "id": "case-1",
            "assertions": [
                {"type": "unknown_type", "value": "test"}
            ]
        }
    ]
    f.write_text(json.dumps(data))
    res = validate_dataset(str(f))
    assert not res.valid
    assert any("input" in e for e in res.errors)
    assert any("unknown_type" in e for e in res.errors)


def test_validate_prompt():
    class MockRepo:
        def get_version_meta(self, name, version):
            if name == "test_prompt":
                return {
                    "prompt": "Hello {{name}}, welcome to {{place}}!"
                }
            raise Exception("not found")

        def get_schema(self, name, version):
            if name == "test_prompt":
                return {
                    "variables": {
                        "name": {"type": "string", "required": True},
                        "place": {"type": "string", "required": False},
                    }
                }
            return {}

    repo = MockRepo()
    res = validate_prompt(repo, "test_prompt", "v1")
    assert res.valid
    assert not res.errors
    assert not res.warnings

    class MockRepoMissing:
        def get_version_meta(self, name, version):
            return {"prompt": "Hello {{name}} and {{age}}!"}

        def get_schema(self, name, version):
            return {
                "variables": {
                    "name": {"type": "string", "required": True}
                }
            }

    res2 = validate_prompt(MockRepoMissing(), "test_prompt", "v1")
    assert not res2.valid
    assert any("age" in e for e in res2.errors)


# ── Self Healing / Backoff Tests ──────────────────────────────────────────────────

def test_retry_with_backoff_success():
    from promptvc.providers.base import BaseProvider
    class MockProvider(BaseProvider):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def run(self, prompt, **kwargs):
            return {"output": "ok"}

        def attempt_action(self):
            self.calls += 1
            if self.calls < 3:
                raise ValueError("Transient error")
            return "success"

    provider = MockProvider()
    res = provider._retry_with_backoff(
        provider.attempt_action,
        transient_exceptions=(ValueError,),
        max_retries=3,
        base_delay=0.01,
    )
    assert res == "success"
    assert provider.calls == 3


def test_retry_with_backoff_failure():
    from promptvc.providers.base import BaseProvider
    class MockProvider(BaseProvider):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def run(self, prompt, **kwargs):
            return {"output": "ok"}

        def attempt_action(self):
            self.calls += 1
            raise ValueError("Fatal error")

    provider = MockProvider()
    with pytest.raises(ValueError):
        provider._retry_with_backoff(
            provider.attempt_action,
            transient_exceptions=(ValueError,),
            max_retries=2,
            base_delay=0.01,
        )
    assert provider.calls == 3


def test_unknown_assertion_warning():
    with pytest.warns(UserWarning, match="Unknown assertion type"):
        res = run_assertion(
            assertion={"type": "unknown_random_type", "value": "test"},
            output="hello",
            tokens=None,
        )
        assert res.passed
        assert "skipped" in res.message


# ── Regression Delta Scoring Tests ────────────────────────────────────────────────

def test_regression_delta_scoring():
    base_results = [
        CaseResult(case_id="case-1", input_vars={}, output="hello", tokens=1, score=1.0),
        CaseResult(case_id="case-2", input_vars={}, output="world", tokens=2, score=0.8),
    ]
    current_results = [
        CaseResult(case_id="case-1", input_vars={}, output="hello", tokens=1, score=0.9), # score dropped
        CaseResult(case_id="case-2", input_vars={}, output="world", tokens=2, score=1.0), # score improved
    ]

    current_by_id = {cr.case_id: cr for cr in current_results}
    base_by_id = {cr.case_id: cr for cr in base_results}

    deltas = {}
    regression_detected = False

    for case_id in sorted(set(current_by_id.keys()) | set(base_by_id.keys())):
        base_cr = base_by_id.get(case_id)
        curr_cr = current_by_id.get(case_id)
        base_score = base_cr.score if base_cr else 0.0
        curr_score = curr_cr.score if curr_cr else 0.0
        delta = curr_score - base_score
        deltas[case_id] = delta
        if delta < -0.001:
            regression_detected = True

    assert deltas["case-1"] == pytest.approx(-0.1)
    assert deltas["case-2"] == pytest.approx(0.2)
    assert regression_detected
