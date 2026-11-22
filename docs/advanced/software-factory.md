# Building a Code Factory with SuperQode

Your code factory is the organization-owned system that combines coding agents, harnesses, models, repositories, context, tools, policies, evaluation gates, and delivery workflows. The SuperQode Software Factory defines that system as code, runs it through durable WorkOrders, checks the result with protected evaluators and SuperGauge, and releases only what a person signs.

```text
Define the Factory (FactorySpec)
      ↓
Queue a trial and run its WorkOrder
      ↓
Verify the exact candidate with hidden evaluators
      ↓
SuperGauge verdict: ship, hold or reject
      ↓
Human signature, then apply
      ↓
Improve the Factory under held-out gates
      ↺
```

The macOS app is the primary interface. The CLI and TUI are fully capable on their own: every step above, from creating a Factory to the release decision, has a `sq factory` command and a `:factory` TUI command that use the same engine and the same files. No hosted coordination server is required.

## The seven layers

A FactorySpec (`.superqode/factory.yaml`) has seven layers, with governance across all of them:

| Layer | In the FactorySpec | What it owns |
| --- | --- | --- |
| Factories-as-code | `apiVersion`, `metadata`, revisions | The versioned definition itself, saved revisions and source commits |
| Data and context | `data_context` | Repository, context and skill files, requirements, and protected evaluator files |
| Compute | `compute` | Where work runs: each task in its own isolated Git worktree (`runner: worktree`), inside the OS sandbox when enabled |
| Inference | `inference` | The harnesses stages bind to, with their model policy and skills |
| Improvement | `improvement` | Acceptance checks and guarded experiments on harnesses, skills, routes and workflow |
| Orchestration | `orchestration` | Stages, dependencies, human gates, acceptance checks, revision loops and intake |
| Access | `access` | The interfaces that can operate the Factory: macOS, CLI, TUI, API and MCP |
| Governance (across all layers) | `governance` | Permissions, budgets, release authority (signers) and the SuperGauge release requirement |

Supporting components:

| Component | Role in the Factory |
| --- | --- |
| `HarnessSpec` | Worker definition: runtime, model policy, tools, context, memory, sandbox, workflow, checks and approvals |
| Harness Protocol and adapters | A common lifecycle across native Core, SDK, ACP, Python, RLM Code and imported harnesses |
| WorkOrder | Goal, task DAG, roles, budgets, leases, worktrees, evidence, checks, review and final decision |
| `sq factory worker` and `sq work worker` | Queue consumption, bounded concurrency, heartbeats, retry and crash recovery |
| Protected verification | Runs evaluators against a read-only copy of the exact candidate |
| SuperGauge | The quality verdict bound to the Factory revision and candidate |
| Session graph and Switchboard | Live sessions, forks, handoffs and route lineage for interactive work |

Factory definition commands compile a saved FactorySpec into a pinned plan, admit it as a WorkOrder, run it, verify it and record the release decision. WorkOrders remain the durable delivery machinery. See [Factory Commands](../cli-reference/factory-commands.md) for every command and its limits.

## From definition to release

```bash
sq factory init --template fix-and-verify
sq factory check --application
sq factory trial "Fix the export freeze"
sq factory worker WORK_ID --live
sq factory verify WORK_ID --execute
sq factory evidence trace WORK_ID
sq factory decide WORK_ID
sq factory release-challenge WORK_ID --key owner
sq factory authorize WORK_ID --proof .superqode/release-proof.json
sq factory apply WORK_ID --candidate-id ARTIFACT_ID --candidate-digest SHA256_DIGEST
```

- Evaluator files are removed from every task worktree before agents start. With `SUPERQODE_SANDBOX` on, the worker sandbox also masks them. Attempts to read or write them are recorded, and edits are dropped.
- Verification reports each acceptance check as passed, failed, blocked or never ran, and each requirement as covered, failed, blocked or uncovered.
- SuperGauge gives **ship**, **hold** or **reject** for the exact candidate. Model judges may hold or reject but never approve.
- Release requires a SuperGauge record at the level set in `governance.release_gauge` (default L2) with a ship verdict, bound to the same revision and candidate, and then a human signature. Neither alone is enough.
- Readiness checks label each finding `configured`, `execution_tested` or `quality_evaluated`; they never produce a score.

## Architecture

```text
                             REPOSITORY
       harness.yaml      .superqode/factory.yaml      eval tasks
            │                       │                     │
            └───────────────┬───────┴─────────────────────┘
                            │ repo-owned contracts
                            ▼
                    SUPERQODE CONTROL PLANE
       macOS app / CLI / TUI / Harness Protocol / event stores
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
          HIDDEN-EVALUATOR VERIFICATION + SUPERGAUGE
              ship / hold / reject → human signature
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
| Define, run and release through a Factory | The macOS app, `sq factory`, or `:factory` |
| Coordinate live sessions and forks | `:switchboard` and `:factory session` |
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

Create the project Factory (it carries the route policy) and inspect route resolution:

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

- author and version seven-layer FactorySpecs in the macOS app, the CLI or the TUI, with explicit model-assisted drafts and pinned trials
- hide evaluator files from worker checkouts, record any access, and drop protected edits
- verify Python CLI candidates with protected probes, emit a SuperGauge ship, hold or reject verdict bound to the candidate, and require that verdict plus a candidate-bound signature before working-tree delivery
- run a project's own build, start and health checks as readiness evidence
- report outcome cost per Factory revision including failed attempts and optimization experiments
- queue work from signed webhooks or declared schedules
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

- SuperQode provides focused Telegram/Slack/Discord remote control and a local companion API. The open-source package does not provide synchronized multi-client collaboration or hosted team administration.
- Contextual policy is file-backed and terminal-operated; SuperQode does not provide a hosted organization identity or policy administration service.
- Usage budgets are enforced at task boundaries, not streamed during one provider call; an in-flight call can finish above its limit, but its output cannot enter the integration tree.
- The credential broker currently injects named bindings for `fetch` and `web_fetch`; arbitrary third-party native-runtime HTTP clients require their own broker adapter.
- The default WorkOrder store is local SQLite; operating a shared filesystem and process supervisor remains the deployer's responsibility.

These boundaries describe the supported execution, evidence, delivery, and improvement workflows without implying hosted collaboration capabilities.

## Repository-owned workflows

SuperQode centers the repository-owned harness and durable WorkOrder. Define the execution contract, run work through isolated workers, inspect the resulting evidence, and review an exact candidate before integration. Evaluation and guarded optimization can then inform later harness revisions.

Import compatible Omnigent agent definitions into a SuperQode HarnessSpec. See
[Omnigent Compatibility](omnigent-compat.md) for supported fields and import instructions.

## Read next

- [WorkOrders](workorders.md): lifecycle, roles, workers, evidence, and delivery gates
- [Harness System](harness-system.md): the complete `HarnessSpec` contract
- [Run, Measure, Optimize](harness-optimization.md): scorecards and guarded improvement
- [Software Factory CLI](../cli-reference/factory-commands.md): exact route and lineage commands
- [WorkOrder CLI](../cli-reference/work-commands.md): exact execution and decision commands
