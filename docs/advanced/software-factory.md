# Terminal-First Software Factory

SuperQode's Software Factory is the durable delivery system inside its broader Agent Engineering product. It orchestrates multiple coding-agent harnesses and provides the execution, evaluation, governance, and optimization controls required to deliver verified repository changes.

The Software Factory is a first-class product capability within Agent Engineering. It is broader than the `sq factory` command group, and it does not treat one autonomous chat session as a complete delivery system.

```text
Build the harness
      ↓
Run sessions or durable WorkOrders
      ↓
Evaluate patches, checks, cost, and evidence
      ↓
Accept, merge, reject, or recover
      ↓
Improve the harness under regression gates
      ↺
```

The primary interface is the terminal. SuperQode does not require a hosted coordination server, web workspace, desktop application, or mobile client to finish work.

## The product model

| Factory layer | SuperQode component | What it owns |
| --- | --- | --- |
| Worker definition | `HarnessSpec` | Runtime, model policy, tools, context, memory, sandbox, workflow, checks, and approvals. |
| Runtime portability | Harness Protocol and adapters | A common lifecycle across native Core, SDK, ACP, Python, RLM Code, and imported harnesses. |
| Interactive operation | Session graph and Switchboard | Live sessions, peers, forks, handoffs, steering, approvals, and share artifacts. |
| Routing and lineage | `sq factory` | Project routes plus recorded model, runtime, harness, and mode changes. |
| Durable delivery | WorkOrder | Goal, task DAG, roles, budgets, leases, worktrees, evidence, checks, review, and final decision. |
| Execution plane | `sq work worker` | Persistent queue consumption, bounded concurrency, heartbeats, retry, and crash recovery. |
| Operator surface | `sq work watch` | Live task, lease, budget, gate, artifact, worker, and event visibility. |
| Quality system | Harness eval and benchmark | Comparable scorecards and regression gates across harness variants. |
| Improvement loop | Harness candidates, `improve`, and `optimize` | Staged candidates, negative evidence, held-out gates, audit, adoption, and rollback-friendly version control. |

The `factory` command group is therefore one module inside the Software Factory: it controls route intent and lineage. WorkOrders are the module that makes work finish.

## Architecture

```text
                             REPOSITORY
       harness.yaml      .superqode/factory.yaml      eval tasks
            │                       │                     │
            └───────────────┬───────┴─────────────────────┘
                            │ repo-owned contracts
                            ▼
                    SUPERQODE TERMINAL PLANE
             CLI / TUI / Harness Protocol / event stores
                    │                       │
           interactive sessions       durable WorkOrder
          switchboard + lineage      task DAG + budgets + gates
                    │                       │
                    └──────────┬────────────┘
                               ▼
                        HEADLESS WORKERS
             HarnessSpecs + runtimes + isolated worktrees
                               │
                 patches + reviews + checks + traces
                               ▼
                    EVIDENCE AND DECISION LEDGER
                  accept / merge / reject / recover
                               │
                               ▼
                      EVALUATE AND IMPROVE
                candidate → held-out gate → human adopt
```

The local default is SQLite plus repository-owned files. A foreground worker is designed to be supervised by launchd, systemd, Kubernetes, a CI executor, or a terminal multiplexer. This keeps process ownership visible and avoids a hidden background service.

## Choose the right operating path

| You need to… | Start with… |
| --- | --- |
| Work interactively with one coding agent | `superqode --harness harness.yaml` |
| Run a repeatable one-shot harness task | `sq harness run --spec harness.yaml --prompt "..."` |
| Coordinate live sessions and forks | `:switchboard` and `:factory` |
| Deliver a repository change through roles and gates | `sq work create`, then `sq work worker` |
| Keep a builder or CI machine consuming work | `sq work worker` |
| Watch execution without a browser | `sq work watch WORK_ID` |
| Queue prompts for one long-lived harness session | `sq harness worker` |
| Compare or improve harness configurations | `sq harness eval` and `sq harness improve` |

There are two deliberate durable worker commands:

