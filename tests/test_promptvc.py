from promptvc.core.diff import compute_diff


def test_compute_diff_basic():
    result = compute_diff("Hello world", "Hello AI world")

    assert isinstance(result, list)
    assert "+ AI" in result or any("AI" in r for r in result)