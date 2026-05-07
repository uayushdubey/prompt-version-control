# promptvc

> **Git for prompts** — a version control system for LLM prompts

[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-active-brightgreen.svg)]()
[![CLI](https://img.shields.io/badge/interface-CLI-blueviolet.svg)]()

`promptvc` is a Python CLI tool that brings the discipline of version control to LLM prompts. Track every change, compare revisions, measure token usage, and replay exact prompt runs — all from your terminal.

---

## The Problem

Prompts are the source code of AI applications. Yet in most teams, they live as:

- **Hardcoded strings** buried inside Python files
- **Slack messages** or Notion docs that go stale
- **Undocumented trial-and-error** with no record of what worked

This creates real consequences:

| Problem | Impact |
|---|---|
| No version history | You can't roll back a prompt that broke production |
| No reproducibility | You can't recreate the exact input that caused a bug |
| No auditability | You don't know who changed what or when |
| No comparison | You can't measure whether a new prompt is better |
| No token visibility | Costs are unpredictable across iterations |

Teams ship AI features by instinct, not evidence. `promptvc` changes that.

---

## The Solution

`promptvc` treats prompts as first-class versioned artifacts — the same way Git treats source code.

```
promptvc commit summarizer \
  --prompt "Summarize this article in 3 bullet points." \
  --message "Initial version"
```

From that point, every iteration is tracked, diffable, auditable, and replayable.

- **Versioning** — every change creates an immutable snapshot
- **Reproducibility** — re-run any exact version against any provider
- **Auditability** — full history with messages, timestamps, and token counts
- **Experimentation** — diff two versions word-by-word before promoting

---

## Features

- **Immutable versioning** — commits create permanent, append-only snapshots (`v1`, `v2`, ...)
- **Token tracking** — every version records its token count automatically
- **Prompt diff** — compare any two versions by word, line, or character
- **Run execution** — execute prompts against a provider and record the output
- **Run history** — every execution is logged with output, tokens, and timestamp
- **Locking** — freeze a version against further changes
- **CLI-first** — designed for terminals, scripts, and CI pipelines
- **Provider abstraction** — plug in any backend (mock, OpenAI, Anthropic, etc.)

---

## How It Works

### Prompt Spaces

A **prompt space** is a named collection of versions for a single prompt. Think of it like a Git repository for one logical prompt — e.g. `summarizer`, `classifier`, `system-prompt`.

```
.promptvc/
├── summarizer.json
├── classifier.json
└── system-prompt.json
```

Each space lives as an atomic JSON file inside a `.promptvc/` directory, created automatically on `init`.

### Versions

Every `commit` produces an immutable version (`v1`, `v2`, `v3`, ...) containing:

```json
{
  "id": "v2",
  "prompt": "Summarize this article in 3 concise bullet points.",
  "message": "More concise framing",
  "timestamp": "2024-11-01T10:42:00Z",
  "tokens": 11,
  "locked": false,
  "hash": "a3f9..."
}
```

Versions are never mutated. A new commit always creates a new entry.

### Run System

The `run` command executes a prompt version through a registered provider. The result — including output and token usage — is appended to the space's run history and never discarded.

### Storage

All data is stored locally in `.promptvc/` as plain JSON. No database, no daemon, no network required.

---

## Installation

```bash
pip install promptvc
```

Or install from source:

```bash
git clone https://github.com/your-org/promptvc.git
cd promptvc
pip install -e .
```

**Requirements:** Python 3.9+

---

## Quick Start

```bash
# 1. Initialize a repository in your project
promptvc init

# 2. Commit your first prompt
promptvc commit summarizer \
  --prompt "Summarize this article in 3 bullet points." \
  --message "Initial version"

# 3. Iterate
promptvc commit summarizer \
  --prompt "Summarize this article in 3 concise bullet points. Be direct." \
  --message "Added directness instruction"

# 4. View history
promptvc log summarizer

# 5. Compare versions
promptvc diff summarizer v1 v2

# 6. Run a version
promptvc run summarizer v2
```

---

## CLI Reference

### `init`

Initialize a `promptvc` repository in the current directory.

```bash
promptvc init
```

Creates a `.promptvc/` directory used for all prompt storage.

---

### `commit`

Create a new version of a prompt.

```bash
promptvc commit <name> [--prompt TEXT] [--message TEXT]
```

| Argument | Description |
|---|---|
| `name` | Prompt space name (e.g. `summarizer`) |
| `--prompt` | Prompt text. If omitted, prompts interactively |
| `--message` | Commit message. If omitted, prompts interactively |

**Example:**

```bash
promptvc commit summarizer \
  --prompt "Summarize this in 3 bullet points." \
  --message "Baseline version"
```

```
✓ Committed v1  [9 tokens]
```

---

### `log`

Display the full version history of a prompt space.

```bash
promptvc log <name>
```

**Example:**

```bash
promptvc log summarizer
```

```
v3  |  2024-11-03 09:15  |  14 tokens  |  "Tightened tone"
v2  |  2024-11-02 14:30  |  12 tokens  |  "Added directness"
v1  |  2024-11-01 10:00  |  9 tokens   |  "Baseline version"
```

---

### `get`

Print the prompt text for a specific version.

```bash
promptvc get <name> <version>
```

**Example:**

```bash
promptvc get summarizer v2
```

```
Summarize this article in 3 concise bullet points. Be direct.
```

---

### `diff`

Compare two versions of a prompt.

```bash
promptvc diff <name> <v1> <v2>
```

**Example:**

```bash
promptvc diff summarizer v1 v2
```

```
  Summarize
  this
  article
  in
  3
- bullet
+ concise
+ bullet
  points.
+ Be
+ direct.
```

Additions are prefixed with `+`, removals with `-`, and unchanged tokens with a space.

---

### `run`

Execute a prompt version using a provider and record the result.

```bash
promptvc run <name> <version> [--provider PROVIDER]
```

| Argument | Description |
|---|---|
| `name` | Prompt space name |
| `version` | Version ID (e.g. `v2`) |
| `--provider` | Provider name (default: `mock`) |

**Example:**

```bash
promptvc run summarizer v2 --provider mock
```

```
✓ Ran summarizer@v2

Output:
[mock output for: Summarize this article in 3 concise bullet points. Be direct.]

Tokens: 12
```

Run results are stored in the prompt space and can be audited at any time.

---

### `lock`

Lock a version to prevent future modification.

```bash
promptvc lock <name> <version>
```

**Example:**

```bash
promptvc lock summarizer v1
```

```
✓ Locked summarizer@v1
```

Locked versions cannot be overwritten. Use this to protect approved, production-grade prompts.

---

### `list`

List all prompt spaces in the repository.

```bash
promptvc list
```

```
classifier
summarizer
system-prompt
```

---

## Project Structure

```
promptvc/
├── cli/
│   ├── commands/
│   │   ├── commit.py       # commit handler
│   │   ├── diff.py         # diff handler
│   │   ├── get.py          # get handler
│   │   ├── list.py         # list handler
│   │   ├── lock.py         # lock handler
│   │   ├── log.py          # log handler
│   │   └── run.py          # run handler + provider registry
│   └── main.py             # CLI entry point
├── core/
│   ├── diff.py             # diff engine (word/line/char)
│   ├── lock.py             # locking logic
│   ├── repo.py             # orchestration layer
│   ├── storage.py          # JSON persistence engine
│   └── tokenizer.py        # token counting
└── providers/
    └── mock.py             # mock provider (for testing)
```

---

## Provider System

`promptvc` uses a provider abstraction to decouple prompt execution from any specific LLM backend.

A provider must implement one method:

```python
def run(self, prompt: str) -> dict:
    return {
        "output": "...",   # required
        "tokens": 42,      # optional
    }
```

The built-in `mock` provider is used by default for testing and development. New providers (OpenAI, Anthropic, Bedrock, etc.) can be registered in `cli/commands/run.py` without changing any other part of the system:

```python
_PROVIDER_REGISTRY = {
    "mock":   MockProvider(),
    "openai": OpenAIProvider(),   # future
}
```

---

## Use Cases

**AI product teams** — version the prompts driving your features the same way you version your code. Never lose a working prompt again.

**Prompt engineers** — iterate with confidence. Compare token counts, diff wording changes, and lock approved versions for production.

**ML / research teams** — build reproducible prompt experiments. Re-run any exact version against any provider to validate results.

**CI/CD pipelines** — integrate `promptvc run` into your pipeline to validate prompt output before deployment.

---

## Roadmap

- [ ] OpenAI and Anthropic provider integrations
- [ ] Remote storage backend (S3, GCS)
- [ ] Prompt evaluation / scoring system
- [ ] `promptvc push` / `promptvc pull` for team sharing
- [ ] Web dashboard for run history visualization
- [ ] Cost tracking per run

---

## Contributing

Contributions are welcome. To get started:

```bash
git clone https://github.com/your-org/promptvc.git
cd promptvc
pip install -e ".[dev]"
```

Please open an issue before submitting a pull request for significant changes.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

<p align="center">
  Built for developers who treat prompts as seriously as code.
</p>