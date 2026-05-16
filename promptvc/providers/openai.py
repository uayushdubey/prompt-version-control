import os
import time
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
    def run(self, prompt: str, **kwargs) -> Dict[str, Any]:
        model = kwargs.get("model", "gpt-4o-mini")
        timeout = kwargs.get("timeout", 60)
        max_tokens = kwargs.get("max_tokens")

        create_kwargs = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "timeout": timeout,
        }
        
        if max_tokens is not None:
            create_kwargs["max_tokens"] = max_tokens

        retries = 2
        response = None
        for attempt in range(retries + 1):
            try:
                response = self._client.chat.completions.create(**create_kwargs)
                break
            except openai.OpenAIError as e:
                if attempt < retries:
                    time.sleep(0.5 * (attempt + 1))
                else:
                    raise RuntimeError(
                        f"OpenAI API failed after {retries + 1} attempts: {str(e)}"
                        ) from e
        if response is None:
            raise RuntimeError("OpenAI API failed after retries with no response")
        output = ""
        if (
            response.choices
            and response.choices[0].message
            and response.choices[0].message.content
        ):
            output = response.choices[0].message.content

        tokens = (
            response.usage.total_tokens
            if getattr(response, "usage", None)
            else None
        )
        return {
            "output": output,
            "tokens": tokens,
            "model_used": model,
        }