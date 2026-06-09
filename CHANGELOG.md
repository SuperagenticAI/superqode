# Changelog

All notable changes to SuperQode will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.40] - 2026-06-09

### Added

- **Multi-repo search** — `:workspace add|remove|list` registers repositories (persisted in `~/.superqode/workspace.json`); grep/glob gain an `all_repos` fan-out that searches every registered repo in one ripgrep pass, labeling matches by repo. Absolute paths are honored inside the workspace and permission-gated outside it (`SUPERQODE_ALLOW_EXTERNAL_SEARCH`).
- **Harness over MCP** — `superqode mcp` (stdio, or `--http`) exposes HarnessSpec workflows as MCP tools (`list_harnesses`, `describe_harness`, `run_harness`) for any MCP client, alongside the existing A2A and ACP servers.
- **Adaptive context compaction** — compaction threshold and kept-recent window now auto-scale to the model's real context window and run by default (`SUPERQODE_AUTO_COMPACT=0` to disable).
- **Local context-window detection** — probes the live server for the *loaded* window per backend (Ollama `/api/ps`, llama.cpp `/props`, LM Studio `/api/v1/models`, vLLM/DS4 `/v1/models`). New `:context` command to show/pin/re-detect the window.
- **Post-edit verification** — fast per-file diagnostics (ruff/py_compile, eslint, gofmt, JSON/YAML) run after the agent edits a file, with findings fed back so it self-corrects (`SUPERQODE_VERIFY_EDITS`, `SUPERQODE_FORMAT_ON_EDIT`).
- **Dangling tool-call repair** — synthesizes a tool result for any unanswered tool call (interrupted/cancelled/malformed/resumed), keeping the message history provider-valid.
- **Thinking-log verbosity** — `:thinking normal|verbose|off` (Ctrl+T cycles); calm default folds iterations into a live status with a tidy per-tool trace.
- Documentation: new *Local Context & Compaction* and *Multi-Repo Search & Edit Safety* guides; harness-over-MCP docs.

### Changed

- **Search tools** — grep/glob now spawn ripgrep directly with structured `--json` output (no shell), report truncation/partial results, and steer the model toward subagents for open-ended search.
- **Welcome screen & input box** — responsive centered layout, refreshed messaging, thicker titled prompt box, and trimmed hints bar.

### Fixed

- Streaming agent loop now compacts context — local/BYOK sessions no longer overflow the window (the streaming path previously never compacted).

## [0.1.39] - 2026-06-06

### Added

- **Plan mode** — new `plan_mode` config flag that blocks tool execution in the agent loop, allowing side-effect-free planning and review before any action is taken.
- **Memory system overhaul** — new provider-based memory architecture with `LocalAgentMemoryProvider`, `SpecMemProvider`, `Mem0Provider`, `CogneeProvider`, and `SupermemoryProvider`. Configurable via `memory:` section in `superqode.yaml` with provider-specific settings.
- **Project trust system** — per-user trust store (`~/.superqode/trust.json`) for project workspaces, with risk signal detection for plugins, MCP configs, and hooks. Mark projects trusted/safe via `set_project_trust()`.
- **Transcript export** — conversation transcripts can now be exported to portable JSON/text formats via `transcript_export.py`.
- **Session share artifacts** — new `share_artifacts` module for sharing session context across agents.
- **Pure mode** — `pure_mode.py` for restricted/safe agent operation.
- **Developer workflow documentation** — new `docs/developer-workflows.md` guide.
- **Plan mode tests** (`test_agent_loop_harness.py`), **memory tests** (`test_agent_memory.py`), **project trust tests** (`test_project_trust.py`), **developer workflow doc tests** (`test_developer_workflow_docs.py`), and expanded runtime tests.

### Changed

- `AgentLoop` now checks `config.plan_mode` before executing tools, returning a denied result when active.
- Memory `__init__.py` exports a unified `create_memory_provider()` factory and `available_memory_providers()` discovery function.
- Slash completions, TUI widgets, and QE commands updated for plan mode awareness.

## [0.1.38] - 2026-06-06

### Added

