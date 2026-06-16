from __future__ import annotations

import argparse
import sys
import os
import glob as globlib
import json
import time
import uuid
import difflib
import warnings
import shutil
from typing import Any, Callable, Dict, List, Optional, Set, Sequence

# Disable warnings
warnings.filterwarnings("ignore", category=FutureWarning)

# promptvc imports
from promptvc.core import (
    PromptRepo,
    PromptVCError,
    LockError,
    TraceRecord,
    TraceStore,
    run_evaluation,
    run_case_assertions,
    CaseResult,
    load_pipeline,
    validate_pipeline,
    execute_pipeline,
    StepResult,
    compare_versions,
    validate_dataset,
    validate_prompt,
    PromptFormat,
    render_prompt,
    messages_to_plain,
    extract_variables_from_prompt,
    MatrixConfig,
    run_matrix_eval,
    format_matrix_table,
    save_matrix_report,
    compute_space_analytics,
    compute_global_analytics,
    BudgetGuard,
    BudgetExceededError,
    get_session_guard,
)
from promptvc.config import (
    load_config,
    save_config,
    get_config_value,
    set_config_value,
    list_config,
)
from promptvc.providers import get_provider
from promptvc.utils.template import (
    render_template,
    extract_variables,
    find_unused_variables,
)
from promptvc.utils.console import (
    safe_print,
    print_error_panel,
    success,
    error,
    warning,
    section,
    pretty_diff,
    dim,
    bold,
    muted,
    badge,
    print_box,
    print_table,
    divider,
    spinner,
    _colorize,
    Color,
)
from promptvc.utils.cost import (
    estimate_cost, format_cost, format_latency,
    compute_cost_breakdown, format_cost_breakdown, CostBreakdown,
)
from promptvc.utils.diff import compute_diff, apply_unified_diff
from promptvc.security.secrets import SecretsStore, SecretsError

Handler = Callable[[argparse.Namespace], None]


# ── Common CLI Helpers & Utils ──────────────────────────────────────────────────

def get_repo() -> Optional[PromptRepo]:
    """Instantiate PromptRepo, printing a clean error if it fails."""
    try:
        return PromptRepo()
    except Exception as exc:
        print_error_panel(f"Failed to load repository: {exc}")
        return None


def require_arg(args: argparse.Namespace, attr: str) -> Optional[str]:
    """Return a stripped CLI argument value, or print an error and return None."""
    value = getattr(args, attr, None)
    if not value or not value.strip():
        print_error_panel(f"Missing required argument: <{attr}>")
        return None
    return value.strip()


def _parse_vars(var_args: Optional[List[str]]) -> Dict[str, str]:
    """Parse var arguments formatted as key=value."""
    if not var_args:
        return {}
    variables: Dict[str, str] = {}
    for entry in var_args:
        if "=" not in entry:
            raise ValueError(f"Invalid --var format: '{entry}'. Expected 'key=value'.")
        key, value = entry.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Invalid --var format: '{entry}'. Key must not be empty.")
        variables[key] = value.strip()
    return variables


def _collect_schema_variables(
    schema_vars: Dict[str, Dict],
    provided_vars: Dict[str, str],
    is_non_interactive: bool = False,
) -> Dict[str, str]:
    """Collect required variables specified in schema."""
    collected: Dict[str, str] = {}
    for var_name, spec in schema_vars.items():
        if var_name in provided_vars:
            continue
        required = spec.get("required", False)
        default  = spec.get("default")
        if default is not None:
            collected[var_name] = str(default)
            continue
        if required:
            if is_non_interactive:
                raise RuntimeError(f"Missing required variable '{var_name}' in non-interactive mode.")
            value = input(dim(f"  {var_name}: ")).strip()
            collected[var_name] = value
    return collected


def _collect_template_variables(
    required_vars: Set[str],
    provided_vars: Dict[str, str],
    is_non_interactive: bool = False,
) -> Dict[str, str]:
    """Interactively collect variables required by the prompt template."""
    missing = required_vars - set(provided_vars.keys())
    if not missing:
        return {}
    if is_non_interactive:
        first_missing = sorted(missing)[0]
        raise RuntimeError(f"Missing required variable '{first_missing}' in non-interactive mode.")
    safe_print(bold("\n  Variables needed:"))
    collected: Dict[str, str] = {}
    for var in sorted(missing):
        value = input(dim(f"  {var}: ")).strip()
        collected[var] = value
    return collected


def _time_ago(ts: str) -> str:
    """Return a human-readable relative timestamp for status command."""
    if not ts:
        return "—"
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = now - dt
        secs = int(diff.total_seconds())
        if secs < 60:
            return f"{secs}s ago"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return ts.split("T")[0]


# ── Command Handlers ─────────────────────────────────────────────────────────────

def handle_init(_: argparse.Namespace) -> None:
    repo = PromptRepo()
    repo.init_repo()
    safe_print(success("✓ Repository initialized."))


def status_command(args: argparse.Namespace) -> None:
    repo   = PromptRepo()
    spaces = repo.list_spaces()

    provider = get_config_value("provider") or "mock"
    model    = get_config_value(f"models.{provider}") or "—"

    cwd = os.path.basename(os.getcwd())

    recent_activity: list[tuple[str, str, str, str]] = []
    total_spaces  = len(spaces)
    total_versions = 0
    total_runs    = 0

    for space_name in spaces:
        try:
            space_data = repo.storage.load_space(space_name)
        except Exception:
            continue

        versions = space_data.get("versions", {})
        total_versions += len(versions)

        runs = space_data.get("runs", [])
        total_runs += len(runs)
        if runs:
            last_run = runs[-1]
            recent_activity.append((
                space_name,
                last_run.get("version", "?"),
                "run",
                last_run.get("timestamp", ""),
            ))

        evals = space_data.get("evaluations", [])
        if evals:
            last_eval = evals[-1]
            recent_activity.append((
                space_name,
                last_eval.get("version", "?"),
                "eval",
                last_eval.get("timestamp", ""),
            ))

        changes = space_data.get("file_changes", [])
        if changes:
            last_change = changes[-1]
            recent_activity.append((
                space_name,
                last_change.get("version", "?"),
                "apply",
                last_change.get("timestamp", ""),
            ))

    recent_activity.sort(key=lambda x: x[3], reverse=True)
    recent_activity = recent_activity[:8]

    safe_print()
    summary_lines = [
        badge("Workspace", cwd),
        badge("Provider ", f"{provider} / {model}"),
        badge("Spaces   ", str(total_spaces)),
        badge("Versions ", str(total_versions)),
        badge("Runs     ", str(total_runs)),
    ]
    print_box("promptvc status", summary_lines)

    if spaces:
        safe_print()
        safe_print(bold("  Spaces"))
        space_rows = []
        for name in sorted(spaces):
            try:
                data = repo.storage.load_space(name)
                latest = data.get("latest", "—")
                ver_count = len(data.get("versions", {}))
                run_count = len(data.get("runs", []))
                space_rows.append([name, latest, str(ver_count), str(run_count)])
            except Exception:
                space_rows.append([name, "—", "—", "—"])
        print_table(["Space", "Latest", "Versions", "Runs"], space_rows)

    if recent_activity:
        safe_print()
        safe_print(bold("  Recent Activity"))
        activity_rows = []
        for (name, ver, action, ts) in recent_activity:
            action_colored = {
                "run":   _colorize("run",   Color.CYAN),
                "eval":  _colorize("eval",  Color.MAGENTA),
                "apply": _colorize("apply", Color.YELLOW),
            }.get(action, action)
            activity_rows.append([name, ver, action_colored, _time_ago(ts)])
        print_table(["Space", "Version", "Action", "When"], activity_rows)

    safe_print()


def commit_command(args: argparse.Namespace) -> None:
    repo = get_repo()
    if repo is None:
        return

    name = require_arg(args, "name")
    if name is None:
        return

    prompt = _resolve_input("prompt", getattr(args, "prompt", None), "Enter prompt text:")
    if prompt is None:
        return

    message = _resolve_input("message", getattr(args, "message", None), "Enter commit message:")
    if message is None:
        return

    result = repo.commit(name, prompt, message)

    safe_print()
    safe_print(success(f"✓ Committed {result['id']}"))
    safe_print(dim(f"  Space   : {name}"))
    safe_print(dim(f"  Message : {result['message']}"))
    safe_print(dim(f"  Tokens  : {result['tokens']}"))
    safe_print(dim(f"  Hash    : {result['hash'][:16]}…"))
    safe_print()
    safe_print(_colorize(f"  Run it: promptvc run {name} {result['id']}", Color.CYAN))
    safe_print()


def _resolve_input(field: str, value: str | None, prompt_label: str) -> str | None:
    if value and value.strip():
        return value.strip()
    return _read_input(field, prompt_label)


def _read_input(field: str, prompt_label: str) -> str | None:
    safe_print(f"\n  {prompt_label}")
    try:
        value = input(dim("  > ")).strip()
    except (EOFError, KeyboardInterrupt):
        safe_print(warning("\n  Input cancelled."))
        return None

    if not value:
        safe_print(warning(f"  ✗ {field} cannot be empty."))
        return None

    return value


def log_command(args: argparse.Namespace) -> None:
    repo = get_repo()
    if repo is None:
        return

    try:
        name = require_arg(args, "name")
        if name is None:
            return

        versions = repo.log(name)

        if not versions:
            safe_print(warning(f"  No versions found for '{name}'."))
            return

        latest_id = versions[0]["id"]
        safe_print()
        safe_print(bold(f"  {name}"))
        safe_print(dim(f"  {len(versions)} version(s)\n"))

        headers = ["Version", "Message", "Tokens", "Status", "Date"]
        rows = []
        for v in versions:
            vid     = v["id"]
            locked  = v.get("locked", False)
            is_latest = vid == latest_id

            ver_label = vid
            if is_latest:
                ver_label += _colorize("  ← latest", Color.BOLD_GREEN)

            status = _colorize("🔒 locked", Color.YELLOW) if locked else _colorize("○  active", Color.GREEN)
            date   = v.get("timestamp", "")
            date   = date.split("T")[0] if date else "—"
            msg    = v.get("message", "")[:52] + ("…" if len(v.get("message","")) > 52 else "")

            rows.append([ver_label, msg, str(v.get("tokens", 0)), status, date])

        print_table(headers, rows, title=name)
        safe_print()

    except PromptVCError as exc:
        safe_print(f"✗ {exc}")
    except ValueError as exc:
        safe_print(f"✗ {exc}")


def get_command(args: argparse.Namespace) -> None:
    repo = get_repo()
    if repo is None:
        return

    try:
        name    = require_arg(args, "name")
        version = require_arg(args, "version")

        if not all([name, version]):
            return

        if version.lower() == "latest":
            space   = repo.storage.load_space(name)
            version = space.get("latest") or version

        prompt = repo.get(name, version)

        safe_print()
        safe_print(bold(f"  {name} @ {version}"))
        safe_print(dim("  ─────────────────────────────────────────────────────"))
        for line in prompt.splitlines():
            safe_print(f"  {line}")
        safe_print(dim("  ─────────────────────────────────────────────────────"))
        safe_print()

    except PromptVCError as exc:
        safe_print(f"✗ {exc}")
    except ValueError as exc:
        safe_print(f"✗ {exc}")


