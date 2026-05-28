import os
import time
from typing import Any, Dict, Optional

from .base import BaseProvider


class GeminiProvider(BaseProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError(
                "The 'google-generativeai' library is required to use GeminiProvider. "
                "Install it with: pip install promptvc[gemini]"
            )
        api_key = self.config.get("api_key") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set")
        self._api_key = api_key
        genai.configure(api_key=self._api_key)
        self._models: Dict[str, Any] = {}

    def run(self, prompt: str, **kwargs) -> Dict[str, Any]:
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError(
                "The 'google-generativeai' library is required to use GeminiProvider. "
                "Install it with: pip install promptvc[gemini]"
            )
        model_name = kwargs.get("model", "gemini-1.5-pro")
        timeout = kwargs.get("timeout", 60)
        max_tokens = kwargs.get("max_tokens")

        if model_name not in self._models:
            self._models[model_name] = genai.GenerativeModel(model_name)
        model = self._models[model_name]
        
        generate_kwargs: Dict[str, Any] = {
            "request_options": {"timeout": timeout}
        }
        
        if max_tokens is not None:
            generate_kwargs["generation_config"] = genai.types.GenerationConfig(
                max_output_tokens=max_tokens
            )

        try:
            response = self._retry_with_backoff(
                lambda: model.generate_content(prompt, **generate_kwargs),
                transient_exceptions=(Exception,),
                max_retries=2,
                base_delay=0.5,
            )
        except Exception as e:
            raise RuntimeError(f"Gemini API failed: {str(e)}") from e

        if response is None:
            raise RuntimeError("Gemini API failed after retries with no response")
        output = ""
        if hasattr(response, "text") and response.text:
            output = response.text
        elif hasattr(response, "candidates") and response.candidates:
            try:
                output = response.candidates[0].content.parts[0].text
            except Exception:
                output = ""

        tokens = None
        input_tokens = None
        output_tokens = None
        if response and hasattr(response, "usage_metadata") and response.usage_metadata:
            tokens = getattr(response.usage_metadata, "total_token_count", None)
            input_tokens = getattr(response.usage_metadata, "prompt_token_count", None)
            output_tokens = getattr(response.usage_metadata, "candidates_token_count", None)

        return {
            "output": output,
            "tokens": tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model_used": model_name,
        }

