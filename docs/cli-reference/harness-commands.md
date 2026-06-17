# Harness Commands

The `superqode harness` command group creates, inspects, runs, and debugs harness specs. A harness spec is a portable YAML file that defines what a coding agent is allowed to do: model policy, tools, permissions, workflow, context, and observability.

New to harnesses? Start with [Bring Your Own Harness](../getting-started/bring-your-own-harness.md) for a guided walkthrough, then use this page as the command reference. The deep-dive on every spec field lives in [Harness System](../advanced/harness-system.md).

```bash
superqode harness COMMAND [OPTIONS]
```

## Command Summary

| Command | Purpose |
| --- | --- |
| `wizard` | Build a spec interactively, no hand-written YAML |
| `init` | Scaffold a spec from a built-in template |
| `list-templates` | List built-in templates |
| `list-backends` | List available runtime backends |
| `explain` | Plain-English summary of what a spec does |
| `compile` | Resolved spec and effective runtime policy (JSON) |
| `diff` | Differences between two specs |
| `validate` | Validate a spec or emit its JSON Schema |
| `inspect` | Spec plus backend capability compatibility |
| `doctor` | Diagnose a spec before running it |
| `test` | Fast smoke test plus failure digest |
| `eval` | Scorecard across tasks and harness variants |
| `auto-bench` | First-run model probe and recommendation wrapper |
| `optimize` | Export and optionally run a meta-harness optimization project |
| `run` | Run a task through a spec |
| `registry` | Local publish/list/install hub for harness specs |
| `import-omnigent` | Convert an Omnigent `agent.yaml` into a spec |
| `runs` | List persisted runs |
| `events` | Normalized events for a run |
| `evidence` | Readable evidence report for a run |
| `graph` | Planned spec graph or persisted run graph |
| `replay` | Replay plan for a run (optionally re-execute) |
| `fork` | Fork a run by copying its event prefix |
| `inbox` | Manage durable session inputs |
| `drain` | Execute pending durable inputs once |
| `worker` | Run a durable inbox worker loop |

---

## Authoring

### `harness wizard`

Build a `harness.yaml` interactively. Asks for a name, a model-family starting point, the provider/model, write/shell/network permissions, approval profile, tool-call format, and an optional multi-agent workflow, then writes the file and explains it in plain English. This is the recommended way to create a harness.

```bash
superqode harness wizard
superqode harness wizard --output team.yaml --force
```

| Option | Description |
| --- | --- |
| `-o, --output PATH` | Spec file to write (default `harness.yaml`) |
| `--force` | Overwrite an existing file |

### `harness init`

Scaffold a spec from a built-in template, optionally applying a workflow preset. Also creates `.agents/skills` and `.agents/roles` directories.

```bash
superqode harness init my-coder --template qwen-coding
superqode harness init team --template coding --preset plan-implement-review
superqode harness init team --template coding --minimal
```

| Option | Description |
| --- | --- |
| `-t, --template` | `coding`, `no-tool`, `qwen-coding`, `glm-coding`, `gemma4-coding`, `gemma4-no-tool`, `ds4-coding`, `ds4-fast-local` (default `coding`) |
| `-o, --output PATH` | Spec file to write (default `harness.yaml`) |
| `--preset` | `single`, `plan-implement-review`, `fix-and-verify`, `parallel-review`, `security-review`, `release-check`, `router`, `evaluator-optimizer` |
| `--minimal` | Write a small spec with `inherits: <template>` instead of a fully expanded template |
| `--force` | Overwrite an existing file |

The `qwen-coding` and `glm-coding` templates reference a model-policy pack, so the matching tuning (temperature, parallel tools, history budget) is applied automatically.

Specs can also compose from templates or relative files:

```yaml
version: 1
name: team-coder
inherits: coding
model_policy:
  primary: ollama/qwen3-coder
```

Mappings are deep-merged, child scalar values override the base, and list fields replace the base list.

### `harness list-templates`

List built-in templates with their flavor, runtime, and description.

```bash
superqode harness list-templates
superqode harness list-templates --json
```

### `harness list-backends`

