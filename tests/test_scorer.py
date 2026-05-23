from promptvc.core.scorer import RuleScorer, CompositeScorer, CheckResult


def test_rule_scorer_exact_match():
    scorer = RuleScorer()
    # Test passing case
    res = scorer.score(
        output="Hello World",
        checks=[{"type": "exact_match", "expected": "Hello World"}]
    )
    assert res.score == 1.0
    assert len(res.checks) == 1
    assert res.checks[0].passed

    # Test failing case
    res2 = scorer.score(
        output="Hello World",
        checks=[{"type": "exact_match", "expected": "Hello AI"}]
    )
    assert res2.score == 0.0
    assert not res2.checks[0].passed


def test_rule_scorer_contains():
    scorer = RuleScorer()
    res = scorer.score(
        output="Hello World",
        checks=[{"type": "contains", "expected": "Hello"}]
    )
    assert res.score == 1.0
    assert res.checks[0].passed

    res2 = scorer.score(
        output="Hello World",
        checks=[{"type": "contains", "expected": "AI"}]
    )
    assert res2.score == 0.0
    assert not res2.checks[0].passed


def test_rule_scorer_not_contains():
    scorer = RuleScorer()
    res = scorer.score(
        output="Hello World",
        checks=[{"type": "not_contains", "expected": "AI"}]
    )
    assert res.score == 1.0
    assert res.checks[0].passed

    res2 = scorer.score(
        output="Hello World",
        checks=[{"type": "not_contains", "expected": "Hello"}]
    )
    assert res2.score == 0.0
    assert not res2.checks[0].passed


def test_rule_scorer_regex():
    scorer = RuleScorer()
    res = scorer.score(
        output="Hello 123 World",
        checks=[{"type": "regex", "expected": r"\d+"}]
    )
    assert res.score == 1.0
    assert res.checks[0].passed

    res2 = scorer.score(
        output="Hello World",
        checks=[{"type": "regex", "expected": r"\d+"}]
    )
    assert res2.score == 0.0
    assert not res2.checks[0].passed


def test_rule_scorer_starts_ends_with():
    scorer = RuleScorer()
    res = scorer.score(
        output="Hello World",
        checks=[
            {"type": "starts_with", "expected": "Hello"},
            {"type": "ends_with", "expected": "World"},
        ]
    )
    assert res.score == 1.0
    assert len(res.checks) == 2
    assert all(c.passed for c in res.checks)


def test_rule_scorer_max_length():
    scorer = RuleScorer()
    res = scorer.score(
        output="Hello World",
        checks=[{"type": "max_length", "expected": 15}]
    )
    assert res.score == 1.0
    assert res.checks[0].passed

    res2 = scorer.score(
        output="Hello World",
        checks=[{"type": "max_length", "expected": 5}]
    )
    assert res2.score == 0.0
    assert not res2.checks[0].passed


def test_rule_scorer_similarity():
    scorer = RuleScorer()
    res = scorer.score(
        output="Hello World",
        checks=[{"type": "similarity", "expected": "Hello AI World", "threshold": 0.5}]
    )
    assert res.score > 0.5
    assert res.checks[0].passed


def test_composite_scorer_deterministic():
    composite = CompositeScorer()
    res = composite.score(
        output="Hello World",
        checks=[{"type": "exact_match", "expected": "Hello World"}],
        llm_judge_cfg={"criteria": "Is it friendly?", "weight": 0.5},
        provider=None,
        deterministic=True
    )
    assert res.score == 1.0
    assert res.method == "rule"
