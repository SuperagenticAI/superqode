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

The existing-harness screen stays short by offering three categories:
`agent-subscriptions`, `agent-acp`, and `other-harnesses`. The subscription
screen keeps vendors in a stable order and shows the remaining setup directly
for the highlighted row. Other rows remain one-line choices. This prevents row
numbers from moving between machines while keeping installed and unavailable
routes clear without turning the picker into a catalogue page.

```text
:connect agent-subscriptions
:connect agent-acp
:connect other-harnesses
```

Each vendor row also carries badges for harness licence, model openness, and
transport, for example `open harness`, `open weights`, `ACP`. These are two
independent facts rather than one category: Codex ships an Apache-2.0 harness
that drives only OpenAI models, and Factory Droid is a closed harness that
runs whatever model you bring. Open and Closed rows add the SPDX licence to
that line when SuperQode has verified it, so `open harness · AGPL-3.0` and
`open harness · MIT` are told apart without leaving the picker. A blank licence
means unverified rather than absent, so no badge is drawn.

Row numbers are screen positions. The displayed number, arrow-key highlight,
mouse target, and typed number always select the same row. Named shortcuts such
as `:connect codex` remain stable regardless of row position.

When SuperQode owns the loop, the harness step is also directly addressable:

```text
:connect harness-core
:connect harness-rlm
:connect harness-workbench
:connect harness-pipy
:connect harness-presets
:connect harness-repo
```

The models screen holds the three routes where SuperQode owns the tool loop:

```text
:connect local
:connect byok
:connect plan
```

`:connect plan` covers subscriptions that expose a model endpoint, so a plan
you already pay for can drive a SuperQode harness instead of the vendor agent.
Its direct routes are `plan-zai`, `plan-grok`, `plan-copilot`, `plan-moonshot`,
`plan-qwen`, `plan-opencode`, `plan-ollama-cloud`, `plan-deepseek`, and
`plan-minimax`, each used as `:connect <route>`.

