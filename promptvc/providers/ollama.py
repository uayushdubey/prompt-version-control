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
        stream = kwargs.get("stream", False)
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": stream
        }

        retries = 2
        response = None

        for attempt in range(retries + 1):
            try:
                response = requests.post(self.base_url, json=payload, timeout=timeout)
                response.raise_for_status()
                break
            except requests.exceptions.ConnectionError as e:
                if attempt < retries:
                    time.sleep(0.5 * (attempt + 1))
                else:
                    raise RuntimeError("Ollama is not running. Start with: ollama serve") from e
            except requests.exceptions.RequestException as e:
                if attempt < retries:
                    time.sleep(0.5 * (attempt + 1))
                else:
                    raise RuntimeError(
                        f"Ollama API failed: {e}. Make sure model '{model}' is installed (run: ollama pull {model})") from e

        if response is None:
            raise RuntimeError("Ollama API failed after retries with no response")

        try:
            response_json = response.json()
        except ValueError as e:
            raise RuntimeError(f"Failed to parse Ollama JSON response: {e}") from e

        if "response" not in response_json:
            raise RuntimeError(f"Invalid Ollama response: {response_json}")
        output = response_json.get("response") or ""

        if "error" in response_json:
            raise RuntimeError(f"Ollama error: {response_json['error']}")
        return {
            "output": output,
            "tokens": None,
            "model_used": model,
        }