def inspect_command(args: argparse.Namespace) -> None:
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

    locked    = prompt_data.get("locked", False)
    timestamp = prompt_data.get("timestamp", "—")
    tokens    = prompt_data.get("tokens", "—")
    sha_hash  = prompt_data.get("hash", "—")
    if sha_hash and sha_hash != "—":
        sha_hash = sha_hash[:16] + "…"

    schema      = repo.get_schema(args.name, args.version)
    schema_vars = schema.get("variables", {}) if schema else {}
    template_vars = extract_variables(raw_prompt)

    safe_print()
    safe_print(bold(f"  {args.name} @ {args.version}"))
    safe_print()

    safe_print(dim("  ── Prompt ───────────────────────────────────────────"))
    for line in raw_prompt.splitlines():
        safe_print(f"  {line}")
    safe_print(dim("  ─────────────────────────────────────────────────────"))
    safe_print()

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

    status_str = _colorize("🔒 locked", Color.YELLOW) if locked else _colorize("○  active", Color.GREEN)
    info_lines = [
        badge("Timestamp", timestamp),
        badge("Tokens   ", str(tokens)),
        badge("Hash     ", sha_hash),
        badge("Status   ", status_str),
    ]
    print_box(f"Metadata  {args.name} @ {args.version}", info_lines)

    safe_print()
    safe_print(bold("  Example Usage"))
    vars_for_example = sorted(schema_vars) if schema_vars else sorted(template_vars)
    var_flags = " ".join(f'--var {v}="<value>"' for v in vars_for_example)
    cmd = f"  promptvc run {args.name} {args.version}"
    if var_flags:
        cmd += f" {var_flags}"
    safe_print(_colorize(cmd, Color.CYAN))
    safe_print()


def diff_command(args: argparse.Namespace) -> None:
    repo = get_repo()
    if repo is None:
        return

    try:
        name = require_arg(args, "name")
        v1   = require_arg(args, "v1")
        v2   = require_arg(args, "v2")
        if not all([name, v1, v2]):
            return

        text1 = repo.get(name, v1)
        text2 = repo.get(name, v2)

        meta1 = repo.get_version_meta(name, v1)
        meta2 = repo.get_version_meta(name, v2)
        tok1  = meta1.get("tokens", 0)
        tok2  = meta2.get("tokens", 0)

        use_text = getattr(args, "text", False)
        use_stat = getattr(args, "stat", False)

        safe_print()
        safe_print(bold(f"  {name}  {v1} → {v2}"))
        safe_print()

        if use_stat:
            words1 = len(text1.split())
            words2 = len(text2.split())
            chars1 = len(text1)
            chars2 = len(text2)

            def _delta(a: int, b: int) -> str:
                d = b - a
                if d > 0:
                    return _colorize(f"+{d}", Color.GREEN)
                elif d < 0:
                    return _colorize(str(d), Color.RED)
                return dim("±0")

            headers = ["Metric", v1, v2, "Δ"]
            rows = [
                ["Tokens", str(tok1), str(tok2), _delta(tok1, tok2)],
                ["Words",  str(words1), str(words2), _delta(words1, words2)],
                ["Chars",  str(chars1), str(chars2), _delta(chars1, chars2)],
            ]
            print_table(headers, rows, title="Diff Stats")
            return

        if use_text:
            lines1 = text1.splitlines(keepends=True)
            lines2 = text2.splitlines(keepends=True)
            diff = list(difflib.unified_diff(
                lines1, lines2,
                fromfile=f"{name}/{v1}",
                tofile=f"{name}/{v2}",
                lineterm="",
            ))
            if not diff:
                safe_print(dim("  No text differences found."))
            else:
                safe_print(pretty_diff("\n".join(diff)))
            tok_delta = tok2 - tok1
            tok_str = (_colorize(f"+{tok_delta}", Color.GREEN) if tok_delta > 0
                       else _colorize(str(tok_delta), Color.RED) if tok_delta < 0
                       else dim("±0"))
            safe_print()
            safe_print(dim(f"  Token delta: {tok_str}  ({tok1} → {tok2})"))
            return

        diff_lines = compute_diff(text1, text2)
        changes    = [l for l in diff_lines if not l.startswith("  ")]

        if not changes:
            safe_print(dim("  No differences found."))
        else:
            for line in changes:
                if line.startswith("+"):
                    safe_print(_colorize(line, Color.GREEN))
                elif line.startswith("-"):
                    safe_print(_colorize(line, Color.RED))
                else:
                    safe_print(line)

        added   = sum(1 for l in changes if l.startswith("+"))
        removed = sum(1 for l in changes if l.startswith("-"))
        tok_delta = tok2 - tok1
        tok_str = (_colorize(f"+{tok_delta}", Color.GREEN) if tok_delta > 0
                   else _colorize(str(tok_delta), Color.RED) if tok_delta < 0
                   else dim("±0"))

        safe_print()
        info_lines = [
            badge("Lines added  ", _colorize(f"+{added}", Color.GREEN)),
            badge("Lines removed", _colorize(f"-{removed}", Color.RED)),
            badge("Token delta  ", tok_str),
        ]
        print_box(f"Diff  {v1} → {v2}", info_lines)

    except PromptVCError as exc:
        safe_print(f"✗ {exc}")
    except ValueError as exc:
        safe_print(f"✗ {exc}")


def lock_command(args: argparse.Namespace) -> None:
    repo = get_repo()
    if repo is None:
        return

    try:
        name    = require_arg(args, "name")
        version = require_arg(args, "version")

        if not all([name, version]):
            return

        if version.lower() == "latest":
            space   = repo.storage.load_space(name)
            version = space.get("latest") or version

        repo.lock(name, version)
        safe_print(success(f"✓ Locked {name} @ {version}"))
        safe_print(_colorize(
            f"  This version is now read-only. No further operations can be performed on it.",
            Color.DIM,
        ))

    except PromptVCError as exc:
        safe_print(f"✗ {exc}")
    except ValueError as exc:
        safe_print(f"✗ Invalid input: {exc}")


def list_command(args: argparse.Namespace) -> None:
    repo = get_repo()
    if repo is None:
        return

    try:
        spaces = repo.list_spaces()

        if not spaces:
            safe_print(dim("\n  No prompt spaces found. Run: promptvc commit <name>"))
            return

        safe_print()
        headers = ["Space", "Latest", "Versions"]
        rows = []
        for name in sorted(spaces):
            try:
                space = repo.storage.load_space(name)
                latest    = space.get("latest", "—")
                ver_count = len(space.get("versions", {}))
            except Exception:
                latest    = "—"
                ver_count = "?"
            rows.append([name, str(latest), str(ver_count)])

        print_table(headers, rows, title="Prompt Spaces")
        safe_print()

    except PromptVCError as exc:
        safe_print(f"✗ {exc}")


def run_command(args: argparse.Namespace) -> None:
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
            tips=[
                "Available: openai, anthropic, gemini, ollama, mock",
                f"Set default with: promptvc config set provider openai",
            ],
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

    stream = getattr(args, "stream", False)
    if stream:
        provider_kwargs["stream"] = True

    repo = PromptRepo()

    version = args.version
    if version.lower() == "latest":
        try:
            space   = repo.storage.load_space(args.name)
            version = space.get("latest") or version
        except Exception:
            pass

    try:
        prompt_data = repo.get_version_meta(args.name, version)
    except Exception:
        print_error_panel(
            f"Prompt version not found: '{args.name} @ {args.version}'",
            tips=[f"Run: promptvc log {args.name}  to see available versions"],
        )
        return

    raw_prompt = prompt_data.get("prompt")
    if raw_prompt is None:
        print_error_panel(f"'{args.name}@{version}' has no prompt text.")
        return

    schema = repo.get_schema(args.name, version)
    schema_vars = schema.get("variables", {}) if schema else {}

    variables = _parse_vars(getattr(args, "var", None))
    is_dry_run = getattr(args, "dry_run", False)
    is_non_interactive = getattr(args, "non_interactive", False)

    fmt = prompt_data.get("format", "raw")

    if schema_vars:
        required_vars = {
            n for n, s in schema_vars.items()
            if s.get("required", False) and s.get("default") is None
        }
    else:
        required_vars = extract_variables_from_prompt(raw_prompt, fmt)

    if is_dry_run:
        missing = required_vars - set(variables.keys())
        try:
            rendered_prompt = render_prompt(raw_prompt, variables, fmt)
        except Exception:
            rendered_prompt = raw_prompt
        info_lines = [
            badge("Prompt",  f"{args.name} @ {args.version}"),
            badge("Provider", f"{provider_name}" + (f" / {model}" if model else "")),
        ]
        if missing:
            info_lines.append(warning(f"Missing vars: {', '.join(sorted(missing))}"))
        print_box("Dry Run Preview", info_lines)
        safe_print()
        safe_print(dim("── Rendered Prompt ──────────────────────────────"))
        if isinstance(rendered_prompt, list):
            safe_print(json.dumps(rendered_prompt, indent=2, ensure_ascii=False))
        else:
            safe_print(rendered_prompt)
        safe_print(dim("─────────────────────────────────────────────────"))
        return

    try:
        if schema_vars:
            interactive_vars = _collect_schema_variables(
                schema_vars, variables, is_non_interactive
            )
        else:
            interactive_vars = _collect_template_variables(
                required_vars, variables, is_non_interactive
            )
    except RuntimeError as exc:
        var_name = str(exc).split("'")[1] if "'" in str(exc) else "unknown"
        print_error_panel(
            str(exc),
            where=f"{args.name} @ {args.version}",
            tips=[
                f'Supply it with --var {var_name}="<value>"',
                "Or run without --non-interactive for interactive input",
            ],
            hint_cmd=f"promptvc inspect {args.name} {args.version}",
        )
        return

    variables = {**interactive_vars, **variables}
    rendered_prompt = render_prompt(raw_prompt, variables, fmt)

    unused = find_unused_variables(raw_prompt, variables)
    if unused:
        safe_print(warning(f"⚠  Unused variable(s): {', '.join(sorted(unused))}"))

    model_used = model or provider_name
    cost = None

    # execution metadata
    trace_id = str(uuid.uuid4())
    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).isoformat()
    t_start = time.monotonic()

    trace_store = TraceStore(repo.storage._root)

    provider_kwargs_copy = dict(provider_kwargs)
    if isinstance(rendered_prompt, list):
        provider_kwargs_copy["messages"] = rendered_prompt
        prompt_param = ""
    else:
        prompt_param = rendered_prompt

    try:
        with spinner(f"Running {args.name} @ {version} via {provider_name}…"):
            result = provider.run(prompt_param, **provider_kwargs_copy)
    except Exception as exc:
        error_msg = str(exc)
        print_error_panel(
            f"Provider call failed: {exc}",
            where=f"{provider_name}" + (f" / {model}" if model else ""),
            tips=["Check your API key and network connection",
                  f"Try the mock provider: --provider mock"],
        )
        latency_ms = (time.monotonic() - t_start) * 1000
        trace_rec = TraceRecord(
            trace_id=trace_id,
            timestamp=timestamp,
            prompt_name=args.name,
            version=version,
            rendered_prompt=rendered_prompt,
            variables=variables,
            provider=provider_name,
            model=model_used,
            output="",
            tokens=None,
            input_tokens=None,
            output_tokens=None,
            latency_ms=latency_ms,
            cost_usd=None,
            score=None,
            error=error_msg,
        )
        try:
            trace_store.append(trace_rec)
        except Exception:
            pass
        return

    latency_ms = (time.monotonic() - t_start) * 1000

    if not isinstance(result, dict):
        print_error_panel("Provider returned invalid response format.")
        return

    output = result.get("output") or ""
    tokens       = result.get("tokens")
    model_used   = result.get("model_used") or model or provider_name
    input_tokens  = result.get("input_tokens")
    output_tokens = result.get("output_tokens")
    
    if model_used:
        if input_tokens is not None and output_tokens is not None:
            cost = estimate_cost(model_used, input_tokens, output_tokens)
        elif tokens is not None:
            cost = estimate_cost(model_used, int(tokens * 0.8), int(tokens * 0.2))

    trace_rec = TraceRecord(
        trace_id=trace_id,
        timestamp=timestamp,
        prompt_name=args.name,
        version=version,
        rendered_prompt=rendered_prompt,
        variables=variables,
        provider=provider_name,
        model=model_used,
        output=output,
        tokens=tokens,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
        cost_usd=cost,
        score=None,
        error=None,
    )
    try:
        trace_store.append(trace_rec)
    except Exception as exc:
        safe_print(warning(f"⚠ Warning: Failed to persist trace: {exc}"))

    try:
        run_record = {
            "version":      version,
            "output":       output,
            "tokens":       tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms":   round(latency_ms),
            "cost_usd":     cost,
            "model_used":   model_used,
            "timestamp":    repo._utc_now_iso(),
        }
        repo.storage.append_run(args.name, run_record)
    except Exception as exc:
        safe_print(warning(f"⚠ Warning: Failed to persist run record: {exc}"))

    token_str = (
        f"{input_tokens} in + {output_tokens} out = {tokens} total"
        if (input_tokens is not None and output_tokens is not None)
        else str(tokens) if tokens is not None else "—"
    )

    info_lines = [
        badge("Provider", f"{provider_name} / {model_used}"),
        badge("Latency ", format_latency(latency_ms)),
        badge("Tokens  ", token_str),
        badge("Cost    ", format_cost(cost)),
    ]
    safe_print()
    print_box(f"{args.name} @ {version}", info_lines)

    safe_print()
    safe_print(dim("── Output ───────────────────────────────────────────"))
    safe_print(output)
    safe_print(dim("─────────────────────────────────────────────────────"))
    safe_print(success(f"\n✓ Run complete"))


