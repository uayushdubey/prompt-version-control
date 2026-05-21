from __future__ import annotations

import io
import os
import sys
import time
import threading
from contextlib import contextmanager
from typing import Generator, List, Optional, Sequence

# ── Force UTF-8 output on Windows so box-drawing/emoji chars work ─────────────
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
    except Exception:
        pass


ENABLE_COLOR: bool = (
    "NO_COLOR" not in os.environ
    and sys.stdout.isatty()
)


class Color:
    RESET      = "\033[0m"
    BOLD       = "\033[1m"
    DIM        = "\033[2m"
    ITALIC     = "\033[3m"
    RED        = "\033[31m"
    GREEN      = "\033[32m"
    YELLOW     = "\033[33m"
    BLUE       = "\033[34m"
    MAGENTA    = "\033[35m"
    CYAN       = "\033[36m"
    WHITE      = "\033[37m"
    BOLD_GREEN = "\033[1;32m"
    BOLD_RED   = "\033[1;31m"
    BOLD_CYAN  = "\033[1;36m"
    BOLD_BLUE  = "\033[1;34m"
    BOLD_YELLOW = "\033[1;33m"
    BOLD_MAGENTA = "\033[1;35m"


def _colorize(text: str, *codes: str) -> str:
    if not ENABLE_COLOR:
        return text
    prefix = "".join(codes)
    return f"{prefix}{text}{Color.RESET}"


# ── Basic helpers (backward-compatible) ───────────────────────────────────────

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


def dim(text: str) -> str:
    return _colorize(text, Color.DIM)


def bold(text: str) -> str:
    return _colorize(text, Color.BOLD)


def muted(text: str) -> str:
    return _colorize(text, Color.DIM, Color.WHITE)


def safe_print(text: str = "") -> None:
    try:
        print(text)
    except (UnicodeEncodeError, UnicodeDecodeError):
        try:
            print(text.encode("utf-8", "replace").decode("utf-8", "replace"))
        except Exception:
            print(text.encode("ascii", "replace").decode())


def print_success(text: str) -> None:
    safe_print(success(text))


def print_error(text: str) -> None:
    safe_print(error(text))


def print_warning(text: str) -> None:
    safe_print(warning(text))


def print_info(text: str) -> None:
    safe_print(info(text))


def get_symbol(ok: bool = True) -> str:
    try:
        "✓".encode("utf-8")
        return "✓" if ok else "✗"
    except Exception:
        return "[OK]" if ok else "[ERR]"


# ── Diff rendering ─────────────────────────────────────────────────────────────

def pretty_diff(diff: str) -> str:
    lines = []
    for line in diff.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            lines.append(_colorize(line, Color.DIM))
        elif line.startswith("+"):
            lines.append(_colorize(line, Color.GREEN))
        elif line.startswith("-"):
            lines.append(_colorize(line, Color.RED))
        elif line.startswith("@@"):
            lines.append(_colorize(line, Color.CYAN, Color.BOLD))
        else:
            lines.append(line)
    return "\n".join(lines)


# ── Table renderer ─────────────────────────────────────────────────────────────

def print_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    *,
    title: Optional[str] = None,
    col_colors: Optional[Sequence[Optional[str]]] = None,
) -> None:
    """
    Print a Unicode box-drawing table to stdout.

    Example:
        print_table(["Version", "Tokens", "Status"], [["v1", "42", "unlocked"]])
    """
    all_rows = [list(headers)] + [list(r) for r in rows]
    col_count = max(len(r) for r in all_rows) if all_rows else 0

    # Pad all rows to same width
    for r in all_rows:
        while len(r) < col_count:
            r.append("")

    # Strip ANSI codes for width measurement
    def visible_len(s: str) -> int:
        import re
        return len(re.sub(r"\033\[[0-9;]*m", "", s))

    col_widths = [
        max(visible_len(row[c]) for row in all_rows)
        for c in range(col_count)
    ]

    def pad(s: str, width: int) -> str:
        vl = visible_len(s)
        return s + " " * (width - vl)

    sep_line  = "┼".join("─" * (w + 2) for w in col_widths)
    top_line  = "┬".join("─" * (w + 2) for w in col_widths)
    bot_line  = "┴".join("─" * (w + 2) for w in col_widths)

    if title:
        total_width = sum(w + 3 for w in col_widths) - 1
        title_str = f" {title} "
        padding = max(0, total_width - len(title_str))
        left_pad = padding // 2
        right_pad = padding - left_pad
        safe_print(_colorize(f"┌{'─' * left_pad}{title_str}{'─' * right_pad}┐", Color.BOLD_CYAN))
    else:
        safe_print(_colorize(f"┌{top_line}┐", Color.DIM))

    # Header row
    header_cells = []
    for c, h in enumerate(headers):
        cell_text = pad(h, col_widths[c])
        header_cells.append(_colorize(f" {cell_text} ", Color.BOLD))
    safe_print(_colorize("│", Color.DIM) + _colorize("│", Color.DIM).join(header_cells) + _colorize("│", Color.DIM))
    safe_print(_colorize(f"├{sep_line}┤", Color.DIM))

    # Data rows
    for row in rows:
        cells = []
        for c, cell in enumerate(row):
            color = (col_colors[c] if col_colors and c < len(col_colors) else None)
            padded = pad(cell, col_widths[c])
            if color and ENABLE_COLOR:
                cells.append(f" {color}{padded}{Color.RESET} ")
            else:
                cells.append(f" {padded} ")
        safe_print(_colorize("│", Color.DIM) + _colorize("│", Color.DIM).join(cells) + _colorize("│", Color.DIM))

    safe_print(_colorize(f"└{bot_line}┘", Color.DIM))


