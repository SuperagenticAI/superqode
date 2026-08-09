# Native RLM Harness

SuperQode's `rlm` harness gives the coding model one executable tool: a
persistent Python environment. The model writes Python to inspect the
repository, select context, edit files and run commands. It does not receive
separate `read`, `grep`, `edit` or `bash` tools.

Start it directly:

```bash
superqode --harness rlm
```

Or switch from the TUI:

```text
:harness switch rlm
```

The model-facing tool list contains only `python`. The persistent namespace
includes these objects:

```python
matches = workspace.search("authenticate", "src")
source = workspace.read("src/auth.py")
workspace.edit("src/auth.py", "old", "new")

result = shell.run(["uv", "run", "pytest", "tests/auth"])
result.ok
```

Start child RLM sessions from the same Python environment:

```python
children = rlm.run_batch([
    "Inspect the implementation and identify the likely defect",
    "Inspect the tests and reproduce the failure",
])

children[0].send("Pay particular attention to session recovery")
results = rlm.wait_all(children)
```

Every child receives the same single persistent `python` tool. Child records
carry stable IDs, parent ancestry, status and results. Handles support
`status()`, `send()`, `steer()`, `wait()`, `cancel()` and `delete()`.

The TUI streams child start and result events and provides an initial command
surface:

```text
:rlm session
:rlm agents
:rlm send <agent-id> <message>
:rlm steer <agent-id> <instruction>
:rlm cancel <agent-id>
```

## Goals and completion gates

A goal can remain attached to the RLM session across multiple prompts:

```text
:rlm goal Ship the authentication fix without changing the public API
:rlm policy
```

Autonomous completion gates are host commands that must pass after the model
finishes. Add one or more gates before starting the task:

```text
:rlm autonomous "uv run pytest -q"
:rlm autonomous "uv run ruff check ."
```

If a gate fails, its exit status and bounded output are returned to the same
RLM session for another turn. The default limit is three rounds. Gate activity
is streamed as `autonomous_gates_start` and `autonomous_gates_result` evidence
and appears in the TUI as an `rlm.gates` host-operation card. It does not add a
second model-facing tool; the coding model still receives only `python`.

Clear autonomous mode and its gates with:

```text
:rlm autonomous off
```

HarnessSpec users can configure `goal`, `autonomous`, `gates`,
`autonomous_max_rounds`, and `gate_timeout` under `runtime.config`. The goal and
policy are persisted beside the session in `.policy.json`.

Variables and imports survive subsequent Python calls in the same running
session:

```python
failures = shell.run(["uv", "run", "pytest", "-q"]).stdout
```

Later:

```python
[line for line in failures.splitlines() if "auth" in line.lower()]
```

## Current runtime boundary

The initial RLM kernel runs Python with the permissions of the SuperQode
process. Python can import `os`, use `subprocess`, read environment variables
and access anything available to that process. The harness picker shows this
warning before activation, and unattended execution requires the same explicit
pure-permissions opt-in used by other host-executing harnesses.

Run the harness inside a container or another external isolation boundary when
working with untrusted prompts or repositories. Per-operation approval cannot
secure unrestricted host Python because Python code can bypass wrapper APIs.

## Sessions

RLM sessions are separate from Core, Workbench, PiPy, RLM Code and Prime Agent:

```text
~/.superqode/rlm/sessions/<workspace>/<session>.jsonl
```

The conversation and Python tool results are stored in the session tree. Child
status, ancestry and completed results are recorded beside the root session in
an `.agents.jsonl` journal. SuperQode restores those records when it resumes a
session. A child that was still queued or running when the process stopped is
reported as `interrupted`; it is never presented as successfully completed.

The Python namespace remains exact while the SuperQode process is running.
After every successful Python call, SuperQode also checkpoints each
serializable user variable independently to `.kernel.pkl`. On restart it
restores the values it can deserialize while rebuilding the host-owned
`workspace`, `shell` and `rlm` objects. Modules, open files, locks, live agent
handles and other process-bound values are skipped without preventing simpler
state from recovering. The checkpoint is trusted local runtime state and should
not be copied from an untrusted source.

With the normal provider gateway, each child is launched as a detached Python
worker. Its request, control stream, log and atomic result live in a
session-owned worker directory. Closing the TUI does not terminate that worker.
When the session is reopened, the supervisor verifies the journaled worker PID
against its request identity and reattaches to the result file. Follow-up,
steering and cancellation commands travel through the worker's control JSONL.

Injected/custom stream functions, including deterministic test transports, run
children in-process because an arbitrary Python callback cannot be transferred
to another interpreter. If an in-process child is active during restart it is
reported as `interrupted`. Set `runtime.config.durable_children: false` to use
that behavior explicitly.

Relocate RLM state with:

```bash
export SUPERQODE_RLM_DIR=/path/to/rlm-state
export SUPERQODE_RLM_SESSION_DIR=/path/to/rlm-sessions
```

## Other RLM routes

`rlm` is the built-in SuperQode harness. It has no Prime Agent, TypeScript or
RLM Code dependency.

- `rlm-code` runs the separately installed RLM Code package and preserves its
  research trajectories and configured recursion policies.
- `prime-agent` keeps the existing Prime Agent Python RPC integration.
- `pipy` is the native Python Pi-style harness with four default model tools.

These routes keep independent sessions and can remain installed together.
