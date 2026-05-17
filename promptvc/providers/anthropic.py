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
            except Exception as e:
                if attempt < retries:
                    time.sleep(0.5 * (attempt + 1))
                else:
                    raise RuntimeError(f"Anthropic API failed after {retries + 1} attempts: {e}") from e
                    
        if response is None:
            raise RuntimeError("Anthropic API failed after retries with no response")

        output = ""
        if getattr(response, "content", None) and len(response.content) > 0:
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    output = block.text
                    break
        tokens = None
        if getattr(response, "usage", None):
            input_tokens = getattr(response.usage, "input_tokens", 0)
            output_tokens = getattr(response.usage, "output_tokens", 0)
            tokens = input_tokens + output_tokens

        return {
            "output": output,
            "tokens": tokens,
            "model_used": model,
        }
