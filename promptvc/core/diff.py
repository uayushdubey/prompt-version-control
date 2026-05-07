from __future__ import annotations

import difflib
from typing import Dict, List, Literal, TypedDict

__all__ = ["compute_diff", "format_diff", "compute_diff_stats"]


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


# -------------------------
# Internal Helpers
# -------------------------

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