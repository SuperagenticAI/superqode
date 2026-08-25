# RLM Routes Compared

SuperQode can run several Recursive Language Model routes. They come from the
same research line but make opposite engineering choices. This page explains
what each one actually does so the choice is made on mechanism rather than on
branding.

**Start with [Native RLM](rlm.md).** It is the production route: first-party,
maintained in this repository, with a sandboxed kernel and no external package
to install. The others exist for reasons named below.

| Route | Engine | Where it runs | Selector |
| --- | --- | --- | --- |
| [Native RLM](rlm.md) | Python and PiPy, first-party | Resident Python root; kernel on host, in Docker, or in Monty | `--harness rlm` |
| [RLM Code](rlm-code.md) | Python, separate package | Inside SuperQode | `runtime.backend: rlm-code` |
| [Prime Agent](../providers/prime-agent.md) | TypeScript agent with an IPython kernel | Separate process over Python-hosted RPC; ACP optional | `:prime connect` or `runtime.backend: prime-agent` |
| [Recursive tools](../local-recursive-dynamic-coding.md) | SuperQode agent loop | Inside SuperQode | `context_handle`, `spawn_harness` |

## Which to use

**Native RLM** for coding work. One persistent Python tool, a resident root
worker that owns the complete recursive tree, `context` and `llm_query` for
working over a corpus, goals with completion gates, and a `docker` profile that
runs the interpreter inside a container. Nothing else to install.

**RLM Code** for research and evaluation: paper reproduction, benchmark packs,
LID and generalization metrics, and the trajectory analysis built around them.
It is a separately released package with its own experiment-shaped surface, and
it is the right tool when the run is the artifact.

**Prime Agent** when you specifically want Prime's agent and its ecosystem.

**Recursive tools** when you want recursion inside SuperQode's own loop rather
than a separate harness.

The native route now covers the coding case that RLM Code's agent mode was
reaching toward, so new coding work should start there. RLM Code keeps the
research surface, which the native harness does not attempt to replace.

## Lineage

RLM Code implements the semantics of the Recursive Language Models paper
directly, and adds the locally in-distribution profile from the RLM authors'
harness generalization work. Its center of gravity is the experiment.

Prime Agent is built on the TypeScript `pi` agent and TUI packages. Its
TypeScript host owns providers, sessions, scheduling and child lifecycle, while
an IPython process provides the model-facing control environment. SuperQode can
run Prime through its separate native Python RPC client without changing that
internal architecture.

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

**Native RLM** combines the two useful levels. `llm_query()` and
`llm_query_batched()` are bounded semantic calls over context already held as
data. `rlm.run()` starts a complete child coding session when the work needs a
repository, kernel and conversation of its own. One resident root supervisor
owns every descendant, so depth, child count and concurrency are enforced over
the full tree rather than per process.

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

**Native RLM exposes the repository as `context`.** The root can measure,
select, search and chunk it without placing the corpus in conversation, then
keep subcall answers in Python variables. PiPy compaction remains available for
conversation that does accumulate. This makes offloading a normal programming
operation rather than an evaluation-only profile.

One route prevents context pressure. The other treats it. That difference
explains most of the others.

## Execution safety

The gap here is large and worth stating plainly.

Native RLM offers three profiles. `host` runs Python with the permissions of the
SuperQode process and says so on every activation route. `docker` runs the
persistent interpreter inside a hardened container, so `import os` and every
file the model opens belong to the container, with completion gates running in
the same boundary. `monty` runs it inside a Python interpreter with no
subprocess and no real filesystem, which is why that profile refuses writes and
commands rather than pretending to verify anything.

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

