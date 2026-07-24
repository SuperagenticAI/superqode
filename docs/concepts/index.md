# Core Concepts

SuperQode is the open-source, terminal-first Agent Engineering framework for your code factory, with first-class support for local and open models. It gives builders one repeatable contract for model choice, runtime backend, tool access, sandbox policy, approvals, session history, event capture, and output handling.

Use this section to understand the pieces that make a SuperQode run predictable across local models, hosted providers, ACP agents, and optional runtime SDKs.

---

## Quick Navigation

<div class="grid cards" markdown>

-   **Code Engineering**

    ---

    Apply evaluation, governance, provenance, and optimization to code produced by humans and agents.

    [:octicons-arrow-right-24: Learn Code Engineering](code-engineering.md)

-   **Code Factory**

    ---

    Build an organization-owned system for turning intent into verified code changes.

    [:octicons-arrow-right-24: Understand Code Factories](code-factory.md)

-   **Connection Methods and Vendors**

    ---

    Review Local, ACP, BYOK, SDK, MCP, and A2A methods with their supported vendors and direct commands.

    [:octicons-arrow-right-24: Review connections](modes.md)

-   **Authentication**

    ---

    Understand how API keys, local agent auth, and provider setup work.

    [:octicons-arrow-right-24: Learn about auth](authentication.md)

-   **Harness System**

    ---

    Define runtime, model policy, tools, sandbox behavior, checks, hooks, events, and output rules in one spec.

    [:octicons-arrow-right-24: Learn harnesses](../advanced/harness-system.md)

-   **Runtime Backends**

    ---

    Run the same harness through the builtin loop, OpenAI Agents SDK, Google ADK, DeepAgents, PydanticAI, or Codex SDK.

    [:octicons-arrow-right-24: Runtime guide](../runtimes.md)

-   **Tools And Permissions**

    ---

    Control file, search, edit, shell, network, diagnostics, MCP, todo, and skill tools with explicit policy.

    [:octicons-arrow-right-24: Tools guide](../advanced/tools-system.md)

-   **Safety**

    ---

    Use approvals, sandbox profiles, command analysis, project trust, and plugin checks to keep agent work bounded.

    [:octicons-arrow-right-24: Safety guide](../advanced/safety-permissions.md)

</div>

---

## What SuperQode Provides

SuperQode separates an agent system into stable pieces:

| Concept | Meaning |
| --- | --- |
| Harness | The run contract: flavor, runtime, model policy, tools, sandbox, workflow, checks, hooks, events, and output |
| Connection method | How SuperQode reaches models, agents, tools, and services through Local, ACP, BYOK, SDK, MCP, or A2A |
| Runtime | The execution engine behind a harness, such as `builtin`, `openai-agents`, `adk`, `deepagents`, `pydanticai`, or `codex-sdk` |
| Model policy | Model, fallback, reasoning, temperature, context, local hardware, and tool-call behavior |
| Tool policy | The explicit set of capabilities the agent can use |
| Execution policy | Read, write, shell, network, approval, and command rules |
| Session | Persisted conversation state that can be resumed, forked, exported, or shared |
| Event graph | Normalized model, tool, approval, sandbox, memory, and result events from a run |

The harness is the product contract. Runtimes and providers are interchangeable execution choices behind that contract.

Together, these components form a code factory: the organization-owned system that connects coding agents to repositories, policies, evaluation gates, evidence, and delivery workflows.

## How A Run Fits Together

```text
1. CONNECT     Choose ACP, BYOK, local model, Codex SDK, Claude SDK, or another runtime path
2. SPEC        Load or generate a HarnessSpec
3. POLICY      Resolve model, tools, sandbox, approvals, hooks, checks, and output rules
4. EXECUTE     Run through the selected backend
5. OBSERVE     Stream TUI output and persist normalized events when enabled
6. REVIEW      Inspect files, session history, run events, graph output, and checks
```

## Connection Methods and Vendors

| Method | Best for | Typical command |
| --- | --- | --- |
| ACP | External coding agents that own their own model and tool loop | `:connect acp opencode` |
| BYOK | Hosted providers using your API keys | `:connect byok openai <openai-model>` |
| Local | Ollama, LM Studio, MLX, vLLM, SGLang, DS4, and other local servers | `:connect local ollama qwen3:8b` |
| SDK | Vendor SDK and authenticated client runtimes | `:connect codex` |
| MCP | Tool and resource servers | `:mcp connect` |
| A2A | Remote agent services | `:a2a connect <url>` |

See [Connection Methods and Vendors](modes.md) for the complete connection
method, vendor, provider, and ACP agent inventory.

## Harness Flavors

| Flavor | Purpose |
| --- | --- |
| `coding` | Repository-aware coding with file, search, edit, shell, todo, MCP, checks, and approval policy |
| `no_tool` | Model-only reasoning without repository tools, shell access, or hidden filesystem context |

Start with a built-in template:

```bash
superqode harness init my-coder --template coding --output harness.yaml
superqode harness doctor --spec harness.yaml
superqode harness run --spec harness.yaml --prompt "summarize this repository"
```

## Runtime Backends

| Runtime | Purpose |
| --- | --- |
| `builtin` | SuperQode native agent loop |
| `openai-agents` | OpenAI Agents SDK adapter |
| `adk` | Google ADK adapter |
| `deepagents` | Optional DeepAgents adapter for graph and middleware-heavy workflows |
| `pydanticai` | Optional PydanticAI adapter with SuperQode tool bridging |
| `codex-sdk` | Codex SDK runtime using local Codex login where available |

List installed and available runtimes:

```bash
superqode runtime list
superqode harness list-backends
```

## Safety Model

SuperQode makes capabilities explicit:

- harness specs decide whether read, write, shell, and network access are allowed
- approval profiles decide which operations require confirmation
- permission rules can allow, deny, or ask for specific tool calls
- local sandbox modes can confine shell commands
- project trust protects local plugins, MCP configs, and hooks
- no-tool harnesses remove repository and shell tools entirely

For details, see [Safety & Permissions](../advanced/safety-permissions.md).

## Sessions, Sharing, And Memory

SuperQode keeps coding work inspectable:

- `superqode sessions list` shows saved sessions
- `superqode sessions tree` shows branches and forks
- `superqode share create <session-id>` creates a local portable share artifact
- `superqode memory remember "..."` stores explicit project facts and preferences
- `superqode harness events <run-id>` and `superqode harness graph <run-id>` inspect harness runs

## Design Principles

- Harness-first, provider-neutral, runtime-neutral
- Local models are first-class
- Tools are policy-controlled capabilities
- No-tool reasoning is a supported path, not a workaround
- Sessions, events, and exports should make agent work readable
- Configuration should help developers start quickly and deepen only when needed

## Next Steps

- [Installation](../getting-started/installation.md)
- [Quick Start](../getting-started/quickstart.md)
- [Connection Methods and Vendors](modes.md)
- [Harness System](../advanced/harness-system.md)
- [Runtime Backends](../runtimes.md)
- [Tools System](../advanced/tools-system.md)
