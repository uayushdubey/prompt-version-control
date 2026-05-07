# promptvc

Git for prompts — a version control system for LLM prompts.

---

## What This Project Is

promptvc is a command-line tool for managing, executing, and auditing LLM prompts with the same discipline applied to source code. It treats prompts as versioned artifacts: immutable, traceable, and executable.

It is not a prompt playground. It is not a wrapper around an LLM API. It is infrastructure for teams and engineers who need to manage prompts with the same rigor they apply to code.

---

## The Problem

Prompts are increasingly load-bearing logic in production systems. Yet most teams manage them in ways they would never manage application code: pasted into Notion, hardcoded into scripts, modified in place with no history, and tested informally if at all.

When a prompt changes, there is typically no record of what changed, who changed it, why, or what the output looked like before and after. When something breaks, there is no baseline to roll back to. When a team member wants to know which version of a prompt is currently in production, there is no answer.

This is not sustainable as LLM usage matures.

---

## What promptvc Does

promptvc gives prompts the properties that source code has always had:

- **Versioning.** Every prompt is stored as an immutable, timestamped version. Commits are explicit and require a message.
- **Execution.** Prompts can be run against a configured provider. Results are recorded alongside the version that produced them.
- **Reproducibility.** Any version can be retrieved and re-executed. Run history is preserved per version.
- **Code modification.** Prompts can be applied to files via an LLM-powered apply pipeline that generates a strict unified diff, requires confirmation, and logs every change made.

---

## Key Capabilities

### Prompt Versioning

Every commit creates an immutable version with a unique ID, SHA-256 hash, token count, commit message, and UTC timestamp. Versions cannot be modified after creation. They can only be locked, which prevents any further operations on that version.

### Token Diffing

Compare token counts between any two versions of a prompt. Useful for cost estimation and understanding how a prompt has grown or shrunk over iterations.

### Run System

Execute any prompt version against a configured provider. The result, including output and token usage, is recorded and stored with the version. This creates a full audit trail of what a prompt produced at any point in time.

### Apply System

The apply command is the core feature for prompt-driven code modification. Given a prompt name, version, and target file, it:

1. Loads the raw prompt text for that version.
2. Reads the target file.
3. Constructs a structured instruction that asks the LLM to return only a unified diff.
4. Sends the combined input to the configured provider.
5. Displays the proposed diff for review.
6. Applies the diff safely using an internal patch engine, with confirmation required before any write occurs.

The LLM is explicitly instructed not to return full file content, not to include explanations, and not to use markdown. If no changes are needed, it returns `NO_CHANGES` and the tool exits cleanly.

### Diff-Based Patch Engine

An internal diff parser applies unified diffs to file content without any third-party patching library. Lines prefixed with `- ` are removed, lines prefixed with `+ ` are added, and metadata lines (`---`, `+++`, `@@`) are ignored. If a line marked for removal does not exist in the original content, the operation fails with an explicit error rather than silently continuing.

### File Change Tracking

Every successful apply operation is logged to the space's storage record. Each log entry includes the version used, the file path, the full diff, and a UTC timestamp. This creates a complete history of which prompts modified which files and when.

### Changes Command

Retrieve the full file modification history for a prompt space, displayed in reverse chronological order. Each entry shows the timestamp, version, and file path.

### Config System

Provider configuration is stored in `.promptvc/config.json`. The provider name and API key can be set via the CLI and are used as defaults for all subsequent commands. No API key is required unless a provider that needs one is invoked.

### Multi-Provider Support

The provider layer is abstracted behind a protocol. Current implementations:

- **mock** — returns deterministic output, requires no API key, suitable for testing.
- **openai** — calls the OpenAI API using the configured key.

New providers can be added by implementing the `run(prompt: str) -> dict` interface.

---

## Quick Example

A complete workflow from initialization to file modification:

```bash
# Initialize the repository
promptvc init

# Commit a prompt
promptvc commit refactor-imports \
  --message "Extract and clean import blocks" \
  --prompt "Reorganize all imports alphabetically and remove unused ones."

# View the version log
promptvc log refactor-imports

# Configure the provider
promptvc config set-provider openai
promptvc config set-api-key sk-...

# Apply the prompt to a file
promptvc apply refactor-imports v1 --file src/main.py

# Review the proposed diff in the terminal, then confirm or abort

# View the file change history
promptvc changes refactor-imports
```

---

## CLI Reference

### `promptvc init`

Initialize the repository. Creates the `.promptvc/` directory and required storage structure.

---

### `promptvc commit <name> --message <msg> --prompt <text>`

Create a new version of a prompt space. Each commit is immutable and receives an auto-incremented version ID (`v1`, `v2`, etc.).

```bash
promptvc commit summarize --message "Initial version" --prompt "Summarize the following text."
```

---

### `promptvc log <name>`

Display all versions for a prompt space, sorted newest to oldest. Shows version ID, message, token count, and timestamp.

