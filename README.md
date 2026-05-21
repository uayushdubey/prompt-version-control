# promptvc

### Git-like Version Control, Observable Execution, and Assertion-Driven Testing for LLM Prompts.

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue)](https://python.org)
[![Testing Status](https://img.shields.io/badge/tests-passing-success)](tests/)

---

## 1. Why promptvc?

### The Problem: Prompt Engineering is Broken
Prompts are the load-bearing logical components of modern AI-powered software systems. They dictate user experiences, control structured data schema outputs, and drive automated code changes. Yet, while software engineering has spent decades developing rigorous versioning, unit testing, and telemetry for source code, prompts are treated as disposable strings.

Currently, developers manage prompts in ways they would never tolerate for code:
* **Ad-Hoc Storage:** Copy-pasted in Notion notebooks, hardcoded as python strings, or scattered across miscellaneous JSON configuration files.
* **No Auditable History:** Edited directly in production databases or config files with zero lineage, no commit messages, and no rollback options.
* **Silent Regressions:** Altering a prompt to fix one edge case silently breaks five others, with no regression test suite to flag the degradation.
* **Lack of Observability:** Run history, token usage, cost, and latency are rarely measured, let alone mapped to the specific prompt iteration that produced them.

### The Solution
`promptvc` brings software engineering discipline to prompt engineering. It is a zero-dependency, local-first CLI tool and Python core that treats prompts as versioned, immutable, and executable assets. Commit prompt changes, write unit test suites, orchestrate multi-step pipelines, and profile performance and cost metrics directly from your terminal.

---

## 2. What promptvc Is (and Is NOT)

* **IS Developer Infrastructure:** A CLI tool and core logic engine designed to integrate with local dev loops, automated testing suites, and CI/CD pipelines.
* **IS Immutable Lineage:** Committing a prompt registers a new version on disk (`v1`, `v2`, etc.) with a SHA-256 hash. Once created, version history cannot be modified; it can only be locked or evolved via subsequent commits.
* **IS Local-First & Multi-Provider:** Swaps execution environments (OpenAI, Anthropic, Gemini, Ollama, or a local mock provider) seamlessly via CLI options without editing templates or variables.
* **IS NOT a Web Playground:** No heavy visual canvas, drag-and-drop workflow builders, or cloud hosting dependencies.
* **IS NOT an Agent Framework:** It does not wrap your application code inside opinionated execution chains. It provides the clean versioning and execution layer for your prompts.

---

## 3. Core Capabilities

### 🗃️ Immutable Version Control & Registry
Manage prompts inside spaces (e.g., `summarize`, `code_review`). Each committed version is serialized as an immutable record containing:
* Raw prompt content with standard `{{variable}}` templates.
* Auto-generated token calculations and SHA-256 text hashes.
* Explicit commit messages, author metadata, and ISO timestamps.
* Optional variable validation schemas.
* **Lock Guard:** Run `promptvc lock` to freeze a prompt version permanently, blocking any mutations or overrides to guarantee reproducibility.

### 🧪 Assertion & Golden-File Testing (`promptvc test`)
Evaluate LLM outputs against strict behavioral unit tests without external testing dependencies:
* **Flexible Assertions:**
  * `contains` / `not_contains`: Assert presence or absence of substrings.
  * `regex`: Assert output matches a regular expression pattern.
  * `json_valid`: Confirm that the output is valid, parsable JSON.
  * `min_tokens` / `max_tokens`: Restrict output token range to prevent truncation or bloat.
  * `golden`: Assert semantic similarity against a baseline file using Jaccard word-set distance thresholds.
* **Golden Generation:** Run `promptvc test golden` to run test inputs against models and automatically generate or update baseline golden files.
* **Test Discovery:** Execute `promptvc test list` to search your workspace and list all JSON test suites.

### ⛓️ Multi-Step Orchestration Pipelines (`promptvc pipe`)
Chain sequential LLM invocations together into pipelines:
* Reference preceding step outputs with `{{ steps.step_id.output }}` template references.
* Read global pipeline parameters using `{{ input.variable_name }}` syntax.
* Run validations using `promptvc pipe validate` to check variable resolution, prompt exists, and step references before execution.
* Tracks execution duration, costs, and token consumption step-by-step.

### 💬 Interactive Shell REPL (`promptvc shell`)
Debug prompts, evaluate variables, and test model configurations within a stateful session:
* Select spaces and versions: `use summarize v2`.
* Bind variables interactively: `var text="Example content"`.
* Configure parameters: `set provider anthropic` or `set model claude-3-5-sonnet-20241022`.
* Call execution: `run` (streams response and displays token counts, latency, and costs).
* Profiling console: `cost` summarizes cumulative cost and latency for the shell session.

### 🛠️ Safe, Diff-Based Code Patching (`promptvc apply`)
Apply prompts to codebases safely and traceably:
* **Safe Encoding Detection:** Iterates through common encodings (`utf-8-sig`, `utf-8`, `utf-16`, `latin-1`) to read source files without corruption.
* **Diff Parsing:** Instructs the LLM to output only unified diff patches.
* **Patch Verification:** The tool parses the diff, validates removal lines against original source code, and displays a colored unified diff in the terminal.
* **Manual Confirmation:** Modifies the file only upon user approval, and logs the change to the space's `file_changes` registry for tracking.
* **Batch Mode:** Execute changes across multiple directories using `--dir` and `--glob` flags.

---

## 4. How It Works (Deep Dive)

### Core Architecture Flow
```
                     +---------------------------------------+
                     |         CLI Layer (main.py)           |
                     +---------------------------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |       Core Registry (repo.py)         |
                     +---------------------------------------+
                                  /            \
                                 /              \
                                v                v
       +----------------------------+        +----------------------------+
       |   Lock Guard (lock.py)     |        |   Storage Layer (storage.py) |
       +----------------------------+        +----------------------------+
                                \                /
                                 \              /
                                  v            v
                     +---------------------------------------+
                     |     Template Engine (template.py)     |
                     +---------------------------------------+
                                         |
                                         v
                     +---------------------------------------+
                     |    Provider Abstraction Registry      |
                     +---------------------------------------+
                        /          |            |          \
                       v           v            v           v
                  [ OpenAI ] [ Anthropic ]  [ Gemini ]  [ Ollama ]
```

* **CLI Layer (`cli/main.py`):** Parses command arguments, configures standard streams, routes commands to their handlers, and handles interactive variable compilation.
* **Core Registry (`core/repo.py`):** Coordinates logic flows. Loads prompt configurations, resolves `latest` aliases, enforces schemas, logs evaluations, and validates mutability.
* **Lock Guard (`core/lock.py`):** Validates write operations against space metadata, raising `VersionLockedError` or `AlreadyLockedError` before state serialization.
* **Storage Layer (`core/storage.py`):** Interacts with local JSON database files inside `.promptvc/spaces/`. Writes use temporary file swaps (`tempfile.NamedTemporaryFile` + atomic rename) to prevent corruption.
* **Template Engine (`utils/template.py`):** Uses standard library operations to extract template variables, apply defaults, check for unused inputs, and inject variables.
* **Provider Abstraction (`providers/`):** Standardizes APIs to match the uniform execution contract: `run(prompt: str, **kwargs) -> dict`. Outputs format as:
  ```json
  {
    "output": "Text returned by model",
    "tokens": 125,
    "input_tokens": 80,
    "output_tokens": 45,
    "latency_ms": 320,
    "cost_usd": 0.000375,
    "model_used": "gpt-4o-mini"
  }
  ```

---

## 5. CLI Workflows (Real Examples)

### Step 1: Initialize the Local Workspace
Create the local database directory:
```bash
$ promptvc init
✓ Workspace initialized at .promptvc
```

### Step 2: Commit a Prompt Version
Commit a prompt space to register your instructions. You can supply the prompt string inline:
```bash
$ promptvc commit review_code \
    --prompt "Identify code smells in this code: {{code}}" \
    --message "Initial code review template"

✓ Committed v1
  Space   : review_code
  Message : Initial code review template
  Tokens  : 9
  Hash    : fc7a20c91836102a...
```

### Step 3: Run the Prompt
Inject variables and execute the prompt using a local mock provider or a cloud provider:
```bash
$ promptvc run review_code v1 --provider mock --var code="def add(a, b): return a + b"

┌─── review_code @ v1 ───┐
│ Provider: mock / mock  │
│ Latency : 0ms          │
│ Tokens  : 9            │
│ Cost    : —            │
└────────────────────────┘

── Output ───────────────────────────────────────────
b + a nruter :)b ,a(dda fed
─────────────────────────────────────────────────────

✓ Run complete
```

### Step 4: Write and Execute a Test Suite
Create a test suite file: `promptvc-test/reviewer_tests.json`:
```json
[
  {
    "id": "basic_addition",
    "input": {
      "code": "def add(a, b): return a + b"
    },
    "assertions": [
      { "type": "contains", "value": "return" },
      { "type": "max_tokens", "value": 150 }
    ]
  }
]
```

Run the assertions:
```bash
$ promptvc test run review_code v1 --suite promptvc-test/reviewer_tests.json

  promptvc test  ·  review_code @ v1
  Suite    : promptvc-test/reviewer_tests.json  (1 case)
  Provider : mock

  ✓  basic_addition

┌────────── Test Results ──────────┐
│ Case           │ Assertions │ Result │
├────────────────┼────────────┼────────┤
│ basic_addition │ 2/2        │ PASS   │
└────────────────┴────────────┴────────┘

┌─── All tests passed ✓ ───┐
│ Cases     : 1/1 passed   │
│ Assertions: 2/2 passed   │
└──────────────────────────┘

✓ Test suite complete
```

### Step 5: Compose an Orchestration Pipeline
Define a pipeline config in `promptvc-test/example_pipeline.json`:
```json
{
  "name": "review_pipeline",
  "steps": [
    {
      "id": "review",
      "space": "review_code",
      "version": "v1"
    }
  ]
}
```

Run the pipeline:
```bash
$ promptvc pipe run promptvc-test/example_pipeline.json --var code="def add(a, b): return a + b"

  Pipeline: review_pipeline
  Steps: 1

Running step 1/1: review (review_code @ v1)...
✓ Step review complete in 0ms

┌─────────────── Pipeline Results ───────────────┐
│ Step   │ Status │ Tokens │ Latency │ Cost      │
├────────┼────────┼────────┼─────────┼───────────┤
│ review │ OK     │ 9      │ 0ms     │ $0.000000 │
└────────┴────────┴────────┴─────────┴───────────┘

✓ Pipeline review_pipeline completed successfully.
```

---

## 6. Developer Experience & Observability

`promptvc` optimizes your workflow speed and diagnostics:
* **Interactive vs Non-Interactive:** If required variables are absent and you are running locally, the CLI prompts you interactively. In CI environments, appending `--non-interactive` immediately exits with a non-zero code to prevent pipeline hangs.
* **Cost & Latency Audits:** Every execution logs token consumption and calculates costs using a built-in cost mapping matrix (supporting Claude 3.5 Sonnet, GPT-4o, Gemini 1.5 Pro, and local Ollama).
* **Cross-Platform Compatibility:** Reconfigures stream encoders to UTF-8 on Windows at startup to prevent charmap encoding errors when displaying tables, badges, and emojis in PowerShell.

---

## 7. Stability & Production Hardening

Recent updates have transitioned `promptvc` into a hardened, production-grade CLI:
* **Fail-Fast Checks:** The `apply` command validates target files and directories *before* prompting for template variables, preventing wasted API calls and runtime hangs.
* **Alias Resolution:** The `latest` tag is resolved natively to the latest version across `run`, `eval`, `get`, and `lock` commands.
* **Atomic Serialization:** Disk updates use temporary file swaps, eliminating risk of database corruption if execution is interrupted mid-write.
* **Strict Error Handling:** Enforces database constraints (such as mutability constraints) and catches `LockError`/`AlreadyLockedError` cleanly at the top-level CLI wrapper.
* **Filtered List Indexes:** Space listings query structures directly, ignoring configuration files or temporary logs.

---

## 8. Use Cases

* **Prompt Regression Testing in CI/CD:** Add `promptvc test run` into Git hooks and deployment scripts to prevent poor prompts from reaching production.
* **Offline Local Execution:** Run versioned prompts against local instances via `Ollama` for sensitive databases or air-gapped workstations.
* **Self-Auditing Code Modification:** Track which prompts changed which codebase files and when, utilizing `changes` to view file change logs.
* **Model Quality/Cost Benchmarking:** Change `--provider` and `--model` during comparisons to analyze output performance differences across providers before locking in production choices.

---

## 9. Installation & Quick Start

### Installation
Clone the repository and install the project in editable mode:
```bash
git clone https://github.com/uayushdubey/prompt-version-control.git
cd prompt-version-control
pip install -e .
```

Verify your installation:
```bash
$ promptvc status
```

### Configure Settings
Bind your default provider and keys:
```bash
$ promptvc config set provider openai
$ promptvc config set api_keys.openai "your-api-key"
$ promptvc config set models.openai "gpt-4o-mini"
```

---

## 10. Roadmap

* [ ] **LLM-As-A-Judge assertions:** Add support for semantic and model-graded validation steps inside test suites.
* [ ] **Remote Registry Integration:** Sync local prompt spaces with cloud registries (S3/PostgreSQL) for team collaboration.
* [ ] **Telemetry Export:** Export evaluation and run records directly into monitoring systems like LangSmith or Weights & Biases.
* [ ] **Custom Provider Plugins:** Support adding custom API models via local python plugin files.

---

## 11. License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.