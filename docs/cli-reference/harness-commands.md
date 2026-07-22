# Harness Commands

The `superqode harness` command group creates, inspects, runs, and debugs harness specs. A harness spec is a portable YAML file that defines what a coding agent is allowed to do: model policy, tools, permissions, workflow, context, and observability.

Harness specs are separate from `superqode.yaml`. `superqode.yaml` configures the project environment. A harness file such as `harness.yaml` or `superqode.local.yaml` configures one repeatable agent run. You can keep many harness files in a repository and load the one you want with `--harness` or `:harness`.

New to harnesses? Start with [Bring Your Own Harness](../getting-started/bring-your-own-harness.md) for a guided walkthrough, then use this page as the command reference. The deep-dive on every spec field lives in [Harness System](../advanced/harness-system.md).

```bash
superqode harness COMMAND [OPTIONS]
```

## Command Summary

| Command | Purpose |
| --- | --- |
| `list` | List selectable built-in and discovered harnesses |
| `show` | Show the resolved tools and policy for a selectable harness |
| `use` | Persist a project default harness in `superqode.yaml` |
| `customize` (TUI) | Copy a catalog preset to editable project YAML |
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
| `eval-packs` | List bundled eval task packs |
| `auto-bench` | First-run model probe and recommendation wrapper |
| `mine-failures` | Mine structured self-improvement failures from test/eval JSON |
| `logbook` | Manage the file-backed self-improvement logbook |
| `audit-candidate` | Audit a proposed harness before accepting it |
| `candidates` | Inspect accepted/rejected self-improvement attempts |
| `improve` | Export and optionally run a failure-guided harness improvement project |
| `optimize` | Export and optionally run a meta-harness optimization project |
| `run` | Run a task through a spec |
| `registry` | Local publish/list/install hub for harness specs |
| `import-agent` | Compile concise SuperQode `agent.yaml` into a spec |
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

## Selecting a Harness

The default `core` harness keeps model context small with a compact prompt and four
tools: `read`, `write`, `edit`, and `bash`. Select `workbench` when a task benefits
from the broader native search, patch, web, planning, and coordination toolset.

```bash
superqode harness list
superqode harness list --recommended
superqode harness current
superqode harness show core
superqode --harness workbench --print "fix the failing test"
superqode --harness kimi-coding --print "fix the failing test"
superqode harness use workbench
```

`harness use` stores the choice under `superqode.harness` in `superqode.yaml`.
An explicit `--harness` name or HarnessSpec path takes precedence. In the TUI, the
equivalent commands are `:harness list` and `:harness use <name-or-path>`.
Entering `:harness` or `:harness switch` without a harness name opens the
interactive Harness Switcher. It shows stable workflows, maintained
provider/model families, and project or user harnesses. Use the arrow keys and
Enter to continue the current session, `F` to fork before switching, `I` to
inspect the selected harness, `A` to show the complete catalog, and Escape to
cancel. `:harness all` opens the complete picker directly. The CLI keeps
`superqode harness list` complete for scripting compatibility; add
`--recommended` to match the default TUI view.

The list reports each harness runtime, readiness state, and continuity level.
`superqode harness current` resolves the project default. During an interactive
TUI session, `:harness switch <name>` changes the harness while retaining the
session ID and normalized conversation history. Add `--fork` to the switch
command when the selected harness should receive an independent branch.

For non-interactive work, combine the top-level session and harness options:

```bash
superqode --print --resume SESSION_ID --harness workbench "continue the task"
superqode --print --fork SESSION_ID --harness kimi-coding "try another approach"
```

