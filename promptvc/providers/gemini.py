import os
import time
from typing import Any, Dict, Optional

import google.generativeai as genai

from .base import BaseProvider


class GeminiProvider(BaseProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        api_key = self.config.get("api_key") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set")
        genai.configure(api_key=api_key)

    def run(self, prompt: str, **kwargs) -> Dict[str, Any]:
        model_name = kwargs.get("model", "gemini-1.5-pro")
        timeout = kwargs.get("timeout")
        max_tokens = kwargs.get("max_tokens")

        model = genai.GenerativeModel(model_name)
        
        generate_kwargs: Dict[str, Any] = {}
        
        if max_tokens is not None:
            generate_kwargs["generation_config"] = genai.types.GenerationConfig(
                max_output_tokens=max_tokens
            )
            
        if timeout is not None:
            generate_kwargs["request_options"] = {"timeout": timeout}

        retries = 2
        response = None
        for attempt in range(retries + 1):
            try:
                response = model.generate_content(prompt, **generate_kwargs)
                break
            except Exception as e:
                if attempt < retries:
                    time.sleep(0.5 * (attempt + 1))
                else:
                    raise RuntimeError(
                        f"Gemini API failed after {retries + 1} attempts: {str(e)}"
                    ) from e
                    
        if response is None:
            raise RuntimeError("Gemini API failed after retries with no response")

        try:
            output = response.text
        except Exception:
            # Handle cases where response is blocked by safety filters or empty
            output = ""

        return {
            "output": output,
            "tokens": None,
            "model_used": model_name,
        }