def eval_command(args: argparse.Namespace) -> None:
    provider_name = (
        getattr(args, "provider", None)
        or get_config_value("provider")
        or "mock"
    )
    provider = get_provider(provider_name)

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

    version = args.version
    if version.lower() == "latest":
        try:
            space   = repo.storage.load_space(args.name)
            version = space.get("latest") or version
        except Exception:
            pass

    try:
        prompt_data = repo.get_version_meta(args.name, version)
    except Exception:
        print_error_panel(
            f"Prompt '{args.name} @ {version}' not found.",
            hint_cmd=f"promptvc log {args.name}",
        )
        return

    raw_prompt = prompt_data.get("prompt")
    if raw_prompt is None:
        print_error_panel(f"'{args.name}@{version}' has no prompt text.")
        return
    fmt = prompt_data.get("format", "raw")

    try:
        with open(args.dataset, "r", encoding="utf-8") as f:
            dataset = json.load(f)
    except Exception as exc:
        print_error_panel(
            f"Failed to load dataset: {exc}",
            tips=["Ensure the file exists and is valid JSON",
                  "Dataset must be a list of objects with at least an 'input' field"],
        )
        return

    if not isinstance(dataset, list):
        print_error_panel("Dataset must be a JSON array of objects.")
        return

    model_used = model or provider_name
    results = []
    total_tokens = 0
    total_cost = 0.0
    total_latency = 0.0

    safe_print()
    safe_print(bold(f"  Evaluating {args.name} @ {args.version}"))
    safe_print(dim(f"  Provider : {provider_name}" + (f" / {model}" if model else "")))
    safe_print(dim(f"  Dataset  : {args.dataset}  ({len(dataset)} cases)"))
    safe_print()

    for i, row in enumerate(dataset, start=1):
        if not isinstance(row, dict):
            safe_print(warning(f"  ⚠  Skipping row {i}: not a JSON object"))
            continue

        variables: Dict[str, Any] = row
        try:
            rendered_prompt = render_prompt(raw_prompt, variables, fmt)
        except Exception as exc:
            safe_print(warning(f"  ⚠  Row {i} template error: {exc}"))
            continue

        unused = find_unused_variables(raw_prompt, variables)
        if unused:
            safe_print(warning(f"  ⚠  Row {i}: unused vars: {', '.join(sorted(unused))}"))

        provider_kwargs_copy = dict(provider_kwargs)
        if isinstance(rendered_prompt, list):
            provider_kwargs_copy["messages"] = rendered_prompt
            prompt_param = ""
        else:
            prompt_param = rendered_prompt

        t0 = time.monotonic()
        try:
            with spinner(f"  [{i}/{len(dataset)}] Running case {i}…"):
                result = provider.run(prompt_param, **provider_kwargs_copy)
        except Exception as exc:
            safe_print(warning(f"  ✗  Case {i} failed: {exc}"))
            continue
        latency_ms = (time.monotonic() - t0) * 1000

        output = result.get("output") or ""
        tokens = result.get("tokens")
        actual_model = result.get("model_used") or model_used

        cost = None
        if tokens:
            cost = estimate_cost(actual_model, int(tokens * 0.8), int(tokens * 0.2))
            total_tokens += tokens
            if cost is not None:
                total_cost += cost
        total_latency += latency_ms

        results.append({
            "case":      i,
            "input":     row,
            "output":    output,
            "tokens":    tokens,
            "latency_ms": round(latency_ms),
            "cost_usd":  cost,
            "model_used": actual_model,
        })

    if not results:
        print_error_panel("No results produced. Check your dataset and provider.")
        return

    safe_print()
    headers = ["#", "Tokens", "Latency", "Cost", "Output (preview)"]
    rows = []
    for r in results:
        preview = (r["output"] or "")[:60].replace("\n", " ")
        if len(r["output"] or "") > 60:
            preview += "…"
        rows.append([
            str(r["case"]),
            str(r["tokens"] or "—"),
            format_latency(r["latency_ms"]),
            format_cost(r["cost_usd"]),
            preview,
        ])
    print_table(headers, rows, title=f"Eval: {args.name} @ {args.version}")

    avg_latency = total_latency / len(results) if results else 0
    summary_lines = [
        badge("Cases    ", f"{len(results)} / {len(dataset)}"),
        badge("Total tokens", str(total_tokens) if total_tokens else "—"),
        badge("Total cost  ", format_cost(total_cost) if total_cost else "—"),
        badge("Avg latency ", format_latency(avg_latency)),
    ]
    safe_print()
    print_box("Evaluation Summary", summary_lines)

    repo.log_evaluation(
        name=args.name,
        version=version,
        dataset=args.dataset,
        results=results,
    )
    safe_print(success(f"\n✓ Evaluation complete — {len(results)} cases stored"))


def compare_command(args: argparse.Namespace) -> None:
    provider_name = (
        getattr(args, "provider", None)
        or get_config_value("provider")
        or "mock"
    )
    provider = get_provider(provider_name)

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

    for ver in [args.v1, args.v2]:
        try:
            repo.get_version_meta(args.name, ver)
        except Exception:
            print_error_panel(
                f"Version '{args.name} @ {ver}' not found.",
                hint_cmd=f"promptvc log {args.name}",
            )
            return

    meta_v1 = repo.get_version_meta(args.name, args.v1)
    meta_v2 = repo.get_version_meta(args.name, args.v2)
    prompt_v1 = meta_v1.get("prompt", "")
    prompt_v2 = meta_v2.get("prompt", "")
    fmt_v1 = meta_v1.get("format", "raw")
    fmt_v2 = meta_v2.get("format", "raw")

    try:
        with open(args.dataset, "r", encoding="utf-8") as f:
            dataset = json.load(f)
    except Exception as exc:
        print_error_panel(f"Failed to load dataset: {exc}")
        return

    if not isinstance(dataset, list):
        print_error_panel("Dataset must be a JSON array.")
        return

    safe_print()
    safe_print(bold(f"  Comparing {args.name}: {args.v1} vs {args.v2}"))
    safe_print(dim(f"  Provider : {provider_name}" + (f" / {model}" if model else "")))
    safe_print(dim(f"  Dataset  : {args.dataset}  ({len(dataset)} cases)"))
    safe_print()

    comparisons = []
    for i, row in enumerate(dataset, start=1):
        if not isinstance(row, dict):
            safe_print(warning(f"  ⚠  Skipping row {i}: not a JSON object"))
            continue

        variables: Dict[str, Any] = row

        try:
            rendered_v1 = render_prompt(prompt_v1, variables, fmt_v1)
            rendered_v2 = render_prompt(prompt_v2, variables, fmt_v2)
        except Exception as exc:
            safe_print(warning(f"  ⚠  Row {i} template error: {exc}"))
            continue

        provider_kwargs_v1 = dict(provider_kwargs)
        if isinstance(rendered_v1, list):
            provider_kwargs_v1["messages"] = rendered_v1
            prompt_param_v1 = ""
        else:
            prompt_param_v1 = rendered_v1

        provider_kwargs_v2 = dict(provider_kwargs)
        if isinstance(rendered_v2, list):
            provider_kwargs_v2["messages"] = rendered_v2
            prompt_param_v2 = ""
        else:
            prompt_param_v2 = rendered_v2

        try:
            with spinner(f"  [{i}/{len(dataset)}] Running case {i} ({args.v1})…"):
                t0 = time.monotonic()
                result_v1 = provider.run(prompt_param_v1, **provider_kwargs_v1)
                lat_v1 = (time.monotonic() - t0) * 1000

            with spinner(f"  [{i}/{len(dataset)}] Running case {i} ({args.v2})…"):
                t0 = time.monotonic()
                result_v2 = provider.run(prompt_param_v2, **provider_kwargs_v2)
                lat_v2 = (time.monotonic() - t0) * 1000
        except Exception as exc:
            safe_print(warning(f"  ✗  Case {i} failed: {exc}"))
            continue

        out_v1 = result_v1.get("output") or ""
        out_v2 = result_v2.get("output") or ""
        tok_v1 = result_v1.get("tokens")
        tok_v2 = result_v2.get("tokens")

        comparisons.append({
            "case":    i,
            "input":   row,
            "v1_output":   out_v1,
            "v2_output":   out_v2,
            "v1_tokens":   tok_v1,
            "v2_tokens":   tok_v2,
            "v1_latency":  round(lat_v1),
            "v2_latency":  round(lat_v2),
        })

    if not comparisons:
        print_error_panel("No comparison results. Check dataset and provider.")
        return

    headers = ["#", f"{args.v1} tokens", f"{args.v1} latency",
               f"{args.v2} tokens", f"{args.v2} latency", "Δ tokens"]
    rows = []
    for c in comparisons:
        t1 = c["v1_tokens"] or 0
        t2 = c["v2_tokens"] or 0
        delta = t2 - t1
        delta_str = (f"+{delta}" if delta > 0 else str(delta)) if (t1 and t2) else "—"
        rows.append([
            str(c["case"]),
            str(c["v1_tokens"] or "—"),
            format_latency(c["v1_latency"]),
            str(c["v2_tokens"] or "—"),
            format_latency(c["v2_latency"]),
            delta_str,
        ])

    safe_print()
    print_table(headers, rows, title=f"Compare: {args.name}  {args.v1} vs {args.v2}")

    safe_print()
    for c in comparisons:
        safe_print(_colorize(f"  ── Case {c['case']} ──────────────────────────────", Color.DIM))
        input_preview = str(c["input"])[:120]
        safe_print(dim(f"  Input: {input_preview}"))
        safe_print()

        v1_label = _colorize(f"  {args.v1}", Color.BOLD_CYAN)
        v2_label = _colorize(f"  {args.v2}", Color.BOLD_MAGENTA)
        safe_print(v1_label)
        for line in (c["v1_output"] or "").splitlines()[:10]:
            safe_print(f"    {line}")

        safe_print()
        safe_print(v2_label)
        for line in (c["v2_output"] or "").splitlines()[:10]:
            safe_print(f"    {line}")
        safe_print()

    safe_print(success(f"✓ Compared {args.v1} vs {args.v2}  ({len(comparisons)} cases)"))


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
    provider: Any,
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

    diff_hash = hashlib.sha256(f"{os.path.abspath(file_path)}:{output}".encode("utf-8")).hexdigest()

    if repo.storage.is_diff_applied(file_path, diff_hash):
        safe_print(dim(f"  This diff has already been applied to '{file_path}'. Skipping."))
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

    backup_path = file_path + ".promptvc.bak"

    try:
        shutil.copy2(file_path, backup_path)
    except Exception as exc:
        print_error_panel(f"Failed to create backup of '{file_path}': {exc}")
        return False

    try:
        with open(file_path, "w", encoding=encoding) as f:
            f.write(new_content)
    except OSError as exc:
        print_error_panel(f"Failed to write '{file_path}': {exc}. Rolling back changes.")
        try:
            shutil.copy2(backup_path, file_path)
        except Exception as roll_exc:
            print_error_panel(f"CRITICAL: Failed to rollback from backup file: {roll_exc}")
        return False
    finally:
        if os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except Exception:
                pass

    try:
        repo.storage.record_applied_diff(file_path, diff_hash)
    except Exception as exc:
        safe_print(warning(f"⚠ Warning: Failed to record applied diff hash: {exc}"))

    repo.log_file_change(
        name=args.name,
        version=args.version,
        file_path=file_path,
        diff=output,
    )
    safe_print(success(f"  ✓ Applied to '{file_path}'"))
    return True


