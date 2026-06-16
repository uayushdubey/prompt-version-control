from __future__ import annotations

import os
from typing import Any, Dict, Iterator, Optional

from .base import BaseProvider


class OpenAIProvider(BaseProvider):
    """
    OpenAI ChatCompletion provider.

    Supports:
    - All GPT-4, GPT-4o, o3, o4 model families
    - system_prompt injection
    - temperature, top_p, seed controls
    - Streaming output
    - Accurate input/output token split for cost calculation
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        try:
            import openai  # noqa: F401
        except ImportError:
            raise ImportError(
                "The 'openai' library is required to use OpenAIProvider. "
                "Install it with: pip install promptvc[openai]"
            )
        api_key = self.config.get("api_key") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY not set. "
                "Set it via environment variable or: promptvc secrets set openai <key>"
            )
        import openai as _openai
        self._client = _openai.OpenAI(api_key=api_key)

    def run(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Execute a prompt against the OpenAI Chat Completions API.

        Kwargs:
            model (str): Model ID. Default: "gpt-4o-mini"
            max_tokens (int): Max output tokens. Default: None (model default)
            temperature (float): Sampling temperature 0-2. Default: 1.0
            top_p (float): Nucleus sampling. Default: None
            seed (int): Deterministic seed. Default: None
            system_prompt (str): System message content. Default: None
            timeout (float): Request timeout. Default: 60
            messages (list): Raw messages list to override prompt+system_prompt. Default: None

        Returns:
            dict with keys:
                output (str): Generated text
                tokens (int): Total tokens
                input_tokens (int): Prompt tokens
                output_tokens (int): Completion tokens
                model_used (str): Actual model ID
        """
        import openai as _openai

        model = kwargs.get("model", "gpt-4o-mini")
        max_tokens = kwargs.get("max_tokens")
        temperature = kwargs.get("temperature")
        top_p = kwargs.get("top_p")
        seed = kwargs.get("seed")
        system_prompt = kwargs.get("system_prompt")
        timeout = kwargs.get("timeout", 60)
        raw_messages = kwargs.get("messages")

        # Build messages list
        if raw_messages is not None:
            messages = raw_messages
        else:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

        create_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "timeout": timeout,
        }

        if max_tokens is not None:
            create_kwargs["max_tokens"] = int(max_tokens)

        if temperature is not None:
            create_kwargs["temperature"] = float(temperature)

        if top_p is not None:
            create_kwargs["top_p"] = float(top_p)

        if seed is not None:
            create_kwargs["seed"] = int(seed)

        try:
            response = self._retry_with_backoff(
                lambda: self._client.chat.completions.create(**create_kwargs),
                transient_exceptions=(_openai.APIConnectionError, _openai.InternalServerError),
                max_retries=3,
                base_delay=1.0,
            )
        except _openai.OpenAIError as e:
            raise RuntimeError(f"OpenAI API failed: {e}") from e

        if response is None:
            raise RuntimeError("OpenAI API failed after retries with no response")

        output = ""
        if (
            response.choices
            and response.choices[0].message
            and response.choices[0].message.content
        ):
            output = response.choices[0].message.content

        input_tokens: Optional[int] = None
        output_tokens: Optional[int] = None
        total_tokens: Optional[int] = None

        if getattr(response, "usage", None):
            input_tokens = getattr(response.usage, "prompt_tokens", None)
            output_tokens = getattr(response.usage, "completion_tokens", None)
            total_tokens = getattr(response.usage, "total_tokens", None)
            if total_tokens is None and input_tokens is not None and output_tokens is not None:
                total_tokens = input_tokens + output_tokens

        return {
            "output": output,
            "tokens": total_tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model_used": response.model if hasattr(response, "model") and response.model else model,
        }

    def stream(self, prompt: str, **kwargs) -> Iterator[str]:
        """Stream output chunks from the OpenAI API."""
        import openai as _openai

        model = kwargs.get("model", "gpt-4o-mini")
        system_prompt = kwargs.get("system_prompt")
        temperature = kwargs.get("temperature")
        max_tokens = kwargs.get("max_tokens")
        timeout = kwargs.get("timeout", 60)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        create_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "timeout": timeout,
            "stream": True,
        }
        if temperature is not None:
            create_kwargs["temperature"] = float(temperature)
        if max_tokens is not None:
            create_kwargs["max_tokens"] = int(max_tokens)

        try:
            stream = self._client.chat.completions.create(**create_kwargs)
            for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield delta.content
        except _openai.OpenAIError as e:
            raise RuntimeError(f"OpenAI streaming failed: {e}") from e