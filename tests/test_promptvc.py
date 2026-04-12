"""
tests/test_promptvc.py
~~~~~~~~~~~~~~~~~~~~~~
Comprehensive test suite for the promptvc core engine.

Run with:
    python -m pytest tests/ -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import tempfile
from pathlib import Path

from promptvc.core.repo import PromptRepo, CommitResult, _sha256, _sort_versions_desc
from promptvc.core.storage import (
    StorageEngine,
    PromptSpaceNotFoundError,
    VersionNotFoundError,
    RepoNotInitializedError,
)
from promptvc.core.tokenizer import (
    WhitespaceTokenizer,
    WordPunctTokenizer,
    CharacterEstimateTokenizer,
    get_tokenizer,
    register_tokenizer,
    unregister_tokenizer,
    BaseTokenizer,
)
from promptvc.core.lock import (
    LockGuard,
    VersionLockedError,
    AlreadyLockedError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_root(tmp_path):
    """Provide a fresh temp directory for each test."""
    return tmp_path


@pytest.fixture
def repo(tmp_root):
    """Return an initialized PromptRepo backed by a temp directory."""
    r = PromptRepo(root=tmp_root)
    r.init_repo()
    return r


# ===========================================================================
# Tokenizer tests
# ===========================================================================

class TestWhitespaceTokenizer:
    def test_basic_count(self):
        t = WhitespaceTokenizer()
        assert t.count("hello world foo") == 3

    def test_empty_string(self):
        assert WhitespaceTokenizer().count("") == 0

    def test_whitespace_only(self):
        assert WhitespaceTokenizer().count("   ") == 0

    def test_single_word(self):
        assert WhitespaceTokenizer().count("hello") == 1

    def test_multiple_spaces(self):
        assert WhitespaceTokenizer().count("a  b   c") == 3


class TestWordPunctTokenizer:
    def test_punctuation_splits(self):
        t = WordPunctTokenizer()
        # "Hello," "world" "!"
        count = t.count("Hello, world!")
        assert count >= 3  # at least 3 tokens

    def test_empty(self):
        assert WordPunctTokenizer().count("") == 0


class TestCharacterEstimateTokenizer:
    def test_basic(self):
        t = CharacterEstimateTokenizer()
        # 8 chars / 4 = 2 tokens
        assert t.count("12345678") == 2

    def test_empty(self):
        assert CharacterEstimateTokenizer().count("") == 0

    def test_minimum_one(self):
        # Even a single character should return at least 1
        assert CharacterEstimateTokenizer().count("a") >= 1


class TestTokenizerRegistry:
    def test_get_whitespace(self):
        t = get_tokenizer("whitespace")
        assert isinstance(t, WhitespaceTokenizer)

    def test_get_wordpunct(self):
        assert isinstance(get_tokenizer("wordpunct"), WordPunctTokenizer)

    def test_get_character(self):
        assert isinstance(get_tokenizer("character"), CharacterEstimateTokenizer)

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown tokenizer"):
            get_tokenizer("nonexistent")

    def test_register_and_use(self):
        class DummyTokenizer(BaseTokenizer):
            def count(self, text: str) -> int:
                return 42

        register_tokenizer("dummy", DummyTokenizer)
        t = get_tokenizer("dummy")
        assert t.count("anything") == 42
        unregister_tokenizer("dummy")

    def test_register_duplicate_raises(self):
        class A(BaseTokenizer):
            def count(self, text): return 1

        register_tokenizer("unique_tok", A)
        with pytest.raises(ValueError, match="already registered"):
            register_tokenizer("unique_tok", A)
        unregister_tokenizer("unique_tok")

    def test_unregister_builtin_raises(self):
        with pytest.raises(ValueError, match="Cannot unregister built-in"):
            unregister_tokenizer("whitespace")

    def test_register_non_tokenizer_raises(self):
        with pytest.raises(TypeError):
            register_tokenizer("bad", str)  # type: ignore


# ===========================================================================
# LockGuard tests
# ===========================================================================

class TestLockGuard:
    def _version(self, locked=False):
        return {
            "id": "v1", "prompt": "x", "message": "m",
            "timestamp": "2024-01-01T00:00:00+00:00",
            "tokens": 1, "locked": locked, "hash": "abc",
        }

    def test_assert_mutable_ok(self):
        LockGuard.assert_mutable(self._version(locked=False), "ns", "v1")

    def test_assert_mutable_raises(self):
        with pytest.raises(VersionLockedError):
            LockGuard.assert_mutable(self._version(locked=True), "ns", "v1")

    def test_assert_not_already_locked_ok(self):
        LockGuard.assert_not_already_locked(self._version(locked=False), "ns", "v1")

    def test_assert_not_already_locked_raises(self):
        with pytest.raises(AlreadyLockedError):
            LockGuard.assert_not_already_locked(self._version(locked=True), "ns", "v1")

    def test_apply_lock_returns_new_dict(self):
        original = self._version(locked=False)
        locked = LockGuard.apply_lock(original)
        assert locked["locked"] is True
        assert original["locked"] is False  # immutable — original unchanged

    def test_is_locked(self):
        assert LockGuard.is_locked(self._version(locked=True)) is True
        assert LockGuard.is_locked(self._version(locked=False)) is False


# ===========================================================================
# StorageEngine tests
# ===========================================================================

class TestStorageEngine:
    def test_initialize_creates_dir(self, tmp_root):
        engine = StorageEngine(root=tmp_root)
        assert not engine.is_initialized
        created = engine.initialize()
        assert created is True
        assert engine.is_initialized

    def test_initialize_idempotent(self, tmp_root):
        engine = StorageEngine(root=tmp_root)
        engine.initialize()
        created_again = engine.initialize()
        assert created_again is False

    def test_uninitialized_raises(self, tmp_root):
        engine = StorageEngine(root=tmp_root)
        with pytest.raises(RepoNotInitializedError):
            engine.list_space_names()

    def test_save_and_load(self, tmp_root):
        engine = StorageEngine(root=tmp_root)
        engine.initialize()
        data = {"versions": {}, "latest": None}
        engine.save_space("test_space", data)
        loaded = engine.load_space("test_space")
        assert loaded["versions"] == {}
        assert loaded["latest"] is None

    def test_load_missing_space_raises(self, tmp_root):
        engine = StorageEngine(root=tmp_root)
        engine.initialize()
        with pytest.raises(PromptSpaceNotFoundError):
            engine.load_space("ghost")

    def test_next_version_id_empty(self, tmp_root):
        engine = StorageEngine(root=tmp_root)
        engine.initialize()
        data = engine.load_or_create_space("new_space")
        assert engine.next_version_id(data) == "v1"

    def test_next_version_id_increments(self, tmp_root):
        engine = StorageEngine(root=tmp_root)
        engine.initialize()
        data: dict = {
            "versions": {"v1": {}, "v2": {}, "v3": {}},
            "latest": "v3"
        }
        assert engine.next_version_id(data) == "v4"

    def test_cache_hit(self, tmp_root):
        engine = StorageEngine(root=tmp_root)
        engine.initialize()
        engine.save_space("cached", {"versions": {}, "latest": None})
        d1 = engine.load_space("cached")
        d2 = engine.load_space("cached")
        assert d1 is d2  # same object — cache hit

    def test_invalidate_cache(self, tmp_root):
        engine = StorageEngine(root=tmp_root)
        engine.initialize()
        engine.save_space("inv", {"versions": {}, "latest": None})
        d1 = engine.load_space("inv")
        engine.invalidate_cache("inv")
        d2 = engine.load_space("inv")
        assert d1 is not d2  # different object after cache clear

    def test_get_version_ok(self, tmp_root):
        engine = StorageEngine(root=tmp_root)
        engine.initialize()
        v: dict = {
            "id": "v1", "prompt": "p", "message": "m",
            "timestamp": "t", "tokens": 1, "locked": False, "hash": "h"
        }
        engine.save_space("sp", {"versions": {"v1": v}, "latest": "v1"})
        result = engine.get_version("sp", "v1")
        assert result["prompt"] == "p"

    def test_get_version_missing_raises(self, tmp_root):
        engine = StorageEngine(root=tmp_root)
        engine.initialize()
        engine.save_space("sp2", {"versions": {}, "latest": None})
        with pytest.raises(VersionNotFoundError):
            engine.get_version("sp2", "v99")

    def test_forbidden_name_raises(self, tmp_root):
        engine = StorageEngine(root=tmp_root)
        engine.initialize()
        with pytest.raises(ValueError, match="forbidden characters"):
            engine.save_space("bad/name", {"versions": {}, "latest": None})

    def test_empty_name_raises(self, tmp_root):
        engine = StorageEngine(root=tmp_root)
        engine.initialize()
        with pytest.raises(ValueError, match="must not be empty"):
            engine.save_space("", {"versions": {}, "latest": None})

    def test_list_space_names(self, tmp_root):
        engine = StorageEngine(root=tmp_root)
        engine.initialize()
        for name in ["gamma", "alpha", "beta"]:
            engine.save_space(name, {"versions": {}, "latest": None})
        names = engine.list_space_names()
        assert names == ["alpha", "beta", "gamma"]  # sorted


# ===========================================================================
# PromptRepo integration tests
# ===========================================================================

class TestPromptRepoInit:
    def test_init_creates_directory(self, tmp_root):
        repo = PromptRepo(root=tmp_root)
        assert not repo.is_initialized
        repo.init_repo()
        assert repo.is_initialized
        assert (tmp_root / ".promptvc").is_dir()

    def test_init_idempotent(self, tmp_root):
        repo = PromptRepo(root=tmp_root)
        repo.init_repo()
        repo.init_repo()  # should not raise
        assert repo.is_initialized

    def test_operations_before_init_raise(self, tmp_root):
        repo = PromptRepo(root=tmp_root)
        with pytest.raises(RepoNotInitializedError):
            repo.list_spaces()


class TestCommit:
    def test_first_commit_creates_v1(self, repo):
        result = repo.commit("ns", "Hello {name}", "first commit")
        assert isinstance(result, CommitResult)
        assert result.version == "v1"
        assert result.name == "ns"

    def test_second_commit_is_v2(self, repo):
        repo.commit("ns", "v1 prompt", "first")
        result = repo.commit("ns", "v2 prompt", "second")
        assert result.version == "v2"

    def test_commit_stores_correct_data(self, repo):
        prompt = "Translate: {text}"
        repo.commit("tr", prompt, "add translator")
        meta = repo.get_version_meta("tr", "v1")
        assert meta["prompt"] == prompt
        assert meta["message"] == "add translator"
        assert meta["locked"] is False
        assert meta["hash"] == _sha256(prompt)
        assert meta["tokens"] > 0
        assert meta["timestamp"]

    def test_commit_empty_name_raises(self, repo):
        with pytest.raises(ValueError, match="name"):
            repo.commit("", "prompt", "msg")

    def test_commit_empty_prompt_raises(self, repo):
        with pytest.raises(ValueError, match="prompt"):
            repo.commit("ns", "", "msg")

    def test_commit_empty_message_raises(self, repo):
        with pytest.raises(ValueError, match="message"):
            repo.commit("ns", "prompt", "")

    def test_duplicate_prompts_allowed(self, repo):
        repo.commit("ns", "same prompt", "first")
        repo.commit("ns", "same prompt", "second — duplicate allowed")
        log = repo.log("ns")
        assert len(log) == 2

    def test_many_commits_version_sequence(self, repo):
        for i in range(5):
            repo.commit("seq", f"prompt {i}", f"commit {i}")
        log = repo.log("seq")
        ids = [v["id"] for v in log]
        assert ids == ["v5", "v4", "v3", "v2", "v1"]

    def test_token_count_recorded(self, repo):
        repo.commit("ns", "one two three four five", "msg")
        meta = repo.get_version_meta("ns", "v1")
        assert meta["tokens"] == 5  # whitespace tokenizer

    def test_sha256_hash_recorded(self, repo):
        text = "my special prompt"
        repo.commit("ns", text, "msg")
        meta = repo.get_version_meta("ns", "v1")
        assert meta["hash"] == _sha256(text)


class TestLog:
    def test_log_returns_versions_desc(self, repo):
        repo.commit("ns", "p1", "c1")
        repo.commit("ns", "p2", "c2")
        repo.commit("ns", "p3", "c3")
        log = repo.log("ns")
        assert [v["id"] for v in log] == ["v3", "v2", "v1"]

    def test_log_missing_space_raises(self, repo):
        with pytest.raises(PromptSpaceNotFoundError):
            repo.log("nonexistent")

    def test_log_single_version(self, repo):
        repo.commit("ns", "only", "only commit")
        log = repo.log("ns")
        assert len(log) == 1
        assert log[0]["id"] == "v1"


class TestGet:
    def test_get_returns_prompt_text(self, repo):
        repo.commit("ns", "My prompt text", "msg")
        assert repo.get("ns", "v1") == "My prompt text"

    def test_get_specific_version(self, repo):
        repo.commit("ns", "first", "c1")
        repo.commit("ns", "second", "c2")
        assert repo.get("ns", "v1") == "first"
        assert repo.get("ns", "v2") == "second"

    def test_get_missing_space_raises(self, repo):
        with pytest.raises(PromptSpaceNotFoundError):
            repo.get("ghost", "v1")

    def test_get_missing_version_raises(self, repo):
        repo.commit("ns", "p", "m")
        with pytest.raises(VersionNotFoundError):
            repo.get("ns", "v99")


class TestListSpaces:
    def test_empty_repo(self, repo):
        assert repo.list_spaces() == []

    def test_multiple_spaces_sorted(self, repo):
        repo.commit("zebra", "p", "m")
        repo.commit("apple", "p", "m")
        repo.commit("mango", "p", "m")
        assert repo.list_spaces() == ["apple", "mango", "zebra"]

    def test_same_space_multiple_commits(self, repo):
        repo.commit("only_one", "p1", "c1")
        repo.commit("only_one", "p2", "c2")
        assert repo.list_spaces() == ["only_one"]


class TestLock:
    def test_lock_sets_flag(self, repo):
        repo.commit("ns", "prompt", "msg")
        repo.lock("ns", "v1")
        meta = repo.get_version_meta("ns", "v1")
        assert meta["locked"] is True

    def test_lock_missing_space_raises(self, repo):
        with pytest.raises(PromptSpaceNotFoundError):
            repo.lock("ghost", "v1")

    def test_lock_missing_version_raises(self, repo):
        repo.commit("ns", "p", "m")
        with pytest.raises(VersionNotFoundError):
            repo.lock("ns", "v99")

    def test_lock_already_locked_raises(self, repo):
        repo.commit("ns", "p", "m")
        repo.lock("ns", "v1")
        with pytest.raises(AlreadyLockedError):
            repo.lock("ns", "v1")

    def test_other_versions_unaffected_by_lock(self, repo):
        repo.commit("ns", "p1", "m1")
        repo.commit("ns", "p2", "m2")
        repo.lock("ns", "v1")
        meta_v2 = repo.get_version_meta("ns", "v2")
        assert meta_v2["locked"] is False

    def test_commit_after_lock_creates_new_version(self, repo):
        """Locking does not prevent new commits — only mutation of the locked version."""
        repo.commit("ns", "original", "first")
        repo.lock("ns", "v1")
        result = repo.commit("ns", "updated", "second")
        assert result.version == "v2"
        assert repo.get("ns", "v1") == "original"  # locked v1 unchanged
        assert repo.get("ns", "v2") == "updated"


class TestLatest:
    def test_latest_after_commit(self, repo):
        repo.commit("ns", "first", "c1")
        repo.commit("ns", "second", "c2")
        latest = repo.latest("ns")
        assert latest is not None
        assert latest["id"] == "v2"
        assert latest["prompt"] == "second"

    def test_latest_missing_space_raises(self, repo):
        with pytest.raises(PromptSpaceNotFoundError):
            repo.latest("ghost")


class TestDiffTokens:
    def test_diff_positive(self, repo):
        repo.commit("ns", "short", "c1")
        repo.commit("ns", "longer prompt here", "c2")
        diff = repo.diff_tokens("ns", "v1", "v2")
        assert diff > 0

    def test_diff_negative(self, repo):
        repo.commit("ns", "longer prompt here for sure", "c1")
        repo.commit("ns", "tiny", "c2")
        diff = repo.diff_tokens("ns", "v1", "v2")
        assert diff < 0

    def test_diff_same(self, repo):
        repo.commit("ns", "hello world", "c1")
        repo.commit("ns", "foo bar", "c2")
        diff = repo.diff_tokens("ns", "v1", "v2")
        assert diff == 0


class TestPersistence:
    def test_data_survives_new_instance(self, tmp_root):
        """Ensure JSON is written correctly and a fresh repo reads it back."""
        repo1 = PromptRepo(root=tmp_root)
        repo1.init_repo()
        repo1.commit("persist", "hello persistence", "first")
        repo1.lock("persist", "v1")

        # Simulate a new Python session — fresh instance, same root
        repo2 = PromptRepo(root=tmp_root)
        assert repo2.is_initialized

        meta = repo2.get_version_meta("persist", "v1")
        assert meta["prompt"] == "hello persistence"
        assert meta["locked"] is True

    def test_multiple_spaces_persist(self, tmp_root):
        repo1 = PromptRepo(root=tmp_root)
        repo1.init_repo()
        repo1.commit("alpha", "alpha prompt", "a1")
        repo1.commit("beta", "beta prompt", "b1")

        repo2 = PromptRepo(root=tmp_root)
        assert set(repo2.list_spaces()) == {"alpha", "beta"}


class TestCustomTokenizer:
    def test_custom_tokenizer_used(self, tmp_root):
        class AlwaysTen(BaseTokenizer):
            def count(self, text: str) -> int:
                return 10

        repo = PromptRepo(root=tmp_root, tokenizer=AlwaysTen())
        repo.init_repo()
        repo.commit("ns", "any text", "msg")
        meta = repo.get_version_meta("ns", "v1")
        assert meta["tokens"] == 10


# ===========================================================================
# Helper function tests
# ===========================================================================

class TestHelpers:
    def test_sha256_deterministic(self):
        h1 = _sha256("hello")
        h2 = _sha256("hello")
        assert h1 == h2

    def test_sha256_different_inputs(self):
        assert _sha256("hello") != _sha256("world")

    def test_sha256_length(self):
        assert len(_sha256("x")) == 64  # hex digest

    def test_sort_versions_desc(self):
        versions = [
            {"id": "v1"}, {"id": "v3"}, {"id": "v2"}
        ]
        result = _sort_versions_desc(versions)  # type: ignore
        assert [v["id"] for v in result] == ["v3", "v2", "v1"]