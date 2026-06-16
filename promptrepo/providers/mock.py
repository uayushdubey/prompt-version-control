from typing import Any, Dict, Optional

from .base import BaseProvider


class MockProvider(BaseProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

    def run(self, prompt: str, **kwargs) -> dict:
        raw_messages = kwargs.get("messages")
        if raw_messages is not None:
            import json
            prompt_str = json.dumps(raw_messages)
        else:
            prompt_str = prompt
        return {
            "output": prompt_str[::-1],
            "tokens": len(prompt_str.split()),
        }