- `sq harness worker` drains prompt inputs for one HarnessSpec session. Use it for a durable agent inbox.
- `sq work worker` drains dependency-aware WorkOrder tasks. Use it for repository delivery with roles, isolation, checks, review, and merge decisions.

## End-to-end builder quickstart

### 1. Build a repository-owned harness

```bash
sq harness init repo-coder --template coding --output harness.yaml
sq harness validate --spec harness.yaml
sq harness doctor --spec harness.yaml
sq harness explain --spec harness.yaml
```

Commit `harness.yaml` when you want the worker definition reviewed and versioned with the repository.

An existing Omnigent agent can enter through the same path:

```bash
sq harness import-omnigent path/to/agent.yaml --output harness.yaml
sq harness validate --spec harness.yaml
```

### 2. Define the finish line

Create a WorkOrder in draft so roles and dependencies can be added before it is queued:

```bash
sq work create "Implement and review the authentication fix" \
  --repo . \
  --task-id investigate \
  --task-title "Investigate" \
  --role investigator \
  --harness rlm-code \
  --acceptance-test "uv run pytest -q tests/test_auth.py" \
  --max-workers 2 \
  --max-seconds 1800
```

Copy the printed `work_...` id, then build the task graph:

```bash
sq work add-task work_... "Implement the smallest safe fix" \
  --task-id implement --role implementer --harness harness.yaml \
  --depends-on investigate

sq work add-task work_... "Review the resulting patch" \
  --task-id review --role reviewer --harness review \
  --depends-on implement

sq work queue work_...
```

### 3. Run and watch from two terminals

Terminal one runs a bounded worker dedicated to this WorkOrder:

```bash
sq work worker work_... --id builder-01 --concurrency 2 --once
```

Terminal two is the operator cockpit:

```bash
sq work watch work_...
```

Ready tasks are claimed atomically. Patch-producing roles receive isolated Git worktrees, evidence-only roles are prevented from changing files, dependencies see safely integrated predecessor work, and overlapping changes block rather than overwrite one another.

### 4. Gate and deliver the exact result

```bash
sq work check work_...
sq work prepare work_...
sq work diff work_...
sq work approve work_... --actor maintainer --reason "reviewed and green"
sq work merge work_... --actor maintainer --cleanup
```

SuperQode does not stage or commit the user's checkout. Approval is tied to the prepared candidate digest, and merge rechecks target drift before applying it.

### 5. Measure and improve the harness

```bash
sq harness eval \
  --spec harness.yaml \
  --tasks evals/tasks.yaml \
  --split held-out \
  --live

sq harness improve \
  --spec harness.yaml \
  --tasks evals/tasks.yaml \
  --budget 4 \
  --search-mode frontier \
  --selection-policy pareto
```

Evaluation is a seesaw gate: a candidate that regresses a task the baseline solved fails by default. Improvement candidates and failures remain evidence; adoption is explicit unless the operator deliberately selects an apply option.

## Routes and policy lineage

Routes describe intent instead of vendor names:

| Route | Intent |
| --- | --- |
| `private` | Prefer local models and private execution. |
| `local` | Use local providers where possible. |
| `cheap` | Prefer local or lower-cost BYOK models. |
| `best` | Allow the strongest configured model and runtime. |
| `review` | Prefer reviewer harnesses and high-reasoning models. |
| `long-context` | Prefer long-context models and harnesses. |
| `no-subscription` | Avoid subscription-only runtimes; use local or BYOK routes. |

Create the project policy and inspect route resolution:

```bash
sq factory init-policy
sq factory policy
sq factory routes
sq factory resolve-route no-subscription
```

`.superqode/factory.yaml` belongs to the project. The current factory module records route, model, runtime, and harness lineage. WorkOrders enforce workers, elapsed time, cumulative cost, tokens, tool calls, and task risk. Usage limits are checked at task boundaries and fail closed when a configured metric is not reported; provider-side request limits remain the right companion for an exact ceiling inside one live model call.

## Operating the worker pool

Run a global builder pool:

```bash
sq work worker --id builder-mac-01 --concurrency 4
```

Inspect it from another terminal:

```bash
sq work workers
sq work list --status running
sq work watch work_...
sq work events work_... --limit 20
```

