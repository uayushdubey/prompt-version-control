from __future__ import annotations

from typing import List


def validate_unified_diff(diff: str) -> List[str]:
    """Return list of validation errors (empty = valid)."""
    errors = []
    lines = diff.splitlines()
    if not lines:
        errors.append("Empty diff")
        return errors

    has_header = False
    for idx, line in enumerate(lines):
        line_num = idx + 1
        if line.startswith(("---", "+++", "@@")):
            has_header = True
            continue
        if not (line.startswith("+") or line.startswith("-") or line.startswith(" ") or line == ""):
            errors.append(f"Line {line_num} does not start with '+', '-', or space: {line!r}")

    return errors


def apply_unified_diff(original: str, diff: str, *, validate: bool = True) -> str:
    """Apply diff with pre-validation."""
    if validate:
        errors = validate_unified_diff(diff)
        if errors:
            raise ValueError(f"Invalid diff: {'; '.join(errors)}")

    original_lines = original.splitlines()
    diff_lines = diff.splitlines()

    result = []
    i = 0  # pointer for original_lines

    for line_idx, line in enumerate(diff_lines):
        if line.startswith(("---", "+++", "@@")):
            continue

        if line.startswith("- "):
            content = line[2:]
            if i >= len(original_lines) or original_lines[i] != content:
                raise ValueError(f"Mismatch while removing at original line {i+1}: expected {content!r}, got {original_lines[i] if i < len(original_lines) else 'EOF'!r}")
            i += 1  # skip (remove)

        elif line.startswith("+ "):
            content = line[2:]
            result.append(content)

        elif line.startswith("-"):
            content = line[1:]
            if i >= len(original_lines) or original_lines[i] != content:
                raise ValueError(f"Mismatch while removing at original line {i+1}: expected {content!r}, got {original_lines[i] if i < len(original_lines) else 'EOF'!r}")
            i += 1

        elif line.startswith("+"):
            content = line[1:]
            result.append(content)

        else:
            # unchanged line (context)
            if line.startswith(" "):
                content = line[1:]
            else:
                content = line

            if i >= len(original_lines):
                raise ValueError(f"Unexpected end of original content at diff line {line_idx+1}")
            if original_lines[i] != content:
                raise ValueError(f"Mismatch in context line at original line {i+1}: expected {content!r}, got {original_lines[i]!r}")
            result.append(original_lines[i])
            i += 1

    # append remaining original lines
    result.extend(original_lines[i:])

    ret = "\n".join(result)
    if original.endswith("\n") and not ret.endswith("\n"):
        ret += "\n"
    return ret