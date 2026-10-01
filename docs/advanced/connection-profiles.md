# Connection Profiles

Connection profiles determine how SuperQode connects to model providers and
agent runtimes. Each profile has a connector type, optional runtime, local
availability check, and the menu it appears on.

The root screen offers an existing agent, a SuperQode harness with your model,
or a harness you build. Agent menus include subscriptions, Open/Closed
harnesses and the ACP catalog. Selecting a SuperQode harness opens its model
sources: local, BYOK and subscriptions/accounts. Every profile stays reachable
by name, so `:connect codex` does not require navigating the menus.

## Model and agent sources (`:connect`)

### 1. Local (connector: local, runtime: builtin)

Connects to local/self-hosted model servers. Opens a local provider picker (Ollama, MLX, LM Studio, vLLM, SGLang, TGI, DS4). Keeps the selected native harness.

### 2. ACP (Agent Client Protocol) (connector: acp-picker)

Opens an interactive picker showing installed and featured ACP agents. The
complete discovered registry remains available through `:connect acp all`.
No model auth setup is needed before browsing the catalog.

### 3. BYOK (Bring Your Own Key) (connector: byok, runtime: builtin)

Brings your own API key. Opens a cloud provider picker, then model selector.
Keeps the selected native harness. Credential detection checks configured
credentials; account access is verified by the provider on the first request.

### 4. Subscriptions (connector: subscription-picker)

Opens the vendor screen below. Always available. Esc returns to the root
screen.

### 5. Open and Closed Harnesses

`v2` is the default. The agents screen lists two harness sources rather than
one combined row. Open vs Closed is the harness licence, not the model family.

`v1` (`SUPERQODE_CONNECT_MENU=v1` or `"connect_menu": "v1"` in
`~/.superqode/config.json`) restores the older single **Other harnesses** row:
optional integrations that are neither main connection profiles nor ACP
agents, with Hugging Face Tau shown alongside its live installation status.

- **Open harnesses** (`:connect open-harnesses`): OSI-licensed harnesses.
  Connect with a provider key or a local model. Includes Tau, DeepSeek
  Harness, DeepAgents SDK, OpenCode, Prime Agent, jcode, Grok Build, Qwen
  Code, fast-agent, Pi, Goose, Cline, OpenHands, Mistral Vibe, Hermes Agent,
  Letta Code, Kimi Code, and fx.
- **Closed harnesses** (`:connect closed-harnesses`): proprietary harnesses
  on that vendor's key. Includes Factory Droid, Junie, Muse Code, Qoder CLI,
  Poolside, and Warp Agent (setup guidance only).

`:connect other-harnesses` still works; it opens the Open list.

## Native model subscriptions

The SuperQode model-source picker offers **Local**, **BYOK** and
**Use your subscription (Experimental)**. Every experimental provider card
is labelled **Partner integration in progress**. Alibaba Token Plan, Grok,
Kimi Code models, MiniMax Token Plan and OpenAI/ChatGPT are information-only
entries: selecting one does not authenticate, switch harnesses or connect a
model. Provider access and integration still need confirmation and testing.
Claude/Anthropic subscription access is excluded.

Vendor agent accounts remain under **Existing harnesses → Subscriptions**.
Existing native model-plan shortcuts below remain directly available for
compatibility; they are separate from the experimental cards.

| Source | Route |
| --- | --- |
| MiniMax Token Plan | `:connect plan-minimax`: native model access using `MINIMAX_TOKEN_PLAN_API_KEY` with an `sk-cp` key, or `superqode auth login minimax-token-plan`. Uses `https://api.minimax.io/v1`; ordinary MiniMax/OpenAI keys cannot substitute. |
| Grok account | `:connect plan-grok` / `:grok api`: native model access using the Grok CLI session. |

Codex, Copilot, Kimi Code and other vendor agents retain their own coding
loops. Select them under Existing harnesses. OpenCode Zen, Ollama Cloud and
DeepSeek API credits use BYOK. GLM and Alibaba Coding Plans require their
supported-agent setup rather than appearing as native Core/RLM model sources.
Older direct `plan-*` shortcuts remain supported for existing configurations;
they are omitted from the model-source picker and its completion list.