Built-in templates also appear in the selectable catalog and can be activated
directly. `list-templates` remains available for authoring and compatibility.
Maintained family presets such as `kimi-coding` track the validated stable model;
versioned presets such as `kimi-k3-coding` stay pinned for reproducibility. In the
TUI, `:harness customize kimi-coding` creates an editable project copy under
`.superqode/harnesses/`.

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
| `-t, --template` | `coding`, `no-tool`, `kimi-coding`, `kimi-k3-coding`, `qwen-coding`, `glm-coding`, `glm52-coding`, `gemma4-coding`, `gemma4-no-tool`, `ds4-coding`, `ds4-fast-local` (default `coding`) |
| `-o, --output PATH` | Spec file to write (default `harness.yaml`) |
| `--preset` | `single`, `plan-implement-review`, `fix-and-verify`, `parallel-review`, `security-review`, `release-check`, `router`, `evaluator-optimizer` |
| `--minimal` | Write a small spec with `inherits: <template>` instead of a fully expanded template |
| `--force` | Overwrite an existing file |

The `qwen-coding`, `glm-coding`, and `glm52-coding` templates reference a model-policy pack, so the matching tuning (temperature, parallel tools, history budget) is applied automatically. `glm52-coding` routes through the first-party Z.AI general API.

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

### `harness import-agent`

Compile a concise SuperQode `agent.yaml` into a full `HarnessSpec`. The authoring
shape intentionally supports the useful Omnigent-style fields SuperQode is
adopting: `executor`, `tools`, `skills`, `os_env`, `policies`, and agent-valued
tools.

```bash
superqode harness import-agent agent.yaml --output harness.yaml
```

Example:

```yaml
name: coding_supervisor
prompt: Coordinate coding work through named tools and subagents.
executor:
  harness: codex
  model: databricks-gpt-5-5
skills:
  - code-review
tools:
  github:
    type: mcp
    command: uvx
    args: [github-mcp-server]
  reviewer:
    type: agent
    prompt: Review proposed changes for correctness and tests.
    executor:
      harness: claude-sdk
      model: claude-sonnet
```

MCP tool declarations are compiled into `runtime.config.mcp_servers`. Harness
runtimes that support SuperQode's MCP bridge connect those servers for the run
and expose discovered tools as `mcp_<server>_<tool>` tool calls.

Agent tool declarations are compiled into child `AgentSpec`s. This is the
SuperQode runtime surface for Omnigent-style `tools.<name>.type: agent` entries.
In the builtin harness runtime, the parent gets the `agent_session` tool for
persistent child sessions:

```text
agent_session(action="start", agent="reviewer", message="Review this diff", session_id="reviewer-main")
agent_session(action="resume", agent="reviewer", session_id="reviewer-main")
agent_session(action="send", agent="reviewer-main", message="Now check tests")
agent_session(action="wait", agent="reviewer-main")
agent_session(action="approve", agent="reviewer")
agent_session(action="reject", agent="reviewer", message="Use a safer command")
agent_session(action="close", agent="reviewer")
```

The `session_id` is optional on `start`; when supplied, another parent run can
reattach to the child context later with `resume`.

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

When a runtime exposes provider usage, eval JSON includes per-task and per-variant `usage` with `tokens_in`,
`tokens_out`, `total_tokens`, `cost_usd`, plus `tokens_per_success`, `cost_per_success`, and
`latency_ms_per_success`. Unknown provider usage remains `null` rather than estimated.

```bash
superqode harness eval --spec base.yaml --variant optimized.yaml --tasks tasks.yaml  # exits 2 on regression
superqode harness eval --spec base.yaml --variant optimized.yaml --tasks tasks.yaml --allow-regressions
superqode harness eval --spec base.yaml --tasks tasks.yaml --live --json
superqode harness eval --spec base.yaml --variant candidate.yaml --tasks tasks.yaml --split held-out
```

| Option | Description |
| --- | --- |
| `--spec PATH` | Baseline spec (repeatable; first is the baseline) |
| `--variant PATH` | Candidate spec compared against the baseline (repeatable) |
| `--tasks PATH` | Task file to score against (required) |
| `--provider` / `--model` / `--runtime` / `--sandbox` | Execution overrides |
| `--split {all,held-in,held-out}` | Run all tasks or only one eval split |
| `--live` | Execute tasks against the model endpoint |
| `--allow-regressions` | Do not exit non-zero when a variant regresses (override the seesaw gate) |
| `--json` | Emit JSON |

