from __future__ import annotations

import argparse

from promptvc.core.repo import PromptRepo
from promptvc.utils.template import extract_variables


def inspect_command(args: argparse.Namespace) -> None:
    """
    Inspect a prompt version and display developer-relevant information.
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
    schema = repo.get_schema(args.name, args.version)

    # Extract once (avoid duplication)
    variables = extract_variables(raw_prompt)
    schema_vars = schema.get("variables", {}) if schema else {}

    print(f"Prompt: {args.name}@{args.version}")

    print("\n--- Content ---")
    print(raw_prompt)

    print("\n--- Variables ---")

    if schema_vars:
        for var_name in sorted(schema_vars):
            var_info = schema_vars[var_name]

            required = var_info.get("required", False)
            req_label = "(required)" if required else "(optional)"

            var_type = var_info.get("type")
            type_label = f"[{var_type}]" if var_type else ""

            default = var_info.get("default")
            description = var_info.get("description")

            detail_parts = []
            if description:
                detail_parts.append(description)
            if default is not None:
                detail_parts.append(f"default: {default}")

            detail = " | ".join(detail_parts) if detail_parts else ""
            suffix = f"  - {detail}" if detail else ""

            print(f"  {var_name} {type_label} {req_label}{suffix}")

    else:
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
            print(f"  Timestamp: {metadata['timestamp']}")
        if metadata.get("tokens") is not None:
            print(f"  Tokens:    {metadata['tokens']}")
        if metadata.get("hash") is not None:
            print(f"  Hash:      {metadata['hash']}")

    print("\n--- Status ---")
    print(f"  Locked: {'Yes' if locked else 'No'}")

    print("\n--- Example Usage ---")

    if schema_vars:
        var_flags = " ".join(f'--var {var}="value"' for var in sorted(schema_vars))
        print(f"  promptvc run {args.name} {args.version} {var_flags}")
    elif variables:
        var_flags = " ".join(f'--var {var}="value"' for var in sorted(variables))
        print(f"  promptvc run {args.name} {args.version} {var_flags}")
    else:
        print(f"  promptvc run {args.name} {args.version}")