# Benchmark Commands

Run coding harness benchmarks across multiple agent targets.

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

The tasks file is a JSON array of task definitions:

```json
[
  {
    "id": "task-001",
    "prompt": "Implement a fibonacci function in Python"
  },
  {
    "id": "task-002",
    "prompt": "Write a markdown parser in TypeScript"
  }
]
```

Each task contains a unique `id` and a `prompt` sent to each target. Results are compared across targets by task ID, producing a side-by-side report of completion rates, time, and output quality.

### Supported Targets

| Target | Description |
|--------|-------------|
| `superqode` | SuperQode harness |
| `opencode` | OpenCode ACP agent |
| `pi` | pi.ai coding agent |
| `deepagents` | DeepAgents harness |