Exit codes: `0` ok, `1` an eval errored, `2` a variant regressed a baseline-solved task.

Task files are YAML:

```yaml
tasks:
  - id: smoke
    split: held-in
    prompt: "Reply with hello"
    expect_contains: hello
  - id: heldout-smoke
    split: held-out
    prompt: "Reply with ready"
    expect_contains: ready
```

Use `held-in` for tasks the optimizer may see while proposing changes, and `held-out` for the final candidate
gate. Tasks without `split` default to `held-in`.

### `harness eval-packs`

List bundled eval packs, or print the path to one pack:

```bash
superqode harness eval-packs
superqode harness eval-packs local-recursive-smoke
superqode harness eval --spec harness.yaml --tasks "$(superqode harness eval-packs local-recursive-smoke)" --live
```

### `harness bench` and `harness bench-verify`

Run a publishable same-model comparison from a HarnessBench manifest. The output preserves every raw repetition, aggregate quality/cost/latency variance, Pareto membership, source fingerprints, and artifact checksums.

```bash
superqode harness bench --manifest harnessbench.yaml --output results/july
superqode harness bench-verify results/july
```

The manifest fixes the task file, at least two HarnessSpecs, provider, model, runtime, sandbox, split, and repetition count. `--live` or `--dry-run` can override its execution setting. Dry runs validate packaging but are not valid promotion evidence. See [HarnessBench](../advanced/harnessbench.md).

### `harness auto-bench`

Run the quick model-facing wrapper around `harness test` or `harness eval` and print a recommendation.

```bash
superqode harness auto-bench --spec harness.yaml
superqode harness auto-bench --spec harness.yaml --tasks tasks.yaml --live
```

### `harness mine-failures`

Mine structured failure records from existing `harness test --json` or `harness eval --json` output. This does
not change the harness; it creates evidence that can feed the logbook and `harness improve`.

```bash
superqode harness eval --spec harness.yaml --tasks tasks.yaml --live --json > eval.json
superqode harness mine-failures --eval-result eval.json --output .superqode/self-improve/failures.json
superqode harness mine-failures --harbor-run harbor-results/ --output .superqode/self-improve/failures.json
```

| Option | Description |
| --- | --- |
| `--test-result PATH` | Previous `harness test --json` output. Can be repeated |
| `--eval-result PATH` | Previous `harness eval --json` output. Can be repeated |
| `--harbor-run PATH` | Harbor/Terminal-Bench style JSON, JSONL, or result directory. Can be repeated |
| `--output PATH` | JSON failure report to write |
| `--json` | Emit JSON |

### `harness logbook`

Maintain a repo-local, file-backed self-improvement logbook. The first MVP logbook stores recurring failure
patterns under `.superqode/self-improve/logbook/failure_patterns.yaml`.

```bash
superqode harness logbook update --from-failures .superqode/self-improve/failures.json
superqode harness logbook show
superqode harness logbook export --output .superqode/self-improve/logbook.md
superqode harness logbook prune --min-count 2 --max-patterns 50
```

Logbook entries track `count`, `confidence`, `status`, first/last seen timestamps, source references, and
negative-result slots. `prune` removes low-signal or stale memory while keeping active/pinned entries.

### `harness audit-candidate`

Audit a proposed harness before accepting or applying it. The audit compares the base and candidate specs,
checks editable/protected surfaces, detects permission widening and weakened checks, verifies held-out eval
gates, and compares the proposal against the native candidate ledger.

