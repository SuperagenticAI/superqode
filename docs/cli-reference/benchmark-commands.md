# Benchmark Commands

Run coding harness benchmarks across multiple agent targets.

Harness JSON reports include context diagnostic events when available. Comparison
rows distinguish actual character reductions from shadow proposals, count
retrieval failures and selector calls, and mark usage incomplete when selector
spend is unknown. Character measurements do not establish provider token savings
or coding-quality improvements; matched grading remains required.

---

## benchmark run

Run benchmark tasks across one or more targets.

```bash
superqode benchmark run <tasks.json> [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `tasks.json` | Path to a JSON file defining benchmark tasks |

### Options

| Option | Description |
|--------|-------------|
| `--target` | Target to benchmark (repeatable, e.g., `--target superqode --target opencode`) |

### Examples

```bash
superqode benchmark run tasks.json --target superqode --target opencode --target pi --target deepagents
```

---

## Tasks File Format

The tasks file is a JSON object containing a `tasks` array:

```json
{
  "tasks": [
    {
      "id": "task-001",
      "prompt": "Implement a fibonacci function in Python",
      "cwd": "./fixture",
      "checks": [["python", "grader.py"]],
      "protected_paths": ["grader.py"],
      "timeout_seconds": 300
    }
  ]
}
```

Each task has a unique `id` and `prompt`. Relative working directories resolve
against the manifest directory. Executable `checks` grade the result independently;
`protected_paths` reject changes to those grader files. `expected_text` is also
available for basic fixtures. A successful process exit without a correctness
criterion is ungraded.

### Supported Targets

| Target | Description |
|--------|-------------|
| `superqode` | SuperQode harness |
| `opencode` | OpenCode ACP agent |
| `pi` | pi.ai coding agent |
| `deepagents` | DeepAgents harness |

## benchmark compare

```bash
sq benchmark compare comparison.json --repetitions 3 --output results.json
```

In the TUI, `:benchmark compare` accepts the same arguments.

The manifest includes `tasks` as above and at least two distinct `targets`:

```json
{
  "targets": [
    {"name": "superqode", "provider": "PROVIDER", "model": "MODEL", "revision": "REVISION", "command": ["sq", "harness", "run", "--spec", "/absolute/path/harness.yaml", "--json", "--prompt"]},
    {"name": "pi", "provider": "PROVIDER", "model": "MODEL", "revision": "REVISION", "command": ["pi", "--mode", "json", "--provider", "PROVIDER", "--model", "MODEL", "-p"]}
  ],
  "tasks": [
    {"id": "case", "prompt": "Implement the fixture", "cwd": "./fixture", "checks": [["python", "grader.py"]], "protected_paths": ["grader.py"]}
  ]
}
```

Replace the placeholders, select the same provider/model in both harnesses and
verify installed revisions before running. Revision fields record declarations;
they do not install or independently verify executable versions. Each command
receives the task prompt as its final argument.

`--repetitions` accepts 1 to 20 trials (default 3). Each attempt starts from a fresh
copy of one captured source snapshot, and target order alternates between trials.
The report includes grading, workspace hashes, median/p95 latency and reported
cost per solved trial, including failed-attempt spend. Unknown or partial usage
remains unknown; reported cost is an estimate, not billing evidence. A comparison
is eligible only with executable grading, isolated workspaces, matching reported
model identity, revision declarations and complete usage.

The scorecard also requires the same unique task/repetition pairs for every
target, matching source and grading-contract hashes, and one revision and command
per target. `comparison_blockers` explains missing or inconsistent evidence.
Protected graders are checked before and after grading. These checks validate
report consistency; revision declarations still need independent verification,
and ordinary subprocess workspaces do not isolate global settings or credentials.

A live Pi comparison is deferred. The included regression fixtures test the
runner and scorecard without paid model requests; they do not establish a
competitive performance advantage.