import hashlib

def apply_command(args: argparse.Namespace) -> None:
    is_dry_run       = getattr(args, "dry_run", False)
    is_non_interactive = getattr(args, "non_interactive", False)
    target_file      = getattr(args, "file", None)
    target_dir       = getattr(args, "dir", None)
    glob_pattern     = getattr(args, "glob", "*")

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


def changes_command(args: argparse.Namespace) -> None:
    repo = PromptRepo()

    try:
        space = repo.storage.load_space(args.name)
    except Exception as exc:
        print_error_panel(
            f"Prompt space '{args.name}' not found.",
            hint_cmd=f"promptvc list",
        )
        return

    file_changes = space.get("file_changes") or []

    if not file_changes:
        safe_print(dim(f"\n  No file changes recorded for '{args.name}'."))
        return

    safe_print()
    safe_print(bold(f"  File changes for: {args.name}"))
    safe_print()

    headers = ["Timestamp", "Version", "File"]
    rows = []
    for change in reversed(file_changes):
        ts      = change.get("timestamp", "—")
        date    = ts.split("T")[0] if "T" in ts else ts
        time_   = ts.split("T")[1][:8] if "T" in ts else ""
        ver     = change.get("version", "—")
        fpath   = change.get("file", "—")
        rows.append([f"{date} {time_}".strip(), _colorize(ver, Color.CYAN), fpath])

    print_table(headers, rows, title=f"Changes  {args.name}")
    safe_print()


def config_command(args: argparse.Namespace) -> None:
    action = getattr(args, "action", None)
    
    if action == "set":
        key = getattr(args, "key", None)
        value_raw = getattr(args, "value", None)
        if not key or value_raw is None:
            safe_print("Error: 'set' requires <key> and <value>")
            return
        
        parsed_value = _parse_value(value_raw)
        set_config_value(key, parsed_value)
        safe_print(f"Set {key} = {parsed_value}")
        
    elif action == "get":
        key = getattr(args, "key", None)
        if not key:
            safe_print("Error: 'get' requires <key>")
            return
        val = get_config_value(key)
        if val is None:
            safe_print(f"Key not found: {key}")
        else:
            if isinstance(val, dict):
                safe_print(json.dumps(val, indent=2))
            else:
                safe_print(str(val))
                
    elif action == "list":
        config = list_config()
        safe_print(json.dumps(config, indent=2))
    else:
        safe_print("Unknown config action. Use set, get, or list.")


def _parse_value(val: str) -> Any:
    lower_val = val.lower()
    if lower_val == "true":
        return True
    if lower_val == "false":
        return False
    if lower_val == "null":
        return None
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def _run_test_suite_internal(
    suite: list,
    raw_prompt: str,
    provider,
    provider_kwargs: dict,
    golden_dir: str,
    args: argparse.Namespace,
    version_label: str,
    silent: bool = False,
    fmt: str = "raw"
) -> list[CaseResult]:
    case_results = []
    for i, case in enumerate(suite, start=1):
        case_id   = case.get("id", f"case-{i}")
        input_vars = case.get("input", {})

        try:
            rendered = render_prompt(raw_prompt, input_vars, fmt)
        except Exception as exc:
            if not silent:
                safe_print(warning(f"  ⚠  {case_id} ({version_label}): template error — {exc}"))
            continue

        provider_kwargs_copy = dict(provider_kwargs)
        if isinstance(rendered, list):
            provider_kwargs_copy["messages"] = rendered
            prompt_param = ""
        else:
            prompt_param = rendered

        try:
            if not silent:
                with spinner(f"  [{i}/{len(suite)}] {case_id} ({version_label})…"):
                    result = provider.run(prompt_param, **provider_kwargs_copy)
            else:
                result = provider.run(prompt_param, **provider_kwargs_copy)
        except Exception as exc:
            if not silent:
                safe_print(warning(f"  ✗  {case_id} ({version_label}): provider failed — {exc}"))
            continue

        output = result.get("output") or ""
        tokens = result.get("tokens")

        deterministic = getattr(args, "deterministic", False)
        cr = run_case_assertions(
            case,
            output,
            tokens,
            golden_dir,
            provider=provider,
            deterministic=deterministic,
        )
        case_results.append(cr)

        if not silent:
            if cr.passed:
                safe_print(_colorize(f"  ✓  {case_id} ({version_label})  (Score: {cr.score:.2f})", Color.BOLD_GREEN))
            else:
                safe_print(_colorize(f"  ✗  {case_id} ({version_label})  (Score: {cr.score:.2f})", Color.BOLD_RED))
                for a in cr.failed_assertions:
                    safe_print(dim(f"       [assertion: {a.assertion_type}] {a.message}"))
                    if a.expected:
                        safe_print(dim(f"         expected: {a.expected}"))
                    if a.actual:
                        safe_print(dim(f"         actual  : {a.actual}"))
                for c in cr.failed_checks:
                    safe_print(dim(f"       [check: {c.check_type}] {c.message}"))
                    if c.expected:
                        safe_print(dim(f"         expected: {c.expected}"))
                    if c.actual:
                        safe_print(dim(f"         actual  : {c.actual}"))
                if cr.score_feedback:
                    safe_print(dim(f"       [feedback] {cr.score_feedback.strip()}"))

    return case_results


