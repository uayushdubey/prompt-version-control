# promptvc

Git for prompts — a version control system for LLM prompts.

---

## What This Project Is

`promptvc` is a command-line tool for managing, executing, and auditing LLM prompts with the same discipline applied to source code. It treats prompts as versioned artifacts: immutable, traceable, and executable.

It is not a prompt playground. It is not a wrapper around an LLM API. It is infrastructure for engineers and teams who need to manage prompts with the rigor they apply to production code.

---

## The Problem

Prompts are increasingly load-bearing logic in production systems. Yet most teams manage them in ways they would never manage application code: pasted into Notion, hardcoded into scripts, modified in place with no history, and tested informally if at all.

When a prompt changes, there is typically no record of what changed, who changed it, why, or what the output looked like before and after. When something breaks, there is no baseline to roll back to. When a team member wants to know which version of a prompt is currently in production, there is no answer.

This is not sustainable as LLM usage matures.

---

## What promptvc Does

`promptvc` gives prompts the properties that source code has always had:

**Versioning.** Every prompt is stored as an immutable, timestamped version. Commits are explicit and require a message.

**Execution.** Prompts can be run against any configured provider — cloud or local. Results are recorded alongside the version that produced them.

**Evaluation.** Prompts can be tested against a structured dataset. Results are collected per case and stored for future comparison.

**Comparison.** Two versions of a prompt can be run against the same dataset and their outputs compared side by side, enabling informed decisions about which version performs better.

**Reproducibility.** Any version can be retrieved and re-executed. Run history and evaluation records are preserved per version.

**Code modification.** Prompts can be applied to files via an LLM-powered apply pipeline that generates a strict unified diff, requires confirmation, and logs every change made.

**Structured Inputs.** Prompts can define schemas for their inputs, enabling type-aware, self-documented, and interactive execution without hardcoding variables.

**Multi-provider flexibility.** Switch between OpenAI, Gemini, Anthropic, Ollama, or a deterministic mock provider at any time — per command or globally — without changing prompt definitions.

**Local LLM support.** Run prompts entirely on-device via Ollama. No API key. No network dependency. Full version control and evaluation tooling, offline.

---

## Key Capabilities

### Prompt Versioning

Every commit creates an immutable version with a unique ID, SHA-256 hash, token count, commit message, and UTC timestamp. Versions cannot be modified after creation. They can only be locked, which prevents any further operations on that version.

### Token Diffing

Compare token counts between any two versions of a prompt. Useful for cost estimation and understanding how a prompt has grown or shrunk over iterations.

### Prompt Templates and Schema

Prompts can contain template variables using the `{{variable_name}}` syntax:

```
Fix the following code:\n{{code}}\nStyle guide: {{style}}
```

**Template behavior:**

- Variables are extracted automatically from the prompt text.
- Any variable referenced in the template must be provided at runtime, either via `--var` or interactively.
- Extra variables provided but not referenced in the template produce a warning and are ignored.

**Schema support:**

A prompt version can optionally define a schema that describes its variables:

```json
{
  "variables": {
    "code": {
      "type": "string",
      "required": true,
      "description": "Code to fix"
    },
    "style": {
      "type": "string",
      "required": false,
      "default": "PEP8",
      "description": "Style guide to apply"
    }
  }
}
```

When a schema is present:

- Required variables with no `--var` value are collected interactively at runtime.
- Optional variables use their `default` value if not provided.
- `--var key=value` overrides both schema defaults and interactive input.

When no schema is present, the template engine falls back to extracting variables directly from `{{...}}` placeholders. Missing variables are still collected interactively.

**Non-interactive mode:**

In CI/CD environments where interactive input is not possible, use `--non-interactive` to fail fast if any required variables are missing rather than hanging on a prompt:

```bash
promptvc run fix_code v2 --var code="print('hi')" --non-interactive
```

If a required variable is absent and `--non-interactive` is set, the command exits with a non-zero status and a descriptive error message.

**CLI override:**

```bash
promptvc run fix_code v2 --var code="print('hi')" --var style=pep8
```

