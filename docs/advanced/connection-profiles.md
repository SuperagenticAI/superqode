# Connection Profiles

Connection profiles determine how SuperQode connects to model providers and
agent runtimes. Each profile has a connector type, optional runtime, local
availability check, and the menu it appears on.

Profiles are split across two screens. The root screen holds the three ways
SuperQode's own harness runs a model plus two submenus. The subscriptions
screen holds the vendor coding agents. Every profile stays reachable by name
regardless of the screen it appears on, so `:connect codex` never requires a
detour through the submenu.

## Root Screen (`:connect`)

### 1. Local (connector: local, runtime: builtin)

Connects to local/self-hosted model servers. Opens a local provider picker (Ollama, MLX, LM Studio, vLLM, SGLang, TGI, DS4). Always available.

### 2. ACP (Agent Client Protocol) (connector: acp-picker)

Opens an interactive picker showing installed and featured ACP agents. The
complete discovered registry remains available through `:connect acp all`.
No model auth setup is needed before browsing the catalog.

### 3. BYOK (Bring Your Own Key) (connector: byok, runtime: builtin)

Brings your own API key. Opens a cloud provider picker, then model selector. Uses builtin runtime. detect() checks for configured provider credentials.

### 4. Subscriptions (connector: subscription-picker)

Opens the vendor screen below. Always available. Esc returns to the root
screen.

### 5. Other Harnesses (connector: harness-picker)

Opens a focused list of optional harness integrations that are neither main
connection profiles nor ACP agents. Hugging Face Tau appears here with its live
installation status.

## Subscriptions Screen (`:connect subscriptions`)

### Codex Subscription (connector: runtime, runtime: codex-sdk)

Self-contained: brings its own model and auth via Codex login. Requires openai_codex package and ~/.codex/auth.json. Auto-connects on selection.

### Claude Code Subscription (connector: acp, agent: claude)

Uses the locally authenticated Claude Code ACP adapter. The vendor adapter owns
the subscription login and credential store. The API-key SDK remains available
explicitly through `:runtime claude-agent-sdk`.

### Cursor Subscription (connector: acp, agent: cursor)

Uses the signed-in Cursor Agent CLI and its native ACP mode.

### Amp Subscription (connector: acp, agent: amp)

Uses the signed-in Amp CLI through the `acp-amp` adapter.

### Antigravity CLI (connector: runtime)

Handoff profile: shows the command to run `agy` in a terminal. Does not connect SuperQode's own loop. Requires agy binary on PATH.

### Grok Subscription (connector: acp, agent: grok)

Runs **Grok Build**, xAI's own coding agent, on an eligible SuperGrok or X Premium+ account. The vendor's agent owns the loop. Requires the `grok` binary on PATH and a local `grok login` (`~/.grok/auth.json`). SuperQode starts `grok agent stdio` over ACP.

To run **SuperQode's own harness** on the same subscription instead, use `:grok api [model]`. That imports the CLI session token into SuperQode's auth store and routes through the `grok-cli` provider (CLI chat proxy). The live catalog default is whatever `grok models` reports (currently grok-4.6). The `grok-cli` *runtime* (`:runtime grok-cli`) is the headless `grok -p` path and is not what Subscriptions opens.

### GitHub Copilot (connector: copilot)

One visible subscription entry. It prefers the official GitHub Copilot SDK
(`copilot-sdk`) for SuperQode-native harness controls and falls back to the
installed official CLI (`copilot --acp --stdio`) when the SDK is absent.

### Gemini CLI (connector: acp, agent: gemini)

Runs Google's Gemini CLI through `gemini --acp`. Requires the `gemini` command
and either its sign-in or `GEMINI_API_KEY`. Consumer Google AI accounts should
use Antigravity instead.

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

## TUI Usage

In the TUI, use `:connect` to open the root screen. Each profile shows
availability status. Navigate with arrows or number keys. Enter on
**Subscriptions** opens the vendor screen, and Esc there returns to the root
screen instead of leaving the flow. `H` still opens the Other Harnesses picker
from the root screen.

Direct shortcuts:

- `:connect subscriptions` - open the vendor screen
- `:connect codex` - connect Codex SDK directly
- `:connect cursor` - Cursor subscription through ACP
- `:connect amp` - Amp subscription through ACP
- `:connect acp gemini` - Google Gemini CLI over ACP (API-key route, not a subscription)
- `:connect devin` - Cognition Devin CLI over ACP
- `:connect droid` - Factory Droid subscription through ACP
- `:connect droid-key` - Factory Droid with `FACTORY_API_KEY` (Closed harnesses)
- `:connect junie` - JetBrains Junie on a JetBrains AI / Junie plan (Subscriptions)
- `:connect junie-key` - Junie with `JETBRAINS_API_KEY` (Closed harnesses)
- `:connect muse-key` - Muse Code with `META_API_KEY` (Closed harnesses)
- `:connect qoder-key` - Qoder CLI with `QODER_PERSONAL_ACCESS_TOKEN` (Closed harnesses)
- `:connect poolside-key` - Poolside with `POOLSIDE_API_KEY` (Closed harnesses)
- `:connect zcode` - ZCode inspect card (Closed harnesses; not launchable yet)
- `:connect letta` - Letta Code setup card (Open harnesses; install `letta`, then `/connect` or `/login`)
- `:connect warp` - Warp Agent CLI setup card (Open harnesses; install `warp`, then sign in or `WARP_API_KEY`)
- `:connect kiro` - Kiro/Amazon Q Developer subscription through ACP
- `:connect glm-cli` - GLM Coding Plan through ACP
- `:connect copilot` - prefer the official SDK, with installed CLI/ACP fallback
- `:connect acp copilot` - advanced Copilot CLI ACP compatibility path
- `:connect other-harnesses` - browse optional non-ACP harnesses such as Tau
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
superqode -C claude --print "summarize changes"
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
- GitHub Copilot profile -> SDK runtime when installed, otherwise Copilot ACP subprocess
- Explicit `:copilot sdk` / `:copilot cli` -> force either official route
- Claude profile -> runtime: claude-agent-sdk
- BYOK/Local -> runtime: builtin
- ACP -> no runtime change (ACP subprocess)
- Antigravity -> handoff (no runtime)
- Grok subscription (`:connect grok`) -> Grok Build ACP subprocess (`grok agent stdio`)
- Grok headless (`:runtime grok-cli`) -> `grok -p --output-format streaming-json`
- Grok via SuperQode harness (`:grok api`) -> `grok-cli` provider + CLI session token
- Qwen Code -> Qwen Code ACP subprocess (`qwen --acp`)
- Kimi Code -> Kimi Code ACP subprocess (`kimi acp`)
- Advanced -> user picks runtime

When --connect implies a runtime, it sets SUPERQODE_RUNTIME but does not override an explicit --runtime flag.
