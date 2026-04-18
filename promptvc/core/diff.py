from __future__ import annotations

import difflib
from typing import List, Literal

__all__ = ["compute_diff", "format_diff"]


DiffMode = Literal["word", "char", "line"]


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

    result: List[str] = []

    for line in difflib.ndiff(tokens1, tokens2):
        prefix = line[:2]

        if prefix not in ("- ", "+ ", "  "):
            continue

        result.append(f"{prefix}{line[2:]}")

    return result


def format_diff(diff_lines: List[str], separator: str = "\n") -> str:
    """
    Join diff lines into a printable string.
    """
    return separator.join(diff_lines)


# -------------------------
# Helpers
# -------------------------

def _tokenize(text: str, mode: DiffMode) -> List[str]:
    if mode == "word":
        return text.split()
    elif mode == "char":
        return list(text)
    elif mode == "line":
        return text.splitlines()
    else:
        raise ValueError(f"Invalid diff mode: {mode}")