`--var` can be repeated for multiple variables. It takes precedence over interactive input and schema defaults.

### Execution Model

There are three distinct execution modes:

- **run** — single execution of a prompt version against a provider. Variables are resolved (from `--var`, interactively, or schema defaults) and injected into the prompt before execution. Output and token usage are recorded.
- **eval** — batch execution of a prompt version across a structured dataset. Each input is run independently and all outputs are collected and stored.
- **compare** — comparative evaluation of two prompt versions against the same dataset. Outputs are displayed side by side at runtime. No storage is written for compare operations.

All three modes support the `--provider`, `--model`, `--timeout`, `--max-tokens`, and `--stream` runtime flags, which override global configuration on a per-invocation basis without modifying stored config.

### Evaluation System

The `eval` command runs a prompt version against a JSON dataset. Each item in the dataset must contain an `input` field. The prompt text is prepended to each input, the provider is called, and the output is collected per case. Results are stored under the `evaluations` key in the space record, enabling repeatable testing and regression detection across versions.

Dataset format:

```json
[
  { "input": "Summarize the following paragraph: ..." },
  { "input": "Summarize the following paragraph: ..." }
]
```

### Comparison System

The `compare` command runs two prompt versions against the same dataset and displays outputs side by side. This is a runtime operation — no evaluation records are written. The comparison is intended to inform version selection before committing to an evaluation record.

### Apply System

The `apply` command is the core feature for prompt-driven code modification. Given a prompt name, version, and target file, it:

1. Loads the raw prompt text for that version.
2. Resolves template variables from `--var` flags, schema defaults, or interactive input — before the prompt is sent to the provider.
3. Reads the target file, detecting its encoding automatically (UTF-8, UTF-16, Latin-1, and others). The detected encoding is preserved on write, preventing corruption of files that are not plain ASCII or UTF-8.
4. Constructs a structured instruction that asks the LLM to return only a unified diff.
5. Sends the combined input to the configured provider.
6. Displays the proposed diff for review.
7. Applies the diff safely using an internal patch engine, with confirmation required before any write occurs.

The LLM is explicitly instructed not to return full file content, not to include explanations, and not to use markdown. If no changes are needed, it returns `NO_CHANGES` and the tool exits cleanly.

### Diff-Based Patch Engine

An internal diff parser applies unified diffs to file content without any third-party patching library. Lines prefixed with `-` are removed, lines prefixed with `+` are added, and metadata lines (`---`, `+++`, `@@`) are ignored. If a line marked for removal does not exist in the original content, the operation fails with an explicit error rather than silently continuing.

### File Change Tracking

Every successful apply operation is logged to the space's storage record. Each entry includes the version used, the file path, the full diff, and a UTC timestamp. This creates a complete history of which prompts modified which files and when.

### Config System

Provider configuration is stored in `.promptvc/config.json`. The provider name, API key, and model defaults can be set via the CLI and are used as defaults for all subsequent commands. No API key is required when using the `mock` or `ollama` providers.

```bash
# Set the default provider
promptvc config set provider openai

# Set the default model for a specific provider
promptvc config set models.openai gpt-4o
promptvc config set models.ollama llama3
promptvc config set models.anthropic claude-sonnet-4-20250514
promptvc config set models.gemini gemini-1.5-pro

# Set API keys per provider
promptvc config set api_keys.openai sk-...
promptvc config set api_keys.anthropic sk-ant-...
promptvc config set api_keys.gemini AIza...
```

The `ollama` provider requires no API key; it connects to a locally running Ollama instance. All other cloud providers require an API key to be set before use.

### Multi-Provider Support

The provider layer is abstracted behind a common protocol. All five providers support per-command configuration of model, timeout, max tokens, and retry behavior. The structured return format is consistent across all providers: `{ "output": str, "tokens": int | None, "model_used": str }`.

Current implementations:

- **mock** — returns deterministic output. Requires no API key. Suitable for testing, local development, and CI validation of prompt structure and variable resolution without incurring API costs.
- **openai** — calls the OpenAI API using the configured key. Supports all current chat completion models.
- **anthropic** — calls the Anthropic Messages API. Supports Claude model families. Requires an Anthropic API key.
- **gemini** — calls the Google Gemini API. Supports Gemini 1.0 and 1.5 model families. Requires a Gemini API key.
- **ollama** — runs prompts against a locally hosted Ollama instance. Requires no API key and no network access. Ideal for air-gapped environments, cost-sensitive workflows, or teams evaluating open-weight models. Example: `promptvc run fix v1 --provider ollama --model llama3`.

New providers can be added by implementing the `run(prompt: str, **kwargs) -> dict` interface and registering them in `providers/registry.py`.

**Provider resolution order** across all commands: `--provider` CLI flag → value from `config.json` → `mock`.

**Per-provider model defaults** are stored in `config.json` under `models.<provider>`. The `--model` CLI flag overrides this on a per-invocation basis.

---

## Quick Example

A complete workflow from initialization to evaluation and file modification:

```bash
# Initialize the repository
promptvc init

# Commit two versions of a prompt
promptvc commit summarize \
  --message "Initial summarization prompt" \
  --prompt "Summarize the following text in two sentences."

promptvc commit summarize \
  --message "More concise summarization" \
  --prompt "Summarize the following text in one sentence."

# View version history
promptvc log summarize

# Configure the default provider and model
promptvc config set provider openai
promptvc config set api_keys.openai sk-...
promptvc config set models.openai gpt-4o

# Run a single execution with the configured provider
promptvc run summarize v1

# Run with a different provider and model on this invocation only
promptvc run summarize v1 --provider anthropic --model claude-sonnet-4-20250514

# Run with a local Ollama model, no API key required
promptvc run summarize v1 --provider ollama --model llama3

# Run with template variables and streaming output
promptvc run fix_code v2 --var code="print('hi')" --var style=pep8 --stream

# Run in non-interactive mode for CI/CD
promptvc run fix_code v2 --var code="print('hi')" --non-interactive

# Inspect a prompt version (shows variables, schema, example usage)
promptvc inspect fix_code v2

# Evaluate v1 against a dataset
promptvc eval summarize v1 --dataset ./data/inputs.json

# Evaluate with a specific model and timeout
promptvc eval summarize v1 --dataset ./data/inputs.json --provider gemini --model gemini-1.5-pro --timeout 30

# Compare v1 and v2 side by side on the same dataset
promptvc compare summarize v1 v2 --dataset ./data/inputs.json --provider openai

# Apply a prompt to a source file and review the diff
promptvc apply summarize v2 --file src/main.py

# Apply with template variables
promptvc apply fix_code v2 --file src/utils.py --var style=pep8

# Apply using a local model
promptvc apply fix_code v2 --file src/utils.py --provider ollama --model codellama

# View file modification history
promptvc changes summarize

# Lock a version to prevent further operations
promptvc lock summarize v1
```

---

## CLI Reference

### `promptvc init`

Initialize the repository. Creates the `.promptvc/` directory and required storage structure.

```bash
promptvc init
```

---

### `promptvc commit <name>`

Create a new version of a prompt space. Each commit is immutable and receives an auto-incremented version ID (`v1`, `v2`, etc.).

```bash
promptvc commit summarize \
  --message "Initial version" \
  --prompt "Summarize the following text."
```

| Argument | Required | Description |
|---|---|---|
| `name` | Yes | Prompt space name |
| `--message` | Yes | Commit message |
| `--prompt` | No | Prompt text (prompted interactively if omitted) |

---

### `promptvc log <name>`

Display all versions for a prompt space, sorted newest to oldest. Shows version ID, message, token count, and timestamp.

```bash
promptvc log summarize
```

---

### `promptvc get <name> <version>`

Print the raw prompt text for a specific version.

```bash
promptvc get summarize v2
```

---

### `promptvc inspect <name> <version>`

Display detailed information about a specific prompt version. Useful for understanding what a prompt expects before running it.

```bash
promptvc inspect fix_code v2
```

Output includes:

- **Content** — the raw prompt text.
- **Variables** — all template variables. If a schema exists, shows each variable's required/optional status, default value, and description. Otherwise, falls back to names extracted from `{{...}}` placeholders.
- **Metadata** — timestamp, token count, and SHA-256 hash.
- **Status** — whether the version is locked.
- **Example Usage** — a ready-to-run `promptvc run` command with `--var` placeholders for each variable.

---

### `promptvc diff <name> <v1> <v2>`

Show the token count difference between two versions.

```bash
promptvc diff summarize v1 v3
```

---

### `promptvc run <name> <version>`

Execute a specific prompt version using the configured provider. Records the output and token usage.

If the prompt contains template variables, any missing values are collected interactively unless `--non-interactive` is set. Provider resolution order: `--provider` flag → configured default → `mock`.

```bash
promptvc run summarize v2
promptvc run summarize v2 --provider openai --model gpt-4o
promptvc run summarize v2 --provider anthropic --model claude-sonnet-4-20250514
promptvc run summarize v2 --provider gemini --model gemini-1.5-pro
promptvc run summarize v2 --provider ollama --model llama3
promptvc run fix_code v2 --var code="print('hi')" --var style=pep8
promptvc run fix_code v2 --var code="print('hi')" --non-interactive
promptvc run summarize v2 --stream --max-tokens 512 --timeout 30
```

| Argument | Required | Description |
|---|---|---|
| `name` | Yes | Prompt space name |
| `version` | Yes | Version ID |
| `--provider` | No | Provider name (default: configured or `mock`) |
| `--model` | No | Model name to use for this invocation. Overrides the provider's configured default. |
| `--timeout` | No | Request timeout in seconds |
| `--max-tokens` | No | Maximum tokens in the provider response |
| `--stream` | No | Stream output to the terminal as it is generated |
| `--var` | No | Template variable in `key=value` format. Can be repeated. |
| `--non-interactive` | No | Fail immediately if required variables are missing. Prevents interactive prompts. |

---

### `promptvc eval <name> <version>`

Run a prompt version against a structured dataset. Each input is executed independently. Results are stored under `evaluations` in the space record.

```bash
promptvc eval summarize v1 --dataset ./data/inputs.json
promptvc eval summarize v1 --dataset ./data/inputs.json --provider openai --model gpt-4o
promptvc eval summarize v1 --dataset ./data/inputs.json --provider ollama --model llama3 --timeout 60
```

| Argument | Required | Description |
|---|---|---|
| `name` | Yes | Prompt space name |
| `version` | Yes | Version ID |
| `--dataset` | Yes | Path to dataset JSON file |
| `--provider` | No | Provider name (default: configured or `mock`) |
| `--model` | No | Model name to use for this invocation |
| `--timeout` | No | Request timeout in seconds |
| `--max-tokens` | No | Maximum tokens in the provider response |
| `--non-interactive` | No | Fail immediately if required variables are missing |

Dataset format:

```json
[
  { "input": "Text to process..." },
  { "input": "Another text..." }
]
```

---

### `promptvc compare <name> <v1> <v2>`

Run two prompt versions against the same dataset and display outputs side by side. This is a runtime comparison — no records are written.

```bash
promptvc compare summarize v1 v2 --dataset ./data/inputs.json
promptvc compare summarize v1 v2 --dataset ./data/inputs.json --provider anthropic --model claude-sonnet-4-20250514
promptvc compare summarize v1 v2 --dataset ./data/inputs.json --provider ollama --model llama3
```

| Argument | Required | Description |
|---|---|---|
| `name` | Yes | Prompt space name |
| `v1` | Yes | First version ID |
| `v2` | Yes | Second version ID |
| `--dataset` | Yes | Path to dataset JSON file |
| `--provider` | No | Provider name (default: configured or `mock`) |
| `--model` | No | Model name to use for this invocation |
| `--timeout` | No | Request timeout in seconds |
| `--max-tokens` | No | Maximum tokens in the provider response |

---

### `promptvc apply <name> <version>`