def test_run_command(args: argparse.Namespace) -> None:
    provider_name = (
        getattr(args, "provider", None)
        or get_config_value("provider")
        or "mock"
    )
    provider = get_provider(provider_name)
    model = getattr(args, "model", None) or get_config_value(f"models.{provider_name}")

    provider_kwargs = {}
    if model:
        provider_kwargs["model"] = model

    repo = PromptRepo()

    try:
        prompt_data = repo.get_version_meta(args.name, args.version)
    except Exception:
        print_error_panel(
            f"Prompt '{args.name} @ {args.version}' not found.",
            hint_cmd=f"promptvc log {args.name}",
        )
        sys.exit(1)

    raw_prompt = prompt_data.get("prompt", "")

    suite_path = args.suite
    try:
        with open(suite_path, "r", encoding="utf-8") as f:
            suite = json.load(f)
    except Exception as exc:
        print_error_panel(f"Failed to load test suite: {exc}")
        sys.exit(1)

    if not isinstance(suite, list):
        print_error_panel("Test suite must be a JSON array of test case objects.")
        sys.exit(1)

    golden_dir = os.path.dirname(os.path.abspath(suite_path))
    compare_version = getattr(args, "compare", None)

    safe_print()
    safe_print(bold(f"  promptvc test  ·  {args.name} @ {args.version}" + (f" (comparing to {compare_version})" if compare_version else "")))
    safe_print(dim(f"  Suite    : {suite_path}  ({len(suite)} cases)"))
    safe_print(dim(f"  Provider : {provider_name}" + (f" / {model}" if model else "")))
    safe_print()

    fmt = prompt_data.get("format", "raw")

    current_results = _run_test_suite_internal(
        suite, raw_prompt, provider, provider_kwargs, golden_dir, args, version_label=args.version, silent=False, fmt=fmt
    )

    if compare_version:
        try:
            compare_data = repo.get_version_meta(args.name, compare_version)
        except Exception:
            print_error_panel(
                f"Comparison prompt '{args.name} @ {compare_version}' not found.",
                hint_cmd=f"promptvc log {args.name}",
            )
            sys.exit(1)
        raw_prompt_compare = compare_data.get("prompt", "")

        compare_fmt = compare_data.get("format", "raw")

        base_results = _run_test_suite_internal(
            suite, raw_prompt_compare, provider, provider_kwargs, golden_dir, args, version_label=compare_version, silent=True, fmt=compare_fmt
        )

        current_by_id = {cr.case_id: cr for cr in current_results}
        base_by_id = {cr.case_id: cr for cr in base_results}

        headers = ["Case", f"Score ({compare_version})", f"Score ({args.version})", "Delta", "Result"]
        rows = []
        regression_detected = False

        for case_id in sorted(set(current_by_id.keys()) | set(base_by_id.keys())):
            base_cr = base_by_id.get(case_id)
            curr_cr = current_by_id.get(case_id)

            base_score = base_cr.score if base_cr else 0.0
            curr_score = curr_cr.score if curr_cr else 0.0
            delta = curr_score - base_score

            if delta > 0.001:
                delta_str = _colorize(f"+{delta:.2f}", Color.BOLD_GREEN)
            elif delta < -0.001:
                delta_str = _colorize(f"{delta:.2f}", Color.BOLD_RED)
                regression_detected = True
            else:
                delta_str = "0.00"

            if not curr_cr:
                res_label = _colorize("MISSING", Color.BOLD_RED)
            elif curr_cr.passed:
                res_label = _colorize("PASS", Color.BOLD_GREEN)
            else:
                res_label = _colorize("FAIL", Color.BOLD_RED)

            rows.append([
                case_id,
                f"{base_score:.2f}",
                f"{curr_score:.2f}",
                delta_str,
                res_label
            ])

        print_table(headers, rows, title=f"Regression Report: {compare_version} -> {args.version}")

        base_avg = sum(cr.score for cr in base_results) / len(base_results) if base_results else 0.0
        curr_avg = sum(cr.score for cr in current_results) / len(current_results) if current_results else 0.0
        avg_delta = curr_avg - base_avg

        summary_lines = [
            badge(f"Avg Score ({compare_version})", f"{base_avg:.2f}"),
            badge(f"Avg Score ({args.version})", f"{curr_avg:.2f}"),
            badge("Avg Delta", f"{avg_delta:+.2f}"),
        ]

        failed = False
        fail_reasons = []
        if regression_detected:
            failed = True
            fail_reasons.append("Regression detected: one or more test cases had score drops.")

        if curr_avg < base_avg - 0.001:
            failed = True
            fail_reasons.append("Regression detected: average score dropped.")

        threshold = getattr(args, "threshold", None)
        if threshold is not None:
            threshold = float(threshold)
            if curr_avg < threshold:
                failed = True
                fail_reasons.append(f"Average score {curr_avg:.2f} is below threshold {threshold:.2f}")

        safe_print()
        if not failed:
            print_box("No regressions detected ✓", summary_lines)
            safe_print(success("\n✓ Test suite complete"))
        else:
            print_box("Regression / test failures detected", summary_lines, color=Color.BOLD_RED)
            for reason in fail_reasons:
                safe_print(_colorize(f"\n✗ {reason}", Color.BOLD_RED))
            sys.exit(1)
    else:
        total_assertions = sum(len(cr.assertions) for cr in current_results)
        passed_assertions = sum(
            sum(1 for a in cr.assertions if a.passed) for cr in current_results
        )
        total_checks = sum(len(cr.checks) for cr in current_results)
        passed_checks = sum(
            sum(1 for c in cr.checks if c.passed) for cr in current_results
        )
        passed_cases  = sum(1 for cr in current_results if cr.passed)
        total_cases   = len(current_results)
        avg_score     = sum(cr.score for cr in current_results) / total_cases if total_cases > 0 else 0.0

        headers = ["Case", "Assertions", "Checks", "Score", "Result"]
        rows = []
        for cr in current_results:
            total_a  = len(cr.assertions)
            passed_a = sum(1 for a in cr.assertions if a.passed)
            total_c  = len(cr.checks)
            passed_c = sum(1 for c in cr.checks if c.passed)
            result_label = (
                _colorize("PASS", Color.BOLD_GREEN)
                if cr.passed
                else _colorize("FAIL", Color.BOLD_RED)
            )
            rows.append([
                cr.case_id,
                f"{passed_a}/{total_a}",
                f"{passed_c}/{total_c}",
                f"{cr.score:.2f}",
                result_label
            ])

        print_table(headers, rows, title="Test Results")

        summary_lines = [
            badge("Cases     ", f"{passed_cases}/{total_cases} passed"),
            badge("Assertions", f"{passed_assertions}/{total_assertions} passed"),
            badge("Checks    ", f"{passed_checks}/{total_checks} passed"),
            badge("Avg Score ", f"{avg_score:.2f}"),
        ]

        threshold = getattr(args, "threshold", None)
        if threshold is not None:
            threshold = float(threshold)

        failed = False
        fail_reasons = []

        if passed_cases < total_cases:
            failed = True
            fail_reasons.append(f"{total_cases - passed_cases} case(s) failed assertions or checks")

        if threshold is not None and avg_score < threshold:
            failed = True
            fail_reasons.append(f"Average score {avg_score:.2f} is below threshold {threshold:.2f}")

        safe_print()
        if not failed:
            print_box("All tests passed ✓", summary_lines)
            safe_print(success("\n✓ Test suite complete"))
        else:
            print_box("Test suite failed", summary_lines, color=Color.BOLD_RED)
            for reason in fail_reasons:
                safe_print(_colorize(f"\n✗ {reason}", Color.BOLD_RED))
            sys.exit(1)


def test_golden_command(args: argparse.Namespace) -> None:
    provider_name = (
        getattr(args, "provider", None)
        or get_config_value("provider")
        or "mock"
    )
    provider = get_provider(provider_name)
    model = getattr(args, "model", None) or get_config_value(f"models.{provider_name}")

    provider_kwargs = {}
    if model:
        provider_kwargs["model"] = model

    repo = PromptRepo()
    try:
        prompt_data = repo.get_version_meta(args.name, args.version)
    except Exception:
        print_error_panel(f"Prompt '{args.name} @ {args.version}' not found.")
        sys.exit(1)

    raw_prompt = prompt_data.get("prompt", "")
    fmt = prompt_data.get("format", "raw")

    suite_path = args.suite
    try:
        with open(suite_path, "r", encoding="utf-8") as f:
            suite = json.load(f)
    except Exception as exc:
        print_error_panel(f"Failed to load test suite: {exc}")
        sys.exit(1)

    golden_dir = os.path.dirname(os.path.abspath(suite_path))
    updated = 0

    safe_print()
    safe_print(bold(f"  Updating golden files for {args.name} @ {args.version}"))
    safe_print()

    for i, case in enumerate(suite, start=1):
        case_id    = case.get("id", f"case-{i}")
        input_vars = case.get("input", {})

        golden_assertions = [
            a for a in case.get("assertions", [])
            if a.get("type") == "golden" and a.get("file")
        ]
        if not golden_assertions:
            continue

        try:
            rendered = render_prompt(raw_prompt, input_vars, fmt)
        except Exception as exc:
            safe_print(warning(f"  ⚠  {case_id}: template error — {exc}"))
            continue

        provider_kwargs_copy = dict(provider_kwargs)
        if isinstance(rendered, list):
            provider_kwargs_copy["messages"] = rendered
            prompt_param = ""
        else:
            prompt_param = rendered

        try:
            with spinner(f"  [{i}/{len(suite)}] Running {case_id}…"):
                result = provider.run(prompt_param, **provider_kwargs_copy)
        except Exception as exc:
            safe_print(warning(f"  ✗  {case_id}: failed — {exc}"))
            continue

        output = result.get("output") or ""

        for ga in golden_assertions:
            golden_file = os.path.join(golden_dir, ga["file"])
            os.makedirs(os.path.dirname(golden_file), exist_ok=True)
            with open(golden_file, "w", encoding="utf-8") as f:
                f.write(output)
            safe_print(success(f"  ✓  Updated: {ga['file']}"))
            updated += 1

    safe_print()
    safe_print(success(f"✓ {updated} golden file(s) updated"))


def test_list_command(args: argparse.Namespace) -> None:
    import glob
    pattern = getattr(args, "dir", ".") + "/**/*.json"
    files   = glob.glob(pattern, recursive=True)
    suites  = []

    for f in sorted(files):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list) and data and isinstance(data[0], dict):
                has_assertions = any("assertions" in c for c in data)
                if has_assertions:
                    suites.append((f, str(len(data))))
        except Exception:
            pass

    if not suites:
        safe_print(dim("  No test suites found."))
        return

    safe_print()
    print_table(["Suite File", "Cases"], suites, title="Test Suites")


def test_command(args: argparse.Namespace) -> None:
    sub = getattr(args, "test_subcommand", None)
    if sub == "run":
        test_run_command(args)
    elif sub == "golden":
        test_golden_command(args)
    elif sub == "list":
        test_list_command(args)
    else:
        print_error_panel(
            "Unknown test subcommand.",
            tips=["Usage: promptvc test run <name> <version> --suite <file>",
                  "       promptvc test golden <name> <version> --suite <file>",
                  "       promptvc test list"],
        )
        sys.exit(1)


class ShellSession:
    def __init__(self) -> None:
        self.prompt_name: Optional[str] = None
        self.version: Optional[str] = None
        self.provider_name: str = get_config_value("provider") or "mock"
        self.model: Optional[str] = None
        self.variables: Dict[str, str] = {}
        self.history: List[Dict[str, Any]] = []
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


def _cmd_use(session: ShellSession, parts: List[str]) -> None:
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
    if len(parts) < 3 or parts[1] != "provider":
        safe_print(warning("  Usage: set provider <name>"))
        return
    session.provider_name = parts[2]
    session._update_model()
    safe_print(success(f"  ✓ Provider set to '{parts[2]}'"))


def _cmd_set_model(session: ShellSession, parts: List[str]) -> None:
    if len(parts) < 3 or parts[1] != "model":
        safe_print(warning("  Usage: set model <name>"))
        return
    session.model = parts[2]
    safe_print(success(f"  ✓ Model set to '{parts[2]}'"))


def _cmd_var(session: ShellSession, parts: List[str]) -> None:
    if len(parts) < 2 or "=" not in parts[1]:
        safe_print(warning("  Usage: var key=value"))
        return
    kv = " ".join(parts[1:])
    k, v = kv.split("=", 1)
    session.variables[k.strip()] = v.strip()
    safe_print(dim(f"  {k.strip()} = {v.strip()}"))


def _cmd_vars(session: ShellSession) -> None:
    if not session.variables:
        safe_print(dim("  No variables set."))
        return
    rows = [[k, v] for k, v in session.variables.items()]
    print_table(["Variable", "Value"], rows)


def _cmd_run(session: ShellSession) -> None:
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
    fmt = prompt_data.get("format", "raw")

    required = extract_variables_from_prompt(raw_prompt, fmt)
    missing  = required - set(session.variables.keys())
    if missing:
        safe_print(warning(f"  ⚠  Missing variables: {', '.join(sorted(missing))}"))
        safe_print(dim("  Set them with: var <key>=<value>"))
        return

    try:
        rendered = render_prompt(raw_prompt, session.variables, fmt)
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

    kwargs_copy = dict(kwargs)
    if isinstance(rendered, list):
        kwargs_copy["messages"] = rendered
        prompt_param = ""
    else:
        prompt_param = rendered

    t0 = time.monotonic()
    try:
        result = provider.run(prompt_param, **kwargs_copy)
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