- **OpenAI Codex SDK runtime** (`codex-sdk`) — drive OpenAI Codex from SuperQode using your ChatGPT/Codex login (`~/.codex`), no API key required. A self-contained runtime that owns its own model and auth, with streamed harness events, tool cards, and approval prompts. Models `gpt-5.5` / `gpt-5.4` / `gpt-5.4-mini`. Install with `pip install "superqode[codex-sdk]"`.
- **`:codex` command surface** — `status`, `models`, `model`, `effort`, `sandbox`, `review`, `compact`, plus full thread/session management (`thread`, `sessions`, `resume`, `fork`, `rename`, `archive`, `account`).
- **Claude Agent SDK runtime** (`claude-agent-sdk`) — drive Claude Code from SuperQode using your Anthropic API key (`ANTHROPIC_API_KEY`); the adapter maps the SDK's message/block and permission shapes to SuperQode's harness, with tool cards and approvals. Install with `pip install "superqode[claude-agent-sdk]"` (plus the Claude Code CLI).
- **`:claude` command surface** — `status`, `model`, `permission`, `sessions`, `commands`, `review`.
- **Connection profiles in `:connect`** — product/account-first connection sources (ACP agent, BYOK provider, Local model, Codex subscription, Claude Agent SDK, Antigravity CLI, Advanced runtime) with per-source availability detection, so picking *what* to connect to is separated from the underlying execution engine (`providers/connection_profiles.py`).
- **Antigravity CLI handoff** (`:antigravity` / `:agy`) — `status`, `migrate`, `launch` for Google's local `agy` CLI, offered as a recommended Gemini CLI migration path.
- **Programmatic SDK helpers** — `superqode.codex` (`run_codex`, `stream_codex`, `codex_session`) and `superqode.claude` (`run_claude`, `stream_claude`, `claude_session`) for running Codex/Claude one-shot, streaming typed harness events, or in multi-turn sessions without hand-building an `AgentConfig`. See `examples/codex_sdk_quickstart.py`.
- **Runtime + model status badges** in the TUI status bar, so the active runtime (e.g. `codex-sdk`) and model are always visible.

### Changed

- **`:connect` is now product-first** — the menu leads with the connection source (ACP → BYOK → Local → Codex → Claude → Antigravity → Advanced); the raw runtime/engine picker moved under *Advanced runtime*.
- **`:runtime`** extended to select the new self-contained runtimes (`codex-sdk`, `claude-agent-sdk`) alongside `builtin` / `openai-agents` / `pydanticai` / `adk`, with `:runtime list` reporting availability.
- Prompt completion and slash-command surfaces updated for the new `:codex`, `:claude`, `:antigravity`, and `:connect <source>` commands.
- Dependencies: `openai-codex` pinned to `>=0.1.0b2,<0.2.0`; added `claude-agent-sdk>=0.2.9,<0.3.0` (under the `claude-agent-sdk` extra).

## [0.1.36] - 2026-06-03

### Added

- **Local OS command sandbox** confining shell commands with the operating system's own isolation — macOS Seatbelt (`sandbox-exec`) and Linux Bubblewrap (`bwrap`). Modes via `SUPERQODE_SANDBOX` (`off`, `workspace-write`, `read-only`, `danger-full-access`) and the `:sandbox` command. See [Safety & Permissions](docs/advanced/safety-permissions.md#local-command-sandbox-os-level).
- **Command safety classification** that auto-runs known read-only commands (no prompt), gates writes/network, and blocks destructive ones. Obfuscation-aware: commands are canonicalised before analysis, and dynamic constructs (`$(...)`, backticks, `eval`, pipe-to-shell) can never be classified safe.
- **Network destination allowlist** so trusted installs (PyPI, npm, crates, GitHub, …) run without prompts while arbitrary egress is gated. Extendable via `SUPERQODE_NET_ALLOW`; `SUPERQODE_NET_STRICT` denies untrusted destinations.
- **Rewind & transcript overlay** (`Ctrl+R`, double-`Esc`, or `:rewind`) that truncates the agent's stored history to an earlier message and reloads it for editing.
- **`@` file mentions** — a live fuzzy file picker in the prompt that inlines referenced file contents on submit.
- **Live streaming markdown** so assistant responses render formatted as they stream.
- **`:theme`** picker with multiple accent themes (persisted to `~/.superqode/config.json`).
- **`:export`** to write the conversation to a self-contained HTML file.
- **`:compare <models>`** to re-run the last message across several models/runtimes concurrently and read the answers side by side.
- **`create_skill` tool** making the agent self-extensible — it can author a new `SKILL.md` that is hot-loaded and immediately invocable.
- **BYOK via models.dev** — a dynamic provider catalog and on-the-fly provider synthesis (`providers/catalog.py`, `providers/dynamic.py`) so any models.dev provider can be connected with an API key, with new models appearing without manual edits. Live `/v1/models` discovery (`providers/live_models.py`) lists a provider's currently-available models.
- **Hugging Face model toolchain** (`providers/huggingface/fetch.py`, `convert.py`) — Hub search, dry-run size preview, resumable downloads, local cache scan/delete, and MLX convert + upload. The converter auto-detects text (mlx-lm) vs multimodal (mlx-vlm) models.
- **`superqode models` command group** — `hub`, `download`, `show`, `providers`, `convert-mlx`, `cached`, `rm`, plus `connect setup` guidance.
- **In-process MLX engine** (`providers/local/mlx_engine.py`, `_mlx_worker.py`) with a family-aware tool-call parser (`mlx_tools.py`) for Qwen / Gemma / generic-JSON formats.
- **Gemma-optimized harness profiles** — the model policy routes the whole tool-capable Gemma family (Gemma 3 and 4) to a Gemma-tuned profile (minimal system prompt, strict-JSON tool calls).