```bash
superqode harness eval \
  --spec harness.yaml \
  --variant candidate.yaml \
  --tasks tasks.yaml \
  --split held-out \
  --live \
  --json > heldout.json

superqode harness audit-candidate \
  --base harness.yaml \
  --candidate candidate.yaml \
  --tasks tasks.yaml \
  --eval-result heldout.json \
  --require-heldout \
  --record
```

| Option | Description |
| --- | --- |
| `--base PATH` | Baseline HarnessSpec |
| `--candidate PATH` | Candidate HarnessSpec |
| `--tasks PATH` | Eval task file used to detect held-out requirements |
| `--eval-result PATH` | Candidate eval JSON. Can be repeated |
| `--surfaces TEXT` | Comma-separated editable surfaces |
| `--protected-surfaces TEXT` | Comma-separated protected surfaces |
| `--max-candidate-edits N` | Maximum changed spec fields |
| `--require-heldout` | Require a passing held-out gate |
| `--allow-protected-changes` | Do not reject solely for protected-surface edits |
| `--allow-ungated` | Do not reject solely for missing eval gates |
| `--record` | Append the accepted/rejected decision to `.superqode/self-improve/candidates.jsonl` |
| `--json` | Emit JSON |

### `harness candidates`

Inspect the native JSONL ledger of accepted and rejected self-improvement attempts. This is the durable
negative-result memory used to avoid repeating failed edits.

```bash
superqode harness candidates list
superqode harness candidates show cand_1234abcd5678
superqode harness candidates export --output .superqode/self-improve/candidates.md
```

### `harness improve`

Create a self-improvement meta-harness project from the current spec, eval tasks, mined failures, and logbook
memory. It uses the same optional meta-harness backend as `harness optimize`, but appends self-improvement
guidance to `trace-evidence.md` and records editable/protected harness surfaces.

If the task file has `split: held-out` tasks, `harness improve` includes held-out gating guidance and the
exported meta-harness project includes dry split checks. When `--apply` is used, SuperQode audits the best
candidate first and records the accepted/rejected decision in the candidate ledger.

You can version default improvement boundaries in the harness itself:

```yaml
optimization:
  enabled: true
  require_human_apply: true
  editable_surfaces: [context, workflow, model_policy, agents.tools]
  protected_surfaces: [execution_policy, checks, approvals, sandbox]
  heldout_fraction: 0.3
  max_candidate_edits: 3
```

`--surfaces` and `--protected-surfaces` override the spec for one run.

```bash
superqode harness improve \
  --spec harness.yaml \
  --tasks tasks.yaml \
  --from-failures .superqode/self-improve/failures.json \
  --export-only

superqode harness improve \
  --spec harness.yaml \
  --tasks tasks.yaml \
  --from-failures .superqode/self-improve/failures.json \
  --backend codex \
  --budget 1
```

| Option | Description |
| --- | --- |
| `--from-failures PATH` | Failure report from `harness mine-failures`. Can be repeated |
| `--logbook-dir PATH` | Self-improvement logbook directory |
| `--candidate-ledger PATH` | JSONL ledger for accepted/rejected candidates |
| `--surfaces TEXT` | Comma-separated surfaces the optimizer may edit |
| `--protected-surfaces TEXT` | Comma-separated surfaces requiring explicit review |
| `--export-only` | Create the project without running meta-harness |
| `--apply` | Audit and copy the best candidate `harness.yaml` back after a successful run |
| `--allow-protected-changes` | Allow audited protected-surface edits during `--apply` |
| `--allow-ungated-apply` | Allow `--apply` without a passing held-out gate |
| `--json` | Emit JSON |

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

### `harness promote`

Deliver an audited candidate through staging, deterministic WorkOrder canary routing, live held-out evidence, activation, and guarded rollback:

```bash
superqode harness promote stage \
  --base harness.yaml --candidate candidate.yaml \
  --tasks eval-tasks.yaml --eval-result heldout-eval.json \
  --actor maintainer

superqode harness promote canary cand_... --percent 10 --actor maintainer
superqode harness promote status cand_... --json
superqode harness promote select harness.yaml --key work_... --json
superqode harness promote activate cand_... \
  --evidence results/canary/scorecard.json --actor maintainer
superqode harness promote rollback cand_... \
  --actor maintainer --reason "cost regression"
```

