import pytest
from promptvc.core.testing import CaseResult


def test_regression_delta_scoring():
    # Verify we can correctly match and compare case scores
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
