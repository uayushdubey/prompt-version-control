from __future__ import annotations

import os
from typing import Any, Dict, Optional

from .base import BaseProvider


class AnthropicProvider(BaseProvider):
    """
    Anthropic Claude provider.

    Supports:
    - All Claude-3 and Claude-4 model families
    - system_prompt injection
    - temperature, top_p, top_k controls
    - Accurate input/output token split for cost calculation
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        try:
            import anthropic  # noqa: F401
        except ImportError:
            raise ImportError(
                "The 'anthropic' library is required to use AnthropicProvider. "
                "Install it with: pip install promptvc[anthropic]"
            )
        api_key = self.config.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY not set. "
                "Set it via environment variable or: promptvc secrets set anthropic <key>"
            )
        import anthropic as _anthropic
        self._client = _anthropic.Anthropic(api_key=api_key)

    def run(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """
        Execute a prompt against the Anthropic API.

        Kwargs:
            model (str): Model ID. Default: "claude-3-5-haiku-20241022"
            max_tokens (int): Max output tokens. Default: 2048
            temperature (float): Sampling temperature 0-1. Default: 1.0
            top_p (float): Nucleus sampling probability. Default: None
            top_k (int): Top-k sampling. Default: None
            system_prompt (str): System message injected before the user turn. Default: None
            timeout (float): Request timeout in seconds. Default: 60
            messages (list): Pass raw messages list to override prompt string. Default: None

        Returns:
            dict with keys:
                output (str): Generated text
                tokens (int): Total tokens (input + output)
                input_tokens (int): Prompt tokens
                output_tokens (int): Completion tokens
                model_used (str): Actual model ID used
        """
        model = kwargs.get("model", "claude-3-5-haiku-20241022")
        max_tokens = kwargs.get("max_tokens", 2048)
        temperature = kwargs.get("temperature")
        top_p = kwargs.get("top_p")
        top_k = kwargs.get("top_k")
        system_prompt = kwargs.get("system_prompt")
        timeout = kwargs.get("timeout", 60)
        raw_messages = kwargs.get("messages")

        # Build messages list
        if raw_messages is not None:
            messages = []
            anthropic_system = system_prompt
            for msg in raw_messages:
                if msg.get("role") == "system":
                    if anthropic_system:
                        anthropic_system += "\n" + msg.get("content", "")
                    else:
                        anthropic_system = msg.get("content", "")
                else:
                    role = msg.get("role", "user")
                    if role in ("model", "assistant"):
                        role = "assistant"
                    else:
                        role = "user"
                    messages.append({"role": role, "content": msg.get("content", "")})
            system_prompt = anthropic_system
        else:
            messages = [{"role": "user", "content": prompt}]

        create_kwargs: Dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }

        if system_prompt:
            create_kwargs["system"] = system_prompt

        if temperature is not None:
            create_kwargs["temperature"] = float(temperature)

        if top_p is not None:
            create_kwargs["top_p"] = float(top_p)

        if top_k is not None:
            create_kwargs["top_k"] = int(top_k)

        try:
            import anthropic as _anthropic
            response = self._retry_with_backoff(
                lambda: self._client.messages.create(**create_kwargs),
                transient_exceptions=(_anthropic.InternalServerError, _anthropic.APIConnectionError),
                max_retries=3,
                base_delay=1.0,
            )
        except Exception as e:
            raise RuntimeError(f"Anthropic API failed: {e}") from e

        if response is None:
            raise RuntimeError("Anthropic API failed after retries with no response")

        # Extract text output
        output = ""
        if getattr(response, "content", None):
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    output = block.text
                    break

        # Accurate input/output token split
        input_tokens: Optional[int] = None
        output_tokens: Optional[int] = None
        total_tokens: Optional[int] = None

        if getattr(response, "usage", None):
            input_tokens = getattr(response.usage, "input_tokens", None)
            output_tokens = getattr(response.usage, "output_tokens", None)
            if input_tokens is not None and output_tokens is not None:
                total_tokens = input_tokens + output_tokens
            elif input_tokens is not None:
                total_tokens = input_tokens
            elif output_tokens is not None:
                total_tokens = output_tokens

        return {
            "output": output,
            "tokens": total_tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model_used": model,
        }