def pipe_run_command(args: argparse.Namespace) -> None:
    pipeline_file = args.pipeline

    try:
        pipeline = load_pipeline(pipeline_file)
    except Exception as exc:
        print_error_panel(
            f"Failed to load pipeline: {exc}",
            tips=["Ensure the file exists and is valid JSON",
                  "See: promptvc pipe validate <file>"],
        )
        sys.exit(1)

    errors = validate_pipeline(pipeline)
    if errors:
        print_error_panel("Pipeline validation failed:", tips=errors)
        sys.exit(1)

    global_vars = _parse_vars(getattr(args, "var", None))
    provider_name = (
        getattr(args, "provider", None)
        or get_config_value("provider")
        or "mock"
    )

    safe_print()
    safe_print(bold(f"  Pipeline: {pipeline.name}"))
    if pipeline.description:
        safe_print(dim(f"  {pipeline.description}"))
    safe_print(dim(f"  Steps: {len(pipeline.steps)}"))
    safe_print()

    plan_rows = [
        [s.id, s.prompt_name, s.version, s.provider or provider_name]
        for s in pipeline.steps
    ]
    print_table(["Step", "Prompt", "Version", "Provider"], plan_rows, title="Pipeline Steps")
    safe_print()

    repo = PromptRepo()

    with spinner(f"Executing pipeline '{pipeline.name}'…"):
        results = execute_pipeline(
            pipeline      = pipeline,
            global_vars   = global_vars,
            repo          = repo,
            default_provider_name = provider_name,
            get_provider_fn = get_provider,
            get_config_fn   = get_config_value,
        )

    total_tokens = 0
    total_cost   = 0.0
    all_ok       = True

    result_rows = []
    for r in results:
        status = _colorize("✓ ok",   Color.BOLD_GREEN) if r.ok else _colorize("✗ failed", Color.BOLD_RED)
        tok    = str(r.tokens) if r.tokens else "—"
        cost   = None
        if r.tokens and r.model_used:
            cost = estimate_cost(r.model_used, int(r.tokens * 0.8), int(r.tokens * 0.2))
            if cost:
                total_cost += cost
        if r.tokens:
            total_tokens += r.tokens
        if not r.ok:
            all_ok = False
        result_rows.append([
            r.step_id,
            tok,
            format_latency(r.latency_ms),
            format_cost(cost),
            status,
        ])

    safe_print()
    print_table(
        ["Step", "Tokens", "Latency", "Cost", "Status"],
        result_rows,
        title=f"Pipeline Results: {pipeline.name}",
    )

    safe_print()
    for r in results:
        if r.error:
            safe_print(_colorize(f"  ✗ [{r.step_id}] {r.error}", Color.BOLD_RED))
            continue
        safe_print(bold(f"  [{r.step_id}] output:"))
        for line in (r.output or "").splitlines()[:15]:
            safe_print(f"    {line}")
        if len((r.output or "").splitlines()) > 15:
            safe_print(dim("    … (truncated)"))
        safe_print()

    summary_lines = [
        badge("Steps  ", f"{len(results)} completed"),
        badge("Tokens ", str(total_tokens) if total_tokens else "—"),
        badge("Cost   ", format_cost(total_cost) if total_cost else "—"),
    ]
    print_box("Pipeline complete" if all_ok else "Pipeline failed", summary_lines,
              color=Color.BOLD_GREEN if all_ok else Color.BOLD_RED)

    if not all_ok:
        sys.exit(1)

    safe_print(success("\n✓ Pipeline finished successfully"))


def pipe_validate_command(args: argparse.Namespace) -> None:
    pipeline_file = args.pipeline

    try:
        pipeline = load_pipeline(pipeline_file)
    except Exception as exc:
        print_error_panel(f"Failed to parse pipeline: {exc}")
        sys.exit(1)

    errors = validate_pipeline(pipeline)

    safe_print()
    safe_print(bold(f"  Pipeline: {pipeline.name}"))
    safe_print(dim(f"  Steps: {len(pipeline.steps)}"))
    safe_print()

    step_rows = [
        [s.id, s.prompt_name, s.version, s.provider or "—"]
        for s in pipeline.steps
    ]
    print_table(["Step", "Prompt", "Version", "Provider"], step_rows)

    if errors:
        safe_print()
        for e in errors:
            safe_print(_colorize(f"  ✗ {e}", Color.BOLD_RED))
        sys.exit(1)
    else:
        safe_print(success("\n✓ Pipeline is valid"))


def pipe_command(args: argparse.Namespace) -> None:
    sub = getattr(args, "pipe_subcommand", None)
    if sub == "run":
        pipe_run_command(args)
    elif sub == "validate":
        pipe_validate_command(args)
    else:
        print_error_panel(
            "Unknown pipe subcommand.",
            tips=["Usage: promptvc pipe run <pipeline.json> [--var key=value]",
                  "       promptvc pipe validate <pipeline.json>"],
        )
        sys.exit(1)


def validate_command(args: argparse.Namespace) -> None:
    sub = getattr(args, "validate_subcommand", None)
    if sub == "dataset":
        if not getattr(args, "file", None):
            print_error_panel("Missing dataset file path.", tips=["Usage: promptvc validate dataset <file>"])
            sys.exit(1)
        res = validate_dataset(args.file)
        _print_validation_result(res, f"dataset file: {args.file}")
    elif sub == "prompt":
        if not getattr(args, "name", None) or not getattr(args, "version", None):
            print_error_panel("Missing prompt name or version.", tips=["Usage: promptvc validate prompt <name> <version>"])
            sys.exit(1)
        repo = PromptRepo()
        res = validate_prompt(repo, args.name, args.version)
        _print_validation_result(res, f"prompt '{args.name} @ {args.version}'")
    else:
        print_error_panel(
            "Unknown validate subcommand.",
            tips=[
                "Usage: promptvc validate dataset <file>",
                "       promptvc validate prompt <name> <version>",
            ],
        )
        sys.exit(1)


def _print_validation_result(res: Any, target_label: str) -> None:
    safe_print()
    safe_print(bold(f"  Validation for {target_label}"))
    safe_print()

    if res.valid:
        safe_print(success("  ✓ Validation passed successfully!"))
        if res.warnings:
            safe_print()
            safe_print(warning("  Warnings:"))
            for w in res.warnings:
                safe_print(dim(f"    - {w}"))
        safe_print()
    else:
        print_error_panel("Validation failed.", tips=res.errors)
        if res.warnings:
            safe_print(warning("  Warnings:"))
            for w in res.warnings:
                safe_print(dim(f"    - {w}"))
        sys.exit(1)


def trace_command(args: argparse.Namespace) -> None:
    repo = PromptRepo()
    if not repo.storage.is_initialized:
        print_error_panel("Repository not initialized.", tips=["Run 'promptvc init' first."])
        sys.exit(1)

    store = TraceStore(repo.storage._root)

    name = args.name
    version = getattr(args, "version", None)
    limit = getattr(args, "last", 20) or 20

    try:
        limit = int(limit)
    except (ValueError, TypeError):
        limit = 20

    records = store.query(name, version, limit=limit)

    if getattr(args, "json", False):
        import dataclasses
        safe_print(json.dumps([dataclasses.asdict(r) for r in records], indent=2))
        return

    if not records:
        safe_print(dim(f"  No traces found for prompt '{name}'" + (f" @ {version}" if version else "")))
        return

    safe_print()
    safe_print(bold(f"  Execution Traces for: {name}" + (f" @ {version}" if version else "")))
    safe_print()

    headers = ["Timestamp", "Ver", "Provider", "Model", "Tokens", "Latency", "Score", "Result"]
    rows = []

    for r in records:
        lat = f"{r.latency_ms:.0f}ms" if r.latency_ms else "—"
        tok = str(r.tokens) if r.tokens is not None else "—"
        score = f"{r.score:.2f}" if r.score is not None else "—"

        if r.error:
            result_label = _colorize("ERROR", Color.BOLD_RED)
        else:
            result_label = _colorize("OK", Color.BOLD_GREEN)

        rows.append([
            r.timestamp[:19].replace("T", " "),
            r.version,
            r.provider,
            r.model,
            tok,
            lat,
            score,
            result_label,
        ])

    print_table(headers, rows, title=f"Recent Traces (Last {len(records)})")

    if records:
        last = records[-1]
        safe_print()
        safe_print(bold("  [Latest Trace Details]"))
        safe_print(dim(f"  Trace ID : {last.trace_id}"))
        safe_print(dim(f"  Inputs   : {json.dumps(last.variables)}"))
        if last.error:
            safe_print(_colorize(f"  Error    : {last.error}", Color.BOLD_RED))
        else:
            safe_print(dim("  Output   :"))
            output_lines = last.output.splitlines()
            indented_output = "\n".join(f"    {l}" for l in output_lines[:10])
            safe_print(indented_output)
            if len(output_lines) > 10:
                safe_print(dim("    ... (truncated)"))
        safe_print()


# ── Matrix Evaluation Command ──────────────────────────────────────────────────────

def matrix_command(args: argparse.Namespace) -> None:
    """Run N versions × M test cases and show a comparison matrix."""
    repo = get_repo()
    if repo is None:
        return

    provider_name = (
        getattr(args, "provider", None)
        or get_config_value("provider")
        or "mock"
    )
    try:
        provider = get_provider(provider_name)
    except Exception:
        print_error_panel(f"Unknown provider '{provider_name}'")
        return

    model = getattr(args, "model", None) or get_config_value(f"models.{provider_name}")

    config = MatrixConfig(
        name=args.name,
        versions=args.versions,
        dataset_path=args.dataset,
        provider_name=provider_name,
        model=model,
        deterministic=getattr(args, "deterministic", True),
    )

    safe_print()
    safe_print(bold(f"  Matrix Evaluation: {args.name}"))
    safe_print(dim(f"  Versions: {', '.join(args.versions)}"))
    safe_print(dim(f"  Dataset : {args.dataset}"))
    safe_print(dim(f"  Provider: {provider_name}"))
    safe_print()

    with spinner("Running matrix evaluation…"):
        try:
            result = run_matrix_eval(config, provider=provider, repo=repo)
        except Exception as exc:
            print_error_panel(f"Matrix evaluation failed: {exc}")
            return

    safe_print(format_matrix_table(result))
    safe_print()

    # Winner announcement
    if result.winner:
        safe_print(success(f"  ★ Winner: {result.winner}"))
        stats = result.get_stats(result.winner)
        if stats:
            safe_print(dim(f"    Mean score: {stats.mean_score:.3f}  |  "
                          f"Pass rate: {stats.pass_rate * 100:.0f}%  |  "
                          f"Avg latency: {stats.avg_latency_ms:.0f}ms"))
    safe_print()

    # Save report if requested
    report_path = getattr(args, "save_report", None)
    if report_path:
        try:
            save_matrix_report(result, report_path)
            safe_print(success(f"  ✓ Report saved to: {report_path}"))
        except Exception as exc:
            safe_print(warning(f"  ⚠ Failed to save report: {exc}"))
    safe_print()


# ── Analytics Command ──────────────────────────────────────────────────────────────

