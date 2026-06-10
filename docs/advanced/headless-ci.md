# Headless & CI

Everything for running SuperQode without the TUI: scripts, pipelines, cron jobs, and machine-readable output. Each section is a recipe. Copy it, run it, adapt it.

## One-shot runs

```bash
superqode -p "inspect this repository and suggest the smallest next step"
superqode -p --provider ollama --model gemma4 "fix the failing test"
echo "review this diff" | git diff | superqode -p        # stdin joins the prompt
```

Exit code `0` means the run completed and `1` means it errored or stopped early, so CI steps can gate on it.

## Machine-readable events

```bash
superqode -p --mode json "summarize the architecture" | jq .
```

Emits a stable `superqode.result` JSON document: `content`, `tool_calls_made`, `iterations`, `stopped_reason`, `success`, plus a `changes` summary of files the run touched (`--changes diff` includes the diff itself).

## Schema-validated output (`--output-schema`)

When a pipeline consumes the answer, prose is a liability. Pin the output to a JSON Schema:

```bash
cat > review-schema.json <<'EOF'
{
  "type": "object",
  "required": ["verdict", "issues"],
  "properties": {
    "verdict": {"type": "string", "enum": ["approve", "request_changes"]},
    "issues": {"type": "array", "items": {"type": "string"}}
  }
}
EOF

superqode -p --output-schema review-schema.json "review the uncommitted changes"
```

What happens: the schema is embedded in the prompt; the final message is parsed leniently (fences and surrounding prose tolerated) and validated; **one corrective retry** runs automatically on failure. On success, stdout is exactly the validated JSON document. On failure after the retry, the errors print to stderr and the exit code is `2`, which is distinguishable from a run failure (`1`).

With `--mode json`, the result document gains `structured_output`, `schema_errors`, and `schema_valid` fields instead.

## Quality gates (`--rubric`)

```bash
superqode -p --rubric @done-criteria.txt "migrate the config parser to tomllib"
```

A separate grader call judges the final answer against the rubric; "needs revision" feedback re-enters the loop (twice at most) before the run is allowed to finish. Inline text works too: `--rubric "tests pass; no new deps"`. Combine with `--output-schema`: the rubric shapes the work, the schema shapes the report.

## Sessions: resume, fork, export

```bash
superqode sessions list
superqode -p --resume 4f2a "continue where we left off"
superqode -p --fork 4f2a "try the other approach instead"

superqode sessions export 4f2a --format markdown        # readable transcript
superqode sessions export 4f2a --format json            # full message data
superqode sessions export 4f2a --format html -o run.html  # one shareable file
```

The HTML export is a self-contained dark-mode page with no external assets. Attach it to a PR or paste it into a ticket.

## Isolation for risky runs

```bash
superqode -p --sandbox git-worktree "upgrade all dependencies and fix breakage"
```

The run executes in a disposable git worktree; your checkout is untouched and the worktree is cleaned up afterward. Combine with an [exec policy](policies.md) for belt-and-braces CI safety.

## Recipe: a nightly autonomous fix bot

```bash
#!/usr/bin/env bash
set -euo pipefail
export SUPERQODE_DEFERRED_TOOLS=auto          # small prompt for the local model
export SUPERQODE_SHELL_ENV_POLICY=filter-secrets

superqode -p --mode json \
  --provider ollama --model gemma4 \
  --sandbox git-worktree \
  --rubric "the full test suite passes; the diff is minimal" \
  --output-schema fix-report.schema.json \
  "find one flaky or failing test and fix it properly" > report.json

jq -e '.schema_valid and .success' report.json
```

## Harness runs in CI

Prefer a pinned, reviewable contract? Use a harness spec instead of flags. Same engine, declarative configuration, richer event log:

```bash
superqode harness run --spec harness.yaml --prompt "make the smallest safe fix"
superqode harness events <run-id>
```

See [Harness System](harness-system.md).
