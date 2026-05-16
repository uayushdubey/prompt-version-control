from typing import Any, Dict, Optional

class BaseProvider:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def run(self, prompt: str, **kwargs) -> dict:
        raise NotImplementedError("Provider must implement run()")