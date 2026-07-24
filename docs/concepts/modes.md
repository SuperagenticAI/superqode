# Connection Methods and Vendors

SuperQode provides six connection and interoperability methods: Local, ACP,
MCP, A2A, BYOK, and SDK runtimes. The `:connect` picker exposes the methods and
the primary product profiles. Vendor-specific commands remain available for
direct selection.

## Connection Methods

| Method | Connects SuperQode to | Primary command | Execution ownership |
| --- | --- | --- | --- |
| Local | Ollama, LM Studio, MLX, DwarfStar, llama.cpp, vLLM, SGLang, TGI, or another OpenAI-compatible server | `:connect local` | SuperQode runs the harness and calls the local model |
| ACP | An external coding-agent process that implements Agent Client Protocol | `:connect acp` | The external agent owns its model and tool loop |
| BYOK | A hosted model provider using an API key supplied by the user | `:connect byok` | SuperQode runs the harness and calls the provider |
| SDK | A vendor agent SDK or authenticated client runtime | `:connect codex`, `:connect claude`, or another product profile | The vendor runtime owns model access; SuperQode supplies session and policy controls |
| MCP | Tool and resource servers exposed through Model Context Protocol | `:mcp` | MCP extends the active harness or ACP agent; it is not a model connection |
| A2A | Remote agents exposed through Agent2Agent endpoints | `:a2a connect <url>` | The remote agent owns its execution contract |

Harness Protocol is also supported for portable harness import and export. It
defines harness artifacts rather than an intelligence connection.

## TUI Connection Picker

Open the complete product-level picker:

```text
:connect
```

Open a method-specific picker:

```text
:connect local
:connect acp
:connect byok
```

Use a direct product profile:

```text
:connect codex
:connect claude
:connect antigravity
:connect grok
:connect copilot
:connect copilot-acp
:connect zai
```

The root picker is intentionally shorter than the full catalogs. The following
commands show the authoritative installed and configured inventory:

```bash
superqode agents list --protocol acp
superqode providers list
superqode runtime list
```

## Named Product and Vendor Routes

Several vendors can be reached through more than one method. Choose the route
that matches the account, runtime, and harness ownership required for the task.

| Vendor or product | Available routes | Direct selection |
| --- | --- | --- |
| OpenAI Codex | Codex SDK, Codex ACP, OpenAI BYOK | `:connect codex`, `:connect acp codex`, `:connect byok openai <model>` |
| Anthropic Claude | Claude Agent SDK, Claude Code ACP, Anthropic BYOK | `:connect claude`, `:connect acp claude`, `:connect byok anthropic <model>` |
| Google Antigravity | Authenticated Antigravity CLI runtime | `:connect antigravity` |
| Google Gemini | Gemini CLI ACP, Google AI Studio BYOK, Google ADK runtime | `:connect acp gemini`, `:connect byok google <model>`, `:runtime adk` |
| GitHub Copilot | Copilot SDK, Copilot CLI ACP | `:connect copilot`, `:connect copilot-acp` |
| xAI Grok | Grok Build ACP, Grok subscription model route, xAI BYOK | `:connect grok`, `:grok api [model]`, `:connect byok xai <model>` |
| OpenCode | OpenCode ACP, OpenCode Zen BYOK | `:connect acp opencode`, `:connect byok opencode <model>` |
| Z.AI GLM | Z.AI BYOK, GLM ACP | `:connect zai`, `:connect acp glm` |
| Poolside | Pool CLI ACP, Laguna S 2.1 through DwarfStar or llama.cpp | `:connect acp poolside`, `:connect local ds4 laguna-s-2.1` |
| Moonshot AI Kimi | Kimi CLI ACP, Moonshot BYOK | `:connect acp kimi`, `:connect byok moonshot kimi-k3` |
| Alibaba Qwen | Qwen Code ACP, DashScope BYOK, local Qwen models | `:connect acp qwen`, `:connect byok alibaba <model>`, `:connect local ollama qwen3:8b` |
| DeepSeek | DeepSeek BYOK, local DeepSeek and DS4 model paths | `:connect byok deepseek <model>`, `:connect local ds4 <model>` |
| Mistral AI | Mistral Vibe ACP, Mistral BYOK, local Mistral models | `:connect acp mistral-vibe`, `:connect byok mistral <model>` |
| MiniMax | MiniMax BYOK, local MiniMax model paths | `:connect byok minimax <model>`, `:connect local <provider> <model>` |
| Meta | Meta first-party BYOK, local Meta model paths | `:connect byok meta muse-spark-1.1`, `:connect local <provider> <model>` |
| Cursor | Cursor CLI ACP | `:connect acp cursor` |
| Cline | Cline CLI ACP | `:connect acp cline` |
| Factory | Factory Droid ACP | `:connect acp droid` |
| Cognition | Devin ACP | `:connect acp devin` |
| JetBrains | Junie ACP | `:connect acp junie` |
| Amazon | Amazon Bedrock BYOK, Kiro ACP | `:connect byok amazon-bedrock <model>`, `:connect acp kiro` |