List the runtime backends a harness can target (`builtin`, ADK, OpenAI Agents, Codex SDK, Claude Agent SDK, DeepAgents, PydanticAI, and others).

```bash
superqode harness list-backends
```

### `harness import-omnigent`

Convert an Omnigent `agent.yaml` into a SuperQode harness spec.

```bash
superqode harness import-omnigent agent.yaml --output harness.yaml
```

| Option | Description |
| --- | --- |
| `-o, --output PATH` | Spec file to write (default `harness.yaml`) |
| `--name TEXT` | Override the generated spec name |
| `--force` | Overwrite an existing file |

---

## Understanding And Verifying

### `harness explain`

Explain in plain English what a harness lets the model do, and why. Reads the same resolved policy the runtime enforces, so the explanation is the truth, not a restatement of the YAML. Covers the model, tools, permissions, workflow, and context.

```bash
superqode harness explain --spec harness.yaml
superqode harness explain --spec harness.yaml --provider ollama --model qwen3-coder
superqode harness explain --spec harness.yaml --json
```

| Option | Description |
| --- | --- |
| `--spec PATH` | Spec file (required) |
| `--provider TEXT` | Provider used to resolve model policy |
| `--model TEXT` | Model used to resolve model policy |
| `--json` | Emit JSON |

### `harness compile`

Print the resolved spec and the effective runtime policy as JSON: model policy (temperature, tool-call format, iterations, parallelism) and the compiled permission config.

```bash
superqode harness compile --spec harness.yaml --provider ollama --model qwen3-coder
```

| Option | Description |
| --- | --- |
| `--spec PATH` | Spec file (required) |
| `--provider TEXT` | Provider used to resolve model policy |
| `--model TEXT` | Model used to resolve model policy |
| `--json` | Emit JSON |

### `harness diff`

Show policy, tool, and agent differences between two specs. Useful to confirm an edit changed exactly what you intended.

```bash
superqode harness diff base.yaml custom.yaml
```

| Option | Description |
| --- | --- |
| `--json` | Emit JSON |

### `harness validate`

Validate a spec file, or emit the HarnessSpec JSON Schema.

```bash
superqode harness validate harness.yaml
superqode harness validate --spec harness.yaml --json
superqode harness validate --schema
```

| Option | Description |
| --- | --- |
| `--spec PATH` | Spec file (also accepts a positional path) |
| `--json` | Emit JSON |
| `--schema` | Emit the HarnessSpec JSON Schema |

### `harness inspect`