Apply a prompt version to a source file using the configured provider. The LLM returns a unified diff. The diff is displayed for review and applied only after explicit confirmation. File encoding is detected automatically and preserved on write.

If the prompt contains template variables, missing values are collected interactively before the provider is called. `--var` flags override interactive input. Use `--non-interactive` to disable prompting in automated pipelines.

```bash
promptvc apply refactor-imports v2 --file src/utils.py
promptvc apply fix_code v2 --file src/utils.py --var style=pep8
promptvc apply fix_code v2 --file src/utils.py --provider ollama --model codellama
promptvc apply fix_code v2 --file src/utils.py --provider openai --model gpt-4o --non-interactive --var style=pep8
```

| Argument | Required | Description |
|---|---|---|
| `name` | Yes | Prompt space name |
| `version` | Yes | Version ID |
| `--file` | Yes | Path to target file |
| `--provider` | No | Provider name (default: configured or `mock`) |
| `--model` | No | Model name to use for this invocation |
| `--timeout` | No | Request timeout in seconds |
| `--max-tokens` | No | Maximum tokens in the provider response |
| `--var` | No | Template variable in `key=value` format. Can be repeated. |
| `--non-interactive` | No | Fail immediately if required variables are missing |

---

### `promptvc changes <name>`

Display the file modification history for a prompt space, most recent first. Each entry shows the timestamp, version, and file path.

```bash
promptvc changes refactor-imports
```

---

### `promptvc config <action> <value>`

Set configuration values. Stored in `.promptvc/config.json`.

```bash
# Set the default provider
promptvc config set provider openai

# Set a per-provider model default
promptvc config set models.openai gpt-4o
promptvc config set models.anthropic claude-sonnet-4-20250514
promptvc config set models.gemini gemini-1.5-pro
promptvc config set models.ollama llama3

# Set API keys per provider
promptvc config set api_keys.openai sk-...
promptvc config set api_keys.anthropic sk-ant-...
promptvc config set api_keys.gemini AIza...
```

The `ollama` and `mock` providers require no API key.

| Action | Description |
|---|---|
| `set provider <name>` | Set the default provider |
| `set models.<provider> <model>` | Set the default model for a specific provider |
| `set api_keys.<provider> <key>` | Set the API key for a specific provider |

---

### `promptvc lock <name> <version>`

Lock a version to prevent further operations on it.

```bash
promptvc lock summarize v1
```

---

## Architecture

```
promptvc/
  cli/
    commands/         # One file per command
  core/
    repo.py           # Main interface: versioning, execution, tracking, schema
    eval.py           # Evaluation engine: batch execution against datasets
    compare.py        # Comparison engine: side-by-side version evaluation
    storage.py        # Storage engine: read/write space files
    tokenizer.py      # Token counting
    lock.py           # Lock guard logic
  providers/
    mock.py           # Deterministic test provider
    openai.py         # OpenAI API provider
    anthropic.py      # Anthropic Messages API provider
    gemini.py         # Google Gemini API provider
    ollama.py         # Local Ollama provider (no API key required)
    registry.py       # Provider registration and resolution
  utils/
    config.py         # Config file read/write
    diff_apply.py     # Unified diff parser and patch engine
    template.py       # Template variable extraction, validation, and rendering
```

### Storage Layer

Reads and writes JSON space files under `.promptvc/spaces/`. Each space contains versions, run history, evaluation records, and file change logs.

### Version Layer

Managed by `PromptRepo`. Handles commit, retrieval, locking, and log operations. All version IDs are auto-incremented and normalized. Versions may optionally include a `schema` field describing their input variables; `repo.get_schema(name, version)` retrieves it, returning an empty dict for versions committed without one.

### Template Layer

`utils/template.py` provides a minimal, dependency-free template system. It supports `{{variable_name}}` syntax with strict validation. Key functions:

- `extract_variables(template)` — returns all variable names found in the template.
- `validate_variables(template, variables)` — raises `TemplateError` if any required variables are missing.
- `render_template(template, variables)` — validates and substitutes all variables. Missing variables raise an error; extra variables are ignored with a warning.

