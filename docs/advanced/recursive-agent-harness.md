# Recursive Agent Harness

SuperQode supports a local-first path toward recursive agent harnessing:
context stays outside the model window, child harnesses inspect bounded
fragments, and every delegation is sandboxed, budgeted, observable, and
replayable.

This is not a paper-faithful RLM clone and it is not a claim that managed agent
providers secretly run RLM. It is a practical convergence of three public
patterns:

- RLM-style context-as-data: large inputs live in a queryable environment, not
  the prompt.
- Managed-agent separation: the model, sandbox, and session log are separate
  components.
- Dynamic workflows: a root agent can delegate fragment-level work and
  synthesize compact results.

## When It Helps

Recursive harnessing is for large, dense tasks where flat context is brittle:

- monorepo impact scans
- multi-file migrations
- long CI or test-log diagnosis
- trace evidence analysis
- dense repo Q&A with local semantic search

It is not the default path for small edits. It adds latency, especially on
laptop-local models, and should stay opt-in or auto-triggered only when a task
needs fan-out.

## Harness Policy

Use `recursion` to bound local child harness delegation:

```yaml
recursion:
  enabled: true
  max_depth: 1
  max_children: 6
  max_parallel: 2
  max_wall_seconds: 600
  child_model: utility-coder
  child_sandbox: docker
  write_policy: approval
```

The first implementation exposes two local tools:

- `context_handle`: inspect large local artifacts through handles such as
  `file:ci.log`, `repo:src/**/*.py`, `diff:working-tree`, and `run:<run_id>`.
- `spawn_harness`: delegate a bounded child task, or chunk a context handle and
  fan out one child per chunk.

When `spawn_harness` runs inside `HarnessKernel`, each child is a real child
harness run. The kernel creates the child `HarnessRunRecord`, sets
`parent_run_id` and `root_run_id`, applies child tool filtering, emits the child
run lifecycle, and appends `recursive.child.started` /
`recursive.child.completed` events to the parent. Outside a harness-backed
session it falls back to the existing child `AgentLoop` runner without durable
run lineage.

In read-only mode children are restricted to inspection tools such as
`read_file`, `grep`, `glob`, `repo_search`, `code_search`, `context_handle`,
and optional `semantic_search`.

Example agent tool list:

```yaml
agents:
  - id: root-coder
    tools:
      - read_file
      - grep
      - glob
      - repo_search
      - semantic_search
      - context_handle
      - spawn_harness
      - patch
      - bash
```

Example prompt:

```text
Find why checkout double-charges. Use spawn_harness to inspect payment,
webhook, and ledger paths separately, then synthesize the root cause.
```

For long logs or diffs, inspect the handle first:

```text
Use context_handle(action="grep", handle="file:ci-run.log", pattern="ERROR|FAILED")
to locate failure clusters. Then spawn child harnesses for the top clusters.
```

For broad map-style scans, let `spawn_harness` chunk and fan out directly:

```text
Use spawn_harness(
  task="Inspect this chunk for the earliest root-cause failure. Return only evidence and confidence.",
  context_handle="file:ci-run.log",
  fanout=true,
  chunk_chars=12000,
  max_chunks=6,
  max_parallel=2,
  mode="read-only"
), then synthesize the child findings.
```

## Run Lineage

Recursive work should never be opaque. Harness runs now carry lineage fields:

- `parent_run_id`: the immediate run that spawned this run
- `root_run_id`: the top-level run for the recursive tree

Replay and evidence tools can use these fields to render:

```text
root: diagnose checkout double charge
  child: scan payment/
  child: scan webhooks/
  child: scan ledger/
```

## Remote Managed Harnesses

SuperQode is local-first, not local-only. Managed agent platforms should be
modeled as remote harness backends behind the same SuperQode contract:

```yaml
remote_harness:
  enabled: true
  provider: google-agent-engine
  region: us-central1
  context_policy: selected-files
  config:
    mode: generate_content
    base_agent: gemini-flash-latest
    api_key_env: GEMINI_API_KEY
```

Known managed backend names:

