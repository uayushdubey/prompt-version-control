# promptrepo

**Prompt Version Control — Production-grade Git for LLM Prompts**

Manage, test, version, and execute LLM prompts with standard software engineering discipline. All stored locally, offline, and version-controlled.

---

## 1. Problem Statement

Prompts are load-bearing logical components in modern software architectures. They dictate data structures, govern agentic execution paths, and transform codebases. However, prompt engineering and integration workflows frequently lack the basic discipline applied to traditional source code.

In modern development environments, prompts suffer from the following systemic issues:
* **Out-of-band management**: Prompts are copy-pasted into Notion documents, shared over chat tools, or hardcoded directly in application source code.
* **Missing version history**: Prompt text is edited in place on production databases or server parameters with no version lineage, no change documentation, and no rollback mechanism.
* **Silent regressions**: Adjusting a prompt to fix an edge case on one input often degrades output quality across other inputs without triggering errors.
* **Lack of observability**: Latency, token consumption, and API cost metrics are rarely logged or mapped directly to the version of the prompt that generated them.

This lack of control introduces vulnerabilities when deploying LLM integrations to production. A single prompt modification can break backend parsing logic, escalate runtime API costs, or compromise model performance without developer visibility.

---

## 2. What This Tool Is (and Is NOT)

* **It IS a local, version-controlled prompt registry**: Prompts are saved in a structured, local format (`.promptrepo/spaces/*.json`) using sequential, immutable version identifiers.
* **It IS a declarative test and evaluation runner**: Supports assertion verification (JSON validation, token counts, regex checks, semantic similarity) against evaluation datasets directly in the console.
* **It IS a multi-provider execution abstraction**: Runs templates across local instances (Ollama) and cloud APIs (OpenAI, Anthropic, Gemini) using a unified invocation format.
* **It IS NOT a visual prompt playground**: There are no web-based node diagrams, drag-and-drop elements, or third-party cloud hosting requirements.
* **It IS NOT a framework-level runtime wrapper**: It does not force you to write application code inside specific chains, agent classes, or SDK models.

---

## 3. Comparison with Existing Tools

| Metric | promptrepo | LangSmith / W&B | OpenAI Evals | Basic Scripting |
|---|---|---|---|---|
| **Storage Locality** | Local filesystem (`.promptrepo/`) | Cloud-hosted dashboard | Local / Cloud datasets | None / In-code strings |
| **Telemetry Profile** | Latency and Cost checks | Trace trees and logs | Evaluation frameworks | Manual tracking |
| **Code Modification** | Diff-based patching | None | None | None |
| **Dependencies** | Standard Library + Requests | External packages | Python framework core | Custom scripts |
| **CI Integration** | CLI `--non-interactive` | Cloud webhooks | Python command files | Custom setups |

### Advantages of promptrepo
* **Privacy & Compliance**: Since all registry data and trace logs are saved on the local filesystem, promptrepo can be run in secure, air-gapped environments without sending telemetry or prompts to third-party dashboards.
* **Low Overhead**: Extremely fast execution times with lazy registration for third-party client packages.
* **CI-Friendly**: Simple shell execution checks return standard exit codes (0 for pass, 1 for fail), allowing easy pipeline integrations.

---

## 4. System Architecture

The following diagram illustrates how promptrepo processes commands, manages registry storage, coordinates provider executions, and writes trace telemetry.

```mermaid
graph TD
    subgraph CLI Interface Layer
        main["cli/main.py"]
    end

    subgraph Core Controller
        repo["core/repo.py (PromptRepo)"]
    end

    subgraph Local Registry (Storage)
        storage["core/storage.py (StorageEngine)"]
        db[".promptrepo/spaces/*.json"]
        traces[".promptrepo/traces.jsonl"]
    end

    subgraph Utilities
        template["utils/template.py (Template Engine)"]
        cost["utils/cost.py (Pricing Model)"]
        lock["core/repo.py (LockGuard)"]
    end

    subgraph Execution Adapter Layer
        provider["providers/ (OpenAI, Anthropic, Gemini, Ollama, Mock)"]
    end

    main -->|Invokes commands| repo
    repo -->|Verifies locked status| lock
    repo -->|Loads/Writes| storage
    storage -->|Saves state| db
    repo -->|Resolves parameters| template
    repo -->|Invokes provider run| provider
    provider -->|Returns metadata| repo
    repo -->|Computes USD cost| cost
    repo -->|Logs trace transaction| storage
    storage -->|Appends run records| traces
```

