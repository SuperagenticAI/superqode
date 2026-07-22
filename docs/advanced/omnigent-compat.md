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
| `executor.auth` | `ModelPolicySpec.config.auth` and Databricks profile |
| legacy `executor.profile` | `ModelPolicySpec.profile` and preserved config |
| non-agent `tools` | primary agent tool names and preserved tool metadata |
| `tools.<name>.type: mcp` | runtime/agent `mcp_servers` config, exposed as harness-local MCP tools |
| `tools.<name>.type: agent` | child `AgentSpec`, orchestrator workflow, builtin `agent_session` target, and parent-routed child approvals |
| child `executor`, `skills`, `tools`, `instructions`, `os_env` | preserved on the child `AgentSpec`, including inherited tool names and child MCP servers |
| child `output_schema`, `policies`, `params`, timers | preserved in child `AgentSpec.config.omnigent` |
| `skills: [name, ...]` | primary `AgentSpec.skills` and preserved skill filter |
| `skills: all` / `none` | preserved as the Omnigent skill filter |
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
| `open-responses` | `openai-agents` |
| `codex` | `codex-sdk` |
| `codex-native` | `codex-sdk` |
| `claude-native` | `claude-agent-sdk` |
| `pi` | `runtime` |

Unknown harness names are preserved as backend names so custom integrations can
still be inspected and adapted.

## Interop boundary

The importer is a format and execution bridge, not an emulator for Omnigent's server, synchronized clients, collaboration permissions, or managed runner hosts.

SuperQode compiles compatible agent structure into its richer `HarnessSpec`, preserves unsupported Omnigent fields in metadata, and then owns execution through its runtimes, events, WorkOrders, evaluation, contextual policy, credential-safe tools, HarnessBench, and guarded promotion. Reproducing Omnigent's web, mobile, and desktop suite is not the terminal-first product priority.

See [How SuperQode Relates to Omnigent](superqode-vs-omnigent.md) for the ideas the products share, their different priorities, SuperQode's existing remote-access options, and when the import path is useful.
