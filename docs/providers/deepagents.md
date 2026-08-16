# LangChain DeepAgents

DeepAgents is LangChain's MIT-licensed agent harness, built on LangGraph. It
ships a filesystem backend, an `execute` tool, subagent delegation, skills, and
long-term memory. SuperQode supports it through two separate routes, because
DeepAgents ships as two separate products.

| Route | Hub entry | Use it when |
| --- | --- | --- |
| Deep Agents Code | `deepagents-code` | You want the complete prebuilt terminal coding agent, with its own approvals, memory, and skills |
| DeepAgents SDK runtime | `deepagents` | You want a SuperQode HarnessSpec whose loop, graph, and subagents are executed by DeepAgents |

Both are open source under the MIT license at
[langchain-ai/deepagents](https://github.com/langchain-ai/deepagents), so both
appear under the Harness Hub's **Open source** filter.

## Deep Agents Code

`deepagents-code` is the prebuilt coding agent, published as the `dcode`
command. It exposes itself as an ACP server, which is the route SuperQode
connects to.

### Install And Authenticate

```bash
curl -LsSf https://langch.in/dcode | bash
```

OpenAI, Anthropic, and Gemini providers are included. Select others at install
time:

```bash
DEEPAGENTS_CODE_EXTRAS="ollama,openrouter" curl -LsSf https://langch.in/dcode | bash
```

Run `dcode` once and complete `/auth` to connect a provider. Then verify that
SuperQode can discover it:

```bash
superqode agents show deepagents-code
superqode agents doctor deepagents-code
```

### Connect From The TUI

```text
:connect deepagents-code
```

It also appears in the unified Harness Switcher:

```text
:harness
:harness switch deepagents-code
:harness switch deepagents-code --fork
```

Deep Agents Code owns its agent loop, tools, approval mode, and thread history.
SuperQode provides discovery, launch, session continuity, and a normalized
event surface.

## DeepAgents SDK Runtime

The `deepagents` runtime backend takes a SuperQode HarnessSpec and executes it
with `create_deep_agent(...)`. Reach for this when you want DeepAgents graph
state, middleware, filesystem backend behavior, and subagent patterns behind a
spec you own and can evaluate.

### Install

```bash
uv tool install "superqode[deepagents]"
```

SuperQode targets the DeepAgents 0.7 API. Any other release reports a version
problem rather than a missing package, so an upgrade or downgrade is named
directly.

### Provider Integration Packages

DeepAgents resolves the model with LangChain's `init_chat_model`, which
requires the matching LangChain integration package to be importable. The
runtime bundles `langchain-anthropic` and `langchain-google-genai` only, so
local providers fail with an `ImportError` such as:

```text
ImportError: Initializing ChatOllama requires the langchain-ollama package.
Please install it with `pip install langchain-ollama`
```

Install the integration package for your provider into the same tool
environment (use `--force` because `superqode` is already installed):

```bash
uv tool install "superqode[deepagents]" --with langchain-ollama --force
```

Use the equivalent package for other local providers, for example
`langchain-openai` for LM Studio, MLX, or llama.cpp OpenAI-compatible
endpoints. Then re-run `:retry` in an existing session.

### Run The Built-In Preset

```bash
superqode harness show deepagents
superqode harness run deepagents "Add a regression test for the parser"
```

Start a repository-owned spec from the same template:

```bash
superqode harness init deepagents-coder --template deepagents --output harness.yaml
```

A fuller example, with an orchestrator workflow and a review subagent, is in
[`examples/harnesses/deepagents.yaml`](https://github.com/SuperagenticAI/superqode/blob/main/examples/harnesses/deepagents.yaml).

### What The Spec Controls

| HarnessSpec field | DeepAgents equivalent |
| --- | --- |
| `provider` and `model` | `provider:model` model spec |
| Job prompt compiled from the spec | `system_prompt` |
| `agents` after the first, with `delegates_to` or a subagent role | `subagents` |
| `runtime.config.skills` | `skills` |
| `runtime.config.memory` | `memory`, defaulting to `context.instruction_files` |
| `execution_policy.allow_read` and `allow_write` | `FilesystemPermission` deny rules |
| `working_directory` | `FilesystemBackend(root_dir=...)` |

### Constraints

- No-tool harnesses are rejected. The DeepAgents public API is tool-oriented,
  so use the `builtin` runtime for model-only specs.
- `allow_shell: false` is rejected. DeepAgents exposes its `execute` tool
  whenever a filesystem backend is configured.
- DeepAgents runs its own filesystem and `execute` tools, so SuperQode
  approvals do not gate them. The Hub states this before you select the
  harness.

## Choose The DeepAgents Route

| Goal | Route |
| --- | --- |
| Use the complete prebuilt coding agent | `:connect deepagents-code` |
| Run a HarnessSpec you own on the DeepAgents loop | `superqode harness run deepagents "..."` |
| Run a bare JavaScript Deep Agent over ACP | `:connect acp deepagents` |

The third row is the upstream `deepagents-acp` npm package, which runs a
general-purpose Deep Agent rather than the coding agent. It stays in the ACP
catalog as a distinct entry.

## Related Documentation

- [Harness Hub](../harness-hub.md)
- [Connection Methods and Vendors](../concepts/modes.md)
- [Agent Runtimes](../runtimes.md)
- [Harness System](../advanced/harness-system.md)