Inspect a spec together with backend capability compatibility (does the chosen runtime support the spec's workflow, tools, and sandbox).

```bash
superqode harness inspect --spec harness.yaml --runtime builtin --sandbox local
```

| Option | Description |
| --- | --- |
| `--spec PATH` | Spec file (required) |
| `--runtime TEXT` | Override runtime or backend |
| `--sandbox TEXT` | Override sandbox backend |
| `--json` | Emit JSON |

### `harness doctor`

Diagnose a spec before running it: surfaces misconfigurations, backend mismatches, and store issues.

```bash
superqode harness doctor --spec harness.yaml
```

| Option | Description |
| --- | --- |
| `--spec PATH` | Spec file (required) |
| `--runtime TEXT` | Override runtime or backend |
| `--sandbox TEXT` | Override sandbox backend |
| `--store PATH` | Override harness event store directory |
| `--json` | Emit JSON |

### `harness test`

Run a quick readiness probe. Without `--live`, this validates spec loading, doctor checks, and kernel initialization. With `--live`, it also sends a small prompt to the configured model and returns a compact failure digest.

The failure digest classifies a failure by one of the nine harness dimensions (`dimension: {id, label, field}`, e.g. `D1 model selection -> model_policy`), so it points at the spec field to edit, not just what failed.

```bash
superqode harness test --spec harness.yaml
superqode harness test --spec harness.yaml --live --provider ollama --model qwen3-coder --json
```

| Option | Description |
| --- | --- |
| `--spec PATH` | Spec file (also accepts a positional path) |
| `--provider TEXT` | Provider (default `openai`) |
| `--model TEXT` | Model (default `gpt-4o-mini`) |
| `--runtime TEXT` | Override runtime or backend |
| `--sandbox TEXT` | Override sandbox backend |
| `--prompt TEXT` | Prompt for the live model check |
| `--live` | Call the model endpoint |
| `--json` | Emit JSON |

### `harness eval`

Run a task scorecard against one or more harness specs. Use `--variant` to compare task-specific specs against a baseline while keeping variants isolated.

It also acts as a **seesaw gate**: if any variant regresses a task the baseline solved, `harness eval` exits non-zero (code `2`) so you can block a candidate before applying it. The per-variant `regressions_vs_baseline` and a top-level `regressed` / `regressed_variants` are in the JSON. Pass `--allow-regressions` to override the gate.

```bash
superqode harness eval --spec base.yaml --variant optimized.yaml --tasks tasks.yaml  # exits 2 on regression
superqode harness eval --spec base.yaml --variant optimized.yaml --tasks tasks.yaml --allow-regressions
superqode harness eval --spec base.yaml --tasks tasks.yaml --live --json
```

| Option | Description |
| --- | --- |
| `--spec PATH` | Baseline spec (repeatable; first is the baseline) |
| `--variant PATH` | Candidate spec compared against the baseline (repeatable) |
| `--tasks PATH` | Task file to score against (required) |
| `--provider` / `--model` / `--runtime` / `--sandbox` | Execution overrides |
| `--live` | Execute tasks against the model endpoint |
| `--allow-regressions` | Do not exit non-zero when a variant regresses (override the seesaw gate) |
| `--json` | Emit JSON |

Exit codes: `0` ok, `1` an eval errored, `2` a variant regressed a baseline-solved task.

Task files are YAML:

```yaml
tasks:
  - id: smoke
    prompt: "Reply with hello"
    expect_contains: hello
```

### `harness auto-bench`

Run the quick model-facing wrapper around `harness test` or `harness eval` and print a recommendation.

```bash
superqode harness auto-bench --spec harness.yaml
superqode harness auto-bench --spec harness.yaml --tasks tasks.yaml --live
```

### `harness optimize`

Export a HarnessSpec and eval task file into a `superagentic-metaharness` project, then optionally run a meta-harness backend. This keeps harness optimization optional and auditable: use `--export-only` to inspect the generated project, and use `--apply` only when you want the best candidate copied back.

```bash
superqode harness optimize --spec harness.yaml --tasks tasks.yaml --export-only
superqode harness optimize --spec harness.yaml --tasks tasks.yaml --test-result test.json --eval-result eval.json
superqode harness optimize --spec harness.yaml --tasks tasks.yaml --backend codex --budget 1
superqode harness optimize --spec harness.yaml --tasks tasks.yaml --backend codex --apply --output optimized.yaml
superqode harness optimize-inspect mh-project/runs/superqode-optimize
superqode harness optimize-ledger mh-project/runs/superqode-optimize
```

| Option | Description |
| --- | --- |
| `--spec PATH` | Harness spec to optimize |
| `--tasks PATH` | Eval task file used as the optimization contract |
| `--project-dir PATH` | Meta-harness project directory to create |
| `--backend TEXT` | Meta-harness backend, for example `fake`, `codex`, `gemini`, or `omnigent` |
| `--budget INTEGER` | Proposal budget |
| `--export-only` | Create the project without running meta-harness |
| `--apply` | Copy the best candidate `harness.yaml` back after a successful run |
| `--output PATH` | Output path for `--apply` |
| `--trace-evidence PATH` | Additional trace evidence to inject into meta-harness |
| `--test-result PATH` | Previous `harness test --json` output to include as trace evidence. Can be repeated |
| `--eval-result PATH` | Previous `harness eval --json` output to include as trace evidence. Can be repeated |
| `--metaharness-bin TEXT` | Meta-harness executable name or path |
| `--json` | Emit JSON |

When `--trace-evidence` is omitted, SuperQode writes `trace-evidence.md` from the current spec and eval task file. The generated evidence includes the harness runtime, workflow, model policy, permission posture, and task prompts so the optimizer has a useful starting snapshot. Add `--test-result` or `--eval-result` to include previous scorecards and failure digests from prior runs.

Use `harness optimize-inspect RUN_DIR` to summarize a completed meta-harness run. Use `harness optimize-ledger RUN_DIR` to list candidates, objective values, validation state, outcomes, and changed files. Both commands support `--json`. The TUI harness sidebar also shows the latest local meta-harness run under `.superqode/metaharness` or `mh-project` when artifacts are present.

---

## Running

### `harness run`

Run a task through a spec. Single-prompt specs execute one turn through the kernel; non-single workflow specs execute their topology (chain, parallel, router, orchestrator, evaluator-optimizer). Use `--single-step` to force one prompt regardless of topology.

```bash
superqode harness run --spec harness.yaml \
  --provider ollama --model qwen3-coder \
  -p "Read README.md and summarize this project."
```

| Option | Description |
| --- | --- |
| `--spec PATH` | Spec file (required) |
| `-p, --prompt TEXT` | Prompt to run (required) |
| `--provider TEXT` | Provider (default `openai`) |
| `--model TEXT` | Model (default `gpt-4o-mini`) |
| `--runtime TEXT` | Override runtime or backend |
| `--session TEXT` | Reuse a harness session id |
| `--store [memory\|file\|sqlite]` | Override `observability.run_store` |
| `--working-dir DIRECTORY` | Working directory for the run |
| `--sandbox TEXT` | Sandbox backend (default `local`) |
| `--stream` | Print normalized stream events |
| `--single-step` | Force one prompt, ignoring workflow topology |
| `--json` | Emit JSON |

---

## Run History And Debugging

These commands read the harness event store (default `.superqode/sessions`).

### `harness runs`

List persisted runs, optionally filtered by session.

```bash
superqode harness runs
superqode harness runs --session <session-id>
```

| Option | Description |
| --- | --- |
| `--store PATH` | Store directory (default `.superqode/sessions`) |
| `--session TEXT` | Filter by session id |
| `--json` | Emit JSON |

### `harness events`

Show normalized events for a run: model calls, tool calls, approvals, and results.

```bash
superqode harness events <run-id>
superqode harness events <run-id> --after 10
```

| Option | Description |
| --- | --- |
| `--store PATH` | Store directory (default `.superqode/sessions`) |
| `--after INTEGER` | First event index (default `0`) |
| `--json` | Emit JSON |

### `harness evidence`

Show a readable evidence report for a run (what the agent did and the resulting workspace changes).

```bash
superqode harness evidence <run-id>
```

| Option | Description |
| --- | --- |
| `--store PATH` | Store directory (default `.superqode/sessions`) |
| `--json` | Emit JSON |

### `harness graph`

Show the planned graph for a spec, or the persisted event graph for a run.

```bash
superqode harness graph --spec harness.yaml
superqode harness graph <run-id>
```

| Option | Description |
| --- | --- |
| `--spec PATH` | Spec file (for a planned graph) |
| `--store PATH` | Store directory (default `.superqode/sessions`) |
| `--json` | Emit JSON |

### `harness replay`

Show a replay plan for a persisted run, or re-execute it with `--execute`.

```bash
superqode harness replay <run-id>
superqode harness replay <run-id> --execute --provider ollama --model qwen3-coder
```

| Option | Description |
| --- | --- |
| `--execute` | Re-run the prompt instead of only showing the plan |
| `--spec PATH` | Spec override |
| `--prompt TEXT` | Exact prompt to replay if the run did not store one |
| `--provider TEXT` | Provider override for `--execute` |
| `--model TEXT` | Model override for `--execute` |
| `--runtime TEXT` | Runtime override for `--execute` |
| `--sandbox TEXT` | Sandbox backend (default `local`) |
| `--working-dir DIRECTORY` | Working directory |
| `--store PATH` | Store directory (default `.superqode/sessions`) |
| `--json` | Emit JSON |

### `harness fork`

Fork a persisted run by copying its event prefix up to a chosen index, so you can branch a new run from an earlier point.

```bash
superqode harness fork <run-id> --after 8 --session new-branch
```

| Option | Description |
| --- | --- |
| `--store PATH` | Store directory (default `.superqode/sessions`) |
| `--after INTEGER` | Copy events through this event index |
| `--session TEXT` | Session id for the forked run |
| `--json` | Emit JSON |

---

## Durable Inputs (Long-Running Sessions)

For always-on or queued workloads, a harness session has a durable inbox. Inputs are admitted, then drained by a one-shot drain or a long-running worker.

### `harness inbox`

Manage durable session inputs.

```bash
superqode harness inbox add --session <id> --prompt "Refactor the auth module"
superqode harness inbox list --session <id> --status pending
superqode harness inbox recover --session <id> --stale-after 300
```

| Subcommand | Purpose |
| --- | --- |
| `add` | Admit a prompt to a session inbox (`--delivery queue\|steer\|admit-only`, `--id` for exact retry) |
| `list` | List inputs, optionally filtered by `--status pending\|running\|done\|failed` |
| `recover` | Return stale `running` inputs to `pending` |

### `harness drain`

Execute pending durable inputs for one session, then exit. Drains `--limit` inputs (default 1).

```bash
superqode harness drain --spec harness.yaml --session <id> \
  --provider ollama --model qwen3-coder
```

| Option | Description |
| --- | --- |
| `--spec PATH` | Spec file (required) |
| `--session TEXT` | Session id to drain (required) |
| `--provider TEXT` | Provider (default `openai`) |
| `--model TEXT` | Model (default `gpt-4o-mini`) |
| `--runtime TEXT` | Override runtime or backend |
| `--working-dir DIRECTORY` | Working directory |
| `--sandbox TEXT` | Sandbox backend (default `local`) |
| `--store PATH` | Store directory (default `.superqode/sessions`) |
| `--limit INTEGER` | Maximum inputs to drain (default `1`) |
| `--owner-id TEXT` | Drain worker owner id |
| `--lease-seconds INTEGER` | Claim lease duration (default `300`) |
| `--json` | Emit JSON |

### `harness worker`

Run a durable inbox worker loop that claims and drains inputs until stopped (or until `--once` / `--max-runs`).

```bash
superqode harness worker --spec harness.yaml --session <id> \
  --provider ollama --model qwen3-coder --concurrency 2
```

| Option | Description |
| --- | --- |
| `--spec PATH` | Spec file (required) |
| `--session TEXT` | Session id to drain (required) |
| `--provider TEXT` | Provider (default `openai`) |
| `--model TEXT` | Model (default `gpt-4o-mini`) |
| `--runtime TEXT` | Override runtime or backend |
| `--working-dir DIRECTORY` | Working directory |
| `--sandbox TEXT` | Sandbox backend (default `local`) |
| `--store PATH` | Store directory (default `.superqode/sessions`) |
| `--owner-id TEXT` | Worker owner id |
| `--lease-seconds INTEGER` | Claim lease duration (default `300`) |
| `--concurrency INTEGER` | Concurrent worker loops (default `1`) |
| `--poll-seconds FLOAT` | Idle poll delay (default `2.0`) |
| `--max-runs INTEGER` | Stop after this many claimed inputs |
| `--once` | Exit when no pending input is available |
| `--recover-stale / --no-recover-stale` | Recover stale running inputs on startup (default on) |
| `--stale-after INTEGER` | Recover running inputs older than this many seconds (default `300`) |
| `--json` | Emit JSON when the worker exits |

---

## Sharing

### `harness registry`

Use the local registry as a low-risk share hub before moving to a remote marketplace. Publishing validates and copies a spec into `~/.superqode/harness-registry`; installing copies it back into a project.

```bash
superqode harness registry publish harness.yaml
superqode harness registry list
superqode harness registry install team-coder --output harness.yaml
```

| Subcommand | Purpose |
| --- | --- |
| `publish` | Validate and copy a spec into the local registry |
| `list` | Show local registry entries |
| `install` | Copy an entry from the registry into the current project |

---

## Related

- [Bring Your Own Harness](../getting-started/bring-your-own-harness.md): guided walkthrough.
- [Harness System](../advanced/harness-system.md): full spec-field reference.
- [Configuration vs Harness](../concepts/configuration-vs-harness.md): how `harness.yaml` differs from `superqode.yaml`.
- [Runtime Backends](../runtimes.md): the engines a harness can run on.
