from __future__ import annotations


def apply_unified_diff(original: str, diff: str) -> str:
    original_lines = original.splitlines()
    diff_lines = diff.splitlines()

    result = []
    i = 0  # pointer for original_lines

    for line in diff_lines:
        if line.startswith(("---", "+++", "@@")):
            continue

        if line.startswith("- "):
            content = line[2:]
            if i >= len(original_lines) or original_lines[i] != content:
                raise ValueError(f"Mismatch while removing: {content!r}")
            i += 1  # skip (remove)

        elif line.startswith("+ "):
            content = line[2:]
            result.append(content)

        else:
            # unchanged line (context)
            if i >= len(original_lines):
                raise ValueError("Unexpected end of original content")
            result.append(original_lines[i])
            i += 1

    # append remaining original lines
    result.extend(original_lines[i:])

    return "\n".join(result)