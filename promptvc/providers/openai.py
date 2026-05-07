import os

import openai

from .base import BaseProvider


class OpenAIProvider(BaseProvider):
    def __init__(self):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not set")
        self._client = openai.OpenAI(api_key=api_key)

    def run(self, prompt: str) -> dict:
        try:
            response = self._client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
            )
        except openai.OpenAIError as e:
            raise RuntimeError(f"OpenAI API error: {e}") from e

        output = response.choices[0].message.content
        tokens = response.usage.total_tokens if response.usage else None

        return {
            "output": output,
            "tokens": tokens,
        }