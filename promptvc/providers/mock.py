from .base import BaseProvider


class MockProvider(BaseProvider):
    def run(self, prompt: str) -> dict:
        return {
            "output": prompt[::-1],
            "tokens": len(prompt.split()),
        }