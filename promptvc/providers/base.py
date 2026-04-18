class BaseProvider:
    def run(self, prompt: str) -> dict:
        raise NotImplementedError("Provider must implement run()")