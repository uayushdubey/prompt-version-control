# promptvc

**Test, version, and ship LLM prompts without breaking production.**

---

promptvc is a Python CLI tool that brings version control and reproducibility to LLM prompts. It tracks prompt changes, diffs versions at the token and semantic level, executes prompts against configured providers, and replays exact historical runs giving you a verifiable record of what ran, when, and what it returned.

---

## The Problem

LLM prompts in most codebases are strings — hardcoded in source files, passed around as constants, edited in-place, and deployed with no audit trail. When a prompt changes and model output degrades, there is no structured way to identify what changed, when it changed, or what the output looked like before.

This results in real operational problems:

- A prompt gets tweaked during debugging and committed with the rest of a feature diff. A week later, output quality degrades. No one remembers what changed.
- Token counts shift across iterations, pushing requests over context limits or inflating inference costs, with no per-version record to compare against.
- Two engineers are iterating on the same prompt in parallel. One version gets shipped. There is no agreed-upon way to evaluate which performed better.
- A production issue is traced to model output. Reproducing the exact run the exact prompt text, model version, and parameters is not possible because that state was never captured.

The core issue is not that prompts are hard to write. It is that they are treated as configuration managed with none of the rigor applied to code.

---

## What promptvc Does

promptvc models prompts as first-class versioned artifacts. Each time you commit a prompt, promptvc records the full text, a SHA-256 hash, a token count, and a timestamp. Versions are immutable. Once committed, a version cannot be overwritten — only superseded by a new one. This gives you a reliable history you can audit, compare, and return to.

The diff system operates at two levels. Token-level diffs show exactly which tokens were added or removed between two versions. Semantic diffs surface structural changes shifts in instruction framing, role assignments, or output constraints that token diffs can obscure. When you are iterating toward a target behavior, being able to state precisely what changed is the difference between deliberate engineering and guesswork.

The run system executes prompts against a configured provider, records the full request and response, and stores the run against its prompt version. Every run is replayable. If you need to reproduce what happened on a specific version at a specific point in time, you can — without relying on memory or reconstructed state.

---

## Quick Example

```bash
# Initialize a promptvc workspace in the current directory
$ promptvc init

Initialized promptvc workspace at .promptvc/

# Create a prompt space and commit the first version
$ promptvc commit summarizer "Summarize the following text in three sentences. Be concise and factual."

[summarizer] v1 committed
  hash: a3f2c1d8
  tokens: 17
  timestamp: 2025-05-07T10:22:01Z

# Iterate on the prompt and commit a new version
$ promptvc commit summarizer "Summarize the following text in three sentences. Prioritize key facts. Avoid editorial language."

[summarizer] v2 committed
  hash: 9b4e77f1
  tokens: 20
  timestamp: 2025-05-07T10:31:45Z

# Diff the two versions
$ promptvc diff summarizer v1 v2

--- summarizer/v1
+++ summarizer/v2
  Summarize the following text in three sentences.
- Be concise and factual.
+ Prioritize key facts. Avoid editorial language.

Token delta: +3 (17 -> 20)

# Execute the current version
$ promptvc run summarizer --input "The quarterly report showed a 12% increase in operating margin..."

[summarizer] v2 executed
  run_id: run_00042
  tokens_in: 20 | tokens_out: 61
  duration: 1.2s

Output:
  The company reported a 12% improvement in operating margin for the quarter...
```

---

## Core Concepts

**Prompt Spaces**

A prompt space is a named container for a single logical prompt and all its versions. Spaces map to discrete functions in your application a classifier, a summarizer, an extraction prompt, a system message and keep version history scoped and searchable. A space named `invoice-extractor` holds only the versions and runs for that prompt.

**Versions**

Each commit to a space creates a new version (`v1`, `v2`, `v3`, ...). Versions are immutable. Committing the same text twice produces two separate version records, each with its own hash and timestamp. This is intentional: the record reflects what you shipped and when, not just what the current text is.

