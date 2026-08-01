# Connection Methods and Vendors

SuperQode provides six connection and interoperability methods: Local, ACP,
MCP, A2A, BYOK, and SDK runtimes. The `:connect` screen does not open on those
methods, because a method is a transport rather than a decision. It opens on
one question, who should run the coding loop, in three answers: use an agent
someone else built, run a SuperQode harness on a model you choose, or build a
harness for this repository. The methods above are how each answer is carried
out, and every vendor-specific command remains available for direct selection.

## Start With The Outcome

SuperQode has three related selectors:

| Goal | Open | What it selects |
| --- | --- | --- |
| Use a coding agent or model | `:connect` | Account, external coding agent, provider, model, or vendor runtime |
| Change the complete working behavior | `:harness` | Built-in, project, vendor, ACP, optional, installed, or registry harness |
| Change only the execution backend | `:runtime list` | Native or framework-specific runtime adapter |

For a first session, run `superqode`, choose `:connect`, and start coding. Use
`:harness` when you want another agent or run contract. Building a custom
HarnessSpec is a later step.

## Harness Choices

The Harness Switcher is the centralized inventory for runnable harnesses:

```text
:harness
:harness all
:harness current
```

| Harness source | Examples | Ownership |
| --- | --- | --- |
| SuperQode native | Workbench, coding and no-tool templates, model presets | SuperQode owns the tool loop and HarnessSpec policy |
| Vendor coding agents | Codex, GitHub Copilot, Antigravity, Grok, Kimi Code, Qwen Code | Vendor runtime or first-party agent owns the underlying agent behavior |
| ACP agents | OpenCode, Claude Code, GLM Agent, Poolside, and the complete ACP catalog | External ACP process owns its agent loop |
| Optional harness integrations | Hugging Face Tau | External harness runs through SuperQode's Harness Protocol adapter |
| Project HarnessSpecs | `harness.yaml`, `.superqode/harnesses/*.yaml` | Repository owns the complete run contract |
| Installed Python harnesses | Package-provided HarnessSpec and protocol adapters | Installed package owns the adapter; repository can still select policy |
| Registry harnesses | Harnesses installed from the SuperQode registry | Registry artifact becomes a local selectable harness |

Switching can preserve the current conversation or fork an independent branch:

```text
:harness switch workbench
:harness switch qwen-code --fork
:sessions switch
```

## Connection Methods

| Method | Connects SuperQode to | Primary command | Execution ownership |
| --- | --- | --- | --- |
| Local | Ollama, LM Studio, MLX, DwarfStar, llama.cpp, vLLM, SGLang, TGI, or another OpenAI-compatible server | `:connect local` | SuperQode runs the harness and calls the local model |
| ACP | An external coding-agent process that implements Agent Client Protocol | `:connect acp` | The external agent owns its model and tool loop |
| BYOK | A hosted model provider using an API key supplied by the user | `:connect byok` | SuperQode runs the harness and calls the provider |
| SDK | A vendor agent SDK or authenticated client runtime | `:connect subscriptions`, then a product such as `:connect codex`, or use an explicit API-key runtime | The vendor runtime owns model access; SuperQode supplies session and policy controls |
| MCP | Tool and resource servers exposed through Model Context Protocol | `:mcp` | MCP extends the active harness or ACP agent; it is not a model connection |
| A2A | Remote agents exposed through Agent2Agent endpoints | `:a2a connect <url>` | The remote agent owns its execution contract |

Harness Protocol is also supported for portable harness import and export. It
defines harness artifacts rather than an intelligence connection.

## TUI Connection Picker

Open the complete product-level picker:

```text
:connect
```

The root screen has three options, `agents`, `models`, and `build`, one per
rung of the ownership ladder. Open any of them directly:

```text
:connect agents
:connect models
:connect build
```

| Root option | What it asks | What it opens |
| --- | --- | --- |
| `:connect agents` | Use an agent you already have | Vendor coding agents, the full ACP catalog, and optional harness integrations |
| `:connect models` | Run a SuperQode harness on a model you choose | `:connect local`, `:connect byok`, and `:connect plan` |
| `:connect build` | Build your own harness for this repository | Import, preset, wizard, and blank HarnessSpec routes |

Above the options, the root screen lists what it detected on this machine:
installed agents, running local engines, API keys already in the environment,
and agent configuration files in the repository. Nothing has to be read first
to find out what is usable here.

The agents screen groups its rows by readiness rather than by vendor
geography, because where a company is headquartered says nothing about whether
a user can run its agent today:

| Group | Meaning |
| --- | --- |
| Ready now | Installed and signed in, so Enter connects |
| One step away | Installed but not yet authenticated |
| Installable | One documented install command away |
| More | Catalog rows that open a further screen |

Each vendor row also carries badges for harness licence, model openness, and
transport, for example `open harness`, `open weights`, `ACP`. These are two
independent facts rather than one category: Codex ships an Apache-2.0 harness
that drives only OpenAI models, and Factory Droid is a closed harness that
runs whatever model you bring.

Row numbers are registry positions rather than screen positions, so a shortcut
such as `:connect codex` keeps working as readiness changes.

The models screen holds the three routes where SuperQode owns the tool loop:

```text
:connect local
:connect byok
:connect plan
```

`:connect plan` covers subscriptions that expose a model endpoint, so a plan
you already pay for can drive a SuperQode harness instead of the vendor agent.

The build screen leads with importing, because a repository that already has
agent configuration does not need to author anything:

```text
:connect build-import
:connect build-preset
:connect build-wizard
:connect build-blank
```