The template layer is used by both `run` and `apply` before any provider call is made. When `--non-interactive` is active, the layer raises immediately on missing variables rather than entering an interactive collection loop.

### Execution Layer

Three distinct execution paths:

- **run** — single prompt execution via `PromptRepo.run()`. Result is appended to `runs`.
- **eval** — batch execution via `run_evaluation()` in `core/eval.py`. Results are appended to `evaluations` via `repo.log_evaluation()`.
- **compare** — dual batch execution via `compare_versions()` in `core/compare.py`. Runtime only; no storage writes.

All three paths accept a unified provider options dict (`model`, `timeout`, `max_tokens`, `stream`) that is forwarded to the provider at call time.

### Evaluation Layer

`core/eval.py` implements `run_evaluation()`. It loads a JSON dataset, retrieves the prompt text for the specified version, constructs a full prompt per input, calls the provider, and returns structured results. Invalid datasets, missing fields, and missing provider outputs all raise `ValueError`.

### Comparison Layer

`core/compare.py` implements `compare_versions()`. It calls `run_evaluation()` for both versions on the same dataset, validates that result lengths match, and returns a per-case comparison structure containing inputs and outputs from both versions.

### Provider Layer

Providers implement a single method: `run(prompt: str, **kwargs) -> dict`. The return dict must conform to `{ "output": str, "tokens": int | None, "model_used": str }`. Additional fields are allowed for forward compatibility. All providers include retry logic with configurable backoff and structured error handling; transient failures are retried up to the configured limit before raising.

Provider registration is centralized in `providers/registry.py`, which maps provider names to their implementation classes and resolves the active provider at runtime according to the override chain: `--provider` CLI flag → `config.json` default → `mock`.

Each provider accepts the following kwargs at call time (all optional):

| Parameter | Description |
|---|---|
| `model` | Model identifier to use for this call |
| `timeout` | Request timeout in seconds |
| `max_tokens` | Maximum tokens in the response |
| `stream` | If `True`, stream output tokens as they are generated |

### Patch and Diff Engine

`apply_unified_diff(original, diff)` in `promptvc/utils/diff_apply.py` parses a unified diff string and applies it to file content. No external libraries. Strict validation: any removal line that does not match the original raises a `ValueError`. The `apply` command wraps this function with encoding detection before reading and encoding preservation before writing, ensuring that non-UTF-8 source files (UTF-16, Latin-1, etc.) are not silently corrupted.

---

## Storage Model

Each prompt space is stored as a single JSON file under `.promptvc/spaces/`:

```json
{
  "versions": {
    "v1": {
      "id": "v1",
      "prompt": "Summarize the following text in two sentences.",
      "message": "Initial version",
      "timestamp": "2026-01-01T10:00:00+00:00",
      "tokens": 42,
      "locked": false,
      "hash": "a3f5...",
      "schema": {
        "variables": {
          "code": {
            "type": "string",
            "required": true,
            "description": "Code to fix"
          },
          "style": {
            "type": "string",
            "required": false,
            "default": "PEP8"
          }
        }
      }
    }
  },
  "latest": "v1",
  "runs": [
    {
      "version": "v1",
      "output": "...",
      "tokens": 310,
      "model_used": "gpt-4o",
      "timestamp": "2026-01-01T10:05:00+00:00"
    }
  ],
  "evaluations": [
    {
      "version": "v1",
      "dataset": "./data/inputs.json",
      "results": [
        { "input": "...", "output": "...", "tokens": 120, "model_used": "gpt-4o" },
        { "input": "...", "output": "...", "tokens": 134, "model_used": "gpt-4o" }
      ],
      "timestamp": "2026-01-01T10:10:00+00:00"
    }
  ],
  "file_changes": [
    {
      "version": "v1",
      "file": "src/main.py",
      "diff": "--- src/main.py\n+++ src/main.py\n@@\n- import os, sys\n+ import os\n+ import sys",
      "timestamp": "2026-01-01T10:15:00+00:00"
    }
  ]
}
```

