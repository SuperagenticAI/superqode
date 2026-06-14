# Omnigent Compatibility

SuperQode can import Omnigent agent specs without making Omnigent the host runtime.

This is a SuperQode-first compatibility path: take useful Omnigent `agent.yaml`
definitions and convert them into the portable SuperQode `HarnessSpec` shape.
The resulting `harness.yaml` runs through SuperQode's CLI, TUI, runtime backends,
event store, sandbox policy, checks, and workflow tooling.

## When To Use This

Use the importer when:

- you have an Omnigent `agent.yaml` and want to run the equivalent workflow in SuperQode
- you want to evaluate Omnigent examples without adopting Omnigent's server model
- you want a committed `harness.yaml` that your team can inspect, edit, validate, and run
- you want SuperQode to remain the controlling harness while borrowing compatible spec ideas

Do not use this path when you specifically want Omnigent's live web session server,
host registration, or managed host workflow. Those are separate runtime/server concerns.

## Import An Agent

```bash
superqode harness import-omnigent path/to/agent.yaml --output harness.yaml
superqode harness validate --spec harness.yaml
superqode harness doctor --spec harness.yaml
superqode harness run --spec harness.yaml --prompt "summarize this repository"
```

Use `--name` to override the generated harness name:

```bash
superqode harness import-omnigent examples/polly/agent.yaml \
  --name polly-superqode \
  --output polly-harness.yaml
```

Use `--force` only when you intentionally want to replace an existing output file.

## Field Mapping

| Omnigent field | SuperQode target |
| --- | --- |
| `name` | `HarnessSpec.name` and primary agent id |
| `prompt` | primary `AgentSpec.system_prompt` |
| `instructions: AGENTS.md` | `ContextSpec.instruction_files` |
| `executor.harness` | `RuntimeSpec.backend` |
| `executor.model` | `ModelPolicySpec.primary` |
| `executor.auth` | `ModelPolicySpec.config.auth` |
| non-agent `tools` | primary agent tool names and preserved tool metadata |
| `tools.<name>.type: agent` | child `AgentSpec` with orchestrator workflow |
| `os_env.sandbox` | `ExecutionPolicySpec` read/write/shell/network settings |
| `policies`, `params`, `terminals`, timers | preserved in `metadata.omnigent` |

The importer preserves Omnigent-only fields in metadata instead of silently
discarding them. This keeps the generated spec runnable today while leaving a
clear upgrade path as SuperQode grows native equivalents.

## Harness Name Mapping

Common Omnigent harness names are mapped to SuperQode runtime backend names:

| Omnigent harness | SuperQode runtime |
| --- | --- |
| `claude-sdk` | `claude-agent-sdk` |
| `openai-agents` | `openai-agents` |
| `codex` | `codex-sdk` |
| `codex-native` | `codex-sdk` |
| `claude-native` | `claude-agent-sdk` |
| `pi` | `runtime` |

Unknown harness names are preserved as backend names so custom integrations can
still be inspected and adapted.

## What SuperQode Should Borrow Next

The importer is the low-risk compatibility layer. The higher-value ideas to
bring into SuperQode natively are:

- **Layered policies**: session, harness, and admin policy levels with
  `allow`, `deny`, and `ask` verdicts.
- **Policy phases**: evaluate request, response, tool call, tool result,
  shell, and file mutation events consistently across runtimes.
- **Live session coordination**: browser attach, fork, co-drive, comments, and
  terminal/resource streams as a SuperQode server feature.
- **Agent spec ergonomics**: keep concise YAML authoring while compiling into
  SuperQode's richer `HarnessSpec`.

Those are product and architecture ideas to adopt directly in SuperQode, not a
reason to make Omnigent the controlling runtime.

