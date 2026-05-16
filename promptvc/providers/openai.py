import os
from typing import Any, Dict, Optional

import openai

from .base import BaseProvider


class OpenAIProvider(BaseProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        api_key = self.config.get("api_key") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")
        self._client = openai.OpenAI(api_key=api_key)

    def run(self, prompt: str, **kwargs) -> dict:
        model = kwargs.get("model", "gpt-4o-mini")
        timeout = kwargs.get("timeout")
        
        create_kwargs = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if timeout is not None:
            create_kwargs["timeout"] = timeout

        try:
            response = self._client.chat.completions.create(**create_kwargs)
        except openai.OpenAIError as e:
            raise RuntimeError(f"OpenAI API error: {e}") from e

        output = response.choices[0].message.content
        tokens = response.usage.total_tokens if response.usage else None

        return {
            "output": output,
            "tokens": tokens,
        }