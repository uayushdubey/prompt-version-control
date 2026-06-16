from __future__ import annotations

import difflib
from typing import Dict, List, Literal, TypedDict

__all__ = [
    "compute_diff",
    "format_diff",
    "compute_diff_stats",
    "validate_unified_diff",
    "apply_unified_diff",
]


DiffMode = Literal["word", "char", "line"]
_VALID_MODES = {"word", "char", "line"}
_KNOWN_PREFIXES = {"- ", "+ ", "  "}


class DiffEntry(TypedDict):
    type: Literal["add", "remove", "same"]
    value: str


def compute_diff(
    text1: str,
    text2: str,
    mode: DiffMode = "word",
    ignore_whitespace: bool = False,
) -> List[str]:
    """
    Compute a diff between two prompt texts.

    Args:
        text1: Original text
        text2: Modified text
        mode: "word" (default), "char", or "line"
        ignore_whitespace: If True, normalize whitespace before diff

    Returns:
        List[str]: Tagged diff lines:
            "- value" → removed
            "+ value" → added
            "  value" → unchanged

    Raises:
        TypeError: If inputs are not strings
        ValueError: If mode is invalid
    """
    if not isinstance(text1, str) or not isinstance(text2, str):
        raise TypeError(
            f"Both arguments must be str, got "
            f"{type(text1).__name__!r} and {type(text2).__name__!r}."
        )

    if ignore_whitespace:
        text1 = " ".join(text1.split())
        text2 = " ".join(text2.split())

    tokens1 = _tokenize(text1, mode)
    tokens2 = _tokenize(text2, mode)

    entries = _build_diff_entries(tokens1, tokens2)
    return [_entry_to_string(e) for e in entries]


def format_diff(diff_lines: List[str], separator: str = "\n") -> str:
    """Join diff lines into a printable string."""
    return separator.join(diff_lines)


def compute_diff_stats(diff_lines: List[str]) -> Dict[str, int]:
    """
    Return counts of added, removed, and unchanged lines in a diff.

    Args:
        diff_lines: Output of compute_diff()

    Returns:
        dict with keys: "added", "removed", "unchanged"
    """
    stats: Dict[str, int] = {"added": 0, "removed": 0, "unchanged": 0}

    for line in diff_lines:
        prefix = line[:2] if len(line) >= 2 else ""
        if prefix == "+ ":
            stats["added"] += 1
        elif prefix == "- ":
            stats["removed"] += 1
        elif prefix == "  ":
            stats["unchanged"] += 1

    return stats


def _tokenize(text: str, mode: DiffMode) -> List[str]:
    """
    Split text into tokens based on the given mode.

    Raises:
        ValueError: If mode is not one of the supported values.
    """
    if not text:
        return []

    if mode == "word":
        return text.split()
    elif mode == "char":
        return list(text)
    elif mode == "line":
        return text.splitlines()
    else:
        raise ValueError(
            f"Invalid diff mode: '{mode}'. "
            f"Expected one of: {', '.join(sorted(_VALID_MODES))}."
        )


def _build_diff_entries(tokens1: List[str], tokens2: List[str]) -> List[DiffEntry]:
    """
    Produce a list of structured DiffEntry objects from two token sequences.

    Filters out ndiff metadata lines (e.g. '? ...' hint lines).
    """
    entries: List[DiffEntry] = []

    for line in difflib.ndiff(tokens1, tokens2):
        prefix = line[:2]
        if prefix not in _KNOWN_PREFIXES:
            continue
        entries.append(_make_entry(prefix, line[2:]))

    return entries


def _make_entry(prefix: str, value: str) -> DiffEntry:
    """Convert an ndiff prefix and value into a structured DiffEntry."""
    type_map = {"- ": "remove", "+ ": "add", "  ": "same"}
    return {"type": type_map[prefix], "value": value}


def _entry_to_string(entry: DiffEntry) -> str:
    """Serialize a DiffEntry back to a tagged string."""
    prefix_map = {"remove": "- ", "add": "+ ", "same": "  "}
    return f"{prefix_map[entry['type']]}{entry['value']}"


# ── Unified Diff Application (from diff_apply.py) ───────────────────────────────────

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
