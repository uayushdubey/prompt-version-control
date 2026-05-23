from __future__ import annotations
import argparse
import glob as globlib
import os
from typing import Dict, List, Optional, Set

from promptvc.core.repo import PromptRepo
from promptvc.providers.registry import get_provider
from promptvc.cli.helpers import (
    _parse_vars,
    _collect_schema_variables,
    _collect_template_variables,
)
from promptvc.utils.config import get_config_value
from promptvc.utils.diff_apply import apply_unified_diff
from promptvc.utils.template import render_template, find_unused_variables, extract_variables
from promptvc.utils.console import (
    success, error, warning, section, pretty_diff,
    dim, bold, safe_print, print_box, print_error_panel, badge, spinner,
)



def read_file_safe(path: str) -> tuple[str, str]:
    """Read a file trying common encodings in order."""
    for enc in ["utf-8-sig", "utf-8", "utf-16", "latin-1"]:
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read(), enc
        except (UnicodeDecodeError, UnicodeError):
            continue
        except OSError as e:
            raise RuntimeError(f"Cannot read file '{path}': {e}") from e
    raise RuntimeError(f"Cannot decode file '{path}' — unsupported encoding.")


def _apply_to_file(
    file_path: str,
    repo: PromptRepo,
    args: argparse.Namespace,
    rendered_prompt: str,
    provider,
    provider_kwargs: Dict,
    provider_name: str,
    is_non_interactive: bool,
    batch_mode: bool = False,
) -> bool:
    """Apply prompt to a single file. Returns True if changes were applied."""
    try:
        file_content, encoding = read_file_safe(file_path)
    except RuntimeError as exc:
        print_error_panel(str(exc))
        return False

    combined_input = f"""You are a senior software engineer.

Your task is to modify the given file according to the instruction.

INSTRUCTION:
{rendered_prompt}

FILE PATH:
{file_path}

FILE CONTENT:
{file_content}

IMPORTANT:
- Return ONLY a unified diff
- Do NOT return full file content
- Do NOT explain anything
- Do NOT include markdown code fences
- Use this exact format:

--- {file_path}
+++ {file_path}
@@
- old line
+ new line

If no changes are needed, return exactly: NO_CHANGES
"""

    try:
        with spinner(f"Applying to {os.path.basename(file_path)} via {provider_name}…"):
            result = provider.run(combined_input, **provider_kwargs)
    except Exception as exc:
        print_error_panel(
            f"Provider call failed: {exc}",
            where=provider_name,
            tips=["Check your API key and network connection"],
        )
        return False

    if not isinstance(result, dict):
        print_error_panel("Provider returned invalid response format.")
        return False

    output = (result.get("output") or "").strip()

    if not output:
        print_error_panel("Provider returned empty output.")
        return False

    if output == "NO_CHANGES":
        safe_print(dim(f"  No changes needed for '{file_path}'"))
        return False

    if not output.startswith("---"):
        print_error_panel(
            "Invalid diff returned by provider.",
            tips=["The model may have returned prose instead of a diff",
                  "Try a more capable model or rephrase your prompt"],
        )
        safe_print(dim("\nRaw output:"))
        safe_print(output[:500])
        return False

    safe_print()
    safe_print(bold(f"  Proposed changes for: {file_path}"))
    safe_print(pretty_diff(output))

    if is_non_interactive or batch_mode:
        answer = "y"
    else:
        answer = input(dim("\n  Apply changes? (y/n): ")).strip().lower()

    if answer != "y":
        safe_print(dim("  Skipped."))
        return False

    try:
        new_content = apply_unified_diff(file_content, output)
    except ValueError as exc:
        print_error_panel(
            f"Failed to apply diff: {exc}",
            tips=["The diff may be malformed — try running again",
                  "Use a more capable model for better diff quality"],
        )
        return False

    try:
        with open(file_path, "w", encoding=encoding) as f:
            f.write(new_content)
    except OSError as exc:
        print_error_panel(f"Failed to write '{file_path}': {exc}")
        return False

    repo.log_file_change(
        name=args.name,
        version=args.version,
        file_path=file_path,
        diff=output,
    )
    safe_print(success(f"  ✓ Applied to '{file_path}'"))
    return True


