# SuperQode and Omnigent

If you already understand Omnigent, this page maps familiar concepts to
SuperQode, explains where its terminal workflow differs, and shows how the two
configuration formats can work together.

This page is an orientation guide, not a product ranking or feature scorecard.
Both projects make multiple coding-agent harnesses easier to use, but they
organize the work around different primary experiences.

In one sentence: both projects orchestrate coding-agent harnesses. Omnigent
places the persistent collaborative session at the center of its experience,
while SuperQode places terminal-first Agent Engineering, repository delivery,
evaluation, governance, and guarded optimization around that session.

## The shared idea

Omnigent and SuperQode start from several similar beliefs:

- a useful coding agent is more than a model and prompt
- teams should be able to use more than one model or harness
- agent definitions should be portable and inspectable
- sessions, tool activity, policy, and sandbox decisions should be recorded
- terminal users need a first-class workflow
- custom and local agents should fit beside established coding agents

An Omnigent user will therefore recognize many SuperQode concepts: declarative agent configuration, harness and model selection, persistent sessions, child workers, tools, policies, sandboxes, and terminal execution.

## Where the workflows differ

Omnigent centers the persistent session. Its public architecture connects a server, runner hosts, and synchronized terminal, web, mobile, and desktop interfaces. This is valuable when people want to open, share, and steer the same live session from different devices.

SuperQode centers the builder's repository and terminal. A persistent session
supports interactive work, while a WorkOrder adds the lifecycle needed to
deliver and verify repository changes:

```text
HarnessSpec defines how the coding agent works
        ↓
WorkOrder defines what must finish and how it will be accepted
        ↓
workers run isolated tasks and preserve evidence
        ↓
checks, review, and an exact candidate gate delivery
        ↓
evaluation and improvement make the harness better
```

SuperQode does not reproduce Omnigent's full web, mobile, and desktop client
suite. Its primary experience remains the CLI and TUI, with focused
remote-control options for builders who need to step away from the terminal.

## Continue one session across harnesses

SuperQode can change the active harness without discarding the current
SuperQode session. This makes the multi-harness workflow explicit in both the
CLI and TUI:

```text
:harness
:harness switch
:harness switch workbench
:harness switch kimi-coding
```

The first two commands open the interactive Harness Switcher. It marks the
active harness and supports Enter to continue, `F` to fork and switch, `I` to
inspect, `A` to show the complete catalog, and Escape to cancel.

The switch retains the SuperQode session ID and normalized conversation
history. SuperQode updates the active provider, model, and harness binding, then
records the transition in the session evidence. The TUI status bar shows the
active harness after the connection is established.

Use a fork when another harness should explore an independent approach:

```text
:harness switch workbench --fork
```

The fork copies the conversation into a child session before changing the
harness. The original session remains available and can be restored later.

The harness catalog reports one of three continuity levels:

- `exact-resume` means the runtime can resume its existing external thread
- `context-replay` means SuperQode supplies the normalized conversation history
  to the new harness
- `fresh-session` means the adapter cannot guarantee either form of continuity

This distinction prevents a runtime-specific limitation from being presented
as exact thread resumption. SuperQode preserves its own session and transition
history, while vendor-native thread continuity depends on the selected runtime.

The same information is available outside the TUI:

```bash
sq harness list
sq harness current
sq sessions list
sq sessions show SESSION_ID
```

## Concept map for Omnigent users

The following map connects common Omnigent concepts to the corresponding
SuperQode workflow. It describes product shape rather than relative quality.

| Familiar concept | Related SuperQode concept | How it is used in SuperQode |
| --- | --- | --- |
| Agent definition | `HarnessSpec` | Store the harness, model routes, tools, policy, memory, and runtime metadata with the repository |
| Multiple harnesses | Harness catalog and Harness Protocol | Discover built-in, ACP, SDK, local, and imported harnesses through one terminal workflow |
| Session switching | Durable session binding | Switch the harness in the same session, fork an alternative, restore earlier work, and inspect transition lineage |
| Persistent session | Session store and Switchboard graph | Preserve conversation, provider, model, harness, child sessions, handoffs, and transitions |
| Child-agent coordination | Harness workflows, peers, A2A, and WorkOrder workers | Delegate interactive work or schedule dependent repository tasks |
| Policies and sandboxes | Permissions, hooks, route intent, approvals, and budgets | Apply controls to tool use, execution, and delivery decisions |
| Local execution | Local routing, hardware discovery, airplane mode, and local workers | Run local or open models without changing the repository-owned harness contract |
| Remote supervision | Chat channels, local session API, and optional browser TUI | Supervise terminal work without making web or mobile the primary product surface |
| Delivery review | Typed reviews, deterministic checks, verified merge, and rollback | Decide whether an exact repository candidate is ready to accept |
| Harness improvement | Evaluations, failure mining, candidate ledger, and held-out gates | Measure changes and promote an improved harness under explicit controls |

## Why SuperQode added WorkOrders

Interactive sessions are excellent for exploring and steering work. They do not, by themselves, answer all the questions required for reliable repository delivery:

- Which tasks may run now, and which must wait?
- How do we stop two workers from doing the same task?
- What happens when a worker process or laptop crashes?
- Did the reviewer inspect the completed implementation?
- Which exact patch did the human approve?
- Did acceptance tests pass against that patch?
- Can we merge or roll back without overwriting later user changes?

