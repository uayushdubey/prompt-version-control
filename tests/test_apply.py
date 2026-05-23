import pytest
from promptvc.utils.diff_apply import apply_unified_diff, validate_unified_diff


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


def test_storage_applied_diffs(tmp_path):
    from promptvc.core.storage import StorageEngine
    storage = StorageEngine(root=tmp_path)
    storage.initialize()

    file_path = "src/main.py"
    diff_hash = "some_sha256_hash"

    # Initially not applied
    assert not storage.is_diff_applied(file_path, diff_hash)

    # Record application
    storage.record_applied_diff(file_path, diff_hash)
    assert storage.is_diff_applied(file_path, diff_hash)

    # Verify other diff hash is not applied
    assert not storage.is_diff_applied(file_path, "other_hash")

