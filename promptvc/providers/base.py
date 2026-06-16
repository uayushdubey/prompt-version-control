from __future__ import annotations

import random
import time
from typing import Any, Callable, Dict, Iterator, Optional, Tuple, Type


class BaseProvider:
    """
    Abstract base for all LLM providers.

    Subclasses must implement `run()`.
    Optional: override `stream()` for real streaming support.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config: Dict[str, Any] = config or {}

    def run(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Execute a prompt and return a result dict.

        All providers MUST return at minimum:
            output (str): The generated text
            tokens (Optional[int]): Total token count
            input_tokens (Optional[int]): Input/prompt token count
            output_tokens (Optional[int]): Output/completion token count
            model_used (str): The model identifier that was actually used
        """
        raise NotImplementedError("Provider must implement run()")

    def stream(self, prompt: str, **kwargs) -> Iterator[str]:
        """
        Stream output tokens/chunks as they are generated.

        Default implementation calls run() and yields the full output as one chunk.
        Override in provider subclasses for real streaming.
        """
        result = self.run(prompt, **kwargs)
        output = result.get("output", "")
        if output:
            yield output

    def _retry_with_backoff(
        self,
        fn: Callable[[], Any],
        transient_exceptions: Tuple[Type[BaseException], ...],
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> Any:
        """
        Execute a function with exponential backoff + jitter for transient errors.

        Args:
            fn: Zero-argument callable to execute.
            transient_exceptions: Exception types that warrant a retry.
            max_retries: Maximum number of retry attempts (not counting initial).
            base_delay: Base delay in seconds for exponential backoff.

        Returns:
            The return value of fn() on success.

        Raises:
            The last exception if all retries are exhausted.
        """
        for attempt in range(max_retries + 1):
            try:
                return fn()
            except transient_exceptions:
                if attempt == max_retries:
                    raise
                # Exponential backoff with full jitter
                max_jitter = base_delay * (2 ** attempt)
                delay = random.uniform(0.0, max_jitter)
                time.sleep(delay)