```text
:connect plan-zai
:connect plan-grok
:connect plan-copilot
:connect plan-moonshot
:connect plan-qwen
:connect plan-opencode
:connect plan-ollama-cloud
:connect plan-deepseek
:connect plan-minimax
```

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
:connect muse
:connect grok
:connect copilot
:connect devin
:connect droid
:connect kiro
:connect glm-cli
:connect qwen-code
:connect kimi-code
:connect deepagents-code
:connect junie
:connect fx
:fx
```

Only vendor-plan and vendor-managed sign-in routes appear in this submenu.
API-key-only routes remain under `:connect byok`; transport alternatives such
as the Copilot CLI remain in the ACP picker. Factory Droid's own key is a
Closed harness (`:connect droid-key`), not a Subscriptions row and not
SuperQode BYOK. Junie has both: `:connect junie` on Subscriptions and
`:connect junie-key` on Closed.

The rest of the existing-harness screen depends on the connect menu flag
(`SUPERQODE_CONNECT_MENU` or `connect_menu` in `~/.superqode/config.json`).
`v1` (the compiled default) keeps **Other harnesses**. `v2` replaces that
row with **Open harnesses** and **Closed harnesses**:

```text
:connect other-harnesses
:connect open-harnesses
:connect closed-harnesses
:connect letta
:connect warp
```

Under `v2` the two category rows carry the same `agent-` prefix as the
subscription and ACP rows, so every existing-harness category is selectable by
its registry id as well as its short alias:

```text
:connect agent-open-harnesses
:connect agent-closed-harnesses
```

Open is OSI-licensed harnesses on a key or local model. Closed is proprietary
harnesses on that vendor's key. Setup-card rows such as Letta Code and Warp
Agent are listed so you can find them; SuperQode does not start their loop
from that row yet.

| Open harness | License | Direct selection | What the row does today |
| --- | --- | --- | --- |
| Tau | MIT | `:connect tau` | Switches to the hosted Tau adapter, then asks for a key or local model |
| DeepSeek Harness | MIT | `:connect deepseek-harness` | Switches to the hosted adapter, then DeepSeek BYOK or a local OpenAI-compatible URL |
| DeepAgents SDK | MIT | `:connect deepagents` | Switches to the SDK adapter, then Anthropic, Google, or a documented local extra |
| OpenCode | MIT | `:connect opencode-key` | Asks for a key or local model, then attaches OpenCode over ACP with it |
| Prime Agent | MIT | `:connect prime-agent-key` | Asks for a key or local model, then runs Prime through its Python RPC backend |
| jcode | MIT | `:connect jcode` | Setup card |
| Grok Build | Apache-2.0 | `:connect grok-key` | Attaches on an exported `GROK_CODE_XAI_API_KEY`, otherwise asks for a local endpoint |
| Qwen Code | Apache-2.0 | `:connect qwen-code-key` | Attaches on an exported `QWEN_API_KEY` or `DASHSCOPE_API_KEY`, otherwise asks for a model |
| fast-agent | Apache-2.0 | `:connect fast-agent` | Asks for a key or local model, then attaches fast-agent over ACP with it |
| Pi | MIT | `:connect pi` | Asks for a key or local model, then attaches Pi over ACP with it |
| Goose | Apache-2.0 | `:connect goose-key` | Setup card |
| Cline | Apache-2.0 | `:connect cline-key` | Setup card |
| OpenHands | MIT | `:connect openhands-key` | Setup card |
| Mistral Vibe | Apache-2.0 | `:connect mistral-vibe-key` | Setup card |
| Hermes Agent | MIT | `:connect hermes-key` | Setup card |
| Letta Code | Apache-2.0 | `:connect letta` | Setup card |
| Warp Agent | AGPL-3.0 | `:connect warp` | Setup card |
| Kimi Code | MIT | `:connect kimi-code-key` | Attaches on an exported `MOONSHOT_API_KEY` or `KIMI_API_KEY`, otherwise asks for a model |
| fx | Apache-2.0 | `:connect fx-key` | Attaches on `AI_GATEWAY_API_KEY` (or `fx setup`). No local model or SuperQode BYOK picker |

Eleven rows connect today. Tau, DeepSeek Harness, and DeepAgents switch to a
SuperQode-hosted adapter and then run the model you choose. OpenCode, Grok
Build, Qwen Code, Kimi Code, fast-agent, Pi, Prime Agent, and fx keep their
own loop: the model step only decides which credentials they are handed, and
SuperQode passes those to the agent process alone rather than exporting them
into your shell. fx skips the model picker entirely and injects
`AI_GATEWAY_API_KEY` into the child. Prime is reached over its Python RPC
backend rather than ACP, so a local pick is registered in Prime's own
`models.json` instead of being passed as an environment variable.

The remaining rows print a setup card naming the key or local model to
configure in the harness itself. Every id in the table also works as
`superqode --connect <id>` and completes in the TUI.

A key is only ever passed under a variable that is known to be read: the one
the catalog records for that harness, or the provider's own documented variable
for a model-agnostic agent. When you pick a local endpoint that neither names,
the agent still attaches and SuperQode says the model has to be set inside it,
rather than exporting an endpoint under a name the agent ignores.

Pre-ladder names still resolve, so muscle memory and older documentation keep
working. `:connect subscriptions` lands on the vendor subscription screen, and
`:connect local`, `:connect byok`, and `:connect acp` go straight to their
screens without passing through the root question.

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
| xAI Grok | Grok Build ACP, Grok headless CLI, Grok subscription models, xAI BYOK | `:connect grok`, `:runtime grok-cli`, `:grok api [model]`, `:connect byok xai <model>` |
| OpenCode | OpenCode ACP, OpenCode Zen BYOK | `:connect acp opencode`, `:connect byok opencode <model>` |
| Z.AI GLM | Z.AI BYOK, GLM Coding Plan ACP | `:connect byok zai <model>`, `:connect glm-cli`, `:connect acp glm` |
| Poolside | Pool CLI ACP, Laguna S 2.1 through DwarfStar or llama.cpp | `:connect acp poolside`, `:connect local ds4 laguna-s-2.1` |
| Moonshot AI Kimi | Kimi Code ACP, Moonshot BYOK | `:connect kimi-code`, `:connect byok moonshot kimi-k3` |
| Alibaba Qwen | Qwen Code ACP, DashScope BYOK, local Qwen models | `:connect qwen-code`, `:connect byok alibaba <model>`, `:connect local ollama qwen3:8b` |
| LangChain [DeepAgents](../providers/deepagents.md) | Deep Agents Code ACP, DeepAgents SDK runtime, bare Deep Agent ACP | `:connect deepagents-code`, `superqode harness run deepagents "..."`, `:connect acp deepagents` |
| DeepSeek | DeepSeek BYOK, local DeepSeek and DS4 model paths | `:connect byok deepseek <model>`, `:connect local ds4 <model>` |
| Mistral AI | Mistral Vibe ACP, Mistral BYOK, local Mistral models | `:connect acp mistral-vibe`, `:connect byok mistral <model>` |
| MiniMax | MiniMax BYOK, local MiniMax model paths | `:connect byok minimax <model>`, `:connect local <provider> <model>` |
| Meta | [Muse Code](../providers/muse-code.md) sign-in, Meta first-party BYOK, local Meta model paths | `:connect muse`, `:connect muse-key`, `:connect byok meta muse-spark-1.1`, `:connect local <provider> <model>` |
| Cursor | Cursor subscription through Cursor CLI ACP | `:connect cursor`, `:connect acp cursor` |
| Amp | Amp subscription through its ACP adapter | `:connect amp`, `:connect acp amp` |
| Cline | Cline CLI ACP | `:connect acp cline` |
| Factory | Factory Droid subscription through ACP, or `FACTORY_API_KEY` on Closed | `:connect droid`, `:connect droid-key`, `:connect acp droid` |
| Qoder | Qoder CLI personal access token on Closed | `:connect qoder-key` |
| Poolside | Poolside API key or local OpenAI-compat on Closed | `:connect poolside-key` |
| Z.AI | ZCode desktop harness, inspect only until a CLI/ACP surface exists | `:connect zcode` |
| Cognition | Devin ACP, Devin CLI runtime | `:connect devin`, `:connect acp devin`, `:runtime devin-cli` |
| JetBrains | Junie on a JetBrains AI plan, or `JETBRAINS_API_KEY` on Closed | `:connect junie`, `:connect junie-key`, `:connect acp junie` |
| Vercel fx | fx ACP on a Vercel login, or `AI_GATEWAY_API_KEY` on Open | `:connect fx`, `:connect fx-key`, `:connect acp fx` |
| Letta | Letta Code on Open: Letta Cloud, a provider key, or a local model | `:connect letta` |
| Warp | Warp Agent CLI on Open: Warp account or `WARP_API_KEY` | `:connect warp` |
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
| DeepAgents | `deepagents` | Deep Agents Code | `deepagents-code` |
| Devin | `devin` | Dirac | `dirac` |
| Factory Droid | `droid` | fast-agent | `fast-agent` |
| fount | `fount` | fx | `fx` |
| Gemini CLI | `gemini` | GLM Agent | `glm` |
| Goose | `goose` | Grok Build | `grok` |
| Harn | `harn` | Hermes Agent | `hermes` |
| JetBrains Junie | `junie` | Kilo | `kilo` |
| Kimi Code | `kimi` | Kiro CLI | `kiro` |
| LLMling-Agent | `llmlingagent` | Minion Code | `minion` |
| Mistral Vibe | `mistral-vibe` | OpenClaw | `openclaw` |
| OpenCode | `opencode` | OpenHands | `openhands` |
| Pi | `pi` | Poolside | `poolside` |
| Prime Agent | `prime-agent` | Qoder CLI | `qoder` |
| Qwen Code | `qwen` | siGit Code | `sigit` |
| Stakpak | `stakpak` | stdio Bus | `stdio-bus` |
| VT Code | `vtcode` | | |

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

Factory (`factory`) is a harness-only credential slot for
`:connect droid-key` (`superqode auth login factory`). It is not listed
under `:connect byok`.

The `grok-cli` *provider* is an authenticated subscription route used by
`:grok api`; it is not an API-key BYOK provider. The `grok-cli` *runtime* is
the headless `grok -p` vendor loop (`:runtime grok-cli`).

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