- `google-agent-engine`
- `anthropic-managed`

Google's current Agent Platform documentation describes Agent Runtime as the
managed runtime for deployed agents, with sessions, memory, sandbox execution,
tracing, logging, and monitoring as platform services. Configure
`google-agent-engine` in one of two ways:

- `mode: generate_content` for direct Gemini offload with `GEMINI_API_KEY` and
  no deployed agent endpoint.
- `mode: persisted` or `mode: agent` with `agent_id` and `api_base` for a
  deployed managed-agent interaction endpoint.

Anthropic describes Claude Managed Agents as a hosted service that separates the
brain, sandbox, and session log for long-running work. Configure
`anthropic-managed` with the hosted endpoint for your managed agent and
`ANTHROPIC_API_KEY`. If you want the documented local/hostable SDK path instead
of the hosted Managed Agents service, use the existing `claude-agent-sdk`
runtime backend.

Until a managed backend has its required credentials and, where the selected
mode needs one, an endpoint, it fails closed and reports the missing
configuration instead of silently running locally.

## Dynamic Workflows

The next tier is model-authored orchestration. A root model writes a restricted
plan, and the runtime exposes only safe helpers. The first shipped primitive is
`dynamic_workflow`, a bounded orchestration tool over `spawn_harness`:

```json
{
  "objective": "Audit all route handlers for missing auth checks.",
  "steps": [
    {
      "id": "routes",
      "task": "Inspect this route chunk for missing authentication checks.",
      "context_handle": "repo:src/routes/**/*.py",
      "fanout": true,
      "chunk_chars": 12000,
      "max_chunks": 6,
      "max_parallel": 2,
      "mode": "read-only"
    }
  ],
  "max_children": 8,
  "max_depth": 1
}
```

Each step delegates through `spawn_harness`, so child runs still get kernel
lineage, sandbox/model metadata, and replayable event records. This gives the
agent dynamic orchestration without granting arbitrary host execution.

For a more natural authoring shape, use `dynamic_workflow_script`. This is not
arbitrary Python execution: SuperQode parses the script AST and only accepts
literal `workflow(...)` and `step(...)` calls, then compiles them to the same
`dynamic_workflow` plan.

```python
workflow("Audit all route handlers for missing auth checks.", max_children=8)

step(
    "routes",
    task="Inspect this route chunk for missing authentication checks.",
    context_handle="repo:src/routes/**/*.py",
    fanout=True,
    chunk_chars=12000,
    max_chunks=6,
    max_parallel=2,
    mode="read-only",
)
```

A later tier can add a true sandboxed orchestration runtime with safe helpers:

```python
routes = load_context("repo:src/routes").chunk("files")
findings = []

for route in routes:
    findings.append(spawn_harness(
        task=f"Audit auth checks in {route.path}",
        context_handle=route.handle,
        mode="read-only",
        sandbox="docker",
    ))

FINAL(summarize(findings))
```

This tier depends on the local `spawn_harness` tool, context handles, budget
governance, and recursive replay. It should not ship before those foundations
are tested.

## Constraints

- Local concurrency should default low, usually 2-4 child tasks on a laptop.
- Wide fan-out belongs on a served local pool, multi-GPU host, cloud sandbox, or
  managed agent backend.
- Write-capable child runs need explicit policy and approval.
- Recursion limits are enforced by the harness, not by model instructions.

## Eval Pack

SuperQode ships a small recursive smoke pack:

```bash
superqode harness eval-packs
superqode harness eval-packs local-recursive-smoke
```

Run it live from the SuperQode checkout with a local recursive harness:

```bash
superqode harness eval \
  --spec harness.yaml \
  --tasks "$(superqode harness eval-packs local-recursive-smoke)" \
  --provider openai-compatible \
  --model qwen3:8b \
  --sandbox docker \
  --live
```

The task asks the agent to inspect a bundled CI log via `context_handle`, use
`spawn_harness` for the relevant cluster, and return the planted root cause.
It is intentionally tiny: a fast local proof that context-as-data and bounded
delegation are wired before running larger monorepo/log packs.
