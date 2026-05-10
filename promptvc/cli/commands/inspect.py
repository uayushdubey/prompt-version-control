from __future__ import annotations

import argparse

from promptvc.core.repo import PromptRepo
from promptvc.utils.template import extract_variables


def inspect_command(args: argparse.Namespace) -> None:
    """
    Inspect a prompt version and display developer-relevant information.

    Loads the specified prompt version from the repository, extracts template
    variables, and prints a structured summary including content, variables,
    metadata, lock status, and an example usage hint.

    Args:
        args: Parsed CLI arguments containing 'name' and 'version'.

    Raises:
        ValueError: If the prompt version is not found or has no 'prompt' field.
    """
    repo = PromptRepo()
    prompt_data = repo.get(args.name, args.version)

    if prompt_data is None:
        raise ValueError(f"Prompt '{args.name}@{args.version}' not found.")

    raw_prompt = prompt_data.get("prompt")
    if raw_prompt is None:
        raise ValueError(f"Prompt '{args.name}@{args.version}' has no 'prompt' field.")

    metadata = prompt_data.get("metadata", {})
    locked = prompt_data.get("locked", False)
    variables = extract_variables(raw_prompt)

    print(f"Prompt: {args.name}@{args.version}")

    print("\n--- Content ---")
    print(raw_prompt)

    print("\n--- Variables ---")
    if variables:
        for var in sorted(variables):
            print(f"  {var}")
    else:
        print("  None")

    print("\n--- Metadata ---")
    if not metadata:
        print("  None")
    else:
        if metadata.get("timestamp") is not None:
            print(f"  Timestamp : {metadata['timestamp']}")
        if metadata.get("tokens") is not None:
            print(f"  Tokens    : {metadata['tokens']}")
        if metadata.get("hash") is not None:
            print(f"  Hash      : {metadata['hash']}")

    print("\n--- Status ---")
    print(f"  Locked: {'Yes' if locked else 'No'}")

    if variables:
        var_flags = " ".join(f'--var {var}="value"' for var in sorted(variables))
        print("\n--- Example Usage ---")
        print(f"  promptvc run {args.name} {args.version} {var_flags}")