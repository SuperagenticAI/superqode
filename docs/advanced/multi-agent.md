# Multi-Agent Workflows

SuperQode supports three multi-agent mechanisms: **sub-agents** for isolated tasks, **peer agents** for persistent addressable workers, and **A2A** for external agents that implement the Agent-to-Agent protocol. This page describes the execution and coordination behavior of each mechanism.

## Sub-agents

The `sub_agent` tool starts an isolated child loop for one task and returns one result. The child receives a separate conversation, can receive a restricted tool list, and has a maximum delegation depth of 3. Use it for self-contained tasks whose intermediate steps are not required by the parent.

`task_coordinator` builds on it for splitting a goal into parallel one-shot subtasks.

## Peer agents

Peer agents stay alive across the parent's turns, keep their own context, and are addressable by name. Five tools, available in the `full` tool profile:

| Tool | Behavior |
|---|---|
| `spawn_agent(task_name, message)` | Start a peer working immediately. Names normalize to `lowercase_underscores`; duplicates get `_2` suffixes. Max 8 live peers. |
| `send_input(agent, message, interrupt=false)` | Message a peer by id or name. **If it's busy, the message steers its live run**: it lands between the peer's tool calls. `interrupt=true` cancels its current work and redirects it. If idle, the message starts its next run. |
| `wait_agent(agent, timeout_s=60)` | Block until the peer goes idle and return its latest result. On timeout you get `status: running` back, so do other work and wait again. |
| `list_agents()` | ids, names, statuses, queued inputs, last-result previews. |
| `close_agent(agent)` | Shut a peer down. All peers are closed when the parent exits. |

A typical model-directed exchange:

```text
spawn_agent(task_name="fix_tests",  message="make the failing date tests pass")
spawn_agent(task_name="update_docs", message="document the new CLI flags")
...parent keeps working on its own piece...
wait_agent(agent="fix_tests")        → "All 12 tests pass. Root cause was..."
send_input(agent="fix_tests", message="also add a regression test for DST")
wait_agent(agent="fix_tests")
close_agent(agent="fix_tests")
```

Design guarantees:

- **One level deep.** Peers and sub-agents cannot spawn peers, which keeps the hierarchy bounded.
- **Crash isolation.** An unhandled peer error produces `status: error` and does not terminate the parent.
- **Same policies.** Peers inherit the parent's gateway, tool registry, permission manager, and sandbox: there is no privilege escalation by delegation.
- **In-run steering.** `send_input` to a busy peer uses the same steering mechanism as TUI input submitted during a run.

## A2A: external agents

`a2a_discover` and `a2a_call` reach agents that speak Google's Agent-to-Agent protocol, including other SuperQode instances serving a harness through the A2A server API. Combine freely: a parent can hold local peers *and* call remote A2A agents in the same run. See [A2A Providers](../providers/a2a.md) for serving and calling details.

## Quality control: rubric self-grading

For long or unattended multi-agent runs, a [rubric](agent-loop.md#12-rubric-self-grading) defines completion criteria:

```bash
superqode -p \
  --rubric "Each subtask result is verified, the test suite passes, and the final summary lists every file changed." \
  "split this refactor across agents and execute it"
```

The grader reviews the *parent's* final answer; revision feedback re-enters the parent loop, which can re-dispatch peers as needed.

## Choosing the right mechanism

| Requirement | Mechanism |
|---|---|
| Low-overhead execution of a self-contained task | `sub_agent` |
| Persistent parallel workstreams | peer agents |
| Redirection of an active worker | `send_input(interrupt=true)` |
| A capability provided by an external process or product | A2A |
| unattended quality enforcement | `--rubric` |
