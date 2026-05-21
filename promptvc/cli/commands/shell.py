"""
promptvc/cli/commands/shell.py

`promptvc shell` — interactive REPL for prompt experimentation.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Dict, List, Optional

from promptvc.core.repo import PromptRepo
from promptvc.utils.config import get_config_value
from promptvc.providers.mock import MockProvider
from promptvc.providers.openai import OpenAIProvider
from promptvc.providers.gemini import GeminiProvider
from promptvc.providers.anthropic import AnthropicProvider
from promptvc.providers.ollama import OllamaProvider
from promptvc.providers.registry import register_provider, get_provider
from promptvc.utils.template import render_template, extract_variables
from promptvc.utils.console import (
    safe_print, print_box, print_table, badge,
    bold, dim, success, warning, _colorize, Color,
)
from promptvc.utils.cost import estimate_cost, format_cost, format_latency

for _name, _cls in [
    ("mock", MockProvider), ("openai", OpenAIProvider),
    ("gemini", GeminiProvider), ("anthropic", AnthropicProvider),
    ("ollama", OllamaProvider),
]:
    try:
        register_provider(_name, _cls)
    except ValueError:
        pass

# Try enabling readline for arrow-key history
try:
    import readline  # noqa: F401
    _READLINE = True
except ImportError:
    _READLINE = False


# ── REPL state ─────────────────────────────────────────────────────────────────

class ShellSession:
    def __init__(self) -> None:
        self.prompt_name: Optional[str] = None
        self.version: Optional[str] = None
        self.provider_name: str = get_config_value("provider") or "mock"
        self.model: Optional[str] = None
        self.variables: Dict[str, str] = {}
        self.history: List[Dict[str, Any]] = []   # [{input, output, tokens, latency_ms}]
        self.repo = PromptRepo()
        self.session_cost: float = 0.0

    def _update_model(self) -> None:
        self.model = get_config_value(f"models.{self.provider_name}")

    def prompt_ready(self) -> bool:
        return self.prompt_name is not None and self.version is not None

    def prompt_label(self) -> str:
        if self.prompt_ready():
            return f"{self.prompt_name}@{self.version}"
        return "(no prompt)"

    def ps1(self) -> str:
        label = _colorize(self.prompt_label(), Color.CYAN)
        prov  = _colorize(self.provider_name, Color.DIM)
        return f"{label} [{prov}]> "


# ── Command handlers ───────────────────────────────────────────────────────────

def _cmd_use(session: ShellSession, parts: List[str]) -> None:
    """use <name> <version>  — set active prompt"""
    if len(parts) < 3:
        safe_print(warning("  Usage: use <name> <version>"))
        return
    name, ver = parts[1], parts[2]
    try:
        session.repo.get_version_meta(name, ver)
        session.prompt_name = name
        session.version     = ver
        session.variables   = {}
        safe_print(success(f"  ✓ Now using {name} @ {ver}"))
    except Exception as exc:
        safe_print(warning(f"  ✗ {exc}"))


def _cmd_set_provider(session: ShellSession, parts: List[str]) -> None:
    """set provider <name>  — switch provider"""
    if len(parts) < 3 or parts[1] != "provider":
        safe_print(warning("  Usage: set provider <name>"))
        return
    session.provider_name = parts[2]
    session._update_model()
    safe_print(success(f"  ✓ Provider set to '{parts[2]}'"))


def _cmd_set_model(session: ShellSession, parts: List[str]) -> None:
    """set model <name>  — override model for this session"""
    if len(parts) < 3 or parts[1] != "model":
        safe_print(warning("  Usage: set model <name>"))
        return
    session.model = parts[2]
    safe_print(success(f"  ✓ Model set to '{parts[2]}'"))


def _cmd_var(session: ShellSession, parts: List[str]) -> None:
    """var <key>=<value>  — set a template variable"""
    if len(parts) < 2 or "=" not in parts[1]:
        safe_print(warning("  Usage: var key=value"))
        return
    kv = " ".join(parts[1:])
    k, v = kv.split("=", 1)
    session.variables[k.strip()] = v.strip()
    safe_print(dim(f"  {k.strip()} = {v.strip()}"))


def _cmd_vars(session: ShellSession) -> None:
    """vars  — list current variable values"""
    if not session.variables:
        safe_print(dim("  No variables set."))
        return
    rows = [[k, v] for k, v in session.variables.items()]
    print_table(["Variable", "Value"], rows)


def _cmd_run(session: ShellSession) -> None:
    """run  — execute the current prompt with current vars"""
    if not session.prompt_ready():
        safe_print(warning("  No prompt set. Use: use <name> <version>"))
        return

    try:
        prompt_data = session.repo.get_version_meta(
            session.prompt_name, session.version
        )
    except Exception as exc:
        safe_print(warning(f"  ✗ {exc}"))
        return

    raw_prompt = prompt_data.get("prompt", "")

    # Check for missing variables
    required = extract_variables(raw_prompt)
    missing  = required - set(session.variables.keys())
    if missing:
        safe_print(warning(f"  ⚠  Missing variables: {', '.join(sorted(missing))}"))
        safe_print(dim("  Set them with: var <key>=<value>"))
        return

    try:
        rendered = render_template(raw_prompt, session.variables)
    except Exception as exc:
        safe_print(warning(f"  ✗ Template error: {exc}"))
        return

    model_name = session.model or get_config_value(f"models.{session.provider_name}")
    kwargs: Dict[str, Any] = {}
    if model_name:
        kwargs["model"] = model_name

    try:
        provider = get_provider(session.provider_name)
    except Exception as exc:
        safe_print(warning(f"  ✗ Provider error: {exc}"))
        return

    t0 = time.monotonic()
    try:
        result = provider.run(rendered, **kwargs)
    except Exception as exc:
        safe_print(warning(f"  ✗ Provider failed: {exc}"))
        return
    latency_ms = (time.monotonic() - t0) * 1000

    output = result.get("output") or ""
    tokens = result.get("tokens")
    actual_model = result.get("model_used") or model_name or session.provider_name

    cost = None
    if tokens and actual_model:
        cost = estimate_cost(actual_model, int(tokens * 0.8), int(tokens * 0.2))
        if cost is not None:
            session.session_cost += cost

    session.history.append({
        "prompt_name": session.prompt_name,
        "version": session.version,
        "input": dict(session.variables),
        "output": output,
        "tokens": tokens,
        "latency_ms": round(latency_ms),
        "cost": cost,
    })

    safe_print()
    safe_print(dim("── Output ───────────────────────────────────────────"))
    safe_print(output)
    safe_print(dim("─────────────────────────────────────────────────────"))
    info_lines = [
        badge("Latency", format_latency(latency_ms)),
        badge("Tokens ", str(tokens) if tokens else "—"),
        badge("Cost   ", format_cost(cost)),
    ]
    safe_print()
    print_box("Run complete", info_lines)


def _cmd_history(session: ShellSession) -> None:
    """history  — show run history for this session"""
    if not session.history:
        safe_print(dim("  No runs in this session yet."))
        return
    rows = []
    for i, h in enumerate(session.history, 1):
        preview = (h["output"] or "")[:50].replace("\n", " ")
        rows.append([
            str(i),
            f"{h['prompt_name']}@{h['version']}",
            str(h.get("tokens") or "—"),
            format_latency(h["latency_ms"]),
            preview,
        ])
    print_table(["#", "Prompt", "Tokens", "Latency", "Output preview"], rows,
                title="Session History")


def _cmd_cost(session: ShellSession) -> None:
    """cost  — show estimated cost for this session"""
    if not session.history:
        safe_print(dim("  No runs yet."))
        return
    rows = []
    for i, h in enumerate(session.history, 1):
        rows.append([str(i), format_cost(h.get("cost")), str(h.get("tokens") or "—")])
    print_table(["#", "Cost", "Tokens"], rows)
    safe_print()
    safe_print(badge("Session total", format_cost(session.session_cost)))


def _cmd_inspect(session: ShellSession) -> None:
    """inspect  — show details of the current prompt"""
    if not session.prompt_ready():
        safe_print(warning("  No prompt set. Use: use <name> <version>"))
        return
    try:
        data = session.repo.get_version_meta(session.prompt_name, session.version)
        raw  = data.get("prompt", "")
        safe_print()
        safe_print(bold(f"  {session.prompt_name} @ {session.version}"))
        safe_print(dim("  " + "─" * 50))
        for line in raw.splitlines():
            safe_print(f"  {line}")
        safe_print(dim("  " + "─" * 50))
        vars_ = extract_variables(raw)
        if vars_:
            safe_print(dim(f"  Template vars: {', '.join(sorted(vars_))}"))
    except Exception as exc:
        safe_print(warning(f"  ✗ {exc}"))


def _cmd_help() -> None:
    rows = [
        ["use <name> <ver>",   "Set active prompt"],
        ["set provider <p>",   "Switch provider (openai/anthropic/gemini/ollama/mock)"],
        ["set model <m>",      "Override model for this session"],
        ["var key=value",      "Set a template variable"],
        ["vars",               "List current variables"],
        ["run",                "Execute current prompt"],
        ["inspect",            "Show current prompt text and variables"],
        ["history",            "Show session run history"],
        ["cost",               "Show session cost estimate"],
        ["clear",              "Clear terminal"],
        ["exit / quit",        "Exit the shell"],
        ["help",               "Show this help"],
    ]
    safe_print()
    print_table(["Command", "Description"], rows, title="promptvc shell")
    safe_print()


# ── Main REPL loop ─────────────────────────────────────────────────────────────

def shell_command(args: argparse.Namespace) -> None:
    session = ShellSession()

    safe_print()
    print_box(
        "promptvc shell",
        [
            dim("Interactive prompt experimentation"),
            dim("Type 'help' for commands, 'exit' to quit"),
        ],
    )
    safe_print()

    while True:
        try:
            raw = input(session.ps1()).strip()
        except (EOFError, KeyboardInterrupt):
            safe_print()
            safe_print(dim("  Bye!"))
            break

        if not raw:
            continue

        parts = raw.split()
        cmd   = parts[0].lower()

        if cmd in ("exit", "quit", "q"):
            safe_print(dim("  Bye!"))
            break
        elif cmd == "help":
            _cmd_help()
        elif cmd == "use":
            _cmd_use(session, parts)
        elif cmd == "set" and len(parts) >= 2 and parts[1] == "provider":
            _cmd_set_provider(session, parts)
        elif cmd == "set" and len(parts) >= 2 and parts[1] == "model":
            _cmd_set_model(session, parts)
        elif cmd == "var":
            _cmd_var(session, parts)
        elif cmd == "vars":
            _cmd_vars(session)
        elif cmd == "run":
            _cmd_run(session)
        elif cmd == "inspect":
            _cmd_inspect(session)
        elif cmd == "history":
            _cmd_history(session)
        elif cmd == "cost":
            _cmd_cost(session)
        elif cmd == "clear":
            os.system("cls" if os.name == "nt" else "clear")
        else:
            safe_print(warning(f"  Unknown command: '{cmd}'. Type 'help' for commands."))
