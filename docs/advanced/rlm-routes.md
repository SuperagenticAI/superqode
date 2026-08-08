# RLM Routes Compared

SuperQode can run three Recursive Language Model routes. They come from the
same research line but make opposite engineering choices, and none replaces
another. This page explains what each one actually does so the choice is made
on mechanism rather than on branding.

| Route | Engine | Where it runs | Selector |
| --- | --- | --- | --- |
| [RLM Code](rlm-code.md) | Python, in process | Inside SuperQode | `runtime.backend: rlm-code` |
| [Prime Agent](../providers/prime-agent.md) | TypeScript agent with an IPython kernel | Separate process over Python-hosted RPC; ACP optional | `:prime connect` or `runtime.backend: prime-agent` |
| [Recursive tools](../local-recursive-dynamic-coding.md) | SuperQode agent loop | Inside SuperQode | `context_handle`, `spawn_harness` |

## Lineage

RLM Code implements the semantics of the Recursive Language Models paper
directly, and adds the locally in-distribution profile from the RLM authors'
harness generalization work. Its center of gravity is the experiment.

Prime Agent is a hard fork of the `pi` coding agent with an RLM runtime grafted
on. Its center of gravity is the product. The Python package it ships,
`prime-agent-runtime`, is a kernel-side client of roughly 1,500 lines; the agent
itself is TypeScript. SuperQode's native Python RPC client now owns the host
process, correlation, event stream and lifecycle, while Prime retains the agent
loop and tools.

## What recursion means in each

The word "recursion" describes two different mechanisms.

**RLM Code** recurses synchronously and inside a budget. Code running in the
REPL calls `llm_query()` or `llm_query_batched()` for sub-model calls, capped by
`max_llm_calls`. For full child runs it emits a `delegate` or `delegate_batch`
action, and the runner executes children in a thread pool bounded by
`max_depth`, `branch_width`, `max_children_per_step` and `parallelism`.

Exceeding the depth guard does not raise. It returns an observation with a
negative reward, because in RLM Code a budget is a scoring signal rather than an
error path.

**Prime Agent** recurses asynchronously and live. `await rlm.run(prompt)`
returns a spawn handle as soon as the child is admitted, not when it answers:

```text
rlm_child_id, name, session_dir, model
```

Children are complete agent sessions in Prime's daemon. They are addressable
and disposable through `list_subagents()` and `delete_subagent()`, and they
report back through agent messages after the spawning turn has ended. Depth is
a layered runtime setting that can change during a session rather than a fixed
run parameter.

RLM Code recursion is a bounded, scored computation. Prime Agent recursion is
process orchestration.

## What each does with context

This is the deepest split, and it is a genuine disagreement about the problem.

**RLM Code keeps context out of the model window.** The payload lives as a REPL
variable and the root model sees metadata about it. Profiles select how strict
that is:

| Profile | Root observation | History policy | Decomposition hint |
| --- | --- | --- | --- |
| `reference` | configured | full | no |
| `repo_evidence` | metadata | structural | yes |
| `lid` | opaque | offload | yes |

Under `lid` the root model receives opaque, constant-shape observations, and
root history is offloaded into `history_N` variables as it grows. The root is
deliberately prevented from accumulating context at all.

**Prime Agent admits context and then manages the overflow.** Conversation
enters the window normally, and compaction summarizes older content once a
threshold is crossed, with branch summarization for side work.

One route prevents context pressure. The other treats it. That difference
explains most of the others.

## Execution safety

The gap here is large and worth stating plainly.

RLM Code selects a sandbox runtime through a policy layer over `monty`,
`docker`, `apple_container`, `command` and `local` backends. The `monty`
runtime uses a Python interpreter written in Rust with no filesystem, no
network, no imports and no `eval` or `exec`, with time, memory and allocation
caps enforced by the virtual machine, and execution state that can be frozen to
bytes and resumed.

That design puts the recursion boundary and the sandbox boundary in the same
place: `llm_query` and `FINAL` are external functions, so the interpreter pauses
and yields control to the host whenever the model reaches outside its own
computation.

Prime Agent has no sandbox by default. Its IPython kernel runs with the
permissions of the user who launched it, and it sends no ACP permission
requests, so approval prompts never appear. An optional sandbox extension and
Prime Intellect's cloud sandboxes exist, but neither is the default.

Treat a Prime Agent session as equivalent to running Python and shell commands
yourself. For untrusted repositories, isolate the process externally.

## Self-modification

Prime Agent carries a continual harness: a CRUD store over prompts, memory,
skills and subagents, with versioned entries, `local` or `global` scope, and
recorded refinement events that capture trigger, changes, evidence and outcome.
Skill entries must resolve to a real Python import and callable before they are
accepted. The agent edits this state during a session.

RLM Code never modifies itself inside a run. Improvement happens in an outer
loop through optimizers, benchmarks and a leaderboard.

This is the difference with the most governance weight. One route rewrites its
own operating instructions while working; the other cannot.

## What each is instrumented to answer

RLM Code ships reward profiles that score each action on a clamped scale, and
trajectory similarity metrics built for harness generalization: normalized
Levenshtein distance, trigram containment, trigram Jaccard, weighted trigram
Jaccard and length ratio. Those exist to compare a harness against itself across
task families and input lengths.

Prime Agent ships session JSONL, session statistics and published benchmark
results, without trajectory-similarity instrumentation.

RLM Code is built to answer whether a harness generalized. Prime Agent is built
to answer what happened in a session.

## Integration shape inside SuperQode

| | RLM Code | Prime Agent |
| --- | --- | --- |
| Coupling | Python import, in process | Subprocess over ACP |
| Install | `uv tool install "superqode[rlm-code]"` | `install.sh`, then `/login` |
| Streaming | No, events are replayed from a completed trajectory | Yes, live over ACP |
| Sandbox | Docker by default | None |
| Model selection | HarnessSpec `model_policy` | Launch flags, reconnect |
| Approvals | HarnessSpec policy | None sent by the agent |
| Evidence | Trajectory, generalization metrics, validation events | Session JSONL |
| Token accounting | Reported | Not reported over ACP |

Because RLM Code is imported, SuperQode translates a `HarnessSpec` into a runner
request and normalizes the resulting trajectory. Because Prime Agent is a
process speaking a protocol SuperQode already implements, it needs no
translation layer at all.

## Choosing a route

Use **RLM Code** when the run has to be contained and measured: sandboxed
execution, reproducible trajectories, scoring, and generalization checks across
task families or input lengths.

Use **Prime Agent** when the run has to keep going: long-horizon coding, live
sub-agents, autonomous gates, and session continuity across hours.

Use **recursive tools** when the work belongs inside SuperQode's own loop and
the goal is keeping large artifacts out of the prompt while staying local and
offline.

A useful way to hold the three: RLM Code is the instrument, Prime Agent is the
engine, and the recursive tools are the local workbench.
