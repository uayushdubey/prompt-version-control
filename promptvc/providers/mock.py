from typing import Any, Dict, Optional

from .base import BaseProvider


class MockProvider(BaseProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

    def run(self, prompt: str, **kwargs) -> dict:
        return {
            "output": prompt[::-1],
            "tokens": len(prompt.split()),
        }