# ── Bordered box ───────────────────────────────────────────────────────────────

def print_box(title: str, lines: Sequence[str], *, color: str = Color.BOLD_CYAN) -> None:
    """
    Print a bordered panel with a title.

    Example:
        print_box("Run Result", ["Provider: openai", "Tokens: 312"])
    """
    import re

    def visible_len(s: str) -> int:
        return len(re.sub(r"\033\[[0-9;]*m", "", s))

    max_content = max((visible_len(l) for l in lines), default=0)
    title_str = f" {title} "
    width = max(max_content + 2, len(title_str) + 2)

    padding_total = width - len(title_str)
    lp = padding_total // 2
    rp = padding_total - lp

    safe_print(_colorize(f"┌{'─' * lp}{title_str}{'─' * rp}┐", color))
    for line in lines:
        vl = visible_len(line)
        right_pad = " " * (width - vl - 1)
        safe_print(_colorize("│", color) + f" {line}{right_pad}" + _colorize("│", color))
    safe_print(_colorize(f"└{'─' * width}┘", color))


# ── Inline badge ───────────────────────────────────────────────────────────────

def badge(label: str, value: str, label_color: str = Color.DIM, value_color: str = Color.BOLD) -> str:
    """Return a colored 'label: value' string."""
    return _colorize(f"{label}:", label_color) + " " + _colorize(value, value_color)


# ── Divider ────────────────────────────────────────────────────────────────────

def divider(width: int = 60, char: str = "─") -> None:
    safe_print(_colorize(char * width, Color.DIM))


# ── Spinner ───────────────────────────────────────────────────────────────────

class _Spinner:
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message: str) -> None:
        self.message = message
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)

    def _spin(self) -> None:
        i = 0
        while not self._stop_event.is_set():
            frame = self.FRAMES[i % len(self.FRAMES)]
            colored = _colorize(frame, Color.CYAN)
            try:
                sys.stdout.write(f"\r{colored} {self.message}  ")
                sys.stdout.flush()
            except Exception:
                pass
            time.sleep(0.08)
            i += 1

    def start(self) -> None:
        if ENABLE_COLOR:
            self._thread.start()

    def stop(self, final_msg: Optional[str] = None) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=0.5)
        try:
            sys.stdout.write("\r\033[K")  # clear line
            sys.stdout.flush()
        except Exception:
            pass
        if final_msg:
            safe_print(final_msg)


@contextmanager
def spinner(message: str, done_msg: Optional[str] = None) -> Generator[None, None, None]:
    """Context manager that shows a spinner while work is being done."""
    s = _Spinner(message)
    s.start()
    try:
        yield
    finally:
        s.stop(done_msg)


# ── Error panel ────────────────────────────────────────────────────────────────

def print_error_panel(
    what: str,
    where: Optional[str] = None,
    tips: Optional[List[str]] = None,
    hint_cmd: Optional[str] = None,
) -> None:
    """
    Print a structured error panel with actionable guidance.

    Example output:
        ✗ Error: Missing required variable 'code'
          Where : fix_code @ v2
          Tip   : Supply it with --var code="<value>"
          Run   : promptvc inspect fix_code v2
    """
    safe_print(_colorize(f"\n✗ {what}", Color.BOLD_RED))
    if where:
        safe_print(f"  {_colorize('Where', Color.DIM)} : {where}")
    if tips:
        for i, tip in enumerate(tips):
            label = "Tip  " if i == 0 else "     "
            safe_print(f"  {_colorize(label, Color.DIM)} : {tip}")
    if hint_cmd:
        safe_print(f"  {_colorize('Run  ', Color.DIM)} : {_colorize(hint_cmd, Color.CYAN)}")
    safe_print("")