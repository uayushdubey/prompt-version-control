from __future__ import annotations

import os
from typing import Any, Dict, Iterator, Optional

from .base import BaseProvider


class GeminiProvider(BaseProvider):
    """
    Google Gemini provider.

    Supports:
    - Gemini 1.5, 2.0, 2.5 model families
    - system_prompt injection
    - temperature, top_p, top_k controls
    - Accurate input/output token split
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        try:
            import google.generativeai as genai  # noqa: F401
        except ImportError:
            raise ImportError(
                "The 'google-generativeai' library is required to use GeminiProvider. "
                "Install it with: pip install promptrepo[gemini]"
            )
        api_key = self.config.get("api_key") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY not set. "
                "Set it via environment variable or: promptrepo secrets set gemini <key>"
            )
        self._api_key = api_key
        genai.configure(api_key=self._api_key)
        self._models: Dict[str, Any] = {}

    def _get_model(self, model_name: str, system_prompt: Optional[str] = None):
        """Get or create a GenerativeModel instance, keyed by model+system."""
        import google.generativeai as genai
        cache_key = f"{model_name}::{system_prompt or ''}"
        if cache_key not in self._models:
            kwargs: Dict[str, Any] = {}
            if system_prompt:
                kwargs["system_instruction"] = system_prompt
            self._models[cache_key] = genai.GenerativeModel(model_name, **kwargs)
        return self._models[cache_key]

    def run(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Execute a prompt against the Gemini API.

        Kwargs:
            model (str): Model ID. Default: "gemini-2.0-flash"
            max_tokens (int): Max output tokens. Default: None
            temperature (float): Sampling temperature 0-2. Default: None
            top_p (float): Nucleus sampling. Default: None
            top_k (int): Top-k sampling. Default: None
            system_prompt (str): System instruction. Default: None
            timeout (float): Request timeout. Default: 60
            messages (list): Raw Gemini-format contents list. Default: None

        Returns:
            dict with keys:
                output (str): Generated text
                tokens (int): Total tokens
                input_tokens (int): Prompt tokens
                output_tokens (int): Candidate tokens
                model_used (str): Model ID used
        """
        import google.generativeai as genai

        model_name = kwargs.get("model", "gemini-2.0-flash")
        max_tokens = kwargs.get("max_tokens")
        temperature = kwargs.get("temperature")
        top_p = kwargs.get("top_p")
        top_k = kwargs.get("top_k")
        system_prompt = kwargs.get("system_prompt")
        timeout = kwargs.get("timeout", 60)
        raw_messages = kwargs.get("messages")
        # Build contents list
        gemini_system = system_prompt
        if raw_messages is not None:
            gemini_contents = []
            for msg in raw_messages:
                role = msg.get("role")
                content_text = msg.get("content", "")
                if role == "system":
                    if gemini_system:
                        gemini_system += "\n" + content_text
                    else:
                        gemini_system = content_text
                else:
                    if role == "assistant":
                        role = "model"
                    elif role not in ("user", "model"):
                        role = "user"
                    gemini_contents.append({
                        "role": role,
                        "parts": [{"text": content_text}]
                    })
            content = gemini_contents
        else:
            content = prompt

        model = self._get_model(model_name, gemini_system)

        # Build generation config
        gen_config_kwargs: Dict[str, Any] = {}
        if max_tokens is not None:
            gen_config_kwargs["max_output_tokens"] = int(max_tokens)
        if temperature is not None:
            gen_config_kwargs["temperature"] = float(temperature)
        if top_p is not None:
            gen_config_kwargs["top_p"] = float(top_p)
        if top_k is not None:
            gen_config_kwargs["top_k"] = int(top_k)

        generate_kwargs: Dict[str, Any] = {
            "request_options": {"timeout": timeout},
        }
        if gen_config_kwargs:
            generate_kwargs["generation_config"] = genai.types.GenerationConfig(**gen_config_kwargs)

        try:
            response = self._retry_with_backoff(
                lambda: model.generate_content(content, **generate_kwargs),
                transient_exceptions=(Exception,),
                max_retries=3,
                base_delay=1.0,
            )
        except Exception as e:
            raise RuntimeError(f"Gemini API failed: {e}") from e

        if response is None:
            raise RuntimeError("Gemini API failed after retries with no response")

        # Extract text
        output = ""
        if hasattr(response, "text") and response.text:
            output = response.text
        elif hasattr(response, "candidates") and response.candidates:
            try:
                output = response.candidates[0].content.parts[0].text
            except Exception:
                output = ""

        # Accurate token split
        input_tokens: Optional[int] = None
        output_tokens: Optional[int] = None
        total_tokens: Optional[int] = None

        if response and hasattr(response, "usage_metadata") and response.usage_metadata:
            input_tokens = getattr(response.usage_metadata, "prompt_token_count", None)
            output_tokens = getattr(response.usage_metadata, "candidates_token_count", None)
            total_tokens = getattr(response.usage_metadata, "total_token_count", None)
            if total_tokens is None and input_tokens is not None and output_tokens is not None:
                total_tokens = input_tokens + output_tokens

        return {
            "output": output,
            "tokens": total_tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model_used": model_name,
        }

    def stream(self, prompt: str, **kwargs) -> Iterator[str]:
        """Stream output from Gemini API."""
        import google.generativeai as genai

        model_name = kwargs.get("model", "gemini-2.0-flash")
        system_prompt = kwargs.get("system_prompt")
        temperature = kwargs.get("temperature")
        max_tokens = kwargs.get("max_tokens")
        timeout = kwargs.get("timeout", 60)

        model = self._get_model(model_name, system_prompt)

        gen_config_kwargs: Dict[str, Any] = {}
        if max_tokens is not None:
            gen_config_kwargs["max_output_tokens"] = int(max_tokens)
        if temperature is not None:
            gen_config_kwargs["temperature"] = float(temperature)

        generate_kwargs: Dict[str, Any] = {
            "request_options": {"timeout": timeout},
            "stream": True,
        }
        if gen_config_kwargs:
            generate_kwargs["generation_config"] = genai.types.GenerationConfig(**gen_config_kwargs)

        try:
            for chunk in model.generate_content(prompt, **generate_kwargs):
                if hasattr(chunk, "text") and chunk.text:
                    yield chunk.text
        except Exception as e:
            raise RuntimeError(f"Gemini streaming failed: {e}") from e