### Changed

- Unified the product tagline to **"Your Portable Coding Agent Harness"** across the TUI welcome screen, README, docs, and package metadata, with a refreshed welcome subheading.
- Updated the README header image and documentation logo.
- **Family-based local tool gating** — Gemma 3/4, Qwen 2.5/3, and Llama 3.1+/4 get tools; Gemma 1/2 and Llama 3.0 do not. The agent loop falls back to family detection for custom local tags not in the model registry.
- **Gemma context windows** — modern Gemma (3/4) now use a practical 32K `num_ctx` (matching the Llama/Qwen treatment) instead of the legacy 8K, and Ollama reports their true 128K capability; Gemma 1/2 stay at 8K.
- Dependencies: `mlx-lm` pinned to `>=0.31` (adds Gemma 4 support) and `mlx-vlm` added for multimodal models.

### Fixed

- Rewrote the optional `python_repl` (Monty) tool against the real `pydantic-monty` API; it previously targeted a non-existent API and failed at runtime. Each call now runs in a fresh, fully isolated sandbox (no host filesystem, network, or third-party imports), and the `pydantic-monty` version constraint was corrected.
- **Ollama models not listing** in the TUI — model parsing crashed on `"families": null` (returned by many Ollama models), making model discovery silently return an empty list.
- **Could not exit the TUI from selection pickers** (local LM Studio / MLX / Ollama, BYOK, ACP) — `:exit` / `:quit` / `:q` now work from any picker, and a command/shell line typed inside a picker is no longer swallowed by item selection.
- **TUI freeze on quit** — the exit sequence cancelled Textual's own message pump (via `asyncio.all_tasks()`), freezing the app so it had to be killed; it now shuts down cleanly.

## [0.1.35] - 2026-06-02

### Added

- `codex-sdk` runtime backend for the official OpenAI Codex Python SDK, available through `superqode[codex-sdk]`, runtime selection, HarnessSpec backend selection, normalized harness events, and documented install/use guidance.
- Codex SDK runtime tests covering registry integration, missing-extra behavior, response translation, streaming deltas, and permission callback handling.
- Runtime documentation that explicitly states `reference/codex/sdk/python` is reference material only; SuperQode uses the published `openai-codex` package.

### Changed

- TUI output polish for cleaner final-message rendering, tool/log presentation, command completion behavior, and conversation-history ergonomics.
- Runtime and harness backend documentation now include `codex-sdk` alongside builtin, ADK, OpenAI Agents, DeepAgents, and PydanticAI.

### Fixed

- Slash command completion now exposes the long-form `:connect` command reliably instead of depending on ambiguous one-letter aliases.
- Codex SDK runtime unresolved `ASK` approvals are rejected by default until interactive approval bridging is implemented, avoiding silent auto-approval.

## [0.1.34] - 2026-05-31

### Added