Activation requires a passing live `held-out` HarnessBench scorecard whose base and candidate digests match the staged files. It rejects regression runs and candidates below the baseline mean. See [Harness Promotion](../advanced/harness-promotion.md).

---

## Running

### `harness run`

Run a task through a spec or an installed Python harness. Single-prompt specs
execute one turn through the kernel; non-single workflow specs execute their
topology. Installed harnesses are addressed by name.

```bash
superqode harness run --spec harness.yaml \
  --provider ollama --model qwen3-coder \
  -p "Read README.md and summarize this project."

superqode harness run my-harness "Read README.md and summarize this project."
```

| Option | Description |
| --- | --- |
| `HARNESS [TASK]` | Installed harness name or spec path and task |
| `--spec PATH` | Spec file; alternative to the positional harness |
| `-p, --prompt TEXT` | Prompt; alternative to the positional task |
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

For recursive and dynamic workflow runs, the report includes child run lineage
and any `dynamic_workflow` / `dynamic_workflow_script` plan tree recovered from
tool result metadata.

| Option | Description |
| --- | --- |
| `--store PATH` | Store directory (default `.superqode/sessions`) |
| `--json` | Emit JSON |

### `harness observability status`

Show local and optional external observability sink status.

```bash
superqode harness observability status
superqode harness observability status --spec harness.yaml --json
```

The command reports local JSONL export availability, OTEL-shaped export
availability, and optional live sinks such as MLflow, LangSmith, Logfire, and
Arize/Phoenix. Install the optional SDK set for these integrations:

```bash
uv sync --extra observability
```

Missing optional packages or credentials are reported, not treated as run
failures.

### `harness observability export`

Export a persisted run tree to local observability artifacts and any configured
optional sink.

```bash
superqode harness observability export <run-id>
superqode harness observability export <run-id> --spec harness.yaml --output .superqode/obs/<run-id>
```

The export includes:

- `trace.json`: complete normalized run tree
- `runs.jsonl`: one row per root/child run
- `events.jsonl`: normalized harness events
- `otel_spans.jsonl`: OTEL-shaped spans for trace backends
- `overview.md`: human-readable summary

MLflow, when enabled and installed, logs the export directory as artifacts.
LangSmith creates a run tree, Logfire mirrors the run as spans and log events,
and Arize/Phoenix uses the OTEL collector endpoint path.

| Option | Description |
| --- | --- |
| `--spec PATH` | Spec used to resolve observability exporters |
| `--store PATH` | Store directory (default `.superqode/sessions`) |
| `--output PATH` | Output directory |
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

For dynamic runs, replay output shows the compiled script/plan, step ids,
fan-out markers, and child run ids alongside the normal lineage tree.

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

## Harness Protocol

### `harness protocol`

Inspect Harness Protocol v1 and validate its deterministic reference adapter.

```bash
superqode harness protocol list
superqode harness protocol describe
superqode harness protocol describe acp --json
superqode harness protocol conformance
superqode harness protocol conformance my-harness
```

| Subcommand | Purpose |
| --- | --- |
| `list` | List built-in and installed Python harness adapters |
| `describe [core\|python\|acp]` | Show the protocol event vocabulary and declared reference-adapter capabilities |
| `conformance [harness-id]` | Run lifecycle, envelope, ledger, export, resume, and checkpoint checks |

Installed package harnesses can use the normal run command:

```bash
superqode harness run my-harness "review this diff"
```

With no harness ID, conformance uses a deterministic offline reference. With an
ID, it executes that installed harness. Live model or ACP adapters may require
provider credentials or a running agent. See
[Harness Protocol v1](../advanced/harness-protocol.md).

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
