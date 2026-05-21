from __future__ import annotations

import argparse

from promptvc.core.repo import PromptRepo
from promptvc.utils.template import extract_variables
from promptvc.utils.console import (
    safe_print, print_table, print_box, print_error_panel,
    badge, bold, dim, success, warning, _colorize, Color,
)


def inspect_command(args: argparse.Namespace) -> None:
    """Inspect a prompt version and display all developer-relevant information."""
    repo = PromptRepo()

    try:
        prompt_data = repo.get_version_meta(args.name, args.version)
    except Exception:
        print_error_panel(
            f"Prompt '{args.name} @ {args.version}' not found.",
            hint_cmd=f"promptvc log {args.name}",
        )
        return

    raw_prompt = prompt_data.get("prompt")
    if raw_prompt is None:
        print_error_panel(f"'{args.name}@{args.version}' has no prompt text.")
        return

    # Metadata lives directly on prompt_data, not in a nested "metadata" key
    locked    = prompt_data.get("locked", False)
    timestamp = prompt_data.get("timestamp", "—")
    tokens    = prompt_data.get("tokens", "—")
    sha_hash  = prompt_data.get("hash", "—")
    if sha_hash and sha_hash != "—":
        sha_hash = sha_hash[:16] + "…"  # truncate for readability

    schema      = repo.get_schema(args.name, args.version)
    schema_vars = schema.get("variables", {}) if schema else {}
    template_vars = extract_variables(raw_prompt)

    safe_print()
    safe_print(bold(f"  {args.name} @ {args.version}"))
    safe_print()

    # ── Prompt content ────────────────────────────────────────────────────────
    safe_print(dim("  ── Prompt ───────────────────────────────────────────"))
    for line in raw_prompt.splitlines():
        safe_print(f"  {line}")
    safe_print(dim("  ─────────────────────────────────────────────────────"))
    safe_print()

    # ── Variables ─────────────────────────────────────────────────────────────
    if schema_vars:
        headers = ["Variable", "Type", "Required", "Default", "Description"]
        rows = []
        for var_name in sorted(schema_vars):
            spec     = schema_vars[var_name]
            required = spec.get("required", False)
            req_str  = _colorize("yes", Color.BOLD_GREEN) if required else dim("no")
            default  = str(spec.get("default", "—"))
            vtype    = spec.get("type", "string")
            desc     = spec.get("description", "—")
            rows.append([var_name, vtype, req_str, default, desc])
        print_table(headers, rows, title="Schema Variables")
    elif template_vars:
        headers = ["Variable", "Source"]
        rows = [[v, dim("extracted from template")] for v in sorted(template_vars)]
        print_table(headers, rows, title="Template Variables")
    else:
        safe_print(dim("  No template variables."))

    safe_print()

    # ── Metadata ──────────────────────────────────────────────────────────────
    status_str = _colorize("🔒 locked", Color.YELLOW) if locked else _colorize("○  active", Color.GREEN)
    info_lines = [
        badge("Timestamp", timestamp),
        badge("Tokens   ", str(tokens)),
        badge("Hash     ", sha_hash),
        badge("Status   ", status_str),
    ]
    print_box(f"Metadata  {args.name} @ {args.version}", info_lines)

    # ── Example usage ─────────────────────────────────────────────────────────
    safe_print()
    safe_print(bold("  Example Usage"))
    vars_for_example = sorted(schema_vars) if schema_vars else sorted(template_vars)
    var_flags = " ".join(f'--var {v}="<value>"' for v in vars_for_example)
    cmd = f"  promptvc run {args.name} {args.version}"
    if var_flags:
        cmd += f" {var_flags}"
    safe_print(_colorize(cmd, Color.CYAN))
    safe_print()