The [Z.AI supported-tool guidance](https://docs.z.ai/devpack/tool/others) and
[Alibaba Coding Plan instructions](https://www.alibabacloud.com/help/en/model-studio/coding-plan)
define the external-agent setup requirements. Native MiniMax routing follows
its [Token Plan guidance](https://platform.minimax.io/subscribe/token-plan) and
[OpenAI-compatible API](https://platform.minimax.io/docs/api-reference/text-openai-api).

OpenCode, fast-agent, Pi and omp also offer an **configured agent account**
row after selecting their Open harness. Their own configuration supplies the
account and model. For fast-agent, run `fast-agent auth provider login codex`;
SuperQode launches the account route with `FAST_AGENT_MODEL=codexplan`, including
on reconnect. See [fast-agent's model setup](https://fast-agent.ai/models/).
BYOK/local launch settings remain isolated from these account connections.

Plan and account shortcuts select an interactive TUI route. For a headless
native model run, supply the provider and model explicitly, for example
`superqode --provider minimax-token-plan --model MiniMax-M3 -p "review this"`.
The same plan credential is required; an interactive shortcut cannot silently
fall through to a default API provider.

## Billing and reconnect status

ACP is a transport, not an authentication or billing method. Pi, OpenCode and
omp account connections use the agent's configured provider; SuperQode shows
billing as **agent-managed, unverified**. Installing an agent or finding a
credential does not verify a subscription plan. Fast-agent's account route
keeps the explicit `codexplan` configuration.

Saved connections store transport, authentication, requested billing and
verification separately. Old `auth_mode="acp"` values become agent-managed,
with billing unverified. Verification is checked again on reconnect. Runtime
and model choices are preserved, and an unsupported saved route stops instead
of reconnecting to an older BYOK route.

Copilot account launches ignore provider overrides such as
`COPILOT_PROVIDER_API_KEY`, `COPILOT_PROVIDER_BASE_URL` and
`COPILOT_PROVIDERS_CONFIG`. An explicit `COPILOT_GITHUB_TOKEN` supplies identity;
it does not opt into BYOK. Account quota and billing remain unverified when
GitHub does not expose them. Expired login and quota errors are returned to the
user without a SuperQode API-billing fallback.

## Vendor agents (`:connect subscriptions`)

### Codex Subscription (connector: runtime, runtime: codex-sdk)

Self-contained: brings its own model and auth via Codex login. Requires the
`openai_codex` package; live ChatGPT authentication is checked on connection
and before each prompt. Credential-file existence does not verify access.

### Claude Agent SDK (API key)

Claude is available from the ACP catalog (`:connect acp claude`) and through
the explicit API-key runtime (`:runtime claude-agent-sdk`). It is currently
absent from the Subscriptions menu; `--connect claude` is not a valid profile.

### Gemini CLI (connector: acp, agent: gemini)

Use `:connect gemini-cli` for Google AI Pro / Ultra or Code Assist through
Google sign-in over ACP. Install with `npm install -g @google/gemini-cli`, then
run `gemini` and choose **Sign in with Google** using the account associated
with your plan. The subscription route ignores exported Gemini API keys and
the Vertex AI routing flag in the child process, and reports the ignored
variables. `:connect acp gemini` remains the general ACP route.

### Cursor Subscription (connector: acp, agent: cursor)

Uses the signed-in Cursor Agent CLI and its native ACP mode.

### Amp Subscription (connector: acp, agent: amp)

Uses the signed-in Amp CLI through the `acp-amp` adapter.

### Antigravity CLI (connector: runtime)

Uses the `antigravity-cli` runtime to drive `agy` with Google Sign-In.
Requires a compatible `agy` binary on PATH.

### Grok Subscription (connector: acp, agent: grok)

Runs **Grok Build**, xAI's own coding agent, on an eligible SuperGrok or X Premium+ account. The vendor's agent owns the loop. Requires the `grok` binary on PATH and a local `grok login` (`~/.grok/auth.json`). SuperQode starts `grok agent stdio` over ACP.

To run **SuperQode's own harness** on the same subscription instead, use `:grok api [model]`. That imports the CLI session token into SuperQode's auth store and routes through the `grok-cli` provider (CLI chat proxy). The live catalog default is whatever `grok models` reports (currently grok-4.6). The `grok-cli` *runtime* (`:runtime grok-cli`) is the headless `grok -p` path and is not what Subscriptions opens.

### GitHub Copilot (connector: copilot)

One visible subscription entry. It prefers the official GitHub Copilot SDK
(`copilot-sdk`) for SuperQode-native harness controls and falls back to the
installed official CLI (`copilot --acp --stdio`) when the SDK is absent.

### Devin (connector: acp, agent: devin)

Runs Cognition's Devin CLI through `devin acp`. Requires the `devin` command
and a completed `devin auth login`. Devin owns its own credential store.

### Factory Droid Subscription (connector: acp, agent: droid)

Uses Factory Droid through its locally authenticated CLI and ACP mode.

### Factory Droid API key (connector: vendor-key, profile: droid-key)

Uses Factory Droid with `FACTORY_API_KEY` from the environment or
`superqode auth login factory`. The key is injected into the child ACP process
only. This is the Closed harnesses row, not the Droid CLI login.

```text
:connect droid-key
```

### Kiro Subscription (connector: acp, agent: kiro)

Uses a Kiro or Amazon Q Developer plan through Kiro CLI's vendor-managed sign-in.

### GLM Coding Plan (connector: acp, agent: glm)

Runs `glm-acp-agent` with a paid GLM Coding Plan. The Z.AI general API remains
available under `:connect byok zai`.

### Qwen Code (connector: acp, agent: qwen)

Runs QwenLM's first-party Qwen Code agent through its stable ACP mode. Requires
the `qwen` command and authentication from `qwen auth`.

### Kimi Code (connector: acp, agent: kimi)

Runs Moonshot AI's first-party Kimi Code agent through `kimi acp`. Requires the
`kimi` command and a completed Kimi Code `/login`.

### fx (connector: acp, agent: fx)

Runs Vercel Labs' experimental fx agent through `fx acp`. Requires the `fx`
binary and a local `fx login` (`~/.fx/auth.json`). Models are billed as the
signed-in Vercel team's AI Gateway credits. SuperQode strips
`AI_GATEWAY_API_KEY` on this route so a leftover key cannot divert the
session.

### fx API key (connector: vendor-key, profile: fx-key)

Uses fx with `AI_GATEWAY_API_KEY` from the environment or `fx setup`. The
key is injected into the child ACP process only. This is the Open harnesses
row, not the Vercel login, and not a SuperQode BYOK or local model picker.

```text
:connect fx-key
```

## TUI Usage

In the TUI, use `:connect` to open the root screen. Navigate with arrows or
number keys. Esc returns to the previous screen. Availability means the local
adapter is installed or its credentials are configured; vendor sign-in and
model entitlement are verified on first use. Setup-only integrations explain
their limitation rather than claiming an executable connection.

Optional SDK installation hints target the running Python environment and
retain the installed SuperQode version. Public fresh-install instructions use
`uv tool install "superqode[EXTRA]"`. ACP registry refresh preserves versioned
package requirements, launch arguments and environment defaults. Binary-only
agents show the matching platform archive, checksum when published, and manual
PATH setup instructions.

Direct shortcuts:

- `:connect subscriptions` - open the vendor screen
- `:connect codex` - connect Codex SDK directly
- `:connect grok` - Grok Build on your X/SuperGrok login (ACP)
- `:connect amp` - Amp subscription through ACP
- `:connect antigravity` - Google's Antigravity CLI
- `:connect devin` - Cognition Devin CLI over ACP
- `:connect droid` - Factory Droid subscription through ACP
- `:connect droid-key` - Factory Droid with `FACTORY_API_KEY` (Closed harnesses)
- `:connect junie` - JetBrains Junie on a JetBrains AI / Junie plan (Subscriptions)
- `:connect junie-key` - Junie with `JETBRAINS_API_KEY` (Closed harnesses)
- `:connect muse-key` - Muse Code with `META_API_KEY` (Closed harnesses)
- `:connect qoder-key` - Qoder CLI with `QODER_PERSONAL_ACCESS_TOKEN` (Closed harnesses)
- `:connect poolside-key` - Poolside with `POOLSIDE_API_KEY`, or a local endpoint through `POOLSIDE_STANDALONE_BASE_URL` (Closed harnesses)
- `:connect zcode` - ZCode inspect card (Closed harnesses; not launchable yet)
- `:connect letta` - Letta Code setup card (Open harnesses; install `letta`, then `/connect` or `/login`)
- `:connect warp` - Warp Agent CLI setup card (Open harnesses; install `warp`, then sign in or `WARP_API_KEY`)
- `:connect opencode-key` - pick a key or local model, then attach OpenCode over ACP with it (Open harnesses)
- `:connect grok-key` - Grok Build with `GROK_CODE_XAI_API_KEY`, or a local endpoint (Open harnesses)
- `:connect qwen-code-key` - Qwen Code with `QWEN_API_KEY` / `DASHSCOPE_API_KEY`, or a local endpoint (Open harnesses)
- `:connect fast-agent` - pick a key or local model, then attach fast-agent over ACP with it (Open harnesses)
- `:connect pi` - pick a key or local model, then attach Pi over ACP with it (Open harnesses)
- `:connect fx` - Vercel fx on a Vercel login over ACP (AI Gateway credits)
- `:connect fx-key` - fx with `AI_GATEWAY_API_KEY` (Open harnesses; not a local model)
- `:fx` / `:fx status` - TUI readiness for install and Vercel login
- `:fx login` - consent-gated `fx login`
- `:fx connect` - same as `:connect fx`
- `:connect kiro` - Kiro/Amazon Q Developer subscription through ACP
- `:connect glm-cli` - GLM Coding Plan through ACP
- `:connect copilot` - prefer the official SDK, with installed CLI/ACP fallback
- `:connect acp copilot` - advanced Copilot CLI ACP compatibility path
- `:connect other-harnesses` - v1: optional non-ACP harnesses such as Tau; v2: opens Open harnesses
- `:connect open-harnesses` - Open list (v2)
- `:connect closed-harnesses` - Closed list (v2)
- `:copilot models` - list models available to the signed-in Copilot account
- `:runtime claude-agent-sdk` - explicit Anthropic API-key SDK runtime
- `:connect antigravity` - use `agy` headless mode with its Google Sign-In/keyring
- `:connect byok google` - use a Google API key through the BYOK path
- `:runtime antigravity-sdk` - optional direct Antigravity SDK/API-key runtime
- `:connect grok` - Grok Build, xAI's own coding agent, on your subscription (ACP)
- `:grok api [model]` - SuperQode's harness on the same subscription (opt-in)
- `:connect qwen-code` - QwenLM's first-party Qwen Code agent over ACP
- `:connect kimi-code` - Moonshot AI's first-party Kimi Code agent over ACP
- `:connect byok` - open the cloud provider picker
- `:connect byok <provider>/<model>` - connect to a cloud model directly
- `:connect <model>` - connect by model name alone (e.g. `:connect gpt-5.6`); the provider is resolved from the catalog, preferring first-party providers over gateway mirrors
- `:connect local` - open the local provider picker
- `:connect local <provider>/<model>` - connect to a local model directly
- `:connect acp` - open the ACP agent picker
- `:connect acp <agent>` - connect to an ACP agent directly

Special syntax: `:connect byok -` (previous), `:connect byok !` (history), `:connect byok last` (reconnect).

## CLI Usage

Use `--connect` / `-C` global flag:

```bash
superqode --connect codex --print "review this"
superqode --connect copilot --print "review this"
superqode --connect acp copilot
superqode --runtime claude-agent-sdk --print "summarize changes"
superqode --connect grok
```

Use `superqode connect` subcommands:

```bash
superqode connect acp opencode
superqode connect byok anthropic <anthropic-model>
superqode connect local ollama qwen3:8b
superqode connect setup deepseek --json
```

## Runtime Mapping

- Codex profile -> runtime: codex-sdk
- GitHub Copilot profile -> SDK runtime when installed, otherwise `copilot-cli` runtime
- Explicit `:copilot sdk` / `:copilot cli` -> force either official route
- Claude API-key runtime -> claude-agent-sdk
- Gemini CLI subscription -> Gemini CLI ACP subprocess using Google sign-in
- BYOK/Local -> runtime: builtin
- ACP -> no runtime change (ACP subprocess)
- Antigravity -> antigravity-cli runtime
- Grok subscription (`:connect grok`) -> Grok Build ACP subprocess (`grok agent stdio`)
- Grok headless (`:runtime grok-cli`) -> `grok -p --output-format streaming-json`
- Grok via SuperQode harness (`:grok api`) -> `grok-cli` provider + CLI session token
- Qwen Code -> Qwen Code ACP subprocess (`qwen --acp`)
- Kimi Code -> Kimi Code ACP subprocess (`kimi acp`)
- Advanced -> user picks runtime

When --connect implies a runtime, it sets SUPERQODE_RUNTIME but does not override an explicit --runtime flag.
