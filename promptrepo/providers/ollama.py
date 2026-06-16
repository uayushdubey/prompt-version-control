import time
import requests
from typing import Any, Dict, Optional

from .base import BaseProvider


class OllamaProvider(BaseProvider):
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.base_url = self.config.get("base_url", "http://localhost:11434/api/generate")
    def run(self, prompt: str, **kwargs) -> Dict[str, Any]:
        model = kwargs.get("model", "llama3")
        timeout = kwargs.get("timeout", 60)
        raw_messages = kwargs.get("messages")

        if raw_messages is not None:
            url = self.base_url.replace("/api/generate", "/api/chat")
            payload = {
                "model": model,
                "messages": raw_messages,
                "stream": False,
            }
        else:
            url = self.base_url
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
            }

        try:
            response = self._retry_with_backoff(
                lambda: requests.post(url, json=payload, timeout=timeout),
                transient_exceptions=(requests.exceptions.RequestException,),
                max_retries=2,
                base_delay=0.5,
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError("Ollama is not running. Start with: ollama serve") from e
        except requests.exceptions.RequestException as e:
            raise RuntimeError(
                f"Ollama API failed: {e}. Make sure model '{model}' is installed (run: ollama pull {model})"
            ) from e

        if response is None:
            raise RuntimeError("Ollama API failed after retries with no response")

        try:
            response_json = response.json()
        except ValueError as e:
            raise RuntimeError(f"Failed to parse Ollama JSON response: {e}") from e

        # Check for error before trusting the response field
        if "error" in response_json:
            raise RuntimeError(f"Ollama error: {response_json['error']}")

        if raw_messages is not None:
            if "message" not in response_json:
                raise RuntimeError(f"Invalid Ollama response: {response_json}")
            output = response_json.get("message", {}).get("content") or ""
        else:
            if "response" not in response_json:
                raise RuntimeError(f"Invalid Ollama response: {response_json}")
            output = response_json.get("response") or ""

        prompt_tokens = response_json.get("prompt_eval_count") or 0
        eval_tokens = response_json.get("eval_count") or 0
        tokens = (prompt_tokens + eval_tokens) if (prompt_tokens or eval_tokens) else None

        return {
            "output": output,
            "tokens": tokens,
            "input_tokens": prompt_tokens if prompt_tokens else None,
            "output_tokens": eval_tokens if eval_tokens else None,
            "model_used": model,
        }
