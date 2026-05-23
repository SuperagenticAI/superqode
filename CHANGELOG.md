# Changelog

All notable changes to SuperQode will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
