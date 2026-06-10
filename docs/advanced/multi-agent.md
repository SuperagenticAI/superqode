# Multi-Agent Workflows

SuperQode has three ways to put more than one agent on a problem, from cheapest to most powerful: **sub-agents** (one task, one result), **peer agents** (long-lived, addressable coworkers), and **A2A** (external agents over the Agent-to-Agent protocol). This page shows when to reach for each and exactly how they behave.

## Sub-agents: fire-and-forget delegation

The `sub_agent` tool spawns an isolated child loop for one task and returns its single result. The child gets its own conversation (the parent's context is not consumed), optionally a restricted tool list, and a maximum delegation depth of 3. Use it for "go figure X out and tell me the answer": open-ended exploration whose intermediate steps the parent doesn't need.

`task_coordinator` builds on it for splitting a goal into parallel one-shot subtasks.

## Peer agents: coworkers you can talk to

Peer agents stay alive across the parent's turns, keep their own context, and are addressable by name. Five tools, available in the `full` tool profile:

| Tool | Behavior |
|---|---|
| `spawn_agent(task_name, message)` | Start a peer working immediately. Names normalize to `lowercase_underscores`; duplicates get `_2` suffixes. Max 8 live peers. |
| `send_input(agent, message, interrupt=false)` | Message a peer by id or name. **If it's busy, the message steers its live run**: it lands between the peer's tool calls. `interrupt=true` cancels its current work and redirects it. If idle, the message starts its next run. |
| `wait_agent(agent, timeout_s=60)` | Block until the peer goes idle and return its latest result. On timeout you get `status: running` back, so do other work and wait again. |
| `list_agents()` | ids, names, statuses, queued inputs, last-result previews. |
| `close_agent(agent)` | Shut a peer down. All peers are closed when the parent exits. |

A typical exchange the model drives on its own:

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

- **One level deep.** Peers cannot spawn peers (or sub-agents spawn peers): the hierarchy stays comprehensible and bounded.
- **Crash isolation.** A peer that throws becomes `status: error` with the message as its result; the parent is never taken down.
- **Same policies.** Peers inherit the parent's gateway, tool registry, permission manager, and sandbox: there is no privilege escalation by delegation.
- **Steering, not polling.** `send_input` to a busy peer reuses the same in-run steering mechanism you get when typing into the TUI mid-run.

## A2A: external agents

`a2a_discover` and `a2a_call` reach agents that speak Google's Agent-to-Agent protocol, including other SuperQode instances serving a harness through the A2A server API. Combine freely: a parent can hold local peers *and* call remote A2A agents in the same run. See [A2A Providers](../providers/a2a.md) for serving and calling details.

## Quality control: rubric self-grading

Multi-agent runs are usually long and unattended, which is exactly where a [rubric](agent-loop.md#12-rubric-self-grading) earns its keep:

```bash
superqode -p \
  --rubric "Each subtask result is verified, the test suite passes, and the final summary lists every file changed." \
  "split this refactor across agents and execute it"
```

The grader reviews the *parent's* final answer; revision feedback re-enters the parent loop, which can re-dispatch peers as needed.

## Choosing the right mechanism

| You want... | Use |
|---|---|
| an answer to a self-contained question, cheaply | `sub_agent` |
| parallel workstreams you'll follow up on | peer agents |
| to redirect a worker that's going down the wrong path | `send_input(interrupt=true)` |
| capability that lives in another product/process | A2A |
| unattended quality enforcement | `--rubric` |
