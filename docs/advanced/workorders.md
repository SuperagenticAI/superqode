# WorkOrders

A WorkOrder is SuperQode's durable finish-line contract for coding-agent work. It binds a goal, repository, HarnessSpec, dependency-aware tasks, budgets, acceptance commands, worker leases, artifacts, and the final human decision into one replayable record.

Session graphs answer "which agents are active?" A WorkOrder answers "did the work finish, under which policy, and was it accepted?"

## Where WorkOrders fit

WorkOrders are the durable delivery unit inside SuperQode's [terminal-first Software Factory](software-factory.md):

```text
HarnessSpec defines each worker
        ↓
WorkOrder defines the goal, roles, dependencies, budgets, and finish line
        ↓
work worker executes tasks; work watch operates them
        ↓
checks + review + candidate digest gate delivery
        ↓
eval and improvement use the evidence to improve the harness
```

Use a normal harness session for interactive exploration. Use a WorkOrder when repository changes must survive worker crashes, run in isolation, pass deterministic gates, and end in an explicit accept, merge, reject, or cancel decision.

## Tasks, dependencies, leases, and recovery in plain language

These features exist so multi-agent work can finish reliably even when several workers run at once or one process disappears.

### The task graph is an ordered checklist

"DAG" is the technical name for a list of tasks with dependencies and no circular path. You do not need to think in graph terminology.

For example:

```text
investigate ──→ implement ──→ review ──→ test
                        └────→ docs ─────┘
```

- `review` cannot start until `implement` finishes.
- `docs` can run alongside `review` because both depend only on `implement`.
- `test` waits for both `review` and `docs`.

This prevents a reviewer from reviewing work that does not exist yet, while still allowing independent tasks to run in parallel. SuperQode validates the dependencies before queuing the WorkOrder and rejects circular dependencies.

### A lease is a timed task checkout

When a worker takes a task, SuperQode does not assign it forever. It gives the worker a lease:

```text
worker builder-01 checks out task "implement" for 300 seconds
```

While that lease is active, another worker cannot perform the same task. The running worker sends heartbeats to renew the lease, similar to saying "I am still alive and working."

Without leases, two workers could unknowingly implement the same task, or a task could remain stuck as `running` forever after a laptop, model process, terminal, or CI runner crashes.

### Recovery returns abandoned work to the queue

If the heartbeat stops and the lease becomes stale, SuperQode recovers the task:

1. The abandoned worker identity is recorded in the event and task metadata.
2. The task returns to `pending` when retry attempts remain.
3. Another worker can claim it and continue the WorkOrder.
4. When the attempt limit is exhausted, the task fails explicitly instead of retrying forever.

The active worker service performs this recovery automatically. An operator can also run:

```bash
sq work recover work_... --stale-after 300
```

The practical outcome is simple: start work from the terminal, leave it running, and know that one dead worker will not silently duplicate or permanently strand the job.

## Lifecycle

```text
draft -> queued -> running -> reviewing -> checking -> ready_to_merge
                    |             |           |              |
                    +----------> blocked <----+              +-> merging -> merged
                    |                                        |               |
                    +-> failed                               +-> rejected    +-> rolled_back

Any pre-merge unfinished state may be cancelled. A persisted `merging` state must be finalized or recovered so the database cannot disagree with the target checkout.
```

Tasks have their own `pending`, `running`, `succeeded`, `blocked`, `failed`, and `cancelled` states. A task becomes claimable only when every declared dependency has succeeded.

## Create and run

Create a WorkOrder with a primary task and deterministic acceptance commands:

```bash
sq work create "Implement the smallest safe authentication fix" \
  --repo . \
  --harness coding \
  --acceptance-test "uv run pytest -q tests/test_auth.py" \
  --max-workers 1 \
  --max-seconds 1800 \
  --queue
```

The command prints a time-sortable `work_...` id. Run dependency-ready tasks through their assigned harnesses:

```bash
sq work run work_...
sq work tree work_...
sq work events work_...
sq work artifacts work_...
```

`work run` claims tasks atomically, maintains the worker heartbeat while the harness runs, records run/session lineage, and stores the assistant result as a typed artifact. It stops when there is no ready task or the WorkOrder reaches a review, approval, failure, or cancellation gate.

By default, `work run` creates one WorkOrder integration worktree plus an isolated worktree for every task attempt. Ready tasks run concurrently up to `budget.max_workers`. Each completed task produces a binary-safe patch that is joined into the integration worktree under a process lock. Non-overlapping patches combine; overlapping file changes block the WorkOrder with conflict evidence instead of choosing a winner. Dependency tasks are created from the verified integration tree, so they see every safely joined predecessor change. Acceptance commands run inside the integration worktree. Use `--isolation none` only for intentional, single-worker execution.