### Core Subsystems

1. **CLI Layer (`cli/main.py`)**: Translates command strings to handler calls, configures terminal output, and handles interactive fallbacks when parameters are missing.
2. **Core Controller (`core/repo.py`)**: Coordinates access to the version registry, validation schemas, evaluation metrics, and run executions.
3. **Lock Guard (`core/repo.py`)**: Enforces immutability rules. Blocks write requests targeting locked records.
4. **Storage Engine (`core/storage.py`)**: Manages local space file serialization. Implements transactional JSON writing to protect files from network or system interruptions.
5. **Template System (`utils/template.py`)**: Isolates template parameters, validates arguments, formats defaults, and returns clean prompt buffers.
6. **Provider Layer (`providers/`)**: Normalizes LLM API payloads and returns standardized metadata envelopes.

---

## 5. Installation

Install the package via pip:

```bash
pip install promptrepo
```

To install with specific provider dependencies:

```bash
# Install with all cloud providers
pip install "promptrepo[all]"

# Install individual providers
pip install "promptrepo[openai,anthropic,gemini]"
```

---

## 6. Quick Start

```bash
# 1. Initialize a new local registry
promptrepo init

# 2. Commit a prompt template space
promptrepo commit summarize --prompt "Summarize this: {{text}}" --message "v1 base template"

# 3. Verify history and version log
promptrepo log summarize

# 4. Run execution with variable bindings
promptrepo run summarize latest --var text="Version control improves pipeline stability." --provider mock
```

---

## 7. CLI Command Reference

### init
Initialize a promptrepo repository in the current workspace.
* **Syntax**: `promptrepo init`
* **Behavior**: Creates the `.promptrepo/` directory structure.
* **Example**:
  ```bash
  promptrepo init
  ```

### status
Provide a high-level overview of the current workspace.
* **Syntax**: `promptrepo status`
* **Behavior**: Inspects the registry and displays active spaces, version counts, execution runs, and recent actions.
* **Example**:
  ```bash
  promptrepo status
  ```

### commit
Commit a new version to a prompt space.
* **Syntax**: `promptrepo commit <name> [flags]`
* **Flags**:
  * `--prompt <string>`: Raw prompt text. If omitted, opens interactive multi-line terminal input.
  * `--message <string>`: Commit message. If omitted, opens interactive terminal prompt.
* **Behavior**: Validates that the space exists, checks that the latest version is not locked, and serializes the new version.
* **Example**:
  ```bash
  promptrepo commit translate --prompt "Translate this text to French: {{text}}" --message "v1 translation prompt"
  ```

### log
Display execution commit history for a prompt space.
* **Syntax**: `promptrepo log <name>`
* **Behavior**: Renders a structured history table containing version IDs, messages, token counts, lock status, and dates.
* **Example**:
  ```bash
  promptrepo log translate
  ```

### get
Display the raw prompt content of a specific version.
* **Syntax**: `promptrepo get <name> <version>`
* **Behavior**: Prints the raw template string. Supports the `latest` version alias.
* **Example**:
  ```bash
  promptrepo get translate latest
  ```

### inspect
Display detailed metadata and schema information for a version.
* **Syntax**: `promptrepo inspect <name> <version>`
* **Behavior**: Parses version records and outputs raw prompt text, variables, validation schema fields, lock states, and example CLI commands. Supports the `latest` version alias.
* **Example**:
  ```bash
  promptrepo inspect translate v1
  ```

### diff
Compute the token, character, and text difference between two prompt versions.
* **Syntax**: `promptrepo diff <name> <v1> <v2> [flags]`
* **Flags**:
  * `--text`: Display unified diff lines (like `git diff`).
  * `--stat`: Display comparison metrics table (characters, words, and tokens).
* **Behavior**: Calculates delta metrics between target versions.
* **Example**:
  ```bash
  promptrepo diff translate v1 v2 --text
  ```

