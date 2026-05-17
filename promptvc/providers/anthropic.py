import os
import time
from typing import Any, Dict, Optional

import anthropic

from .base import BaseProvider


class AnthropicProvider(BaseProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        api_key = self.config.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        self._client = anthropic.Anthropic(api_key=api_key)

    def run(self, prompt: str, **kwargs) -> Dict[str, Any]:
        model = kwargs.get("model", "claude-3-haiku-20240307")
        max_tokens = kwargs.get("max_tokens", 1024)
        
        create_kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        
        timeout = kwargs.get("timeout")
        if timeout is not None:
            create_kwargs["timeout"] = timeout

        retries = 2
        response = None
        for attempt in range(retries + 1):
            try:
                response = self._client.messages.create(**create_kwargs)
                break
            except anthropic.APIError as e:
                if attempt < retries:
                    time.sleep(0.5 * (attempt + 1))
                else:
                    raise RuntimeError(f"Anthropic API failed after retries: {e}") from e
                    
        if response is None:
            raise RuntimeError("Anthropic API failed after retries with no response")

        output = ""
        if getattr(response, "content", None):
            output = response.content[0].text

        tokens = None
        if getattr(response, "usage", None):
            tokens = getattr(response.usage, "input_tokens", 0) + getattr(response.usage, "output_tokens", 0)

        return {
            "output": output,
            "tokens": tokens,
            "model_used": model,
        }