The SQLite claim transaction and `budget.max_workers` prevent duplicate or excessive assignments. Built-in scheduling fans out dependency-ready tasks and waits for the bounded batch before admitting newly unblocked work. Filesystem integration is serialized across local scheduler processes, while task execution remains parallel.

## Usage, budgets, and risk policy

`max_workers` is enforced atomically at claim time and `max_seconds` bounds both admission and the live harness wait. Every finished harness call also produces a normalized `usage` artifact containing the provider/model/runtime lineage and whatever token, cost, tool-call, iteration, and latency evidence the runtime reported.

Configure task-boundary gates with `--max-cost`, `--max-tokens`, `--max-tool-calls`, and `--max-risk`. SuperQode checks cumulative accounting before each claim and again after each harness call. A result that exceeds a configured usage limit is blocked before its agent result or patch can enter the integration tree. If a configured metric is not reported by the selected runtime, the gate fails closed instead of guessing that the usage was zero.

Risk is an admission gate. Investigator, reviewer, and tester roles default to `low`; implementer, synthesizer, and custom roles default to `medium`. Set a task explicitly with `--risk low|medium|high|critical`, and cap the WorkOrder with `--max-risk`.

```bash
sq work usage work_...
sq work policy work_... --task implement
sq work policy work_... --phase completion --add-cost 0.50 --add-tokens 20000
```

The second command explains the current decision. The third performs a read-only projection; it does not spend budget or mutate the WorkOrder. `sq work watch` shows observed usage against configured limits and the latest allow/deny decision.

These are task-boundary gates, not streaming provider reservations. One in-flight model call can report a total above the configured limit because the exact usage is known only when that call returns; SuperQode then prevents that output from being integrated and admits no later task. Use provider-side request limits as an additional ceiling when an exact per-call maximum is required.

## Headless workers and the terminal cockpit

`work run` is the foreground, one-WorkOrder path. For a builder machine, CI runner, or enterprise worker host, start the persistent queue service instead:

```bash
# Watch every queued WorkOrder in this store.
sq work worker --id builder-mac-01 --concurrency 4

# Or dedicate a worker to one WorkOrder and exit when it drains.
sq work worker work_... --id ci-17 --concurrency 2 --once
```

The service claims ready tasks until its concurrency limit is reached, while each WorkOrder's own `budget.max_workers` remains a hard independent gate. It renews task heartbeats through the normal harness runner, periodically recovers abandoned leases, and stops claiming on `SIGINT` or `SIGTERM` while active tasks drain. Use `--max-tasks` to bound ephemeral CI workers and the normal provider, model, runtime, sandbox, and isolation options to configure a worker pool.

SuperQode deliberately runs the worker in the foreground instead of forking an opaque background process. Use launchd, systemd, Kubernetes, a CI executor, or a terminal multiplexer to supervise it. A process lock prevents two live services from using the same worker identity.

Isolated worktrees normally live under `~/.superqode/working`. On CI runners,
containers, and locked-down builder hosts, set `SUPERQODE_HOME` to a writable
state directory; WorkOrder worktrees and their registry then live under
`$SUPERQODE_HOME/working` without changing the operating-system home directory.

Every service writes an atomic heartbeat under `.superqode/workorders/workers/`. Inspect the pool and watch one WorkOrder without leaving the terminal:

```bash
sq work workers
sq work watch work_...
sq work watch work_... --once --json
```

The cockpit shows task roles and dependencies, attempts, lease owners and remaining lease time, budgets, checks, review verdicts, integration conflicts, artifact counts, worker health, and the latest lifecycle events. It exits automatically when the WorkOrder reaches a terminal state. The JSON snapshot is suitable for external monitors.

## Dependency-aware tasks

Tasks carry an explicit behavioral role:

| Role | Contract |
| --- | --- |
| `investigator` | Inspect the repository and produce evidence without modifying files. |
| `implementer` | Produce an isolated patch that may join the integration tree. |
| `synthesizer` | Reconcile integrated predecessor work into one coherent patch. |
| `reviewer` | Inspect without edits and emit a structured approval or changes-requested verdict. |
| `tester` | Run verification and report evidence without modifying tracked files. |
| `custom` | User-defined patch-producing task. |

Evidence-only roles are enforced after execution. If they change repository files, the task becomes `blocked`, its rejected patch is preserved as a `workspace_violation` artifact, and the integration tree remains unchanged.

A reviewer must end with one machine-readable line:

```text
SUPERQODE_REVIEW: {"verdict":"approved","summary":"clean","issues":[]}
```

