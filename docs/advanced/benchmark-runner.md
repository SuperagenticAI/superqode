# Benchmark Runner

## Overview

The benchmark harness compares coding agent performance across multiple targets (superqode, opencode, pi, deepagents) on the same task prompts. Each task in a tasks file is run against every selected target, and results are collected into a JSON report for analysis. The harness does not evaluate output correctness; it delegates pass/fail determination to each target CLI's exit code.

## Task File Format

Tasks are defined in a JSON file with a `tasks` array:

```json
{
  "tasks": [
    {
      "id": "task-001",
      "prompt": "Implement a fibonacci function in Python",
      "cwd": "/tmp/workspace",
      "timeout_seconds": 300
    }
  ]
}
```

Field descriptions:

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `id` | yes | | Unique task identifier |
| `prompt` | yes | | Prompt text, passed as the last argument to the target CLI |
| `cwd` | no | `.` | Working directory for the task |
| `timeout_seconds` | no | `300` | Per task timeout in seconds |

## CLI Usage

```bash
superqode benchmark run tasks.json
superqode benchmark run tasks.json --target superqode --target opencode
```

The `--target` flag is repeatable. When omitted, all built-in targets are used.

## Targets

Four built-in targets are available:

| Target | CLI Command |
|--------|-------------|
| superqode | `superqode -p` |
| opencode | `opencode run` |
| pi | `pi -p` |
| deepagents | `deepagents` |

If a target's binary is not found on `PATH`, that target is reported as "skipped" in the results. Only targets present on `PATH` are executed.

## Result Format

Results are output as a JSON array. Each entry contains:

| Field | Type | Description |
|-------|------|-------------|
| `target` | string | Name of the target that ran |
| `task_id` | string | ID of the task that was run |
| `status` | string | One of: `passed`, `failed`, `skipped`, `timeout` |
| `returncode` | int | Exit code of the target CLI (absent on skip/timeout) |
| `duration_seconds` | float | Wall clock time in seconds (absent on skip) |
| `stdout_chars` | int | Character count of stdout (absent on skip/timeout) |
| `stderr_chars` | int | Character count of stderr (absent on skip/timeout) |

Pass/fail status is determined solely by the target CLI's exit code: exit code 0 produces `passed`, any non-zero exit produces `failed`. The benchmark harness does not inspect output for correctness.

## Writing Custom Tasks

Create a JSON file with a `tasks` array. Each task object must contain at least `id` and `prompt`. The prompt is appended as the last argument to the target's CLI command. The target is expected to solve the prompt and exit 0 on success. Use `cwd` to control where the target process runs and `timeout_seconds` to prevent runaway agents.