| | Native RLM | RLM Code | Prime Agent |
| --- | --- | --- | --- |
| Coupling | First-party Python/PiPy | Python import | Prime process over native Python RPC; ACP alternative |
| Install | Included with SuperQode | `uv tool install "superqode[rlm-code]"` | Prime installation and provider login |
| Streaming | Live, replayable resident-worker events | Completed trajectory replay | Live RPC or ACP |
| Root lifecycle | Resident Python worker; attach and detach | One experiment run | Resident TypeScript daemon worker |
| Kernel boundary | Host, Docker, or Monty | Runtime selected by research policy | IPython with user OS permissions by default |
| Model-facing tools | One `python` tool | REPL actions defined by the experiment | One `ipython` tool |
| Evidence | Session tree, worker events, child journal, usage and gates | Trajectory and generalization metrics | Session JSONL and daemon state |

The native route implements the coding harness directly. RLM Code remains a
separate research runtime. Prime remains a separate product; the Python RPC
client gives SuperQode a native host without pretending Prime's TypeScript
agent loop is Python.

## Choosing a route

Use **RLM Code** when the run has to be contained and measured: sandboxed
execution, reproducible trajectories, scoring, and generalization checks across
task families or input lengths.

Use **Prime Agent** when you specifically need its continual harness, IPython
skills, schedules, heartbeats or Prime daemon ecosystem.

Use **Native RLM** for long-horizon coding inside SuperQode when you want the
one-tool architecture, a pure-Python host, explicit semantic subcalls and an
optional interpreter security boundary. Its resident root continues after the
TUI detaches and retains one authoritative recursive tree.

Use **recursive tools** when the work belongs inside SuperQode's own loop and
the goal is keeping large artifacts out of the prompt while staying local and
offline.

RLM Code remains the research instrument. Prime Agent and Native RLM are two
product architectures with similar one-tool programming models and different
host/runtime trade-offs.

## An external RLM: Headlong (related, not runnable)

[Headlong](https://headlong.ai) is a fourth project on the same research
line, from the Laude Institute. It is listed in the Hub under
[Ecosystem watch](../harness-hub.md#headlong), not in the table above: it has
no ACP server, MCP server, SDK, or task-runner API, so there is no route
SuperQode can select or run. It belongs here only because the mechanism is
worth naming precisely against the three routes above, the same way this page
names the others.

| | Headlong | Native RLM | RLM Code | Prime Agent |
| --- | --- | --- | --- | --- |
| Engine | Bash (`shellm`) | Python and PiPy, first-party | Python, separate package | TypeScript host with an IPython kernel |
| What recurses | The whole standing agent, via nested `shellm` runs | `llm_query()` for semantic calls; `rlm.run()` for full child sessions | `llm_query()`/`delegate` under a depth and branch budget | `await rlm.run()` spawning live sub-agent sessions |
| A human message | An observation in one thought stream; the agent may not reply | Starts or continues a turn against a resident root | Starts a bounded, scored run | Starts or continues a session |
| State | Single append-only trajectory (`traj`), shared across a team | Session tree per workspace, resident-worker owned | One experiment's trajectory | Session JSONL per agent |
| Memory | Whole-life logarithmic pyramid (`recap`) plus `mem`/`skills` files, projected fresh each turn (`context`) | Repository exposed as `context` data, plus PiPy compaction for conversation | Context held out of the window as a REPL variable; profile-controlled | Continual harness CRUD over prompts, memory, skills, subagents |
| Self-modification | Fork the Headlong repo (and optionally its own trajectory), test, merge | None inside a run; harness `optimize`/`promote` is an outer loop | None inside a run; optimizers and benchmarks are an outer loop | In-session CRUD over its own prompts and skills |
| Sandbox | Docker for generated code by default | `host`, `docker`, or `monty` profile | `monty`, `docker`, `apple_container`, `command`, or `local` via policy | None by default; optional extension |
| Loop | Never idle; a `thinkers` dispatcher keeps generating thoughts with backoff when no one is talking | Turn-based; the resident root just survives a detached TUI | One bounded run, then done | Session-based; daemon persists between prompts |

The distinction that matters is not which engine is closer to the original
RLM definition: Headlong, Native RLM, RLM Code, and Prime Agent all satisfy
the same recursive-call test. It is that Headlong has no session boundary at
all. The other three start a turn, a run, or a session when a human or a
caller asks for one. Headlong's mind is already running, and a message is
one more thing it observes.
