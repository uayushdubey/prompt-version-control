import pytest
from promptvc.providers.base import BaseProvider
from promptvc.core.testing import run_assertion


def test_retry_with_backoff_success():
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