### lock
Lock a prompt version to prevent modification.
* **Syntax**: `promptrepo lock <name> <version>`
* **Behavior**: Sets the `locked` property to `true` in the space record. Succeeding commits or evaluations targeting this version will block modifications. Supports the `latest` version alias.
* **Example**:
  ```bash
  promptrepo lock translate v1
  ```

### list
List all registered prompt spaces.
* **Syntax**: `promptrepo list`
* **Behavior**: Returns a table listing all space names, their latest active version, and version counts.
* **Example**:
  ```bash
  promptrepo list
  ```

### run
Execute a prompt version against a provider.
* **Syntax**: `promptrepo run <name> <version> [flags]`
* **Flags**:
  * `--provider <string>`: Target provider (openai, anthropic, gemini, ollama, mock).
  * `--model <string>`: Provider model override.
  * `--timeout <int>`: Timeout limit in seconds.
  * `--max-tokens <int>`: Output tokens limit.
  * `--stream`: Stream tokens to stdout.
  * `--var <key=value>`: Template variable binding. Repeatable.
  * `--dry-run`: Renders the template to stdout without executing it.
  * `--non-interactive`: Disable interactive terminal inputs.
* **Example**:
  ```bash
  promptrepo run translate v1 --var text="Hello world" --provider openai
  ```

### eval
Evaluate a prompt version against a dataset.
* **Syntax**: `promptrepo eval <name> <version> [flags]`
* **Flags**:
  * `--dataset <path>`: Required. Path to JSON dataset file.
  * `--provider`, `--model`, `--timeout`, `--max-tokens`, `--stream`, `--non-interactive`.
* **Example**:
  ```bash
  promptrepo eval translate v1 --dataset data.json --provider ollama --model llama3
  ```

### compare
Evaluate two prompt versions on a dataset and display outputs side-by-side.
* **Syntax**: `promptrepo compare <name> <v1> <v2> [flags]`
* **Flags**:
  * `--dataset <path>`: Required. Dataset file path.
  * `--provider`, `--model`, `--timeout`, `--max-tokens`, `--stream`.
* **Example**:
  ```bash
  promptrepo compare translate v1 v2 --dataset data.json
  ```

### apply
Apply a prompt to a target file or directory using LLM-generated diffs.
* **Syntax**: `promptrepo apply <name> <version> [flags]`
* **Flags**:
  * `--file <path>`: Target file path to modify.
  * `--dir <path>`: Target directory path to modify.
  * `--glob <pattern>`: Filter pattern when using `--dir` (default: `*`).
  * `--provider`, `--model`, `--timeout`, `--max-tokens`, `--stream`, `--var`, `--dry-run`, `--non-interactive`.
* **Example**:
  ```bash
  promptrepo apply refactor v1 --file src/main.py --provider openai
  ```

### changes
Display the file change history for a prompt space.
* **Syntax**: `promptrepo changes <name>`
* **Behavior**: Displays a table detailing execution timestamps, prompt versions used, and modified file paths.
* **Example**:
  ```bash
  promptrepo changes refactor
  ```

### config
View or modify configuration parameters.
* **Syntax**: `promptrepo config <action> [key] [value]`
* **Actions**:
  * `set`: Bind value to config key.
  * `get`: Print value of config key.
  * `list`: Output entire config JSON object.
* **Example**:
  ```bash
  promptrepo config set provider openai
  promptrepo config set models.openai gpt-4o-mini
  ```

### test
Manage and execute automated assertion test suites.
* **Syntax**: `promptrepo test <subcommand> [flags]`
* **Subcommands**:
  * `run <name> <version> --suite <path>`: Run assertion test suite.
    * `--threshold <float>`: Optional. Minimum average score (0.0 to 1.0) to pass (CI exit-code gate).
    * `--compare <version>`: Optional. Version ID (e.g. v1) to check for regressions. Displays delta metrics table.
    * `--deterministic`: Optional. Run only rules and skip LLM-as-a-judge assertions for speed/cost.
  * `golden <name> <version> --suite <path>`: Run cases and update stored golden files with the outputs.
  * `list [--dir <path>]`: List all test suite JSON files recursively.
* **Example**:
  ```bash
  promptrepo test run summarize v2 --suite tests/suite.json --compare v1 --threshold 0.8
  ```