def apply_command(args: argparse.Namespace) -> None:
    is_dry_run       = getattr(args, "dry_run", False)
    is_non_interactive = getattr(args, "non_interactive", False)
    target_file      = getattr(args, "file", None)
    target_dir       = getattr(args, "dir", None)
    glob_pattern     = getattr(args, "glob", "*")

    # Validate: must have --file or --dir
    if not target_file and not target_dir:
        print_error_panel(
            "No target specified.",
            tips=["Specify a file:      --file src/main.py",
                  "Or a directory:      --dir src/ --glob '*.py'"],
        )
        return

    provider_name = (
        getattr(args, "provider", None)
        or get_config_value("provider")
        or "mock"
    )

    try:
        provider = get_provider(provider_name)
    except Exception:
        print_error_panel(
            f"Unknown provider '{provider_name}'",
            tips=["Available: openai, anthropic, gemini, ollama, mock"],
        )
        return

    model = (
        getattr(args, "model", None)
        or get_config_value(f"models.{provider_name}")
    )
    provider_kwargs: Dict = {}
    if model:
        provider_kwargs["model"] = model

    timeout = getattr(args, "timeout", None) or get_config_value("defaults.timeout")
    if timeout:
        provider_kwargs["timeout"] = timeout

    max_tokens = getattr(args, "max_tokens", None)
    if max_tokens:
        provider_kwargs["max_tokens"] = max_tokens

    if getattr(args, "stream", False):
        provider_kwargs["stream"] = True

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

    schema = repo.get_schema(args.name, args.version)
    schema_vars = schema.get("variables", {}) if schema else {}
    variables = _parse_vars(getattr(args, "var", None))

    if schema_vars:
        required_vars = {
            n for n, s in schema_vars.items()
            if s.get("required", False) and s.get("default") is None
        }
    else:
        required_vars = extract_variables(raw_prompt)

    # ── Validate target exists BEFORE asking for variables ────────────────────────
    if not is_dry_run:
        if target_file and not os.path.isfile(target_file):
            print_error_panel(
                f"File not found: '{target_file}'",
                tips=["Check the path and try again"],
            )
            return
        if target_dir and not os.path.isdir(target_dir):
            print_error_panel(
                f"Directory not found: '{target_dir}'",
                tips=["Check the path and try again"],
            )
            return

    # ── Dry-run preview ────────────────────────────────────────────────────────
    if is_dry_run:
        missing = required_vars - set(variables.keys())
        try:
            rendered_prompt = render_template(raw_prompt, variables)
        except Exception:
            rendered_prompt = raw_prompt

        info_lines = [
            badge("Prompt  ", f"{args.name} @ {args.version}"),
            badge("Provider", f"{provider_name}" + (f" / {model}" if model else "")),
            badge("Target  ", target_dir or target_file or "—"),
        ]
        if missing:
            info_lines.append(warning(f"Missing vars: {', '.join(sorted(missing))}"))

        print_box("Dry Run Preview", info_lines)
        safe_print()
        safe_print(dim("── Rendered Prompt ──────────────────────────────"))
        safe_print(rendered_prompt)
        safe_print(dim("─────────────────────────────────────────────────"))
        return

    # ── Variable collection ────────────────────────────────────────────────────
    try:
        if schema_vars:
            interactive_vars = _collect_schema_variables(schema_vars, variables, is_non_interactive)
        else:
            interactive_vars = _collect_template_variables(required_vars, variables, is_non_interactive)
    except RuntimeError as exc:
        var_name = str(exc).split("'")[1] if "'" in str(exc) else "unknown"
        print_error_panel(
            str(exc),
            where=f"{args.name} @ {args.version}",
            tips=[f'Supply it with --var {var_name}="<value>"'],
            hint_cmd=f"promptvc inspect {args.name} {args.version}",
        )
        return

    variables = {**interactive_vars, **variables}
    rendered_prompt = render_template(raw_prompt, variables)

    unused = find_unused_variables(raw_prompt, variables)
    if unused:
        safe_print(warning(f"⚠  Unused variable(s): {', '.join(sorted(unused))}"))

    info_lines = [
        badge("Prompt  ", f"{args.name} @ {args.version}"),
        badge("Provider", f"{provider_name}" + (f" / {model}" if model else "")),
    ]

    # ── Single file mode ───────────────────────────────────────────────────────
    if target_file:
        if not os.path.isfile(target_file):
            print_error_panel(
                f"File not found: '{target_file}'",
                tips=["Check the path and try again"],
            )
            return
        info_lines.append(badge("File    ", target_file))
        print_box(f"apply  {args.name} @ {args.version}", info_lines)
        _apply_to_file(
            target_file, repo, args, rendered_prompt,
            provider, provider_kwargs, provider_name, is_non_interactive,
        )
        return

    # ── Directory mode ─────────────────────────────────────────────────────────
    if target_dir:
        if not os.path.isdir(target_dir):
            print_error_panel(
                f"Directory not found: '{target_dir}'",
                tips=["Check the path and try again"],
            )
            return

        pattern = os.path.join(target_dir, "**", glob_pattern)
        files   = sorted(globlib.glob(pattern, recursive=True))
        files   = [f for f in files if os.path.isfile(f)]

        if not files:
            print_error_panel(
                f"No files matched '{glob_pattern}' in '{target_dir}'",
                tips=[f"Try a broader pattern: --glob '*'"],
            )
            return

        info_lines.append(badge("Dir     ", target_dir))
        info_lines.append(badge("Glob    ", glob_pattern))
        info_lines.append(badge("Files   ", str(len(files))))
        print_box(f"apply  {args.name} @ {args.version}", info_lines)
        safe_print()

        if not is_non_interactive:
            safe_print(f"  Will process {len(files)} file(s):")
            for f in files:
                safe_print(dim(f"    {f}"))
            answer = input(dim("\n  Proceed? (y/n): ")).strip().lower()
            if answer != "y":
                safe_print(dim("  Aborted."))
                return

        applied = 0
        for f in files:
            result = _apply_to_file(
                f, repo, args, rendered_prompt,
                provider, provider_kwargs, provider_name, is_non_interactive,
                batch_mode=True,
            )
            if result:
                applied += 1

        safe_print()
        safe_print(success(f"✓ Applied to {applied}/{len(files)} file(s)"))