Product names in this table identify connection paths, not bundled
subscriptions. Authentication and usage terms remain controlled by each
vendor.

## ACP Coding Agents

ACP connects SuperQode to an external coding-agent harness. The agent manages
its own model calls and can expose file editing, shell execution, MCP tools, and
agent-specific commands. SuperQode supplies the terminal interface, session
switching, harness selection, policy controls, and normalized events supported
by the adapter.

Open the ACP picker:

```text
:connect acp
:connect acp enterprise
:connect acp all
```

Connect directly:

```text
:connect acp opencode
:connect acp poolside
:connect acp glm
```

The bundled offline catalog contains the following agents. The `all` picker can
also include additional entries from the official ACP registry and user
definitions.

| Agent | Identifier | Agent | Identifier |
| --- | --- | --- | --- |
| AgentPool | `agentpool` | Amp | `amp` |
| Auggie (Augment Code) | `auggie` | AutoDev Xiuper | `autodev` |
| Blackbox AI | `blackbox` | Bub | `bub` |
| cagent | `cagent` | Claude Code | `claude` |
| Cline | `cline` | Code Assistant | `codeassistant` |
| CodeBuddy Code | `codebuddy` | Codex | `codex` |
| GitHub Copilot | `copilot` | Cortex Code | `cortex` |
| crow-cli | `crow` | Cursor | `cursor` |
| DeepAgents | `deepagents` | Devin | `devin` |
| Dirac | `dirac` | Factory Droid | `droid` |
| fast-agent | `fast-agent` | fount | `fount` |
| Gemini CLI | `gemini` | GLM Agent | `glm` |
| Goose | `goose` | Grok Build | `grok` |
| Harn | `harn` | Hermes Agent | `hermes` |
| JetBrains Junie | `junie` | Kilo | `kilo` |
| Kimi CLI | `kimi` | Kiro CLI | `kiro` |
| LLMling-Agent | `llmlingagent` | Minion Code | `minion` |
| Mistral Vibe | `mistral-vibe` | OpenClaw | `openclaw` |
| OpenCode | `opencode` | OpenHands | `openhands` |
| Pi | `pi` | Poolside | `poolside` |
| Qoder CLI | `qoder` | Qwen Code | `qwen` |
| siGit Code | `sigit` | Stakpak | `stakpak` |
| stdio Bus | `stdio-bus` | VT Code | `vtcode` |

Inspect installation and authentication requirements:

```bash
superqode agents show poolside
superqode agents doctor poolside
superqode agents doctor poolside --live
```

See [ACP Agents](../providers/acp.md) for registry behavior, configuration, and
protocol details.

## BYOK Providers

BYOK connects SuperQode directly to a hosted model API. API keys are read from
environment variables or SuperQode's local credential store. Secrets do not
need to be placed in a HarnessSpec.

```text
:connect byok
:connect byok openai <model>
:connect byok anthropic <model>
```

The built-in provider registry contains these hosted routes:

| Provider | Identifier | Provider | Identifier |
| --- | --- | --- | --- |
| Anthropic | `anthropic` | OpenAI | `openai` |
| Google AI Studio | `google` | Meta | `meta` |
| xAI | `xai` | Mistral AI | `mistral` |
| DeepSeek | `deepseek` | Z.AI general API | `zai` |
| Zhipu AI | `zhipu` | Alibaba DashScope | `alibaba` |
| MiniMax | `minimax` | Moonshot AI | `moonshot` |
| SiliconFlow | `siliconflow` | Baidu | `baidu` |
| ByteDance Doubao | `doubao` | OpenRouter | `openrouter` |
| Together AI | `together` | Groq | `groq` |
| Fireworks AI | `fireworks` | Hugging Face | `huggingface` |
| Cerebras | `cerebras` | Perplexity | `perplexity` |
| Cohere | `cohere` | Amazon Bedrock | `amazon-bedrock` |
| OpenCode Zen | `opencode` | GitHub Copilot model endpoint | `github-copilot` |
| Azure OpenAI | `azure` | Google Vertex AI | `vertex` |
| Cloudflare AI Gateway | `cloudflare` |  |  |

