from __future__ import annotations

import os
import sys


ENABLE_COLOR: bool = (
    "NO_COLOR" not in os.environ
    and sys.stdout.isatty()
)


class Color:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    RED    = "\033[31m"
    GREEN  = "\033[32m"
    YELLOW = "\033[33m"
    BLUE   = "\033[34m"
    CYAN   = "\033[36m"


def _colorize(text: str, *codes: str) -> str:
    if not ENABLE_COLOR:
        return text
    prefix = "".join(codes)
    return f"{prefix}{text}{Color.RESET}"


def success(text: str) -> str:
    return _colorize(text, Color.GREEN, Color.BOLD)


def error(text: str) -> str:
    return _colorize(text, Color.RED, Color.BOLD)


def warning(text: str) -> str:
    return _colorize(text, Color.YELLOW)


def info(text: str) -> str:
    return _colorize(text, Color.CYAN)


def section(title: str) -> str:
    rendered = f"--- {title} ---"
    return _colorize(rendered, Color.BOLD)


def header(text: str) -> str:
    return _colorize(text, Color.BLUE, Color.BOLD)


def pretty_diff(diff: str) -> str:
    """
    Render a unified diff with color highlighting.

    - '+' additions (excluding '+++') → green
    - '-' deletions (excluding '---') → red
    - '@@' hunk headers → cyan
    - file headers ('+++', '---') → dim
    - everything else unchanged
    """
    lines = []

    for line in diff.splitlines():
        # Skip coloring for file headers
        if line.startswith("+++ ") or line.startswith("--- "):
            lines.append(_colorize(line, Color.DIM))

        # Additions
        elif line.startswith("+"):
            lines.append(_colorize(line, Color.GREEN))

        # Deletions
        elif line.startswith("-"):
            lines.append(_colorize(line, Color.RED))

        # Hunk headers
        elif line.startswith("@@"):
            lines.append(_colorize(line, Color.CYAN, Color.BOLD))

        else:
            lines.append(line)

    return "\n".join(lines)

def print_success(text: str) -> None:
    print(success(text))


def print_error(text: str) -> None:
    print(error(text))


def print_warning(text: str) -> None:
    print(warning(text))


def print_info(text: str) -> None:
    print(info(text))

def dim(text: str) -> str:
    return _colorize(text, Color.DIM)