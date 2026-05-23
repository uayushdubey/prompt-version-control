import random
import time
from typing import Any, Callable, Dict, Optional, Tuple, Type


class BaseProvider:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def run(self, prompt: str, **kwargs) -> dict:
        raise NotImplementedError("Provider must implement run()")

    def _retry_with_backoff(
        self,
        fn: Callable[[], Any],
        transient_exceptions: Tuple[Type[BaseException], ...],
        max_retries: int = 2,
        base_delay: float = 0.5,
    ) -> Any:
        """Execute a function with exponential backoff and jitter for specified transient exceptions."""
        for attempt in range(max_retries + 1):
            try:
                return fn()
            except transient_exceptions:
                if attempt == max_retries:
                    raise
                delay = base_delay * (2 ** attempt) + random.uniform(0.0, 0.1)
                time.sleep(delay)