`grok-cli` is an authenticated subscription route used by `:grok api`; it is
not an API-key BYOK provider.

Check provider setup and discover current models:

```bash
superqode providers list
superqode providers doctor openai
superqode providers guide openai
superqode models --provider openai
```

See [BYOK Providers](../providers/byok.md) for API-key variables and detailed
provider configuration.

## Local Providers

Local mode connects to a server running on the current machine or on private
infrastructure.

| Local route | Identifier | Typical use |
| --- | --- | --- |
| Ollama | `ollama` | Local model management and serving |
| Ollama Cloud | `ollama-cloud` | Ollama-hosted model route |
| LM Studio | `lmstudio` | Desktop model serving |
| MLX | `mlx` | Apple Silicon inference |
| vLLM | `vllm` | High-throughput model serving |
| DwarfStar | `ds4` | Laguna S 2.1 and DeepSeek V4 Flash |
| SGLang | `sglang` | Structured and high-throughput serving |
| Hugging Face TGI | `tgi` | Text Generation Inference |
| llama.cpp server | `llamacpp` | GGUF and CPU-first inference |
| Custom OpenAI-compatible server | `openai-compatible` | Private or vendor-specific endpoints |

Open the local picker or select a provider directly:

```text
:connect local
:connect local ollama qwen3:8b
:connect local ds4 laguna-s-2.1
```

See [Local Providers](../providers/local.md) for setup, server lifecycle, model
selection, and hardware guidance.

## SDK Runtimes

SDK runtimes embed or call a vendor execution engine while preserving
SuperQode's terminal, sessions, approvals, plans, and evidence surface.

| Runtime | Selection | Authentication |
| --- | --- | --- |
| Codex SDK | `:connect codex` | Local Codex or ChatGPT login, or OpenAI API key |
| GitHub Copilot SDK | `:connect copilot` | GitHub Copilot account or token |
| Claude Agent SDK | `:connect claude` | Anthropic API key |
| Antigravity CLI | `:connect antigravity` | Google Sign-In through `agy` |
| OpenAI Agents SDK | `:runtime openai-agents` | OpenAI provider credentials |
| Google ADK | `:runtime adk` | Google provider credentials |
| Pydantic AI | `:runtime pydanticai` | Credentials for the selected provider |

List the installed runtime adapters:

```bash
superqode runtime list
```

See [Runtime Backends](../runtimes.md) for optional dependencies, event
normalization, and runtime capability differences.

## MCP Tool Connections

MCP connects tools and resources to a SuperQode harness or to an ACP agent that
accepts MCP server definitions. MCP does not select a model.

```text
:mcp
:mcp list
:mcp doctor
```

Project and user MCP configuration can be stored in:

```text
.superqode/mcp.json
~/.superqode/mcp.json
~/.config/superqode/mcp.json
```

Enabled MCP servers are passed to compatible ACP sessions during
`session/new`. Restart the ACP session after changing MCP configuration.

See [MCP Configuration](../configuration/mcp-config.md) for transports and
configuration. See [MCP Command](../cli-reference/mcp-command.md) for the
harness server interface.

## A2A Agent Connections

A2A connects remote agents through Agent2Agent cards and task endpoints. It is
used for remote delegation and agent-provider integration rather than direct
model selection.

```text
:a2a connect http://localhost:8000
:a2a discover http://agent:8080
:a2a call myagent "Review the authentication module"
```

See [A2A Protocol](../providers/a2a.md) for provider configuration,
authentication, task lifecycle, and streaming.

## Connection Method Versus Harness

A connection chooses the model, external agent, provider, or runtime. A
HarnessSpec defines the controls applied to work:

- context and memory
- tools and skills
- model and runtime policy
- evaluation and acceptance gates
- budgets and permissions
- workflow and optimization settings

Switching a connection does not delete saved sessions or HarnessSpecs. Use
`:sessions` to resume a session and `:harness` to list or switch harnesses.

## Safety and Diagnostics

Connection alone does not grant capabilities. Effective access comes from the
active runtime, harness, provider, agent, and approval policy.

Use the relevant doctor command before important work:

```bash
superqode providers doctor openai
superqode agents doctor opencode --live
superqode harness doctor --spec harness.yaml
```

Review [Safety and Permissions](../advanced/safety-permissions.md) before
enabling shell or write access in important repositories.

## Related Documentation

- [Authentication](authentication.md)
- [Provider Configuration](../providers/index.md)
- [ACP Agents](../providers/acp.md)
- [BYOK Providers](../providers/byok.md)
- [Local Providers](../providers/local.md)
- [Runtime Backends](../runtimes.md)
- [Harness System](../advanced/harness-system.md)