### validate
Validate dataset files or committed prompt version schemas.
* **Syntax**: `promptrepo validate <subcommand>`
* **Subcommands**:
  * `dataset <file>`: Checks if a dataset file is well-formed JSON, contains `input` structures, and matches expected schemas.
  * `prompt <name> <version>`: Checks consistency of schema defaults, variable naming, types, and properties.
* **Example**:
  ```bash
  promptrepo validate dataset test_inputs.json
  promptrepo validate prompt summarize latest
  ```

### trace
Query and inspect execution runs log.
* **Syntax**: `promptrepo trace <name> [version] [flags]`
* **Flags**:
  * `--last <int>`: Retrieve the last N execution traces (default: 20).
  * `--json`: Print raw trace logs as a JSON list.
* **Example**:
  ```bash
  promptrepo trace summarize --last 10
  ```

### pipe
Execute multi-step prompt workflows sequentially.
* **Syntax**: `promptrepo pipe <subcommand>`
* **Subcommands**:
  * `run <pipeline_file> [--var key=value] [--provider name]`: Runs the specified multi-step pipeline.
  * `validate <pipeline_file>`: Verifies pipeline syntax and reference bindings without executing.
* **Example**:
  ```bash
  promptrepo pipe run translate_and_summarize.json --var text="Hello world"
  ```

### shell
Launch the stateful interactive REPL.
* **Syntax**: `promptrepo shell`
* **Behavior**: Opens a command-line prompt loop allowing variable bindings, quick model/provider switching, and real-time cost and latency tracking.
* **Example**:
  ```bash
  promptrepo shell
  ```

---

## 8. Python SDK Reference

The library exports a high-level developer SDK at the root namespace, as well as a lower-level core interface (`PromptRepo`) for advanced repository actions.

### 8.1 run
Substitute variables and execute a specific prompt version against a provider.

```python
def run(
    name: str,
    version: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    timeout: Optional[float] = None,
    max_tokens: Optional[int] = None,
    repo: Optional[PromptRepo] = None,
    **variables: Any,
) -> RunResult
```

#### Example Usage
```python
import promptrepo

result = promptrepo.run(
    name="translator",
    version="v1",
    provider="openai",
    model="gpt-4o-mini",
    temperature=0.3,
    language="Spanish",
    text="Hello, world!"
)

if result.ok:
    print(f"Output: {result.output}")
else:
    print(f"Failed: {result.error}")
```

### 8.2 prompt (Decorator)
Power any Python function with a versioned prompt space. The function's keyword arguments will map directly to template variables.

```python
def prompt(
    name: str,
    version: str = "latest",
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    timeout: Optional[float] = None,
    max_tokens: Optional[int] = None,
    repo: Optional[PromptRepo] = None,
) -> Callable
```

#### Example Usage
```python
import promptrepo

@promptrepo.prompt("summarizer", version="latest", provider="anthropic", model="claude-3-5-sonnet")
def summarize(text: str) -> promptrepo.RunResult:
    pass

result = summarize(text="Prompt Version Control enforces immutability and version safety...")
print(f"Summary: {result.output}")
```

### 8.3 run_context (Context Manager)
Use the `run_context` context manager when you want granular execution control, automatic trace logging, or want to compute aggregate costs/latencies over dynamic sequences.

```python
def run_context(
    name: str,
    version: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    timeout: Optional[float] = None,
    max_tokens: Optional[int] = None,
    repo: Optional[PromptRepo] = None,
) -> Iterator[RunContext]
```

#### Example Usage
```python
import promptrepo

with promptrepo.run_context("classifier", "v2", provider="gemini") as ctx:
    result = ctx.run(text="The pizza was delicious!")
    print(f"Output: {result.output}")
    print(f"Context Latency: {ctx.latency_ms} ms")
```

### 8.4 batch_run
Evaluate a prompt template across multiple input dictionaries in parallel using a thread pool.

```python
def batch_run(
    name: str,
    version: str,
    inputs: List[Dict[str, str]],
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    timeout: Optional[float] = None,
    max_tokens: Optional[int] = None,
    max_workers: int = 4,
    repo: Optional[PromptRepo] = None,
) -> BatchResult
```

