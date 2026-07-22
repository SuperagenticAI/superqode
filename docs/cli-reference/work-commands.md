# WorkOrder Commands

`sq work` is the terminal control surface for durable multi-harness work.

```bash
sq work --help
sq work create --help
sq work run --help
sq work worker --help
sq work watch --help
```

| Command | Purpose |
| --- | --- |
| `work create GOAL` | Create a draft WorkOrder and primary task; pass `--queue` to enqueue it immediately. |
| `work add-task ID GOAL` | Add a dependency-aware task while the WorkOrder is a draft. |
| `work list` | List WorkOrders, optionally filtered with `--status`. |
| `work status ID` | Show the complete WorkOrder contract and current task states. |
| `work usage ID` | Show normalized run, token, cost, tool-call, iteration, and latency accounting. |
| `work policy ID` | Explain the current budget/risk gate or simulate projected usage without changing state. |
| `work tree ID` | Render tasks, dependencies, attempts, leases, and workers. |
| `work queue ID` | Validate dependencies and queue draft or blocked work. |
| `work run ID` | Execute ready tasks in bounded parallel, isolated HarnessSpec workers. |
| `work worker [ID]` | Run a persistent headless worker for one WorkOrder or the global queue. |
| `work workers` | Inspect durable worker heartbeats and active task counts. |
| `work watch ID` | Live terminal cockpit for tasks, leases, budgets, gates, evidence, and events. |
| `work claim [ID]` | Atomically claim one ready task for an external worker. |
| `work heartbeat ID TASK` | Renew the current worker lease. |
| `work complete ID TASK` | Mark leased work complete and record run/session lineage. |
| `work fail ID TASK` | Record failure and retry while attempts remain. |
| `work recover [ID]` | Recover expired worker leases. |
| `work resume ID` | Return blocked work to review or the dependency queue. |
| `work check ID` | Run deterministic acceptance commands in the target repository. |
| `work artifact-add ID` | Attach typed evidence. |
| `work artifacts ID` | List evidence attached to the WorkOrder. |
| `work events ID` | Show the append-only decision timeline. |
| `work prepare ID` | Build the exact candidate patch and check source drift and conflicts. |
| `work diff ID` | Print the content-addressed patch awaiting approval. |
| `work approve ID` | Approve completed work or the exact prepared candidate. |
| `work merge ID` | Apply the approved patch without staging or committing user files. |
| `work rollback ID` | Reverse a verified merge when no later work would be overwritten. |
| `work cleanup ID` | Remove a terminal WorkOrder's managed worktree. |
| `work reject ID` | Reject work without deleting its evidence. |
| `work cancel ID` | Cancel unfinished tasks and release leases. |

The default SQLite database is `.superqode/workorders/store.sqlite3`. Pass `--store` before the subcommand to select another database:

```bash
sq work --store .superqode/team-work.sqlite3 list
```

Run a builder-oriented worker pool and cockpit entirely from the terminal:

```bash
sq work worker --id builder-01 --concurrency 4
sq work workers
sq work watch work_...
```

`work worker` is a foreground service intended for a process supervisor. Ctrl+C stops new claims and drains active tasks. `--once` drains currently claimable work for CI; `--max-tasks` caps an ephemeral worker. Worker concurrency is global capacity, while every WorkOrder's `max_workers` budget remains enforced by the atomic scheduler.

The safe delivery sequence is:

```bash
sq work check work_...
sq work prepare work_...
sq work diff work_...
sq work approve work_... --actor maintainer
sq work merge work_... --actor maintainer --cleanup
```

Preparing records the baseline, candidate, reviewed target, expected merged tree, file list, patch digest, and conflicts. Merge refuses to run when the checkout has changed since review.

Set concurrency on creation with `--max-workers`. SuperQode creates a task worktree per attempt and deterministically joins non-overlapping patches into the WorkOrder integration worktree:

```bash
sq work create "Implement the API" \
  --repo . --task-id api --max-workers 2 --draft
sq work add-task work_... "Update the documentation" --task-id docs
sq work queue work_...
sq work run work_...
```

Parallel work requires Git worktree isolation. If two workers change the same file, the first verified patch remains in the integration tree and the other task becomes `blocked`; no patch is silently discarded or overwritten.

Select a behavioral contract with `--role investigator|implementer|synthesizer|reviewer|tester|custom` on `work create` or `work add-task`. Reviewer and other evidence-only roles cannot modify repository files. Reviewers must emit the structured `SUPERQODE_REVIEW` verdict documented in the [WorkOrder guide](../advanced/workorders.md).

Set task-boundary controls when the WorkOrder is created:

```bash
sq work create "Implement the API" \
  --max-cost 2.00 \
  --max-tokens 200000 \
  --max-tool-calls 250 \
  --max-risk medium \
  --queue

sq work usage work_...
sq work policy work_... --phase completion --add-tokens 25000
sq work policy work_... --task primary --risk high
```

`work policy` is read-only. It projects the supplied counters and risk against the saved WorkOrder, prints every denial reason, and does not claim a task or modify evidence.

See [WorkOrders](../advanced/workorders.md) for the lifecycle, scheduler model, and end-to-end examples.
