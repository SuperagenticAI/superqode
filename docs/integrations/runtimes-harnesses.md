---
title: Runtimes and Harnesses
description: Install agent framework runtimes and compatibility adapters.
---

# Runtimes and harnesses

Runtime adapters execute a `HarnessSpec` through another agent framework while
preserving the SuperQode contract and normalized evidence where the adapter
supports it.

| Runtime | Optional dependency | Select or run | Verify | Detailed guide |
| --- | --- | --- | --- | --- |
| Google Agent Development Kit | `uv tool install "superqode[adk]"` | `runtime.backend: adk` | `superqode runtime doctor adk` | [Python Runtimes](../advanced/python-runtimes.md) |
| OpenAI Agents SDK | `uv tool install "superqode[openai-agents]"` | `runtime.backend: openai-agents` | `superqode runtime doctor openai-agents` | [Python Runtimes](../advanced/python-runtimes.md) |
| PydanticAI | `uv tool install "superqode[pydanticai]"` | `runtime.backend: pydanticai` | `superqode runtime doctor pydanticai` | [Python Runtimes](../advanced/python-runtimes.md) |
| PydanticAI with Logfire | `uv tool install "superqode[pydanticai-logfire]"` | Enable PydanticAI tracing in the HarnessSpec | `superqode runtime doctor pydanticai` | [Agent Runtimes](../runtimes.md#pydanticai) |
| DeepAgents | `uv tool install "superqode[deepagents]"` | `runtime.backend: deepagents` | `superqode runtime doctor deepagents` | [Agent Runtimes](../runtimes.md#deepagents) |
| RLM Code | `uv tool install "superqode[rlm-code]"` | `runtime.backend: rlm-code` | `superqode harness protocol describe rlm-code` | [RLM Code](../advanced/rlm-code.md) |
| Hugging Face Tau | `uv tool install "superqode[tau]"` | `:tau use` or `:harness switch tau` | `:tau status` | [Hugging Face Tau](../advanced/tau.md) |
| DeepSeek Harness | `uv tool install "superqode[deepseek-harness]"` | `:harness switch deepseek-harness` | `superqode harness doctor --spec <file>` | [DeepSeek Harness](../advanced/deepseek-harness.md) |

## Omnigent compatibility

Omnigent support is an included format and execution bridge. It imports a
compatible `agent.yaml` into a repository-owned HarnessSpec; it does not run
the Omnigent server or managed host workflow.

```bash
superqode harness import-omnigent path/to/agent.yaml --output harness.yaml
superqode harness validate --spec harness.yaml
superqode harness doctor --spec harness.yaml
```

See [Omnigent Compatibility](../advanced/omnigent-compat.md) for field mapping
and the interoperability boundary.
