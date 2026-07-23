# Connection Modes

SuperQode connects to intelligence in four ways: ACP agents, BYOK providers, local model servers, and vendor SDK runtimes. The connection mode decides where model work happens and who owns the agent loop. A harness decides what capabilities are allowed during a run.

---

## Overview

| Mode | What it connects to | Best for |
| --- | --- | --- |
| ACP | External coding agents that speak Agent Client Protocol | Full coding-agent workflows where the agent owns its model and tools |
| BYOK | Hosted model providers using your API keys | Cloud models, automation, model comparison, and direct provider usage |
| Local | Local or self-hosted model servers | Privacy, offline work, cost control, and local model experiments |
| SDK | Vendor agent SDKs running inside SuperQode | Using your existing ChatGPT or Claude subscription, or vendor-native agent behavior, with SuperQode's TUI and sessions around it |

Start from the TUI:

```text
:connect
```

Direct examples:

```text
:connect acp opencode
:connect byok openai <openai-model>
:connect local ollama qwen3:8b
:connect codex
:connect claude
```

CLI equivalents:

```bash
superqode connect acp opencode
superqode connect byok openai <openai-model>
superqode connect local ollama qwen3:8b
superqode --runtime codex-sdk --print "review this repo"
```

---

## ACP

ACP mode connects SuperQode to an external coding agent. The agent manages its own model calls and may expose file editing, shell execution, MCP tools, and agent-specific slash commands.

Use ACP when:

- you want a full coding agent rather than a direct model call
- the agent already has its own auth and provider setup
- you want SuperQode's TUI, sessions, exports, and command surface around that agent
- you need agent-owned MCP or shell behavior

Common commands:

```bash
superqode agents list
superqode agents show opencode
superqode agents doctor opencode
superqode agents doctor opencode --live
superqode connect acp opencode
```

Example config:

```yaml
default:
  mode: acp
  agent: opencode

agents:
  opencode:
    description: OpenCode coding agent
    protocol: acp
    command: opencode
```

`coding_agent` is still accepted for older configs, but new config should use `agent`.

---

## BYOK

BYOK mode connects to hosted providers with your own API keys. SuperQode reads keys from environment variables and does not require secrets in YAML.

Use BYOK when:

- you want direct access to hosted models
- you need model comparison or provider switching
- you want API-key-based automation
- you want cost and model metadata where available

Set an API key:

```bash
export OPENAI_API_KEY=your-key
export ANTHROPIC_API_KEY=your-key
export GOOGLE_API_KEY=your-key
```

Connect:

```text
:connect byok openai <openai-model>
```

Check setup:

```bash
superqode providers doctor openai
superqode providers guide openai
superqode models --provider openai
```

Example config:

```yaml
default:
  mode: byok
  provider: openai
  model: <openai-model>

providers:
  openai:
    api_key_env: OPENAI_API_KEY
    recommended_models:
      - <openai-model>
      - <openai-fast-model>
```

---

## Local

Local mode connects to model servers running on your machine or infrastructure.

Use local mode when:

- repository contents should stay on your machine
- you want no per-token API cost
- you are evaluating local coding models
- you need offline or self-hosted workflows

Supported local provider paths include Ollama, LM Studio, MLX, vLLM, SGLang, TGI, and DS4 where installed and configured.

Ollama example:

```bash
ollama serve
ollama pull qwen3:8b
superqode providers doctor ollama --live
```

Connect:

```text
:connect local ollama qwen3:8b
```

Example config:

```yaml
default:
  mode: local
  provider: ollama
  model: qwen3:8b

providers:
  ollama:
    base_url: http://localhost:11434
    recommended_models:
      - qwen3:8b
```

Local tool support depends on the model family and provider. SuperQode has model-family policies for known local models and can fall back to no-tool or reduced-tool operation when a model cannot reliably call tools.

---

## Connection Mode Versus Runtime

Connection mode answers: "What product, provider, agent, or local server am I connected to?"

Runtime answers: "Which execution engine runs the harness?"

Examples:

| Choice | Meaning |
| --- | --- |
| `:connect byok openai <openai-model>` | Use a hosted OpenAI model through SuperQode's provider path |
| `:connect local ollama qwen3:8b` | Use a local Ollama model |
| `:connect acp opencode` | Use an ACP coding agent |
| `:runtime pydanticai` | Switch the runtime backend for compatible harness runs |
| `superqode harness run --spec harness.yaml --runtime openai-agents` | Run a harness through the OpenAI Agents SDK adapter |

See [Runtime Backends](../runtimes.md) for backend details.

---

## SDK runtimes

SDK mode runs a vendor's own agent engine inside SuperQode. You keep SuperQode's TUI, sessions, approvals, plan surface, and exports, while the vendor SDK owns the model calls and its native behaviors.

| Runtime | Sign in with | Notes |
| --- | --- | --- |
| Codex SDK (`:connect codex`) | Your ChatGPT subscription (local Codex login) or an OpenAI API key | Codex-native patches, plans, and command events are normalized into SuperQode's event surface |
| GitHub Copilot SDK (`:connect copilot`) | Your GitHub Copilot account or an explicit GitHub token | Copilot remains the inner agent loop; SuperQode adds normalized events, permission policy, model selection, evidence, and session controls |
| GitHub Copilot ACP (`:connect copilot-acp`) | Your GitHub Copilot CLI login | The official Copilot CLI agent runs over ACP and owns its tools and commands |
| Claude Agent SDK (`:connect claude`) | Your Claude subscription or an Anthropic API key | Claude Code behavior with SuperQode session management; `TodoWrite` feeds the shared plan panel |
| Antigravity (`:connect antigravity`) | Your Google account via the official `agy` CLI | Headless print runtime using `agy`'s OS-keyring login; text streaming only because `agy` does not expose structured tool events |

Use SDK mode when:

- you already pay for a ChatGPT or Claude subscription and want to use it instead of per-token API billing
- you want a vendor's native agent behavior, but with SuperQode's readable sessions, exports, and approval policies around it
- you are comparing vendor agents against local models in one interface

```bash
superqode --runtime codex-sdk --print "summarize this repository"
superqode --connect claude --print "summarize the last change"
```

See [Runtime Backends](../runtimes.md) for the full runtime matrix.


## Choosing A Mode

| Need | Recommended mode |
| --- | --- |
| Full external coding agent | ACP |
| Hosted model with your own key | BYOK |
| Private local inference | Local |
| Repeatable repository automation | Any mode plus a HarnessSpec |
| Pure planning without tools | Any mode plus a no-tool harness |
| Model comparison | BYOK or local, using `:compare` |

---

## Safety Notes

Connection mode does not by itself grant capabilities. The effective capabilities come from the active runtime, harness, provider, and approval policy.

For repeatable safety, use a HarnessSpec:

```bash
superqode harness init planner --template no-tool --output planner.yaml
superqode harness init coder --template coding --output coder.yaml
superqode harness doctor --spec coder.yaml
```

Review [Safety & Permissions](../advanced/safety-permissions.md) before allowing shell or write access in important repositories.

## Next Steps

- [Authentication](authentication.md)
- [Provider Configuration](../providers/index.md)
- [Runtime Backends](../runtimes.md)
- [Harness System](../advanced/harness-system.md)