- Local code search for DS4/local models: `SUPERQODE_SEARCH_ROOTS` allowlists extra **read-only** repo roots (outside the working directory, `os.pathsep`-separated) that search/read tools (`repo_search`, `grep`, `glob`, `code_search`, `read_file`, `list_directory`) may access — so a local model can search a downloaded/cloned repo. Writes, edits, and shell stay confined to the working directory. See [Local Code Search](docs/providers/local.md#local-code-search-no-web-access).
- `code_search` (semantic symbol/definition/reference search) added to the DS4/local tool profile.
- DS4/local system prompts now steer toward local search (`repo_search`/`grep`/`code_search`/`read_file`) and state that no web access is available; configured search roots are listed in the prompt.
- DS4 connect now warms the model (one-token request) with a live elapsed-time indicator, so the user's first real prompt isn't the one paying DS4's one-time cold-load cost. Opt out with `SUPERQODE_DS4_WARMUP=0`.

### Changed

- DS4 model context window now reflects the live `ds4-server --ctx` value reported via `/v1/models` instead of a hardcoded 1M default, so iteration/compaction budgets match the running server.
- `web_search` now degrades gracefully when offline/network-restricted: it returns actionable guidance to use local search tools instead of a raw error.

### Fixed

- `grep` tool passed `--git-ignore` (not a valid ripgrep flag), which made ripgrep exit with an error that was swallowed as "No matches found"; removed the flag and surfaced real search-command failures.
- ACP runs no longer fail when the selected model is the catalog-fallback "OpenCode Default" (`opencode/auto`): the placeholder is normalized so the agent uses its own default model instead of returning an empty response.
- **OpenCode model selection** now takes effect: opencode ignores the `model` field in `session/new` and always started on its default (so every pick ran `big-pickle`). The ACP client now follows up with `session/set_model` for the requested, advertised model after creating the session.

## [0.1.27] - 2026-05-23

### Added

- SuperTUI slash-command improvements for runtime, harness, status, usage, sessions, MCP, and approval workflows.
- OpenAI Agents runtime event mapping for richer tool-search, MCP, and result graph events.

### Changed

- BYOK provider model lists now prefer current models.dev data and replace stale built-in model lists when live data is available.
- Google BYOK defaults now expose only the current Gemini Pro and Flash choices: `gemini-3.1-pro-preview` and `gemini-flash-latest`.
- DS4 documentation now positions DS4 as the preferred local DeepSeek V4 Flash path over generic MLX serving.

### Fixed

- MCP auth storage now respects runtime `HOME` changes and skips unusable keyring backends cleanly.
- CI formatting drift in harness, main CLI, TUI, and harness spec tests.

## [0.1.26] - 2026-05-20

### Added

- Harness event graph persistence for file and SQLite stores, with typed nodes and edges derived from normalized harness events.
- `superqode harness events` and `superqode harness graph` commands for inspecting persisted run timelines and graph structure.
- `superqode harness doctor` for preflight checks across backend installation, spec compatibility, sandbox policy, event-store readiness, rich-event support, approvals, and MCP config paths.
- Rich PydanticAI harness streaming that maps `run_stream_events` into model, tool, result, and approval graph events.
- Rich OpenAI Agents SDK harness streaming that maps SDK stream events into model, tool, approval, and sandbox graph events.
- Rich DeepAgents harness streaming that maps graph streams into model, tool, subagent, memory, sandbox, and result graph events.
- Ready-to-run harness examples for builtin coding, no-tool reasoning, PydanticAI, DeepAgents, OpenAI Agents SDK, Google ADK, Gemma4, and DS4.
- Documentation page for choosing, validating, running, and customizing harness examples.

## [0.1.25] - 2026-05-20

### Added

- PydanticAI runtime support with optional `superqode[pydanticai]` and `superqode[pydanticai-logfire]` extras.
- SuperQode tool bridge for PydanticAI using JSON-schema tool definitions.
- PydanticAI harness backend support for coding specs, no-tool specs, streaming, deferred approvals, native MCP config loading, fallback models, typed-output-friendly runs, and Logfire tracing.
- Prefect and DBOS durable execution wrappers through `runtime.config.pydanticai.durable`.
- Runtime backend documentation for PydanticAI configuration, capabilities, and limits.

### Changed

- Runtime backend documentation is now included in the MkDocs navigation.

### Fixed

- PydanticAI backend capability notes now reflect implemented durable wrapper support.
- Fixed a stale troubleshooting anchor in the documentation.

## [0.1.24] - 2026-05-19

### Added

- HarnessSpec v2 API with declarative specs, built-in templates, YAML/JSON loading, and a compiler bridge to the existing headless profile path.
- Harness kernel and sessions with run storage, typed events, typed output parsing, model policy resolution, sandbox policy helpers, and workflow modes for single, chain, parallel, router, orchestrator, and evaluator-optimizer runs.
- CLI surface for harness specs:
  - `superqode harness list-templates`
  - `superqode harness list-backends`
  - `superqode harness init`
  - `superqode harness validate`
  - `superqode harness inspect`
  - `superqode harness run`
- First-class harness backend names for `builtin`, `adk`, `openai-agents`, `deepagents`, and `pydanticai`.
- Backend streaming contract with normalized delta and end events.
- Gemma4, DS4, DS4 fast local, coding, and no-tool harness templates.
- No-tool model-only flavor for runs that intentionally avoid tools, filesystem access, shell access, and hidden repository context.
- Harness-backed approval flow for OpenAI Agents SDK pauses, including pending approval events, JSON output, TUI `:approve`, and TUI `:reject`.
- Backend capability inspection for HarnessSpec runs, including `superqode harness inspect`, backend availability lookup, approval support reporting, and early warnings for unsupported backend/spec combinations.
- Model-policy compatibility warnings for harness backends that may not honor reasoning, temperature, or max-iteration constraints.
- HarnessSpec JSON Schema output via `superqode harness validate --schema`.
- `SQLiteHarnessStore` for indexed harness sessions, runs, and events.
- `superqode.patch_harness` namespace for legacy patch validation primitives, with compatibility re-exports from `superqode.harness`.

### Changed

- Product documentation now positions SuperQode around harnesses, runtimes, model policy, sandbox policy, typed outputs, workflows, and run/session storage.
- Runtime-backed harness execution now applies effective model policy for prompt level, tool profile, reasoning, temperature, iteration limits, and session history.

### Fixed

- DS4 and Gemma4 local policies now clamp reasoning and tool-call behavior for compact local model execution.
- Harness backend registry now exposes optional framework adapters explicitly instead of hiding them behind a generic runtime wrapper.

## [0.1.23] - 2026-05-18

### Added

- **Pluggable agent runtime** (`superqode.runtime`): the agent loop is now a swappable backend. Choose with `--runtime`, `superqode.yaml: runtime:`, or `SUPERQODE_RUNTIME=`. CLI > YAML > env > builtin default.
- **Three runtimes shipped**:
  - `builtin`: wraps SuperQode's native AgentLoop (default; zero behavior change for existing users).
  - `adk`: Google Agent Development Kit (`pip install superqode[adk]`, requires `google-adk>=1.33.0,<2.0`). Bridges SuperQode tools as ADK `BaseTool` subclasses.
  - `openai-agents`: OpenAI Agents SDK (`pip install superqode[openai-agents]`, requires `openai-agents>=0.17.2`). Bridges tools as `FunctionTool`s with real `needs_approval` HITL, native MCP support, `LitellmModel` for non-OpenAI providers, JSONL session persistence via `SuperQodeSession(SessionABC)`.
- **CLI**: `superqode runtime list` (status table with `--json`), `superqode runtime doctor [name]` (probes optional deps + module imports), `superqode runtime doctor agents-md` (resolved instruction chain).
- **TUI**: `/runtime list`, `/runtime <name>` (mid-session swap), runtime badge in the status bar.
- **HITL for OpenAI Agents**: `:approve [N] [always]` / `:reject [N] [always] ["message"]` slash commands surface pending tool approvals; runs paused with `stopped_reason="needs_approval"` are auto-announced in the conversation log.
- **SandboxAgent integration** for `openai-agents` runtime: recognizes 9 sandbox backends (`local`, `docker` ship in-SDK; `e2b`, `daytona`, `modal`, `vercel`, `runloop`, `blaxel`, `cloudflare` recognized with install hints). When `sandbox_backend` is set, constructs `SandboxAgent` with a `Manifest` that mounts the working directory.
- **AGENTS.md compatibility** with OpenAI Agents SDK conventions: AGENTS.md is canonical; CLAUDE.md is a legacy fallback only loaded when AGENTS.md is absent in the same directory. Deeper-nested files take precedence (parent → child concatenation order).
- New extras in `pyproject.toml`: `adk`, `openai-agents` (with `[litellm]` sub-extra transparently pulled in).
- `docs/runtimes.md`: user-facing documentation for runtime selection.

### Fixed

- AGENTS.md / CLAUDE.md ordering: when both existed in the same directory, CLAUDE.md was previously appended *after* AGENTS.md, effectively overriding it. Now AGENTS.md wins.

### Changed

- `__version__` aligned with `pyproject.toml` (was `0.1.20`, now matches the package version).
- README key-features table gained a "Pluggable runtimes" row.

## [0.1.11] - 2026-02-07

### Fixed

- OpenAI BYOK routing for newer Codex models (`gpt-5.3-codex`) with provider-qualified model handling.
- OpenAI BYOK fallback behavior when account/model rollout differs (retry path to compatible Codex model IDs).
- BYOK streaming empty-response fallback to non-streaming completion to avoid silent failures.

### Changed

- Updated BYOK + ACP model catalogs to include `gpt-5.3-codex` and `claude-opus-4-6` and highlight them as latest/new in picker logic.
- Refreshed default model recommendations and aliases for OpenAI/Anthropic.

## [0.1.9] - 2026-01-31

### Added

- **Amp ACP Support**: Full integration with [Amp](https://ampcode.com) AI coding agent via [acp-amp](https://github.com/SuperagenticAI/acp-amp) adapter
  - New agent definition: `ampcode.com.toml`
  - TUI support: `:connect` → ACP → Amp
  - CLI support: `superqode connect acp amp`
  - Multi-turn conversations with thread continuity
  - MCP server integration
  - Install via `uv tool install acp-amp` or `npm install -g @superagenticai/acp-amp`

### Changed

- Updated ACP agent count from 14 to 15 official agents
- Added Amp to agent registry, icons, and routing

## [0.1.7] - 2026-01-30
- Add Kimi K2.5 Free model to OpenCode ACP/BYOK lists and mappings.
- Set OpenCode ACP session model when selected (avoid default fallback).
- Remove hardcoded model query interception so the agent answers directly.

## [0.1.5] - 2026-01-28
- Expand QE role job descriptions for power roles (unit, integration, api, ui, accessibility, security, usability).
- Highlight power roles in TUI role listing and selection with customization tips.
- Show power-role customization tips after project initialization.

## [0.1.6] - 2026-01-29
- FastAgent command fix.
- MLX model listing and timeout improvements.

## [0.1.4] - 2026-01-26

### Fixed

- Fixed slow binary startup time by switching to One-Dir bundle format.
- Resolved Pydantic `OSError` in PyInstaller builds.
- Fixed `install.sh` to work without `sudo` and handle path correctly.

### Changed

- Renamed QIR (Quality Investigation Report) to QR (Quality Report) for consistency.
- Simplified GitHub Action by removing `deep` mode and adding `run-linter` option.
- Added explicit security tester warnings in GitHub Action.
- Updated release packaging script to bundle supporting scripts.

## [0.1.3] - 2026-01-25

### Changed

- Version bump to 0.1.3

## [0.1.2] - 2026-01-24

### Changed

- Version bump to 0.1.2

## [0.1.0] - 2026-01-23

### Added

- **SuperQode TUI**: Interactive terminal UI for development and exploratory QE workflows
- **Automation CLI**: CI/CD entry points for automated project checks
- **Ephemeral Workspace Model**: Sandbox-first execution with automatic revert
  - Snapshot isolation (file-based)
  - Git snapshot isolation (stash-based)
  - Git worktree isolation (for deeper sandboxing)
- **Multi-Agent QE Architecture**: Multiple agents cross-validate findings
- **Quality Reports (QRs)**: Forensic artifacts documenting issues and fixes
- **Role-Based Testing**: Configurable QE personas (security_tester, api_tester, unit_tester, etc.)
- **Provider Abstraction**: BYOK support for multiple LLM providers
  - LiteLLM gateway (Anthropic, OpenAI, Google, etc.)
  - Ollama support for local models
  - OpenResponses gateway for community models
- **Allow Suggestions Mode**: Optional mode for agents to propose and verify fixes
- **Noise Filtering**: Configurable false-positive filtering for QE findings
- **Constitution System**: Guardrails for agent behavior

### Configuration

- `superqode.yaml` project configuration
- `superqode-template.yaml` full configuration template
- Environment variable support (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.)
- User config (`~/.superqode.yaml`) with project overrides

### Known Limitations

- Test coverage is limited; contributions welcome
- Documentation is evolving; some features may have sparse docs
- Enterprise features require additional licensing

### Security

- All changes are sandboxed; production code is never modified by default
- Human-in-the-loop approval required for all suggestions
- Self-hosted, privacy-first design

### License

- Released under AGPL-3.0
