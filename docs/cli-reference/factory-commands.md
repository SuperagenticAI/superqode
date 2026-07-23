# Factory Commands

`superqode factory` manages model, harness, and route lineage within a SuperQode code factory.

This command group is the routing and lineage module, not the entire code factory. Harness authoring, WorkOrders, headless workers, delivery gates, evaluation, and optimization have their own command groups. Start with [Building a Code Factory with SuperQode](../advanced/software-factory.md) for the complete product model and builder walkthrough.

The factory layer does not replace sessions. It annotates the durable session graph so work can move
between local OSS models, BYOK models, proprietary runtimes, and different harnesses without losing
history.

## factory status

Show factory metadata for the active or selected session.

```bash
superqode factory status [SESSION_ID] [--json]
```

## factory routes

List built-in route presets.

```bash
superqode factory routes [--json]
```

Routes include `private`, `local`, `cheap`, `best`, `review`, `long-context`, and
`no-subscription`.

## factory init-policy

Create `.superqode/factory.yaml` with local-first defaults.

```bash
superqode factory init-policy
superqode factory init-policy --force
```

## factory policy

Show the project policy path and merged policy.

```bash
superqode factory policy
superqode factory policy --json
```

## factory resolve-route

Resolve a route through built-in defaults plus `.superqode/factory.yaml`.

```bash
superqode factory resolve-route no-subscription
superqode factory resolve-route review --json
```

## factory mode

Set the factory route/mode for a session.

```bash
superqode factory mode no-subscription [SESSION_ID]
superqode factory mode private [SESSION_ID]
superqode factory mode best [SESSION_ID]
```

Use `--reason` to record why the mode changed.

## factory switch-model

Record that a session moved to another model/provider/runtime.

```bash
superqode factory switch-model ollama/qwen3-coder [SESSION_ID]
superqode factory switch-model byok/openai/gpt-5 [SESSION_ID]
```

Options:

| Option | Description |
|--------|-------------|
| `--runtime` | Runtime/backend label |
| `--reason` | Why this model was selected |
| `--json` | Emit JSON |

## factory switch-harness

Record that a session moved to another harness.

```bash
superqode factory switch-harness coding [SESSION_ID]
superqode factory switch-harness review [SESSION_ID]
```

## factory fork-model

Fork a session to a worker tagged with a different model/provider.

```bash
superqode factory fork-model [SOURCE_SESSION_ID] --model local/deepseek-coder --role coder
```

Options:

| Option | Description |
|--------|-------------|
| `--model` | Provider/model reference |
| `--role` | Factory worker role |
| `--session-id` | New fork session id |
| `--title` | Fork title |
| `--goal` | Handoff goal appended to the fork |

## factory fork-harness

Fork a session to a worker tagged with a different harness.

```bash
superqode factory fork-harness [SOURCE_SESSION_ID] --harness review --role reviewer
```

## factory lineage

Show recorded factory events for a session.

```bash
superqode factory lineage [SESSION_ID] [--json]
```

Events include mode changes, model switches, and harness switches.

## Current Behavior

Factory commands record durable intent and lineage. The active session graph records
`factory.next_turn`, which runtime and picker flows can consume safely on the next turn.

Continue with [WorkOrder Commands](work-commands.md) when work needs a durable task graph, worker leases, isolated delivery, checks, review, and a final merge decision.