The `schema` field is optional. Versions committed before schema support was introduced will not have it; all runtime behavior falls back gracefully to template-based variable extraction. The `model_used` field in run and evaluation records captures the exact model identifier returned by the provider, enabling post-hoc attribution when defaults change over time.

---

## Use Cases

### Prompt-Driven Development

Use versioned prompts as first-class tools in a development workflow. Commit a refactoring instruction, apply it across files, review the diffs, and log every change. The prompt that produced the change is always traceable.

### Prompt Testing Workflows

Use `eval` to run a prompt version against a fixed dataset before and after changes. Stored evaluation records provide a repeatable baseline. When outputs change unexpectedly, the record identifies which version introduced the regression.

### Regression Detection

Evaluate multiple versions of a prompt against the same dataset and compare stored results. If a newer version produces degraded output on known inputs, the evaluation history makes the regression visible without relying on manual review.

### Prompt Iteration Cycles

Use `compare` to evaluate two candidate versions side by side before deciding which to commit to. Run both against a representative dataset, review per-case outputs in the terminal, and promote the better-performing version. This replaces ad hoc testing with a structured iteration loop.

### Automated Code Modification

Combine `promptvc apply` with a scripting layer to apply prompt-driven transformations across multiple files or repositories. Use `--non-interactive` with pre-supplied `--var` values to run fully unattended. The confirmation step can be bypassed in automated pipelines where output has already been reviewed.

### CI/CD Pipeline Integration

Use `--non-interactive` across `run`, `eval`, and `apply` to ensure that any prompt missing required variables fails the pipeline immediately with a clear error rather than hanging. Combine with the `mock` provider to validate prompt structure, variable resolution, and template rendering in CI without incurring API costs.

### Local and Air-Gapped Workflows

Use the `ollama` provider to run the full `promptvc` feature set — including versioning, evaluation, comparison, and file apply — against locally hosted open-weight models. No network access required after model download. Useful for sensitive codebases, regulated environments, or cost-sensitive teams evaluating open-source LLMs.

### Provider Benchmarking

Run `compare` across the same dataset using different providers or models by changing the `--provider` and `--model` flags. Evaluate which model produces the highest-quality output for a given prompt space before committing to a provider for production use.

### Audit and Traceability

Every file modification made via `apply` is stored with its version reference, diff, and timestamp. Every evaluation is stored with its dataset path, per-case results, and the exact model used. When a question arises about why a file changed, which model produced a given output, or why a prompt was changed, the records provide a complete answer without relying on Git blame or informal documentation.

---

## Roadmap

- **Evaluation scoring.** Attach scorer functions to datasets to produce numeric quality scores per case, enabling automated pass/fail thresholds.
- **Dataset-based regression testing.** Define canonical datasets per prompt space and detect output drift across versions automatically.
- **CI integration.** Run evaluations as part of a CI pipeline, blocking promotion of a prompt version if evaluation scores fall below a defined threshold.
- **SaaS sync.** Push and pull prompt spaces to a remote registry for team sharing and backup.
- **Team collaboration.** Role-based access, version approval flows, and shared change history.
- **Git integration.** Link prompt commits to Git commits, enabling cross-referenced history between code changes and the prompts that drove them.
- **Additional Ollama model management.** Pull, list, and switch Ollama models directly from the `promptvc` CLI without leaving the prompt workflow.

---

## Installation

```bash
git clone https://github.com/uayushdubey/prompt-version-control
cd prompt-version-control
pip install -e .
```

Requires Python 3.9 or later. No external dependencies are required for the core system or the `mock` and `ollama` providers. Cloud providers require their respective packages:

- OpenAI provider: `pip install openai`
- Anthropic provider: `pip install anthropic`
- Gemini provider: `pip install google-generativeai`
- Ollama provider: requires a running [Ollama](https://ollama.com) instance; no Python package dependency.

---

Prompts are not configuration. They are not strings to be tuned and forgotten. They are logic — versioned, executable, and auditable — and they deserve the same engineering discipline as the systems they power.