Each version stores:
- Full prompt text
- SHA-256 content hash
- Token count (using the provider's tokenizer, or a configurable default)
- Commit timestamp
- Optional message

**Runs**

A run is an execution record tied to a specific version. It stores the full input, the raw model response, token usage, latency, and run parameters. Runs are indexed by run ID and are replayable: `promptvc replay run_00042` reconstructs and re-executes the exact request.

**Storage Model**

All data is stored locally under `.promptvc/` as structured JSON. There is no remote dependency, no daemon, and no background process. The directory is designed to be committed to source control alongside your code, giving your team a shared history of prompt changes correlated with code changes.

```
.promptvc/
  config.json          # Workspace config and provider settings
  spaces/
    summarizer/
      versions.json    # Ordered version history
      runs/
        run_00042.json # Individual run records
```

---

## Key Capabilities

**Immutable Version History**

Versions are append-only. Each commit is identified by an auto-incrementing version number and a content hash. You can reference any version by number or hash in diff, run, and replay commands. There is no `--force` flag on a committed version.

**Token-Level and Semantic Diffing**

`promptvc diff` supports two modes. Token diff (`--mode token`) shows character and token-level changes between two versions. Semantic diff (`--mode semantic`) parses prompt structure to surface higher-level changes — instruction additions, constraint removals, role changes — that are not apparent from raw text diffs alone.

**Run History and Replay**

Every execution is stored. `promptvc log runs` lists all runs for a space with version, timestamp, token usage, and latency. `promptvc replay <run_id>` re-executes a historical run against the same version with the same parameters. Useful for regression testing and incident reproduction.

**Locking**

`promptvc lock <space> <version>` marks a version as locked. Locked versions cannot be overwritten or deleted, and a commit to the same space while a lock is active requires explicit confirmation. This prevents accidental drift in prompts that are known to be working in production.

**Provider Abstraction**

Providers are configured per workspace. The execution layer is modular the run system calls a provider interface that is separate from the storage and versioning system. The current implementation ships with a mock provider for local development. OpenAI and Anthropic providers are in active development (see Roadmap).

---

## CLI Reference

**`promptvc init`**

Initialize a new workspace in the current directory.

```bash
promptvc init
promptvc init --provider mock   # specify provider at init time
```

**`promptvc commit`**

Commit a new version of a prompt to a named space.

```bash
promptvc commit <space> "<prompt text>"
promptvc commit summarizer "Summarize in three sentences." --message "tighten output length constraint"
```

**`promptvc log`**

Display version history for a space.

```bash
promptvc log <space>
promptvc log summarizer
promptvc log summarizer --runs   # include run history
```

**`promptvc diff`**

Compare two versions of a prompt.

```bash
promptvc diff <space> <v1> <v2>
promptvc diff summarizer v1 v2
promptvc diff summarizer v1 v2 --mode semantic
```

**`promptvc run`**

Execute the current (or a specific) version of a prompt.

```bash
promptvc run <space>
promptvc run summarizer --input "text to summarize"
promptvc run summarizer --version v1 --input "text to summarize"
promptvc run summarizer --params temperature=0.2,max_tokens=300
```

**`promptvc replay`**

Re-execute a stored run using its exact original parameters.

```bash
promptvc replay <run_id>
promptvc replay run_00042
```

**`promptvc lock`**

Lock a specific version against modification.

```bash
promptvc lock <space> <version>
promptvc lock summarizer v2
promptvc unlock summarizer v2   # remove lock
```

---

## Architecture

promptvc is structured around three independent layers.

**Storage layer** reads and writes the `.promptvc/` directory. All persistence operations go through this layer. The format is plain JSON, readable without tooling, and structured to be committed to source control. The storage layer has no network dependencies.

**Version layer** sits on top of storage and handles the semantics of spaces, commits, immutability, and locking. It enforces the constraint that versions are append-only and maintains the ordered history within each space.

**Execution layer** handles prompt runs. It constructs requests, dispatches to a configured provider, records the full request/response cycle, and writes the run record to storage. The provider interface is a single abstract class with one required method (`complete`). Adding a new provider requires implementing that interface and registering it in the config.

The CLI is a thin wrapper over these three layers. Each command maps to a single operation in one layer. There is no global state between commands.

---

## Use Cases

**AI product teams managing prompt stability across releases**

When a prompt is coupled to a product feature, changes to that prompt are changes to product behavior. Using promptvc, teams can lock prompts at a known-good version prior to a release, track any changes made during the release cycle, and diff the committed version against what is currently in source if behavior diverges.

**Prompt iteration with a structured baseline**

Rather than editing a prompt string in-place and re-testing manually, commit each candidate as a new version. Run both versions against the same inputs. Compare outputs and token counts. The version you discard is still in history if you need to return to it.

**Debugging production output regressions**

When a model output issue is reported, `promptvc log` shows exactly what prompt version was active and when it was committed. If the run was executed through promptvc, `promptvc replay` reproduces the exact request — same prompt version, same parameters — without reconstructing it from memory or logs.

**Cost and token usage tracking per prompt version**

Token counts are recorded at commit time and at run time. As you iterate on a prompt, you can see whether a revision shortened or lengthened the prompt and what effect that had on completion token usage across runs.

---

## Roadmap

The following capabilities are planned or in active development:

**Evaluation system.** Run a prompt version against a fixed test set and score outputs against defined criteria. Store evaluation results per version so you can compare scores across the version history of a space, not just text diffs.

**Provider integrations.** Native support for OpenAI and Anthropic APIs, with provider-specific tokenizer support and model parameter validation at commit time.

**Remote storage backend.** Optional sync to a remote store (S3, GCS, or a hosted backend) for team-shared history. The local-first model remains the default; remote sync is opt-in.

**Team workflows.** Prompt review flows modeled on pull requests — propose a version change, require sign-off before the version becomes the production-locked version for a space.

**CI integration.** A `promptvc check` command for use in CI pipelines. Fails if a locked version has been modified, or if a run against a test input produces output that diverges from a stored baseline.

---

## Installation

Requires Python 3.10 or later.

```bash
pip install promptvc
```

To install from source:

```bash
git clone https://github.com/uayushdubey/promptvc
cd promptvc
pip install -e .
```

Verify the installation:

```bash
promptvc --version
```

---

## Contributing

Issues and pull requests are welcome. Before submitting a PR, run the test suite:

```bash
pytest tests/
```

The provider interface and storage layer have full unit test coverage. New providers should include tests against the mock backend before targeting a live API.

---

## License

MIT. See [LICENSE](./LICENSE) for details.

---

Prompts are not configuration. They are logic. They deserve the same operational discipline as any other artifact you ship.