def analytics_command(args: argparse.Namespace) -> None:
    """Show usage analytics and cost dashboard."""
    repo = get_repo()
    if repo is None:
        return

    output_json = getattr(args, "json", False)
    space_name = getattr(args, "name", None)

    if space_name:
        # Per-space analytics
        try:
            space_data = repo.storage.load_space(space_name)
        except Exception as exc:
            print_error_panel(f"Space '{space_name}' not found: {exc}")
            return

        stats = compute_space_analytics(space_name, repo.storage._root, space_data)

        if output_json:
            import dataclasses
            safe_print(json.dumps({
                "name": stats.name,
                "total_runs": stats.total_runs,
                "total_tokens": stats.total_tokens,
                "total_cost_usd": stats.total_cost_usd,
                "avg_score": stats.avg_score,
                "latency_p50_ms": stats.latency.p50_ms if stats.latency else None,
                "latency_p95_ms": stats.latency.p95_ms if stats.latency else None,
            }, indent=2))
            return

        safe_print()
        info_lines = [
            badge("Space       ", space_name),
            badge("Total Runs  ", str(stats.total_runs)),
            badge("Total Tokens", f"{stats.total_tokens:,}"),
            badge("Total Cost  ", format_cost(stats.total_cost_usd)),
            badge("Avg Score   ", f"{stats.avg_score:.3f}" if stats.avg_score else "—"),
        ]
        if stats.latency:
            info_lines += [
                badge("Latency p50 ", f"{stats.latency.p50_ms:.0f}ms"),
                badge("Latency p95 ", f"{stats.latency.p95_ms:.0f}ms"),
            ]
        print_box(f"Analytics  {space_name}", info_lines)

        if stats.model_breakdown:
            safe_print()
            safe_print(bold("  Model Usage"))
            rows = [
                [m.model, str(m.run_count), f"{m.total_tokens:,}", format_cost(m.total_cost_usd)]
                for m in stats.model_breakdown
            ]
            print_table(["Model", "Runs", "Tokens", "Cost"], rows)

        if stats.version_breakdown:
            safe_print()
            safe_print(bold("  Per-Version Stats"))
            rows = [
                [
                    v.version,
                    str(v.run_count),
                    f"{v.avg_tokens:.0f}" if v.avg_tokens else "—",
                    f"{v.avg_latency_ms:.0f}ms" if v.avg_latency_ms else "—",
                    f"{v.avg_score:.3f}" if v.avg_score else "—",
                ]
                for v in stats.version_breakdown
            ]
            print_table(["Version", "Runs", "Avg Tokens", "Avg Latency", "Avg Score"], rows)
        safe_print()

    else:
        # Global analytics
        global_stats = compute_global_analytics(repo.storage._root, repo.storage)

        if output_json:
            safe_print(json.dumps({
                "total_spaces": global_stats.total_spaces,
                "total_versions": global_stats.total_versions,
                "total_runs": global_stats.total_runs,
                "total_tokens": global_stats.total_tokens,
                "total_cost_usd": global_stats.total_cost_usd,
                "avg_latency_ms": global_stats.avg_latency_ms,
            }, indent=2))
            return

        safe_print()
        info_lines = [
            badge("Spaces      ", str(global_stats.total_spaces)),
            badge("Versions    ", str(global_stats.total_versions)),
            badge("Total Runs  ", str(global_stats.total_runs)),
            badge("Total Tokens", f"{global_stats.total_tokens:,}"),
            badge("Total Cost  ", format_cost(global_stats.total_cost_usd)),
            badge("Avg Latency ", format_latency(global_stats.avg_latency_ms)),
        ]
        print_box("Global Analytics", info_lines)

        if global_stats.top_spaces_by_runs:
            safe_print()
            safe_print(bold("  Top Spaces by Runs"))
            rows = [[name, str(count)] for name, count in global_stats.top_spaces_by_runs]
            print_table(["Space", "Runs"], rows)

        if global_stats.model_breakdown:
            safe_print()
            safe_print(bold("  Model Breakdown"))
            rows = [
                [m.model, str(m.run_count), f"{m.total_tokens:,}", format_cost(m.total_cost_usd)]
                for m in global_stats.model_breakdown
            ]
            print_table(["Model", "Runs", "Tokens", "Cost"], rows)
        safe_print()


# ── Secrets Command ────────────────────────────────────────────────────────────────

def secrets_command(args: argparse.Namespace) -> None:
    """Manage encrypted API keys."""
    repo = PromptRepo()
    store = SecretsStore(repo.storage._root)

    if not store.is_available:
        print_error_panel(
            "The 'cryptography' package is required for secrets management.",
            tips=["Install with: pip install promptvc[secrets]"],
        )
        return

    sub = args.secrets_subcommand

    if sub == "set":
        service = args.service.strip().lower()
        value = getattr(args, "value", None)
        if not value:
            try:
                import getpass
                value = getpass.getpass(dim(f"  Enter API key for '{service}': "))
            except (KeyboardInterrupt, EOFError):
                safe_print(warning("\n  Cancelled."))
                return
        if not value:
            print_error_panel("API key cannot be empty.")
            return
        try:
            store.set(service, value)
            safe_print(success(f"  ✓ API key for '{service}' stored (encrypted)."))
            safe_print(dim(f"    Stored in: {store._path}"))
        except Exception as exc:
            print_error_panel(f"Failed to store secret: {exc}")

    elif sub == "get":
        service = args.service.strip().lower()
        try:
            key = store.get(service)
            if key:
                masked = key[:4] + "*" * (len(key) - 8) + key[-4:] if len(key) > 8 else "***"
                safe_print(success(f"  ✓ API key for '{service}': {masked}"))
            else:
                safe_print(warning(f"  No key stored for '{service}'."))
                safe_print(dim(f"  Hint: promptvc secrets set {service} <key>"))
        except Exception as exc:
            print_error_panel(f"Failed to retrieve secret: {exc}")

    elif sub == "delete":
        service = args.service.strip().lower()
        try:
            deleted = store.delete(service)
            if deleted:
                safe_print(success(f"  ✓ API key for '{service}' deleted."))
            else:
                safe_print(warning(f"  No key stored for '{service}'."))
        except Exception as exc:
            print_error_panel(f"Failed to delete secret: {exc}")

    elif sub == "list":
        try:
            services = store.list_services()
            if not services:
                safe_print(dim("  No secrets stored."))
                safe_print(dim("  Hint: promptvc secrets set openai <key>"))
            else:
                safe_print()
                safe_print(bold("  Stored Services"))
                rows = [[s, "●●●● (encrypted)"] for s in services]
                print_table(["Service", "Key"], rows)
                safe_print()
        except Exception as exc:
            print_error_panel(f"Failed to list secrets: {exc}")


# ── Search Command ─────────────────────────────────────────────────────────────────

def search_command(args: argparse.Namespace) -> None:
    """Full-text search across all prompt spaces."""
    repo = get_repo()
    if repo is None:
        return

    query = args.query.strip()
    tags_only = getattr(args, "tags_only", False)
    output_json = getattr(args, "json", False)

    results = repo.search(
        query,
        search_prompt=not tags_only,
        search_message=not tags_only,
        search_tags=True,
    )

    if output_json:
        safe_print(json.dumps([
            {"space": r.get("space"), "version": r.get("id"), "message": r.get("message"),
             "tags": r.get("tags", []), "timestamp": r.get("timestamp")}
            for r in results
        ], indent=2))
        return

    safe_print()
    if not results:
        safe_print(dim(f"  No results for '{query}'."))
        return

    safe_print(bold(f"  Search: '{query}' — {len(results)} result(s)"))
    safe_print()
    rows = []
    for r in results:
        tags_str = ", ".join(r.get("tags") or []) or "—"
        date = (r.get("timestamp") or "").split("T")[0] or "—"
        msg = (r.get("message") or "")[:48]
        rows.append([r.get("space", ""), r.get("id", ""), msg, tags_str, date])

    print_table(["Space", "Version", "Message", "Tags", "Date"], rows)
    safe_print()


# ── Tag Command ────────────────────────────────────────────────────────────────────

def tag_command(args: argparse.Namespace) -> None:
    """Add tags to a prompt version."""
    repo = get_repo()
    if repo is None:
        return

    try:
        updated = repo.tag_version(
            name=args.name,
            version=args.version,
            tags=args.tags,
            replace=getattr(args, "replace", False),
        )
        tag_list = ", ".join(updated.get("tags") or [])
        safe_print(success(f"  ✓ Tags updated for {args.name} @ {args.version}"))
        safe_print(dim(f"    Tags: {tag_list or '(none)'}"))
    except Exception as exc:
        print_error_panel(f"Failed to tag version: {exc}")


# ── Export Command ─────────────────────────────────────────────────────────────────

def export_command(args: argparse.Namespace) -> None:
    """Export prompt space(s) to a JSON file."""
    repo = get_repo()
    if repo is None:
        return

    output_path = args.output
    export_all = getattr(args, "all", False)
    space_name = getattr(args, "name", None)

    if export_all or not space_name:
        spaces = repo.list_spaces()
    else:
        spaces = [space_name]

    if not spaces:
        safe_print(warning("  No spaces found to export."))
        return

    export_data: Dict[str, Any] = {
        "promptvc_export_version": "1",
        "exported_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "spaces": {},
    }

    for name in spaces:
        try:
            space_data = repo.storage.load_space(name)
            export_data["spaces"][name] = space_data
        except Exception as exc:
            safe_print(warning(f"  ⚠ Skipping '{name}': {exc}"))

    try:
        import os
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, indent=2, ensure_ascii=False)
        safe_print(success(f"  ✓ Exported {len(export_data['spaces'])} space(s) to: {output_path}"))
    except Exception as exc:
        print_error_panel(f"Export failed: {exc}")


# ── Import Command ─────────────────────────────────────────────────────────────────

def import_command(args: argparse.Namespace) -> None:
    """Import prompt space(s) from an exported JSON file."""
    repo = get_repo()
    if repo is None:
        return

    file_path = args.file
    overwrite = getattr(args, "overwrite", False)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print_error_panel(f"File not found: {file_path}")
        return
    except json.JSONDecodeError as exc:
        print_error_panel(f"Invalid JSON in file: {exc}")
        return

    if "spaces" not in data:
        print_error_panel(
            "Invalid export file format.",
            tips=["Expected a file created by: promptvc export"]
        )
        return

    spaces = data["spaces"]
    imported = 0
    skipped = 0

    for name, space_data in spaces.items():
        existing = name in repo.list_spaces()
        if existing and not overwrite:
            safe_print(warning(f"  ⚠ Skipping '{name}' (already exists). Use --overwrite to replace."))
            skipped += 1
            continue
        try:
            repo.storage.save_space(name, space_data)
            action = "Updated" if existing else "Imported"
            safe_print(success(f"  ✓ {action}: {name}"))
            imported += 1
        except Exception as exc:
            safe_print(warning(f"  ⚠ Failed to import '{name}': {exc}"))

    safe_print()
    safe_print(bold(f"  Import complete: {imported} imported, {skipped} skipped."))
    safe_print()


# ── Parser Build & Main Router ───────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="promptvc",
        description="Prompt Version Control — git for LLM prompts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  promptvc init
  promptvc commit summarize --message "v1" --prompt "Summarize: {{text}}"
  promptvc run summarize v1 --provider openai
  promptvc test run summarize v1 --suite tests/summarize.json
  promptvc shell
  promptvc pipe run pipeline.json --var code="$(cat src/main.py)"
  promptvc status
