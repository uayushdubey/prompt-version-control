# 📦 promptrepo

**Prompt Version Control — Production-grade Git for LLM prompts.**

Manage, test, version, and execute your LLM prompts with standard software engineering discipline. All stored locally, offline, and version-controlled.

---

## 🚀 Key Features

* **Git-like Version Control**: Track changes in prompt templates using auto-incrementing IDs (`v1`, `v2`, `v3`) and SHA-256 hashes. Lock stable versions for production safety.
* **Declarative Unit Testing**: Write JSON assertion test suites using token bounds, regex, JSON schema validation, and semantic similarity (Jaccard & LLM-as-a-judge).
* **Multi-Provider Execution**: Standardized python and CLI wrappers for cloud API models (OpenAI, Anthropic, Gemini) and offline/local models (Ollama).
* **Stateful Interactive Shell**: A robust terminal REPL loop with persistent variable binding and cost/latency telemetry tracking.
* **Codebase Refactoring**: Run LLM prompt-diff engines to modify and patch local directories or source files safely with backup-and-rollback guards.
* **Zero Cloud Lock-in**: All version data and execution logs are stored as simple human-readable JSON files in your local `.promptrepo/` registry.

---

## 💾 Installation

Install the package via `pip`:

```bash
pip install promptrepo
```

To install with specific provider dependencies:

```bash
# Install with all cloud providers
pip install "promptrepo[all]"

# Or select individual providers
pip install "promptrepo[openai,anthropic,gemini]"
```

---

## ⚡ Quick Start

Get up and running in under a minute with 4 core commands:

```bash
# 1. Initialize a new local registry
promptrepo init

# 2. Commit your first prompt template space
promptrepo commit summarize --prompt "Summarize this: {{text}}" --message "v1 base template"

# 3. Verify history and version log
promptrepo log summarize

# 4. Run execution with variable bindings
promptrepo run summarize latest --var text="Version control improves pipeline stability." --provider mock
```

---

## 💻 CLI Command Reference

Below is a brief summary of core command patterns. Run `promptrepo --help` or `promptrepo <command> --help` for full parameter options.

| Command | Usage | Description |
|---|---|---|
| `init` | `promptrepo init` | Initialize a new local `.promptrepo` registry. |
| `commit` | `promptrepo commit <space> --prompt <text>` | Save a new immutable version with author log details. |
| `log` | `promptrepo log <space>` | Renders a version history log with token counts and lock status. |
| `lock` | `promptrepo lock <space> <version>` | Mark a version as read-only to prevent deletion or overwriting. |
| `run` | `promptrepo run <space> <version> --var k=v` | Substitute variables and execute against an LLM provider. |
| `eval` | `promptrepo eval <space> <version> --dataset <path>` | Run a prompt space version in batch against an input dataset. |
| `compare` | `promptrepo compare <space> <v1> <v2> --dataset <path>` | Run side-by-side comparative outputs on the same dataset. |
| `test run`| `promptrepo test run <space> <version> --suite <path>` | Execute automated assertions & output checks. |
| `apply` | `promptrepo apply <space> <version> --file <path>` | Refactor codebases using prompt-generated unified diffs. |
| `trace` | `promptrepo trace <space> [version] [--last N]` | Audit performance logs, costs, and latencies from registry. |
| `shell` | `promptrepo shell` | Open the stateful debugging REPL loop with cost tracking. |

---

## 🐍 Python SDK Integration

Avoid hardcoding prompt strings directly in your application code. Keep prompts isolated by using `promptrepo` to resolve, render, and execute versioned prompt assets.

### 1. Programmatic Execution (`run`)
```python
import promptrepo

result = promptrepo.run(
    name="translator",
    version="v1",
    provider="openai",
    model="gpt-4o-mini",
    temperature=0.3,
    # Variable bindings as keyword arguments:
    language="Spanish",
    text="Hello, world!"
)

if result.ok:
    print(f"Output: {result.output}")
    print(f"Total Tokens: {result.tokens}")
    print(f"Latency: {result.latency_ms}ms")
    print(f"Cost: ${result.cost_usd:.5f}")
```

### 2. Wrap Functions with Decorator (`@prompt`)
```python
import promptrepo

@promptrepo.prompt("summarizer", version="latest", provider="anthropic", model="claude-3-5-sonnet")
def summarize(text: str) -> promptrepo.RunResult:
    """This function is backed by promptrepo's 'summarizer' prompt space."""
    pass

# Returns a detailed RunResult containing outputs and usage telemetry
res = summarize(text="Prompt Version Control enforces immutability and version safety...")
print(f"Summary: {res.output}")
```

### 3. Granular Telemetry Tracking (`run_context`)
```python
import promptrepo

with promptrepo.run_context("classifier", "v2", provider="gemini") as ctx:
    result = ctx.run(text="The model performance was outstanding!")
    
    print(f"Prediction: {result.output}")
    print(f"Accumulated Session Cost: {promptrepo.format_cost(ctx.cost.total_cost_usd)}")
```

### 4. Parallel Batch Evaluation (`batch_run`)
```python
import promptrepo

inputs = [
    {"text": "First article context..."},
    {"text": "Second article context..."}
]

batch_result = promptrepo.batch_run(
    name="summarizer",
    version="v1",
    inputs=inputs,
    provider="openai",
    max_workers=4
)

print(f"Success rate: {batch_result.success_rate * 100}%")
print(f"Total Combined Cost: {promptrepo.format_cost(batch_result.total_cost_usd)}")
```

---

## 🛠️ Advanced DevOps & CI/CD Pipelines

### Pre-commit Git Hook Validation
Prevent regressions by validating prompt definitions before code gets pushed. Place this script in `.git/hooks/pre-commit` to gate commits on test thresholds:

```bash
#!/bin/sh
echo "=== Running promptrepo CI Assertion Checks ==="

# Fail the commit if test scores fall below the 85% threshold
promptrepo test run sentiment_analyzer latest --suite tests/sentiment_suite.json --non-interactive --threshold 0.85
if [ $? -ne 0 ]; then
  echo "❌ Regression detected or assertions failed! Aborting commit."
  exit 1
fi

echo "✅ All prompt assertions passed."
exit 0
```

### Programmatic API (`PromptRepo`)
For lower-level access to the repository storage engine, use `PromptRepo` directly:

```python
from promptrepo.core import PromptRepo

repo = PromptRepo()

# Retrieve raw template string
raw_template = repo.get("translator", "v1")

# Lock version to make it read-only
repo.lock("translator", "v1")

# Compare line-by-line unified diffs
diff_lines = repo.token_diff("translator", "v1", "v2")
```

---

## 🔒 Reliability & Production Architecture

* **Transactional Database Writes**: Registry mutations first write to `.tmp` files before renaming to replace target configuration files, preventing corruption during system crashes.
* **Encoding Tolerant Reads**: Code modification engine layers multiple string decoding attempts (UTF-8, UTF-8-sig, Latin-1, UTF-16) to read workspace resources safely.
* **Lazy Module Registration**: Postpones provider dependency imports (like `google-generativeai` or `openai`) until execution time, allowing promptrepo to run lightweight CLI commands without requiring missing packages.
* **Backup and Rollback Safety**: Automatically creates a `.bak` backup file before applying code changes, restoring original states if LLM diff generation fails context checks.