# How SuperQode Relates to Omnigent

If you already understand Omnigent, this page explains which ideas are shared, where SuperQode takes a different approach, and how the two formats can work together.

This is not a claim that one product should reproduce every feature of the other. Both products make multiple coding-agent harnesses easier to use, but they optimize for different working styles.

In one sentence: both products orchestrate multiple coding-agent harnesses, while SuperQode extends that foundation into a terminal-first Software Factory with durable WorkOrders, evaluation, governance, and guarded optimization. Omnigent places greater emphasis on persistent collaborative sessions across terminal, web, mobile, and desktop clients.

## The shared idea

Omnigent and SuperQode start from several similar beliefs:

- a useful coding agent is more than a model and prompt
- teams should be able to use more than one model or harness
- agent definitions should be portable and inspectable
- sessions, tool activity, policy, and sandbox decisions should be recorded
- terminal users need a first-class workflow
- custom and local agents should fit beside established coding agents

An Omnigent user will therefore recognize many SuperQode concepts: declarative agent configuration, harness and model selection, persistent sessions, child workers, tools, policies, sandboxes, and terminal execution.

## The main difference in emphasis

Omnigent centers the persistent session. Its public architecture connects a server, runner hosts, and synchronized terminal, web, mobile, and desktop interfaces. This is valuable when people want to open, share, and steer the same live session from different devices.

SuperQode centers the builder's repository and terminal:

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

SuperQode does not reproduce Omnigent's full web, mobile, and desktop client suite. Its primary experience remains the CLI and TUI, with focused remote-control options for builders who need to step away from the terminal.

## Similar concepts, different implementations

| Need | Omnigent approach | SuperQode approach |
| --- | --- | --- |
| Define an agent | Concise Omnigent YAML | Repo-owned `HarnessSpec`, templates, wizard, and agent import |
| Use different harnesses | Common session layer over built-in and custom harnesses | Harness Protocol and runtime adapters behind the same spec and event contracts |
| Change models or harnesses | Runtime overrides and session switching | Factory routes, switches, forks, task-specific harnesses, and recorded lineage |
| Keep work persistent | The persistent conversation is the central unit | Persistent sessions for conversation plus WorkOrders for repository delivery |
| Coordinate multiple agents | Built-in multi-AI and child-agent session coordination | Harness workflows, peer agents, A2A, Switchboard, and WorkOrder task dependencies |
| Apply guardrails | Contextual policies, server enforcement, and sandboxes | Tool permissions, hooks, sandbox rules, route intent, approvals, and WorkOrder budgets |
| Work locally | Local runner hosts and local model endpoints | Local-first harnesses, hardware discovery, local routing, airplane mode, and local workers |
| Access work remotely | Shared server with terminal, web, mobile, and desktop clients | Chat-channel remote control, local companion API, and an optional browser TUI |
| Decide whether work is ready | Session review, policies, quality protocols, and diffs | Typed reviews, deterministic checks, content-addressed approval, verified merge, and rollback |
| Improve agent behavior | Agent and meta-harness evolution in the Omnigent ecosystem | Eval scorecards, failure mining, candidate ledger, held-out gates, and guarded optimization |

The table describes product shape, not a scorecard. A team may prefer either approach or use the Omnigent configuration format as input to a SuperQode delivery and evaluation workflow.

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

## Which approach fits which workflow?

Choose Omnigent's style when the central need is a persistent shared session that moves fluidly across terminal, browser, phone, desktop, and collaborators.

Choose SuperQode's style when the central need is a repository-owned harness, terminal execution, local/open model depth, durable repository delivery, explicit evidence, and safe harness improvement.

Use both formats when Omnigent agent definitions are useful inputs but SuperQode's WorkOrder, evaluation, or optimization loop is the desired execution and proof layer.

## A concise public description

> SuperQode and Omnigent both orchestrate multiple coding-agent harnesses. Omnigent centers the persistent collaborative session across devices. SuperQode is a terminal-first Software Factory centered on repository-owned harnesses, reliable WorkOrders, evidence-backed delivery, governance, and guarded optimization.

## Official Omnigent references

- [Terminal](https://omnigent.ai/docs/interact/terminal)
- [Custom Agents](https://omnigent.ai/docs/use/custom-agents)
- [Shared Server and architecture](https://omnigent.ai/docs/deploy/overview)
- [Mobile](https://omnigent.ai/docs/interact/mobile)
- [Desktop App](https://omnigent.ai/docs/interact/desktop)
- [Omnigent on Databricks](https://docs.databricks.com/aws/en/omnigent/)