The other accepted verdict is `changes_requested`, with concrete entries in `issues`. Missing JSON, malformed JSON, requested changes, or reviewer file mutations block the WorkOrder. `work prepare` independently verifies that every declared reviewer task has an approved `review` artifact, so low-level worker completion cannot bypass cross-review.

Add tasks while the WorkOrder is still a draft:

```bash
sq work add-task work_... "Inspect the relevant architecture" \
  --task-id investigate \
  --title "Repository investigation" \
  --role investigator \
  --harness rlm-code

sq work add-task work_... "Implement the approved approach" \
  --task-id implement \
  --depends-on investigate \
  --role implementer \
  --harness coding

sq work add-task work_... "Reconcile all implementation output" \
  --task-id synthesize \
  --depends-on implement \
  --role synthesizer \
  --harness coding

sq work add-task work_... "Review the resulting patch" \
  --task-id review \
  --depends-on synthesize \
  --role reviewer \
  --harness review

sq work queue work_...
```

Unknown dependencies, self-dependencies, and dependency cycles are rejected before queuing. Downstream tasks receive bounded `agent_result` and `review` evidence from their declared dependencies in addition to the integrated repository state.

## Worker leases and crash recovery

The low-level commands are useful for external workers and schedulers:

```bash
sq work claim work_... --worker worker-17 --lease 300 --json
sq work heartbeat work_... implement --worker worker-17 --lease 300
sq work complete work_... implement --worker worker-17 --run-id run_...
sq work fail work_... implement --worker worker-17 --error "model endpoint exited"
sq work recover work_... --stale-after 300
```

Only the lease owner may heartbeat, complete, fail, or block a running task. An expired task is returned to the queue while attempts remain; otherwise it fails deterministically. Every claim, heartbeat, recovery, retry, and terminal result is appended to the event timeline. A separate `sq work cancel` process is observed by the active runner and cancels its live harness coroutine rather than merely changing the database record.

## Acceptance and decisions

After every task succeeds, the WorkOrder moves to `reviewing`. Run its acceptance commands, prepare the exact candidate patch, inspect it, and approve its digest:

```bash
sq work check work_...
sq work prepare work_...
sq work diff work_...
sq work approve work_... --actor shashi --reason "reviewed and green"
sq work merge work_... --actor shashi
```

`work prepare` compares the agent workspace with the exact tree captured before execution. It records a binary-safe, content-addressed patch, detects files changed by both the user and the WorkOrder, verifies that the patch applies to the current checkout, and moves clean work to `ready_to_merge`. `work approve` approves that exact candidate; preparing again invalidates the old approval. `work merge` applies the patch without staging or committing the user's files and verifies the resulting Git tree.

Failed checks or integration conflicts move the WorkOrder to `blocked` and preserve their evidence. Resume after addressing the failure:

```bash
sq work resume work_...
sq work check work_...
```

The target checkout is fingerprinted again at merge time. If it changed after review, SuperQode refuses delivery and asks for another `work prepare`; it never silently overwrites later work. A merged candidate can be reversed only while the target still matches the verified post-merge tree:

```bash
sq work rollback work_... --reason "reconsidered after review"
sq work cleanup work_...
```

Cleanup is explicit by default so every task and integration workspace remains available for investigation. `work merge --cleanup` combines verified delivery and cleanup of all WorkOrder-owned worktrees.

When acceptance commands are declared, `work prepare` and `work approve` refuse to advance until the latest recorded check gate passes. Rejection and cancellation are also explicit decisions:

```bash
sq work reject work_... --reason "approach is too risky"
sq work cancel work_... --reason "superseded"
```

## Typed artifacts

Harness results and acceptance results are recorded automatically. Additional plan, patch, review, cost, or log evidence can be attached explicitly:

```bash
sq work artifact-add work_... \
  --task review \
  --kind review \
  --path reviews/security-review.md
```

Artifacts and events live in `.superqode/workorders/store.sqlite3` by default. Override the database for automation with the group-level `--store` option:

```bash
sq work --store /path/to/workorders.sqlite3 list --json
```

## Current boundary

The WorkOrder kernel now owns durable task admission, dependencies, atomic claims, persistent headless workers, worker heartbeats and inspection, retry/recovery, live cancellation, harness execution, typed evidence, deterministic acceptance commands, content-addressed integration candidates, conflict checks, human approval, verified merge, guarded rollback, managed worktree cleanup, and a live terminal cockpit.

The next integrations are layered cost/risk enforcement, credential brokering, richer private scorecards, and guarded harness optimization. The lifecycle and event contracts are designed so those additions do not require another orchestration model.

For the full product hierarchy and end-to-end operator path, return to [Terminal-First Software Factory](software-factory.md). For competitive scope, see [SuperQode and Omnigent](superqode-vs-omnigent.md).