""",
    )
    parser.add_argument("--version", action="version", version="promptvc 0.1.0")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON format")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    subparsers.add_parser("init", help="Initialize a promptvc repository")

    # status
    subparsers.add_parser("status", help="Show workspace overview (spaces, runs, recent activity)")

    # commit
    commit_p = subparsers.add_parser("commit", help="Commit a new prompt version")
    commit_p.add_argument("name", type=str, help="Prompt space name")
    commit_p.add_argument("--prompt", type=str, default=None,
                          help="Prompt text (interactive if omitted)")
    commit_p.add_argument("--message", type=str, default=None,
                          help="Commit message (interactive if omitted)")

    # log
    log_p = subparsers.add_parser("log", help="Show version history for a prompt space")
    log_p.add_argument("name", type=str, help="Prompt space name")

    # get
    get_p = subparsers.add_parser("get", help="Print raw prompt text for a version")
    get_p.add_argument("name", type=str, help="Prompt space name")
    get_p.add_argument("version", type=str, help="Version ID (e.g. v1)")

    # inspect
    inspect_p = subparsers.add_parser("inspect", help="Show detailed metadata for a version")
    inspect_p.add_argument("name", type=str, help="Prompt space name")
    inspect_p.add_argument("version", type=str, help="Version ID (e.g. v1)")

    # diff
    diff_p = subparsers.add_parser("diff", help="Diff two prompt versions")
    diff_p.add_argument("name", type=str, help="Prompt space name")
    diff_p.add_argument("v1", type=str, help="First version ID")
    diff_p.add_argument("v2", type=str, help="Second version ID")
    diff_p.add_argument("--text", action="store_true",
                        help="Show full unified text diff (like git diff)")
    diff_p.add_argument("--stat", action="store_true",
                        help="Show word/char/token breakdown table")

    # lock
    lock_p = subparsers.add_parser("lock", help="Lock a version against modification")
    lock_p.add_argument("name", type=str, help="Prompt space name")
    lock_p.add_argument("version", type=str, help="Version ID to lock")

    # list
    subparsers.add_parser("list", help="List all prompt spaces")

    # run
    run_p = subparsers.add_parser("run", help="Execute a prompt version")
    run_p.add_argument("name", type=str, help="Prompt space name")
    run_p.add_argument("version", type=str, help="Version ID (e.g. v1)")
    run_p.add_argument("--provider", type=str, default=None)
    run_p.add_argument("--model", type=str)
    run_p.add_argument("--timeout", type=int)
    run_p.add_argument("--max-tokens", type=int)
    run_p.add_argument("--stream", action="store_true")
    run_p.add_argument("--var", action="append",
                       help="Template variable (key=value). Repeatable.")
    run_p.add_argument("--dry-run", action="store_true",
                       help="Preview rendered prompt without executing")
    run_p.add_argument("--non-interactive", action="store_true",
                       help="Fail fast if required variables are missing")

    # eval
    eval_p = subparsers.add_parser("eval", help="Evaluate a prompt version on a dataset")
    eval_p.add_argument("name", type=str)
    eval_p.add_argument("version", type=str)
    eval_p.add_argument("--dataset", type=str, required=True)
    eval_p.add_argument("--provider", type=str, default=None)
    eval_p.add_argument("--model", type=str)
    eval_p.add_argument("--timeout", type=int)
    eval_p.add_argument("--max-tokens", type=int)
    eval_p.add_argument("--stream", action="store_true")
    eval_p.add_argument("--non-interactive", action="store_true")

    # compare
    compare_p = subparsers.add_parser("compare", help="Compare two prompt versions on a dataset")
    compare_p.add_argument("name", type=str)
    compare_p.add_argument("v1", type=str)
    compare_p.add_argument("v2", type=str)
    compare_p.add_argument("--dataset", type=str, required=True)
    compare_p.add_argument("--provider", type=str, default=None)
    compare_p.add_argument("--model", type=str)
    compare_p.add_argument("--timeout", type=int)
    compare_p.add_argument("--max-tokens", type=int)
    compare_p.add_argument("--stream", action="store_true")

    # apply
    apply_p = subparsers.add_parser("apply", help="Apply a prompt to a file using an LLM diff")
    apply_p.add_argument("name", type=str)
    apply_p.add_argument("version", type=str)
    apply_p.add_argument("--file", required=False, help="Target file to modify")
    apply_p.add_argument("--dir", type=str, default=None,
                         help="Target directory (apply to all matching files)")
    apply_p.add_argument("--glob", type=str, default="*",
                         help="Glob pattern when using --dir (default: *)")
    apply_p.add_argument("--provider", type=str, default=None)
    apply_p.add_argument("--model", type=str)
    apply_p.add_argument("--timeout", type=int)
    apply_p.add_argument("--max-tokens", type=int)
    apply_p.add_argument("--stream", action="store_true")
    apply_p.add_argument("--var", action="append")
    apply_p.add_argument("--dry-run", action="store_true")
    apply_p.add_argument("--non-interactive", action="store_true")

    # changes
    changes_p = subparsers.add_parser("changes", help="Show file change history for a space")
    changes_p.add_argument("name", type=str)

    # config
    config_p = subparsers.add_parser("config", help="Get or set configuration values")
    config_p.add_argument("action", type=str, choices=["set", "get", "list"])
    config_p.add_argument("key", type=str, nargs="?")
    config_p.add_argument("value", type=str, nargs="?")

    # test
    test_p = subparsers.add_parser("test", help="Run prompt unit tests")
    test_sub = test_p.add_subparsers(dest="test_subcommand")

    t_run = test_sub.add_parser("run", help="Run a test suite")
    t_run.add_argument("name", type=str, help="Prompt space name")
    t_run.add_argument("version", type=str, help="Version ID")
    t_run.add_argument("--suite", type=str, required=True, help="Path to test suite JSON")
    t_run.add_argument("--provider", type=str, default=None)
    t_run.add_argument("--model", type=str)
    t_run.add_argument("--threshold", type=float, help="Minimum average score threshold (0.0 to 1.0) to pass")
    t_run.add_argument("--deterministic", action="store_true", help="Disable LLM-as-judge checks")
    t_run.add_argument("--compare", type=str, help="Comparison version ID (e.g. v1) to check for regressions")

    t_golden = test_sub.add_parser("golden", help="Update golden files from current output")
    t_golden.add_argument("name", type=str)
    t_golden.add_argument("version", type=str)
    t_golden.add_argument("--suite", type=str, required=True)
    t_golden.add_argument("--provider", type=str, default=None)
    t_golden.add_argument("--model", type=str)

    t_list = test_sub.add_parser("list", help="List test suite files in the current project")
    t_list.add_argument("--dir", type=str, default=".", help="Root directory to search")

    # shell
    subparsers.add_parser("shell", help="Launch the interactive REPL")

    # pipe
    pipe_p = subparsers.add_parser("pipe", help="Run multi-step prompt pipelines")
    pipe_sub = pipe_p.add_subparsers(dest="pipe_subcommand")

    p_run = pipe_sub.add_parser("run", help="Execute a pipeline")
    p_run.add_argument("pipeline", type=str, help="Path to pipeline JSON file")
    p_run.add_argument("--var", action="append",
                       help="Global input variable (key=value). Repeatable.")
    p_run.add_argument("--provider", type=str, default=None,
                       help="Default provider for all steps")

    p_val = pipe_sub.add_parser("validate", help="Validate a pipeline file")
    p_val.add_argument("pipeline", type=str, help="Path to pipeline JSON file")

    # validate
    validate_p = subparsers.add_parser("validate", help="Validate a dataset JSON or a committed prompt version")
    validate_sub = validate_p.add_subparsers(dest="validate_subcommand", required=True)

    val_dataset = validate_sub.add_parser("dataset", help="Validate a dataset JSON file")
    val_dataset.add_argument("file", type=str, help="Path to dataset JSON file")

    val_prompt = validate_sub.add_parser("prompt", help="Validate a prompt version's schema consistency")
    val_prompt.add_argument("name", type=str, help="Prompt space name")
    val_prompt.add_argument("version", type=str, help="Version ID")

    # trace
    trace_p = subparsers.add_parser("trace", help="Show execution traces for a prompt")
    trace_p.add_argument("name", type=str, help="Prompt space name")
    trace_p.add_argument("version", type=str, nargs="?", help="Optional version ID filter")
    trace_p.add_argument("--last", type=int, default=20, help="Number of traces to show (default: 20)")
    trace_p.add_argument("--json", action="store_true", help="Output raw traces in JSON format")

    # matrix
    matrix_p = subparsers.add_parser("matrix", help="A/B test N versions against M test cases")
    matrix_p.add_argument("name", type=str, help="Prompt space name")
    matrix_p.add_argument("versions", nargs="+", help="Version IDs to compare (e.g. v1 v2 v3)")
    matrix_p.add_argument("--dataset", required=True, type=str, help="Path to test dataset JSON")
    matrix_p.add_argument("--provider", type=str, default=None)
    matrix_p.add_argument("--model", type=str)
    matrix_p.add_argument("--save-report", type=str, default=None, help="Save JSON report to this path")
    matrix_p.add_argument("--deterministic", action="store_true", help="Disable LLM judge")

    # analytics
    analytics_p = subparsers.add_parser("analytics", help="Show usage analytics and cost dashboard")
    analytics_p.add_argument("name", nargs="?", type=str, help="Prompt space name (omit for global)")
    analytics_p.add_argument("--json", action="store_true", help="Output as JSON")

    # secrets
    secrets_p = subparsers.add_parser("secrets", help="Manage encrypted API keys")
    secrets_sub = secrets_p.add_subparsers(dest="secrets_subcommand", required=True)

    sec_set = secrets_sub.add_parser("set", help="Store an encrypted API key")
    sec_set.add_argument("service", type=str, help="Provider name (e.g. openai, anthropic)")
    sec_set.add_argument("value", type=str, nargs="?", help="API key (prompted if omitted)")

    sec_get = secrets_sub.add_parser("get", help="Retrieve an API key (masked)")
    sec_get.add_argument("service", type=str)

    sec_del = secrets_sub.add_parser("delete", help="Delete a stored API key")
    sec_del.add_argument("service", type=str)

    secrets_sub.add_parser("list", help="List stored service names")

    # search
    search_p = subparsers.add_parser("search", help="Full-text search across all prompt spaces")
    search_p.add_argument("query", type=str, help="Search query")
    search_p.add_argument("--tags-only", action="store_true", help="Search tags only")
    search_p.add_argument("--json", action="store_true", help="Output as JSON")

    # tag
    tag_p = subparsers.add_parser("tag", help="Add tags to a prompt version")
    tag_p.add_argument("name", type=str)
    tag_p.add_argument("version", type=str)
    tag_p.add_argument("tags", nargs="+", help="Tags to add")
    tag_p.add_argument("--replace", action="store_true", help="Replace existing tags")

    # export
    export_p = subparsers.add_parser("export", help="Export prompt space(s) to a JSON file")
    export_p.add_argument("name", nargs="?", type=str, help="Space name (omit for all spaces)")
    export_p.add_argument("--output", "-o", type=str, required=True, help="Output file path")
    export_p.add_argument("--all", action="store_true", help="Export all spaces")

    # import
    import_p = subparsers.add_parser("import", help="Import prompt space(s) from a JSON file")
    import_p.add_argument("file", type=str, help="Path to exported JSON file")
    import_p.add_argument("--overwrite", action="store_true", help="Overwrite existing spaces")

    return parser


def _build_handler_map() -> Dict[str, Handler]:
    return {
        "init":      handle_init,
        "status":    status_command,
        "commit":    commit_command,
        "log":       log_command,
        "get":       get_command,
        "inspect":   inspect_command,
        "diff":      diff_command,
        "lock":      lock_command,
        "list":      list_command,
        "run":       run_command,
        "eval":      eval_command,
        "compare":   compare_command,
        "apply":     apply_command,
        "changes":   changes_command,
        "config":    config_command,
        "test":      test_command,
        "shell":     shell_command,
        "pipe":      pipe_command,
        "validate":  validate_command,
        "trace":     trace_command,
        "matrix":    matrix_command,
        "analytics": analytics_command,
        "secrets":   secrets_command,
        "search":    search_command,
        "tag":       tag_command,
        "export":    export_command,
        "import":    import_command,
    }


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        handler = _build_handler_map()[args.command]
        handler(args)
    except KeyError:
        print_error_panel(
            f"Unknown command: '{args.command}'",
            tips=["Run: promptvc --help  to see available commands"],
        )
        sys.exit(1)
    except PromptVCError as exc:
        print_error_panel(str(exc))
        sys.exit(1)
    except ValueError as exc:
        print_error_panel(f"Validation error: {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        safe_print(_colorize("\n  Interrupted.", Color.DIM))
        sys.exit(130)
    except Exception as exc:
        print_error_panel(
            f"Unexpected error: {exc}",
            tips=["This may be a bug. Please report it at github.com/uayushdubey/prompt-version-control"],
        )
        sys.exit(2)


if __name__ == "__main__":
    main()