#### Example Usage
```python
import promptrepo

inputs = [
    {"text": "First article contents..."},
    {"text": "Second article contents..."}
]

batch_result = promptrepo.batch_run(
    name="summarizer",
    version="v1",
    inputs=inputs,
    provider="openai",
    max_workers=4
)

print(f"Success Rate: {batch_result.success_rate * 100}%")
```

---

## 9. Low-level Core API (PromptRepo)

For programmatic control over repository configurations (such as committing prompts, managing locks, or computing prompt diffs):

```python
from promptrepo.core import PromptRepo
from promptrepo.utils.template import render_template

repo = PromptRepo()

# Initialize if not already initialized
if not repo.storage.is_initialized:
    repo.init_repo()

# Commit a prompt version programmatically
meta = repo.commit(
    name="translator",
    prompt="Translate this text to {{language}}: {{text}}",
    message="v1 initial translation prompt",
    schema={
        "variables": {
            "language": {"type": "string", "required": True},
            "text": {"type": "string", "required": True}
        }
    }
)

# Retrieve raw template string
prompt_template = repo.get("translator", "v1") 

# Lock stable version
repo.lock("translator", "v1")
```

---

## 10. DevOps & CI/CD Integration

### Git Hooks (Pre-commit Validation)
Prevent developers from committing broken prompts or regressions to the codebase.

Create or edit `.git/hooks/pre-commit`:
```bash
#!/bin/sh
echo "=== Running promptrepo pre-commit hooks ==="

# 1. Validate prompt schemas
promptrepo validate prompt sentiment_analyzer latest
if [ $? -ne 0 ]; then
  echo "Prompt validation failed!"
  exit 1
fi

# 2. Run assertion suites (Fail commit if average score falls below threshold)
promptrepo test run sentiment_analyzer latest --suite tests/sentiment_suite.json --non-interactive --threshold 0.85
if [ $? -ne 0 ]; then
  echo "Regression detected or assertions failed! Aborting commit."
  exit 1
fi

echo "All prompt assertions passed."
exit 0
```
Make the hook executable:
```bash
chmod +x .git/hooks/pre-commit
```

### GitHub Actions Workflow
Automatically execute assertion suites on every pull request.

Create `.github/workflows/promptrepo-verify.yml`:
```yaml
name: Verify Prompts

on:
  push:
    branches: [ main, dev ]
  pull_request:
    branches: [ main ]

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout Codebase
        uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'

      - name: Install promptrepo
        run: |
          pip install .

      - name: Configure Defaults & Secrets
        run: |
          promptrepo config set provider openai
          promptrepo config set api_keys.openai "${{ secrets.OPENAI_API_KEY }}"
          promptrepo config set models.openai "gpt-4o-mini"

      - name: Run Test Assertions
        run: |
          promptrepo test run sentiment_analyzer latest --suite tests/sentiment_suite.json --non-interactive --threshold 0.80
```

---

## 11. Stability & Reliability Measures

The codebase incorporates several checks to ensure reliability in production environments:
* **Transactional Serialization**: Database writes write first to a temporary file before renaming it to replace the target. This ensures that space registries are not corrupted if the process crashes mid-write.
* **Encoding Auto-Detection**: Modifying codebase files via `apply` uses layered encoding checks to prevent silent character corruption in non-ASCII codebases.
* **Stream Reconfiguration**: At module startup, `console.py` configures stdout/stderr streams to UTF-8 to prevent encoder faults when printing Unicode elements.
* **Backup and Rollback Safety**: Automatically writes `.bak` backups of codebase files during `apply` actions, safely rolling back changes if a diff fails to apply cleanly.
* **Idempotency Verification**: Validates the target file using SHA-256 fingerprints before modifications to guarantee that a prompt change is not double-applied.
* **Self-Healing Connections**: Combines backoff-with-jitter retry logic for model execution calls to gracefully handle rate-limit (HTTP 429) errors and temporary connection drops.

---

## 12. Roadmap (Upcoming Features)

* **Remote Registry Sync**: Commands to push and pull prompt spaces to cloud systems (PostgreSQL, S3) to support team environments.
* **Scoring Dashboard**: Static site report generation detailing cost trends, latency performance, and test history graphs.