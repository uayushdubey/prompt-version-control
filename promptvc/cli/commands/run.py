from __future__ import annotations

import argparse

from promptvc.core.repo import PromptRepo
from promptvc.core import PromptVCError
from promptvc.providers.mock import MockProvider


def run_command(args: argparse.Namespace) -> None:
    repo = PromptRepo()
    provider = MockProvider()

    try:
        result = repo.run(args.name, args.version, provider)

        print(f"\n✓ Ran {args.name}@{args.version}")
        print(f"\nOutput:\n{result['output']}")
        print(f"\nTokens: {result['tokens']}")

    except PromptVCError as exc:
        print(f"✗ {exc}")
    except ValueError as exc:
        print(f"✗ Invalid input: {exc}")