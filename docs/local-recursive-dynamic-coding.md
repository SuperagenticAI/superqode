# Local Recursive Dynamic Coding

This demo path proves SuperQode's local agentic stack end to end:

- local model
- local Docker sandbox
- large artifact kept outside the prompt with `context_handle`
- recursive child runs through `spawn_harness`
- bounded dynamic orchestration through `dynamic_workflow_script`
- replayable lineage and evidence on disk

Use it for long CI logs, dense diffs, traces, and repo-slice audits where a
small local model should inspect evidence in chunks instead of stuffing the
whole artifact into its context window.

## Harness

Start from the bundled harness:

```bash
examples/harnesses/local-recursive-dynamic.yaml
```

It enables:

- `context_handle`
- `spawn_harness`
- `dynamic_workflow`
- `dynamic_workflow_script`
- conservative recursion caps: depth 1, eight children, parallelism 2,
  eight spawn units, and a 600 second wall-clock cap
- Docker sandboxing
- file-backed observability

The harness is read-only by default. That is intentional: prove recursive
analysis first, then enable write tools only for specific coding tasks.
Harness-backed recursion is also gated by `recursion.enabled`; child runs fail
closed if a spec has not explicitly opted in.

## Eval Pack

List bundled packs:

```bash
superqode harness eval-packs
```

Resolve the dynamic workflow smoke pack:

```bash
superqode harness eval-packs local-dynamic-workflow-smoke
```

The pack asks the agent to use `dynamic_workflow_script` over a bundled CI log
fixture and return the planted root cause:

```text
ROOT_CAUSE: migration 20260619_add_payment_id missed unique index on payments.payment_id
```

## Run Locally

With Ollama and Docker available:

```bash
superqode harness eval \
  --spec examples/harnesses/local-recursive-dynamic.yaml \
  --tasks "$(superqode harness eval-packs local-dynamic-workflow-smoke)" \
  --provider ollama \
  --model qwen3:8b \
  --runtime builtin \
  --sandbox docker \
  --live
```

This is the live proof command for the local RLM integration. It requires an
Ollama-compatible local model named `qwen3:8b` and Docker. If either dependency
is missing, the command should fail before any remote service is contacted.

Use JSON when you want score output for automation:

```bash
superqode harness eval \
  --spec examples/harnesses/local-recursive-dynamic.yaml \
  --tasks "$(superqode harness eval-packs local-dynamic-workflow-smoke)" \
  --provider ollama \
  --model qwen3:8b \
  --runtime builtin \
  --sandbox docker \
  --live \
  --json
```

`harness eval --live` is the scoring path. It may use an in-memory run store, so
the returned task `run_id` is not guaranteed to be replayable after the eval
process exits.

For a replayable proof, run the same task through the file-backed harness store:

```bash
superqode harness run \
  --spec examples/harnesses/local-recursive-dynamic.yaml \
  --provider ollama \
  --model qwen3:8b \
  --runtime builtin \
  --sandbox docker \
  --store file \
  --prompt "Diagnose the root cause in src/superqode/data/eval_fixtures/ci-dynamic-root-cause.log using dynamic_workflow_script and context_handle. Return the ROOT_CAUSE line and identify downstream failures." \
  --json
```

## Inspect Replay

After a file-backed `harness run`, use the returned `run_id`:

```bash
superqode harness replay <run-id>
superqode harness evidence <run-id>
superqode harness observability export <run-id>
```

For dynamic runs, these commands show:

- the dynamic workflow tool used
- whether a restricted script compiled
- the objective
- step ids
- fan-out markers
- child run ids
- normal parent/child lineage
- OTEL-shaped spans for the root run and each child run

The resulting replayable and exportable tree records each bounded child run and
the evidence it inspected.

## Tool Choice

Use `context_handle` when the model needs to peek, grep, or chunk a large local
artifact without loading it into the prompt.

Use `spawn_harness` when there is one narrow child task, for example "inspect
this log cluster" or "scan this package for auth checks."

Use `dynamic_workflow` when the model can express the plan as structured JSON
steps.

Use `dynamic_workflow_script` when the plan is clearer as a restricted
Python-like script:

```python
workflow("diagnose checkout CI root cause", max_children=4, max_depth=1)

step(
    "log-map",
    task="Inspect this log chunk for the earliest root-cause failure.",
    context_handle="file:src/superqode/data/eval_fixtures/ci-dynamic-root-cause.log",
    fanout=True,
    chunk_chars=12000,
    max_chunks=2,
    max_parallel=2,
    mode="read-only",
)
```

`dynamic_workflow_script` is not arbitrary Python execution. SuperQode parses
the script and accepts only literal `workflow(...)` and `step(...)` calls, then
executes the compiled plan through `dynamic_workflow`.
