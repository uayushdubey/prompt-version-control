"""
Tests for new production-grade features in PromptVC v0.2.0

Covers:
- Matrix evaluation engine
- Cost breakdown (CostBreakdown)
- Prompt format types (raw/chat/instruction)
- Tags & search
- Budget guard
- Analytics
- Secrets store (when cryptography available)
- Python SDK
- Tokenizer registry (TiktokenTokenizer fallback)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Cost Engine Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestCostBreakdown:
    def test_known_model_returns_breakdown(self):
        from promptvc.utils.cost import compute_cost_breakdown
        bd = compute_cost_breakdown("gpt-4o", 1000, 500)
        assert bd.is_known_model
        assert bd.input_tokens == 1000
        assert bd.output_tokens == 500
        assert bd.input_cost_usd is not None
        assert bd.output_cost_usd is not None
        assert bd.total_cost_usd is not None
        assert bd.total_cost_usd == pytest.approx(bd.input_cost_usd + bd.output_cost_usd)

    def test_unknown_model_returns_none_costs(self):
        from promptvc.utils.cost import compute_cost_breakdown
        bd = compute_cost_breakdown("some-unknown-model-xyz", 1000, 500)
        assert not bd.is_known_model
        assert bd.input_cost_usd is None
        assert bd.total_cost_usd is None

    def test_free_local_model(self):
        from promptvc.utils.cost import compute_cost_breakdown
        bd = compute_cost_breakdown("llama3", 5000, 2000)
        assert bd.is_known_model
        assert bd.is_free
        assert bd.total_cost_usd == 0.0

    def test_breakdown_addition(self):
        from promptvc.utils.cost import compute_cost_breakdown
        bd1 = compute_cost_breakdown("gpt-4o", 1000, 200)
        bd2 = compute_cost_breakdown("gpt-4o", 500, 100)
        combined = bd1 + bd2
        assert combined.input_tokens == 1500
        assert combined.output_tokens == 300
        assert combined.total_cost_usd == pytest.approx(
            bd1.total_cost_usd + bd2.total_cost_usd, rel=1e-6
        )

    def test_format_cost_breakdown(self):
        from promptvc.utils.cost import compute_cost_breakdown, format_cost_breakdown
        bd = compute_cost_breakdown("gpt-4o-mini", 1000, 500)
        formatted = format_cost_breakdown(bd)
        assert "gpt-4o-mini" in formatted
        assert "1,000" in formatted
        assert "500" in formatted

    def test_format_cost_none(self):
        from promptvc.utils.cost import format_cost
        assert format_cost(None) == "—"
        assert format_cost(0.0) == "free (local)"

    def test_alias_resolution(self):
        from promptvc.utils.cost import compute_cost_breakdown
        bd = compute_cost_breakdown("claude-opus-4", 100, 50)
        assert bd.is_known_model

    def test_new_2025_models_have_pricing(self):
        from promptvc.utils.cost import compute_cost_breakdown
        for model in ["gpt-4.1", "gpt-4.1-mini", "o3", "o4-mini", "gemini-2.5-pro", "gemini-2.5-flash"]:
            bd = compute_cost_breakdown(model, 1000, 200)
            assert bd.is_known_model, f"Model {model} should have known pricing"

    def test_cumulative_cost(self):
        from promptvc.utils.cost import cumulative_cost
        calls = [
            ("gpt-4o", 1000, 200),
            ("gpt-4o", 500, 100),
            ("gpt-4o-mini", 2000, 400),
        ]
        total = cumulative_cost(calls)
        assert total.input_tokens == 3500
        assert total.output_tokens == 700


# ─────────────────────────────────────────────────────────────────────────────
# Prompt Format Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestPromptFormat:
    def test_raw_render(self):
        from promptvc.core.prompt_format import render_prompt, PromptFormat
        result = render_prompt("Hello {{name}}!", {"name": "World"}, fmt=PromptFormat.RAW)
        assert result == "Hello World!"

    def test_chat_render(self):
        from promptvc.core.prompt_format import render_prompt, PromptFormat
        messages = [
            {"role": "system", "content": "You are a {{persona}}."},
            {"role": "user", "content": "Summarize: {{text}}"},
        ]
        rendered = render_prompt(messages, {"persona": "teacher", "text": "hello"}, fmt=PromptFormat.CHAT)
        assert isinstance(rendered, list)
        assert rendered[0]["content"] == "You are a teacher."
        assert rendered[1]["content"] == "Summarize: hello"

    def test_chat_from_json_string(self):
        from promptvc.core.prompt_format import render_prompt, PromptFormat
        messages_json = json.dumps([
            {"role": "user", "content": "Hi {{name}}!"}
        ])
        rendered = render_prompt(messages_json, {"name": "Alice"}, fmt=PromptFormat.CHAT)
        assert rendered[0]["content"] == "Hi Alice!"

    def test_invalid_format_raises(self):
        from promptvc.core.prompt_format import render_prompt
        with pytest.raises(ValueError, match="Invalid prompt format"):
            render_prompt("hello", {}, fmt="invalid_format")

    def test_validate_chat_messages(self):
        from promptvc.core.prompt_format import validate_chat_messages
        # Valid
        validate_chat_messages([{"role": "user", "content": "hi"}])
        # Missing role
        with pytest.raises(ValueError):
            validate_chat_messages([{"content": "hi"}])
        # Invalid role
        with pytest.raises(ValueError):
            validate_chat_messages([{"role": "invalid_role", "content": "hi"}])
        # Empty list
        with pytest.raises(ValueError):
            validate_chat_messages([])

    def test_messages_to_plain(self):
        from promptvc.core.prompt_format import messages_to_plain
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        plain = messages_to_plain(msgs)
        assert "[system]:" in plain
        assert "[user]:" in plain
        assert "You are helpful." in plain

    def test_extract_variables_from_chat(self):
        from promptvc.core.prompt_format import extract_variables_from_prompt, PromptFormat
        messages = [
            {"role": "system", "content": "Act as {{persona}}."},
            {"role": "user", "content": "Process: {{text}}"},
        ]
        vars_ = extract_variables_from_prompt(messages, fmt=PromptFormat.CHAT)
        assert "persona" in vars_
        assert "text" in vars_

    def test_prompt_to_storage_and_back(self):
        from promptvc.core.prompt_format import prompt_to_storage, prompt_from_storage, PromptFormat
        messages = [{"role": "user", "content": "hi"}]
        stored = prompt_to_storage(messages, fmt=PromptFormat.CHAT)
        assert isinstance(stored, str)
        restored = prompt_from_storage(stored, fmt=PromptFormat.CHAT)
        assert restored == messages


# ─────────────────────────────────────────────────────────────────────────────
# Tags & Search Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestTagsAndSearch:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        from promptvc.core.storage import StorageEngine
        from promptvc.core.repo import PromptRepo
        root = Path(self._tmpdir) / ".promptvc"
        storage = StorageEngine(root=root)
        storage.initialize()
        self.repo = PromptRepo()
        self.repo.storage = storage

    def test_commit_with_tags(self):
        v = self.repo.commit("test", "Hello world", "First commit", tags=["prod", "v1"])
        assert "prod" in v["tags"]
        assert "v1" in v["tags"]

    def test_tags_are_normalized_lowercase(self):
        v = self.repo.commit("test2", "Prompt text", "msg", tags=["PRODUCTION", "  api  "])
        assert "production" in v["tags"]
        assert "api" in v["tags"]

    def test_format_stored_in_version(self):
        v = self.repo.commit("test3", "Prompt", "msg", fmt="chat")
        assert v["format"] == "chat"

    def test_tag_existing_version(self):
        self.repo.commit("tagger", "Prompt", "First commit", tags=["old"])
        updated = self.repo.tag_version("tagger", "v1", ["new-tag"])
        assert "old" in updated["tags"]
        assert "new-tag" in updated["tags"]

    def test_tag_replace(self):
        self.repo.commit("tagger2", "Prompt", "First commit", tags=["old"])
        updated = self.repo.tag_version("tagger2", "v1", ["brand-new"], replace=True)
        assert "old" not in updated["tags"]
        assert "brand-new" in updated["tags"]

    def test_find_by_tag(self):
        self.repo.commit("space-a", "Prompt A", "msg", tags=["summarize"])
        self.repo.commit("space-b", "Prompt B", "msg", tags=["classify"])
        results = self.repo.find_by_tag("summarize")
        spaces = [r["space"] for r in results]
        assert "space-a" in spaces
        assert "space-b" not in spaces

    def test_search_by_prompt_text(self):
        self.repo.commit("searchable", "This prompt handles summarization tasks", "msg")
        results = self.repo.search("summarization")
        assert any(r["space"] == "searchable" for r in results)

    def test_search_by_message(self):
        self.repo.commit("searchable2", "Some prompt", "production deployment 2024")
        results = self.repo.search("production deployment")
        assert any(r["space"] == "searchable2" for r in results)

    def test_search_by_tag(self):
        self.repo.commit("searchable3", "Some prompt", "msg", tags=["my-special-tag"])
        results = self.repo.search("my-special-tag")
        assert any(r["space"] == "searchable3" for r in results)

    def test_search_empty_query_returns_nothing(self):
        self.repo.commit("test4", "Prompt", "msg")
        results = self.repo.search("")
        assert results == []


# ─────────────────────────────────────────────────────────────────────────────
# Budget Guard Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestBudgetGuard:
    def test_no_limits_always_passes(self):
        from promptvc.core.budget import BudgetGuard
        guard = BudgetGuard()
        guard.check_pre_run("gpt-4o", 1_000_000, 500_000)  # No exception

    def test_per_run_limit_raises(self):
        from promptvc.core.budget import BudgetGuard, BudgetExceededError
        guard = BudgetGuard(max_cost_per_run=0.001)
        # gpt-4o at 1M input tokens = $2.50, way over limit
        with pytest.raises(BudgetExceededError) as exc_info:
            guard.check_pre_run("gpt-4o", 1_000_000, 0)
        assert "per-run" in str(exc_info.value)

    def test_session_limit_raises_after_accumulation(self):
        from promptvc.core.budget import BudgetGuard, BudgetExceededError
        guard = BudgetGuard(max_session_cost=0.01)
        # Record some usage first
        guard.record_usage("gpt-4o", 1000, 500)  # ~$0.0075
        # Now checking another run should fail
        with pytest.raises(BudgetExceededError) as exc_info:
            guard.check_pre_run("gpt-4o", 1000, 500)
        assert "session" in str(exc_info.value)

    def test_record_usage_accumulates(self):
        from promptvc.core.budget import BudgetGuard
        guard = BudgetGuard()
        guard.record_usage("gpt-4o-mini", 1000, 200)
        guard.record_usage("gpt-4o-mini", 500, 100)
        assert guard.session_cost > 0
        assert len(guard.session_records) == 2

    def test_disabled_guard_ignores_limits(self):
        from promptvc.core.budget import BudgetGuard
        guard = BudgetGuard(max_cost_per_run=0.00001, enabled=False)
        guard.check_pre_run("gpt-4o", 1_000_000, 500_000)  # No exception

    def test_estimate_run_cost(self):
        from promptvc.core.budget import BudgetGuard
        guard = BudgetGuard()
        cost = guard.estimate_run_cost("gpt-4o-mini", 1000, 200)
        assert cost is not None
        assert cost > 0

    def test_reset_session(self):
        from promptvc.core.budget import BudgetGuard
        guard = BudgetGuard()
        guard.record_usage("gpt-4o", 1000, 200)
        guard.reset_session()
        assert guard.session_cost == 0.0
        assert len(guard.session_records) == 0

    def test_unknown_model_skips_budget_check(self):
        from promptvc.core.budget import BudgetGuard
        guard = BudgetGuard(max_cost_per_run=0.000001)
        # Unknown model → cost is None → no exception
        guard.check_pre_run("some-unknown-model-xyz-123", 1_000_000, 500_000)


# ─────────────────────────────────────────────────────────────────────────────
# Matrix Evaluation Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestMatrixEvaluation:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        from promptvc.core.storage import StorageEngine
        from promptvc.core.repo import PromptRepo
        root = Path(self._tmpdir) / ".promptvc"
        storage = StorageEngine(root=root)
        storage.initialize()
        self.repo = PromptRepo()
        self.repo.storage = storage

    def _make_dataset(self, cases):
        path = os.path.join(self._tmpdir, "dataset.json")
        with open(path, "w") as f:
            json.dump(cases, f)
        return path

    def _make_mock_provider(self, outputs):
        """Create a mock provider that returns outputs in sequence."""
        class MockProvider:
            def __init__(self, outputs):
                self._outputs = iter(outputs)
            def run(self, prompt, **kwargs):
                output = next(self._outputs, "default output")
                return {"output": output, "tokens": 10, "input_tokens": 8, "output_tokens": 2, "model_used": "mock"}
        return MockProvider(outputs)

    def test_basic_matrix_evaluation(self):
        from promptvc.core.matrix import MatrixConfig, run_matrix_eval

        self.repo.commit("test", "Prompt v1: {{text}}", "V1")
        self.repo.commit("test", "Prompt v2: {{text}}", "V2")

        dataset = [
            {"id": "case-1", "input": {"text": "hello"}},
            {"id": "case-2", "input": {"text": "world"}},
        ]
        dataset_path = self._make_dataset(dataset)

        provider = self._make_mock_provider(["output1", "output2", "output3", "output4"])
        config = MatrixConfig(name="test", versions=["v1", "v2"], dataset_path=dataset_path)
        result = run_matrix_eval(config, provider=provider, repo=self.repo)

        assert result.name == "test"
        assert set(result.versions) == {"v1", "v2"}
        assert len(result.case_ids) == 2
        assert len(result.cells) == 4  # 2 versions × 2 cases
        assert result.winner in {"v1", "v2"}

    def test_matrix_version_stats(self):
        from promptvc.core.matrix import MatrixConfig, run_matrix_eval

        self.repo.commit("stat-test", "Prompt: {{x}}", "First version")

        dataset = [{"id": "c1", "input": {"x": "a"}}, {"id": "c2", "input": {"x": "b"}}]
        path = self._make_dataset(dataset)
        provider = self._make_mock_provider(["out1", "out2"])

        config = MatrixConfig(name="stat-test", versions=["v1"], dataset_path=path)
        result = run_matrix_eval(config, provider=provider, repo=self.repo)

        stats = result.get_stats("v1")
        assert stats is not None
        assert stats.total_cases == 2
        assert 0.0 <= stats.mean_score <= 1.0

    def test_format_matrix_table(self):
        from promptvc.core.matrix import MatrixConfig, run_matrix_eval, format_matrix_table

        self.repo.commit("fmt-test", "Prompt: {{x}}", "v1")

        dataset = [{"id": "case1", "input": {"x": "hello"}}]
        path = self._make_dataset(dataset)
        provider = self._make_mock_provider(["response"])

        config = MatrixConfig(name="fmt-test", versions=["v1"], dataset_path=path)
        result = run_matrix_eval(config, provider=provider, repo=self.repo)

        table = format_matrix_table(result)
        assert "v1" in table
        assert "case1" in table
        assert "Mean Score" in table

    def test_matrix_with_missing_version(self):
        from promptvc.core.matrix import MatrixConfig, run_matrix_eval

        self.repo.commit("miss-test", "Prompt", "first")

        dataset = [{"id": "c1", "input": {}}]
        path = self._make_dataset(dataset)
        provider = self._make_mock_provider(["ok"])

        config = MatrixConfig(name="miss-test", versions=["v1", "v99_missing"], dataset_path=path)
        result = run_matrix_eval(config, provider=provider, repo=self.repo)

        # v99 cells should have errors
        err_cells = [c for c in result.cells if c.version == "v99_missing"]
        assert all(c.error is not None for c in err_cells)


# ─────────────────────────────────────────────────────────────────────────────
# Tokenizer Registry Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestTokenizerRegistry:
    def test_get_tokenizer_for_gpt4o(self):
        from promptvc.core.tokenizer_registry import get_tokenizer_for_model, TiktokenTokenizer
        tok = get_tokenizer_for_model("gpt-4o")
        assert isinstance(tok, TiktokenTokenizer)
        count = tok.count("Hello world, this is a test.")
        assert count > 0

    def test_get_tokenizer_for_gemini(self):
        from promptvc.core.tokenizer_registry import get_tokenizer_for_model
        from promptvc.core.repo import CharacterEstimateTokenizer
        tok = get_tokenizer_for_model("gemini-2.0-flash")
        assert isinstance(tok, CharacterEstimateTokenizer)

    def test_get_tokenizer_for_local(self):
        from promptvc.core.tokenizer_registry import get_tokenizer_for_model
        from promptvc.core.repo import WordPunctTokenizer
        tok = get_tokenizer_for_model("llama3")
        assert isinstance(tok, WordPunctTokenizer)

    def test_tiktoken_tokenizer_fallback_when_not_installed(self):
        """TiktokenTokenizer should fall back to WordPunct if tiktoken unavailable."""
        from promptvc.core.tokenizer_registry import TiktokenTokenizer
        with patch.dict(sys.modules, {"tiktoken": None}):
            tok = TiktokenTokenizer("cl100k_base")
            # Fallback should still return a positive count
            count = tok.count("Hello world")
            assert count > 0

    def test_tiktoken_registry_available(self):
        from promptvc.core.tokenizer_registry import TokenizerRegistry
        all_names = TokenizerRegistry.list_all()
        assert "tiktoken" in all_names
        assert "whitespace" in all_names
        assert "wordpunct" in all_names


# ─────────────────────────────────────────────────────────────────────────────
# Secrets Store Tests (conditional on cryptography availability)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("cryptography"),
    reason="cryptography package not installed"
)
class TestSecretsStore:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        from promptvc.security.secrets import SecretsStore
        self.store = SecretsStore(Path(self._tmpdir))
        # Use a test master key
        os.environ["PROMPTVC_MASTER_KEY"] = "test_master_key_for_unit_tests_only"

    def teardown_method(self):
        os.environ.pop("PROMPTVC_MASTER_KEY", None)

    def test_set_and_get(self):
        self.store.set("openai", "sk-test-key-12345")
        retrieved = self.store.get("openai")
        assert retrieved == "sk-test-key-12345"

    def test_get_nonexistent_returns_none(self):
        result = self.store.get("nonexistent_service")
        assert result is None

    def test_delete_existing_key(self):
        self.store.set("anthropic", "sk-ant-test")
        deleted = self.store.delete("anthropic")
        assert deleted is True
        assert self.store.get("anthropic") is None

    def test_delete_nonexistent_returns_false(self):
        result = self.store.delete("does_not_exist")
        assert result is False

    def test_list_services(self):
        self.store.set("openai", "key1")
        self.store.set("gemini", "key2")
        services = self.store.list_services()
        assert "openai" in services
        assert "gemini" in services

    def test_service_names_normalized_lowercase(self):
        self.store.set("OpenAI", "key1")
        assert self.store.get("openai") == "key1"

    def test_file_is_encrypted(self):
        self.store.set("openai", "super-secret-key")
        # Read raw bytes — should NOT contain the plaintext key
        raw = self.store._path.read_bytes()
        assert b"super-secret-key" not in raw

    def test_get_for_provider_falls_back_to_env(self):
        os.environ["OPENAI_API_KEY"] = "env-key-fallback"
        try:
            result = self.store.get_for_provider("openai")
            assert result == "env-key-fallback"
        finally:
            del os.environ["OPENAI_API_KEY"]


# ─────────────────────────────────────────────────────────────────────────────
# SDK Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSDK:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        from promptvc.core.storage import StorageEngine
        from promptvc.core.repo import PromptRepo
        root = Path(self._tmpdir) / ".promptvc"
        storage = StorageEngine(root=root)
        storage.initialize()
        self.repo = PromptRepo()
        self.repo.storage = storage
        self.repo.commit("my-prompt", "Summarize: {{text}}", "First version")

    def _patch_repo(self):
        """Patch _resolve_repo to return our test repo."""
        return patch("promptvc.sdk._resolve_repo", return_value=self.repo)

    def test_run_result_structure(self):
        from promptvc.sdk import RunResult, CostBreakdown
        result = RunResult(
            output="test output",
            tokens=100,
            input_tokens=80,
            output_tokens=20,
            latency_ms=250.0,
            cost=None,
            model="mock",
            trace_id="test-trace",
            prompt_name="my-prompt",
            version="v1",
        )
        assert result.ok
        assert result.cost_usd is None

    def test_run_with_mock_provider(self):
        from promptvc.sdk import run
        with self._patch_repo():
            with patch("promptvc.sdk.get_provider") as mock_get:
                mock_provider = MagicMock()
                mock_provider.run.return_value = {
                    "output": "Summary here",
                    "tokens": 50,
                    "input_tokens": 30,
                    "output_tokens": 20,
                    "model_used": "mock",
                }
                mock_get.return_value = mock_provider

                result = run("my-prompt", "v1", provider="mock", text="Hello world")
                assert result.ok
                assert result.output == "Summary here"
                assert result.tokens == 50

    def test_batch_run_returns_correct_count(self):
        from promptvc.sdk import batch_run
        with self._patch_repo():
            with patch("promptvc.sdk.get_provider") as mock_get:
                mock_provider = MagicMock()
                mock_provider.run.return_value = {
                    "output": "result",
                    "tokens": 10,
                    "input_tokens": 8,
                    "output_tokens": 2,
                    "model_used": "mock",
                }
                mock_get.return_value = mock_provider

                results = batch_run(
                    "my-prompt", "v1",
                    inputs=[{"text": "a"}, {"text": "b"}, {"text": "c"}],
                    provider="mock",
                    max_workers=1,
                )
                assert len(results.results) == 3
                assert results.success_count == 3
                assert results.error_count == 0
                assert results.total_tokens == 30

    def test_prompt_decorator(self):
        from promptvc.sdk import prompt
        with self._patch_repo():
            with patch("promptvc.sdk.get_provider") as mock_get:
                mock_provider = MagicMock()
                mock_provider.run.return_value = {
                    "output": "decorated result",
                    "tokens": 20,
                    "input_tokens": 15,
                    "output_tokens": 5,
                    "model_used": "mock",
                }
                mock_get.return_value = mock_provider

                @prompt("my-prompt", version="v1", provider="mock")
                def my_func(text: str):
                    """This docstring is replaced."""

                result = my_func(text="Test input")
                assert result.output == "decorated result"
                assert hasattr(my_func, "prompt_name")
                assert my_func.prompt_name == "my-prompt"

    def test_run_context_manager(self):
        from promptvc.sdk import run_context
        with self._patch_repo():
            with patch("promptvc.sdk.get_provider") as mock_get:
                mock_provider = MagicMock()
                mock_provider.run.return_value = {
                    "output": "context result",
                    "tokens": 15,
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "model_used": "mock",
                }
                mock_get.return_value = mock_provider

                with run_context("my-prompt", "v1", provider="mock") as ctx:
                    # Patch the internal repo
                    ctx._repo = self.repo
                    result = ctx.run(text="test")
                    assert ctx.output == "context result"
                    assert ctx.latency_ms >= 0