Common recovery actions:

| Situation | Action |
| --- | --- |
| Worker host exited | Restart the service; stale leases are recovered automatically. |
| Need an explicit sweep | `sq work recover [WORK_ID] --stale-after 300` |
| Reviewer requested changes | Inspect evidence, then `sq work resume WORK_ID --task review`. |
| Check failed | Fix the cause, resume, and rerun `sq work check`. |
| Patch conflict | Inspect conflict artifacts; SuperQode never chooses a winner silently. |
| Work is superseded | `sq work cancel WORK_ID --reason "superseded"` |
| Result is unacceptable | `sq work reject WORK_ID --reason "..."` |

Ctrl+C or `SIGTERM` stops a persistent worker from claiming more tasks and lets active tasks drain. A worker identity has a process lock, so two live services cannot accidentally operate under the same identity. Atomic heartbeat snapshots live beside the WorkOrder SQLite database under `workers/`.

## What is implemented now

The current factory can:

- define and import portable harnesses
- run many harness and runtime families through shared contracts
- coordinate interactive sessions, peers, forks, handoffs, and lineage
- execute durable role-aware WorkOrders with dependency scheduling
- isolate parallel file changes and integrate them deterministically
- recover crashed workers through leases and heartbeats
- enforce reviewer output and deterministic acceptance gates
- prepare, approve, merge, roll back, and clean up exact candidates
- expose worker and WorkOrder state through terminal and JSON cockpits
- normalize cost, token, tool-call, iteration, and latency evidence and enforce task-boundary budgets
- explain and simulate budget/risk policy decisions from the terminal without mutation
- enforce layered request/response/tool/result/promotion policy and broker host-bound credentials
- produce reproducible HarnessBench packages with raw runs, variance, Pareto scorecards, and checksums
- stage, canary, activate, and roll back guarded harness improvement candidates
- run local, open, BYOK, subscription, SDK, ACP, A2A, and RLM-backed paths

The current boundary is equally important:

- SuperQode does not provide Omnigent-style synchronized web, mobile, and desktop collaboration surfaces. It does provide focused Telegram/Slack/Discord remote control, a local companion API, and an authenticated Enterprise browser TUI.
- Contextual policy is file-backed and terminal-operated; SuperQode does not provide a hosted organization identity or policy administration service.
- Usage budgets are enforced at task boundaries, not streamed during one provider call; an in-flight call can finish above its limit, but its output cannot enter the integration tree.
- The credential broker currently injects named bindings for `fetch` and `web_fetch`; arbitrary third-party native-runtime HTTP clients require their own broker adapter.
- The default WorkOrder store is local SQLite; operating a shared filesystem and process supervisor remains the deployer's responsibility.

These boundaries keep the product honest: SuperQode is already an execution, evidence, delivery, and improvement system for terminal builders, but it does not claim feature parity with a managed collaboration platform.

## Relationship to Omnigent

Omnigent and SuperQode overlap directly in multi-harness operation, portable agent definitions, terminal execution, sessions, tools, models, policy, and sandbox concerns.

Their centers of gravity differ:

- Omnigent centers the persistent, shareable live session across terminal, web, mobile, and desktop interfaces.
- SuperQode centers the repository-owned harness and durable WorkOrder: build it, run it through isolated workers, prove the result, deliver it safely, and improve the harness from evidence.

The products overlap for multi-harness builders, but their different centers make them suitable for different workflows. SuperQode also remains an interop layer for teams that already have Omnigent YAML. See [How SuperQode Relates to Omnigent](superqode-vs-omnigent.md) for the shared ideas and design differences, and [Omnigent Compatibility](omnigent-compat.md) for the importer.

## Read next

- [WorkOrders](workorders.md): lifecycle, roles, workers, evidence, and delivery gates
- [Harness System](harness-system.md): the complete `HarnessSpec` contract
- [Run, Measure, Optimize](harness-optimization.md): scorecards and guarded improvement
- [Software Factory CLI](../cli-reference/factory-commands.md): exact route and lineage commands
- [WorkOrder CLI](../cli-reference/work-commands.md): exact execution and decision commands