A WorkOrder records these answers.

### Task dependencies are an ordered checklist

The technical term is a DAG, but the user-facing idea is simple:

```text
investigate → implement → review → test
```

A task starts only when its prerequisites have succeeded. Independent tasks can still run in parallel.

### A lease is a timed checkout

When `builder-01` takes the implementation task, SuperQode gives that worker a timed lease. No other worker can take the task while the lease is healthy. Heartbeats renew it while work continues.

### Recovery prevents abandoned tasks

If heartbeats stop because the process, model runtime, CI host, or laptop exited, the lease eventually becomes stale. SuperQode records what happened and returns the task to the queue while retries remain. Work does not remain stuck as `running` forever.

These mechanisms are not additional orchestration for its own sake. They make unattended terminal work safe enough to finish.

Read [WorkOrders](workorders.md#tasks-dependencies-leases-and-recovery-in-plain-language) for the full explanation and examples.

## Remote access SuperQode already provides

SuperQode remains terminal-first, but terminal-first does not mean you must sit in front of one terminal for every minute of a long run.

### Telegram, Slack, and Discord

The channel daemon lets a phone supervise agent sessions running on the SuperQode machine:

```bash
uv tool install "superqode[channels]"
superqode daemon --check
superqode daemon --telegram
```

From an allowlisted chat you can:

- start a prompt and receive progress updates
- approve or deny a waiting tool call
- steer the active run with another message
- inspect status, change model, stop the run, or start a new session

Telegram uses long polling, Slack uses Socket Mode, and Discord uses its Gateway connection. The daemon makes outbound connections and does not open a public inbound HTTP port. Unknown chats receive pairing instructions but cannot run the agent.

This is intentionally a focused remote control, not a second full product UI. Channel sessions are regular SuperQode sessions, but the current bot commands do not reproduce the complete `sq work watch` WorkOrder cockpit.

See [Chat Channels: Remote Control](channels.md) for setup, allowlists, commands, and security.

### Local session API

The open CLI includes a small JSON API for session graph and Software Factory companions:

```bash
sq serve api
```

It exposes health, session lists and history, the Switchboard graph, handoffs, factory routes, and model or harness lineage operations. It binds to `127.0.0.1` by default.

A trusted private-network companion can be enabled explicitly:

```bash
sq serve api \
  --host 0.0.0.0 \
  --allow-remote \
  --token "$SUPERQODE_API_TOKEN"
```

This is an API for a companion client, not a bundled Omnigent-style mobile application. Do not expose the plain HTTP server directly to the public internet; use a trusted network and token, or place a properly authenticated TLS proxy in front of it.

### Browser TUI

The Enterprise server package includes an authenticated browser rendering of the SuperQode TUI:

```bash
sq serve web
sq serve web --host 0.0.0.0 --allow-remote --no-open
```

Remote binding requires explicit opt-in and authentication. This gives a browser or phone a terminal-like SuperQode surface. It is not positioned as a synchronized multi-user collaboration suite, and it does not change the CLI/TUI-first product direction.

See [Serve Commands](../cli-reference/serve-commands.md) for availability and security options.

## Use an Omnigent agent definition in SuperQode

SuperQode can import an Omnigent agent without attempting to emulate the Omnigent server:

```bash
sq harness import-omnigent path/to/agent.yaml --output harness.yaml
sq harness validate --spec harness.yaml
sq harness doctor --spec harness.yaml
sq harness run --spec harness.yaml --prompt "inspect this repository"
```

The importer maps common harnesses, models, prompts, tools, MCP servers, child agents, skills, and sandbox fields. Omnigent-only fields are preserved in metadata rather than silently discarded.

The resulting HarnessSpec can then use SuperQode's WorkOrders and evaluation:

```bash
sq work create "Deliver the requested change" \
  --repo . --harness harness.yaml \
  --acceptance-test "uv run pytest -q" \
  --queue

sq work worker work_... --id builder-01 --once
sq work watch work_...

sq harness eval --spec harness.yaml --tasks evals/tasks.yaml --live
```

See [Omnigent Compatibility](omnigent-compat.md) for exact field mapping.

## How the workflows can be used together

Omnigent agent definitions can remain the authoring or collaboration format,
then be imported into a SuperQode repository when the work needs WorkOrder
delivery, evaluation, or optimization.

SuperQode can also be used independently when the primary requirements are a
repository-owned harness, terminal execution, local or open model depth,
durable repository delivery, explicit evidence, and controlled harness
improvement.

This interoperability does not require SuperQode to emulate the Omnigent server
or client suite. It treats the imported definition as an input to SuperQode's
Agent Engineering workflow.

## A concise public description

> SuperQode shares Omnigent's multi-harness foundation and provides a distinct
> terminal-first Agent Engineering workflow. Sessions can continue across
> harnesses, branch into independent approaches, and feed repository-owned
> WorkOrders, evaluation, governance, and guarded optimization.

## Official Omnigent references

- [Terminal](https://omnigent.ai/docs/interact/terminal)
- [Custom Agents](https://omnigent.ai/docs/use/custom-agents)
- [Shared Server and architecture](https://omnigent.ai/docs/deploy/overview)
- [Mobile](https://omnigent.ai/docs/interact/mobile)
- [Desktop App](https://omnigent.ai/docs/interact/desktop)
- [Omnigent on Databricks](https://docs.databricks.com/aws/en/omnigent/)