| Build route | Starting point |
| --- | --- |
| `:connect build-import` | `AGENTS.md`, `CLAUDE.md`, `.claude/`, `.cursor/rules`, Copilot instructions, or `agent.yaml` |
| `:connect build-preset` | A tuned built-in template, cloned into `.superqode/harnesses/` |
| `:connect build-wizard` | Guided questions, for a harness with no existing configuration |
| `:connect build-blank` | A minimal valid `harness.yaml` for people who know the schema |

Imported and cloned specs are written into the repository as YAML, so they are
versioned, reviewable, and evaluable like any other source file.

`:connect agents` opens the vendor submenu. Every product on it is also a
direct profile, so the submenu never becomes a required step:

```text
:connect codex
:connect cursor
:connect amp
:connect antigravity
:connect grok
:connect copilot
:connect devin
:connect droid
:connect kiro
:connect glm-cli
:connect qwen-code
:connect kimi-code
```

Only vendor-plan and vendor-managed sign-in routes appear in this submenu.
API-key-only routes remain under `:connect byok`; transport alternatives such
as the Copilot CLI remain in the ACP picker.

Optional non-ACP harness integrations sit at the bottom of the same screen:

```text
:connect other-harnesses
```

Pre-ladder names still resolve, so muscle memory and older documentation keep
working. `:connect subscriptions` lands on the agents screen, and `:connect
local`, `:connect byok`, and `:connect acp` go straight to their screens
without passing through the root question.

The root picker is intentionally shorter than the full catalogs. Inside the
TUI, `:explore` shows every capability category with its live state on this
machine, and `:tour` shows the ownership ladder with each rung ticked off as
you complete it. The following commands show the same authoritative inventory
from the shell:

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
| Anthropic Claude | Claude Agent SDK, Anthropic BYOK | `:runtime claude-agent-sdk`, `:connect byok anthropic <model>` |
| Google Antigravity | Authenticated Antigravity CLI runtime | `:connect antigravity` |
| Google Gemini | Antigravity CLI, Google AI Studio BYOK, Google ADK runtime | `:connect antigravity`, `:connect byok google <model>`, `:runtime adk` |
| GitHub Copilot | Copilot SDK, Copilot CLI ACP | `:connect copilot`, `:connect copilot-cli`, `:connect acp copilot` |
| xAI Grok | Grok Build ACP, Grok subscription model route, xAI BYOK | `:connect grok`, `:grok api [model]`, `:connect byok xai <model>` |
| OpenCode | OpenCode ACP, OpenCode Zen BYOK | `:connect acp opencode`, `:connect byok opencode <model>` |
| Z.AI GLM | Z.AI BYOK, GLM Coding Plan ACP | `:connect byok zai <model>`, `:connect glm-cli`, `:connect acp glm` |
| Poolside | Pool CLI ACP, Laguna S 2.1 through DwarfStar or llama.cpp | `:connect acp poolside`, `:connect local ds4 laguna-s-2.1` |
| Moonshot AI Kimi | Kimi Code ACP, Moonshot BYOK | `:connect kimi-code`, `:connect byok moonshot kimi-k3` |
| Alibaba Qwen | Qwen Code ACP, DashScope BYOK, local Qwen models | `:connect qwen-code`, `:connect byok alibaba <model>`, `:connect local ollama qwen3:8b` |
| DeepSeek | DeepSeek BYOK, local DeepSeek and DS4 model paths | `:connect byok deepseek <model>`, `:connect local ds4 <model>` |
| Mistral AI | Mistral Vibe ACP, Mistral BYOK, local Mistral models | `:connect acp mistral-vibe`, `:connect byok mistral <model>` |
| MiniMax | MiniMax BYOK, local MiniMax model paths | `:connect byok minimax <model>`, `:connect local <provider> <model>` |
| Meta | Meta first-party BYOK, local Meta model paths | `:connect byok meta muse-spark-1.1`, `:connect local <provider> <model>` |
| Cursor | Cursor subscription through Cursor CLI ACP | `:connect cursor`, `:connect acp cursor` |
| Amp | Amp subscription through its ACP adapter | `:connect amp`, `:connect acp amp` |
| Cline | Cline CLI ACP | `:connect acp cline` |
| Factory | Factory Droid subscription through ACP | `:connect droid`, `:connect acp droid` |
| Cognition | Devin ACP, Devin CLI runtime | `:connect devin`, `:connect acp devin`, `:runtime devin-cli` |
| JetBrains | Junie ACP | `:connect acp junie` |
| Amazon | Amazon Bedrock BYOK, Kiro/Amazon Q Developer subscription through ACP | `:connect byok amazon-bedrock <model>`, `:connect kiro`, `:connect acp kiro` |

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

The default view contains installed and featured agents. The `all` form opens
the complete live registry.

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
| Kimi Code | `kimi` | Kiro CLI | `kiro` |
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
| xAI | `xai` | NVIDIA API Catalog | `nvidia` |
| Poolside | `poolside` | Mistral AI | `mistral` |
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
| Cloudflare AI Gateway | `cloudflare` | Baseten | `baseten` |
| Modal | `modal` |  |  |

`grok-cli` is an authenticated subscription route used by `:grok api`; it is
not an API-key BYOK provider.

Check provider setup and discover current models:

```bash
superqode providers list
superqode providers doctor openai
superqode providers guide openai
superqode models --provider openai
```

Model lists change more frequently than released documentation. The
authoritative current inventory is the in-product catalog:

```bash
superqode models
superqode models --provider <provider>
superqode providers list
```

The picker combines curated built-in routes with live discovery where a
provider exposes it. Harness model policy can then pin a primary model and
fallbacks without changing the connection documentation.

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
| GitHub Copilot | `:connect copilot` | GitHub Copilot account through the SDK or official CLI |
| Claude Agent SDK | `:runtime claude-agent-sdk` | Anthropic API key |
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