```bash
promptvc log summarize
```

---

### `promptvc diff <name> <v1> <v2>`

Show the token count difference between two versions.

```bash
promptvc diff summarize v1 v3
```

---

### `promptvc run <name> <version>`

Execute a specific prompt version using the configured provider. Records the output and token usage.

```bash
promptvc run summarize v2
```

---

### `promptvc config set-provider <provider>`

Set the default provider. Stored in `.promptvc/config.json`.

```bash
promptvc config set-provider openai
```

---

### `promptvc config set-api-key <key>`

Set the API key for the configured provider.

```bash
promptvc config set-api-key sk-...
```

---

### `promptvc apply <name> <version> --file <path>`

Apply a prompt version to a file using the configured provider. The LLM returns a unified diff. The diff is displayed for review, and changes are applied only after explicit confirmation.

```bash
promptvc apply refactor-imports v2 --file src/utils.py
```

---

### `promptvc changes <name>`

Display the file modification history for a prompt space, most recent first.

```bash
promptvc changes refactor-imports
```

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
    repo.py           # Main interface: versioning, execution, tracking
    storage.py        # Storage engine: read/write space files
    tokenizer.py      # Token counting
    lock.py           # Lock guard logic
  providers/
    mock.py           # Deterministic test provider
    openai.py         # OpenAI API provider
  utils/
    config.py         # Config file read/write
    diff_apply.py     # Unified diff parser and patch engine
```

### Storage Layer

Reads and writes JSON space files under `.promptvc/spaces/`. Each space contains versions, run history, and file change records.

### Version Layer

Managed by `PromptRepo`. Handles commit, retrieval, locking, and log operations. All version IDs are auto-incremented and normalized.

### Execution Layer

The `run` method in `PromptRepo` retrieves a prompt, sends it to the provider, validates the result, records the run, and returns the output.

### Provider Layer

Providers implement a single method: `run(prompt: str) -> dict`. The dict must contain an `output` key. Additional fields (`tokens`, `model`, `latency_ms`) are supported for future use.

### Patch and Diff Engine

`apply_unified_diff(original, diff)` in `promptvc/utils/diff_apply.py` parses a unified diff string and applies it to a string of file content. No external libraries. Strict validation: any removal line that does not match the original raises a `ValueError`.

---

## Storage Model

Each prompt space is stored as a single JSON file:

```json
{
  "versions": {
    "v1": {
      "id": "v1",
      "prompt": "Reorganize all imports alphabetically.",
      "message": "Initial version",
      "timestamp": "2026-01-01T10:00:00+00:00",
      "tokens": 42,
      "locked": false,
      "hash": "a3f5..."
    }
  },
  "latest": "v1",
  "runs": [
    {
      "version": "v1",
      "output": "...",
      "tokens": 310,
      "timestamp": "2026-01-01T10:05:00+00:00"
    }
  ],
  "file_changes": [
    {
      "version": "v1",
      "file": "src/main.py",
      "diff": "--- src/main.py\n+++ src/main.py\n@@\n- import os, sys\n+ import os\n+ import sys",
      "timestamp": "2026-01-01T10:10:00+00:00"
    }
  ]
}
```

---

## Use Cases

### Prompt-Driven Development

Use versioned prompts as first-class tools in a development workflow. Commit a refactoring instruction, apply it across files, review the diffs, and log every change. The prompt that produced the change is always traceable.

### Automated Code Modification

Combine `promptvc apply` with a scripting layer to apply prompt-driven transformations across multiple files or repositories. The confirmation step can be bypassed in automated pipelines where output has already been reviewed.

### Audit and Traceability

Every file modification made via `apply` is stored with its version reference, diff, and timestamp. When a question arises about why a file changed, the change log provides a complete answer without relying on Git blame or commit messages written by a human.

### Reproducible Prompt Testing

Run the same prompt version against the same input multiple times and compare outputs. All run records are stored, making it possible to detect drift in provider behavior over time.

---

## Roadmap

- **Evaluation system.** Define expected outputs and run automated evaluations against prompt versions to score quality and detect regressions.
- **SaaS sync.** Push and pull prompt spaces to a remote registry for team sharing and backup.
- **Team workflows.** Role-based access, version approval flows, and shared change history.
- **Git integration.** Link prompt commits to Git commits, enabling cross-referenced history between code changes and the prompts that drove them.
- **Provider expansion.** Add support for Anthropic, Mistral, and local model runners.

---

## Installation

```bash
git clone https://github.com/uayushdubey/prompt-version-control
cd prompt-version-control
pip install -e .
```

Requires Python 3.9 or later. No external dependencies are required for the core system. The OpenAI provider requires the `openai` package.

---

Prompts are not configuration. They are not strings to be tuned and forgotten. They are logic — versioned, executable, and auditable — and they deserve the same engineering discipline as the systems they power.