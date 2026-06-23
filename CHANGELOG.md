# Changelog

All notable changes to SuperQode will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.1] - 2026-06-24

### Added

- **TUI harness wizard** - Added a step-by-step `:harness wizard` flow for creating starter HarnessSpec files from the TUI, plus `:harness init` / flag shortcuts using the same wizard builder as the CLI.
- **TUI CLI parity** - Exposed the remaining CLI command surface in the TUI command list and routed unsupported subcommands through the CLI runner so CLI-only workflows can be launched from the TUI.

### Fixed

- **Smoke script source checkout support** - Made the Omnigent agent-session smoke script import SuperQode reliably when run directly from a checkout.

### Changed

- **Release metadata** - Bumped the package version and runtime `__version__` to `0.2.1`.

## [0.2.0] - 2026-06-23

### Changed

- **Beta launch** - Marked this release as the first public beta for the SuperQode harness engineering framework without requiring pre-release install flags.
- **uv-first project workflow** - Updated contributor docs and GitHub Actions to install, lint, test, build, and deploy through uv.
- **Installation docs** - Removed the unavailable curl installer path and aligned README and docs installation guidance around `uv tool install`, `uvx`, source checkouts, and the official uv documentation.
- **Latest-release install docs** - Updated first-time install commands to use unpinned `uv tool install "superqode"` and `uvx "superqode"` so new users get the latest release from PyPI.
- **Documentation theme** - Enabled both light and dark documentation modes with scheme-specific homepage colors.
- **Documentation homepage polish** - Reduced the homepage title scale, added a feature reference map, documented Harness Independence and Local Dynamic Workflows with RLM in feature lists, and added a CLI reference coverage test for top-level command groups.
- **Release metadata** - Bumped the package version and runtime `__version__` to `0.2.0`.

## [0.1.49] - 2026-06-22

### Fixed

- **Installation docs** - Corrected the pip installation examples in the README and getting-started guide so they no longer repeat the `uv tool install` command.

### Changed

- **Release metadata** - Bumped the package version and runtime `__version__` to `0.1.49`.

## [0.1.48] - 2026-06-22

### Changed

- **Release verification** - Audited documented CLI examples against the real command surface, clarified CLI versus TUI connect behavior, and replaced stale model examples with placeholders or current CLI-advertised examples.
- **Airplane Mode readiness** - Restored compatibility aliases for optional semantic search checks so `superqode local airplane doctor` reports a clear optional-dependency warning instead of an internal import warning.
- **Release metadata** - Bumped the package version and runtime `__version__` to `0.1.48`.

## [0.1.47] - 2026-06-22

### Changed

- **Release positioning** - Updated README and docs positioning around SuperQode as a harness engineering framework for coding agents, optimized for local and open models.
- **Documentation launch polish** - Reworked the docs homepage CTAs, hero copy, local-first quickstart path, and CLI reference coverage for daemon, MCP, skills, SkillOpt, and tools.
- **Provider examples** - Replaced stale hosted-model identifiers in docs with provider/model placeholders and guidance to use current provider model listings.

### Removed

- **Stale marketing assets** - Removed unreferenced header/screenshot images and generated `.DS_Store` files from the release tree.

## [0.1.45] - 2026-06-18

### Added

- **Optional semantic code search** - Added a first-class `semantic_search` tool backed by `cocoindex-code`, registered only when the optional `superqode[semantic]` extra is installed. The tool searches AST-chunked code by intent, supports language/path filters and offset pagination, runs read-only under the existing search permission group, and keeps the heavy indexing/embedding work in the CocoIndex daemon.
- **CocoIndex Code MCP path** - Documented `ccc mcp` as the lightweight MCP integration path for sharing one semantic index across SuperQode and other agents. The MCP configuration guide now includes a ready-to-use `cocoindex-code` stdio server example and notes the MCP `search` parameters.
- **Local-model semantic search guidance** - Documented local Ollama embeddings with `nomic-embed-text`, low-overhead search defaults (`refresh=false` / `refresh_index=false` for repeated searches), index freshness tradeoffs, and optional local harness wiring for DS4/Gemma-style coding harnesses.
- **Semantic search docs** - Added the advanced Semantic Code Search guide and linked it from the tools catalog and documentation navigation.

### Changed

- **Slim semantic dependency** - The `semantic` extra now depends on slim `cocoindex-code>=0.2.35,<0.3` instead of the `[full]` extra, avoiding a default torch/sentence-transformers install in the SuperQode environment. Users who want offline Hugging Face sentence-transformers can still install `cocoindex-code[full]` explicitly.
- **Release metadata** - Bumped the package version and runtime `__version__` to `0.1.45`.

## [0.1.44] - 2026-06-16

### Added

- **Composable harness specs** - Harness YAML now supports top-level `inherits` and `extends` for built-in templates or relative spec files. Specs are resolved at load time, mapping fields are deep-merged, list fields replace the base list, and recursive inheritance has cycle and depth protection.
- **Minimal inherited harness generation** - `superqode harness init --minimal` writes a compact spec that inherits from the selected template. `superqode local doctor --generate ... --minimal` and `superqode local init --minimal` preserve local-model tuning as overrides while keeping the generated YAML small enough for teams to own.
- **Harness readiness testing** - `superqode harness test` performs a fast smoke path across spec loading, doctor checks, kernel initialization, and optional live model prompting. JSON output includes a compact failure digest with likely failure category, implicated components, evidence, and suggested next checks.
- **Harness eval scorecards and variants** - `superqode harness eval` runs task files against one or more specs, compares variants against a baseline, reports pass/fail/skipped counts, score deltas, and regressions, and supports dry runs for CI wiring before a live endpoint is available.
- **Model auto-bench wrapper** - `superqode harness auto-bench` reuses the smoke and eval paths to give a first-run recommendation for local or hosted model setup. Dry runs explain how to proceed, while live failures surface the same digest format as `harness test`.
- **Local harness registry** - `superqode harness registry publish`, `list`, and `install` provide a local share hub under `~/.superqode/harness-registry`, giving teams a low-risk path to publish validated HarnessSpec files before introducing any remote registry.
- **Harness-as-a-service alias** - `superqode serve harness --spec ...` and `--dir ...` expose HarnessSpec workflows through the existing MCP harness server with a command shaped around serving one harness or a directory of harnesses.
- **Meta-harness optimization bridge** - `superqode harness optimize` exports a HarnessSpec and eval task file into a `superagentic-metaharness` project, can run an optional backend such as Codex, Gemini, Omnigent, or fake, writes default trace evidence from the spec, tasks, and optional previous test or eval JSON, exposes `optimize-inspect` and `optimize-ledger`, surfaces the latest ledger in the TUI harness sidebar, and only applies the best candidate spec when `--apply` is passed.
- **Local-first product strategy note** - Added `product/local-first-strategy.md` to capture the current local model CLI surface, near-term direction, and success criteria for local-first harness workflows.
- **Live tool progress and runtime footer in channels** - While the agent works, the "Working on it" message is edited in place with the running tool and call count. Telegram, Slack, and Discord each use their native update path, and the final reply carries a compact `model · cwd` footer.
- **Hermes Agent via ACP, verified end to end** - `uv tool install 'hermes-agent[acp]'`, local OpenAI-compatible server configuration in `~/.hermes/config.yaml`, `superqode agents doctor hermes --live`, and TUI connection through `:connect acp hermes`.
- **Daemon and chat channels** - `superqode daemon` supervises long local runs from Telegram, Slack, or Discord, supports chat steering, relays tool approvals, adds status controls, uses allowlist-first security, and keeps one agent session per chat.
- **Local Agentic Coding positioning** - SuperQode now names its category as agentic software engineering on open models running on your own hardware, with the term carried through the docs and `superqode local` CLI.
- **TUI `:local` command** - The Local Stack Doctor is available inside the TUI through `:local` and `:local doctor`, with non-blocking rendering, `:local packs`, autocomplete, and help integration.
- **Local Stack Doctor** - `superqode local doctor` detects hardware, inference engines, downloaded models, and repository fit, then recommends a tuned local stack and can generate a ready-to-run harness routed to the right provider.
- **Recommendation matrix as data** - Hardware tiers map to ranked engines and models in shipped `stack_matrix.yaml`, with user overrides through `~/.superqode/stack_matrix.yaml`.
- **Model policy packs** - Shipped tuned defaults for open-model families such as `gemma4`, `qwen3`, `qwen-coder`, `ds4`, `devstral`, `gpt-oss`, and `glm`, with user overrides under `~/.superqode/model-packs/`.
- **Local bench** - `superqode local bench` reports time-to-first-token and decode tokens per second against running OpenAI-compatible endpoints.
- **MLX server lifecycle** - `superqode providers mlx server --model <hf-id>` starts `mlx_lm.server`; `superqode providers mlx doctor` checks install and live endpoint readiness.
- **Utility model routing** - `SUPERQODE_UTILITY_PROVIDER` can route small quality-tolerant calls such as grading, memory extraction, and summaries to a cheaper provider or the on-device Apple Foundation Model.
- **`get_context_remaining`** - A read-only tool reports live context window, estimated usage, and remaining budget before automatic compaction.

### Changed

- **Harness docs and CLI reference** - Documented inheritance, minimal init, harness testing, eval scorecards, auto-bench, meta-harness optimization, local registry commands, and the `serve harness` alias in the advanced harness guide and CLI reference.
- **Local model workflow continuity** - The new inherited local harness output builds on the recent local stack work: model inventory, local server lifecycle, local search/inference support, benchmark commands, and CI-focused lint cleanup remain available through the same generated HarnessSpec contract.
- **Release metadata** - Bumped the package version and runtime `__version__` to `0.1.44`.

## [0.1.41] - 2026-06-10

### Added

- **`apply_patch` (patch envelopes)** — native support for the `*** Begin Patch` envelope format that GPT-5.x and local gpt-oss models are trained to emit: Add/Delete/Update File, `*** Move to:` renames, `@@` locators, EOF anchors, multi-file patches with all-or-nothing validation, fuzzy context matching (exact → trailing-whitespace → trimmed), markdown-fence/prose stripping, and workspace + post-edit-verification integration. Bash invocations of `apply_patch <<EOF` heredocs are intercepted and routed to the real tool. Registered in every tool profile.
- **`shell_session` (interactive processes)** — open persistent PTY-backed processes (REPLs, dev servers, debuggers, prompts), `write` to stdin, `poll` new output, `list`, `kill`. Bounded per-call waits with early return on settled output, 2MB rolling buffers with spill-to-disk on return, session reaping, and atexit cleanup so no orphan processes outlive superqode.
- **`view_image` (multimodal context)** — attach local png/jpg/gif/webp files to the conversation as OpenAI-style `image_url` parts for vision-capable models (including local multimodal models like Gemma 4). Image attachments are token-counted at a flat charge instead of their base64 length, stripped before LLM summarization, and pruned (pixels only) once they age out of the protected context window.
- **In-run steering** — `AgentLoop.steer()` injects user messages between iterations of a *live* run (and keeps the run going if a message arrives as the model finishes), instead of waiting for the whole run to complete. Thread-safe; peers and UIs share the same mechanism.
- **Auto-continue on token-limit cuts** — when a response stops with `finish_reason="length"`, the loop asks the model to continue from exactly where it stopped (default 2 continues, `max_auto_continues`), joining the parts into one answer; streaming continues seamlessly.
- **System reminders** — synthetic `<system-reminder>` notes attached to outgoing requests only (never persisted): files changed externally since last read (each change announced once), and stale-todo nudges (rate-limited). `SUPERQODE_REMINDERS=0` disables.
- **Deferred tool loading + `tool_search`** — `SUPERQODE_DEFERRED_TOOLS=auto|all|<names>` hides heavy tool schemas (web, images, sessions, LSP, MCP, agents) from the prompt until the model activates them via a lexical `tool_search`; activated schemas appear on the next call. `auto` applies only to local providers, where schema budget matters most.
- **Peer agents** — long-lived multi-agent suite: `spawn_agent`, `send_input` (steers a busy peer's live run; `interrupt=true` cancels and redirects), `wait_agent`, `list_agents`, `close_agent`. Peers are long-lived AgentLoops with their own context; one level deep (peers cannot spawn peers).
- **Background bash** — `bash` gains `run_in_background`: starts the command as a persistent session and returns its `session_id` immediately for later `shell_session` poll/write/kill.
- **Turn diff** — per-turn aggregate of file changes ("Turn changed 3 file(s) (+45/-12): …") emitted to the thinking trace; the combined diff is retained on `AgentLoop.last_turn_diff` for UIs and hooks.
- **Shell env policy** — `SUPERQODE_SHELL_ENV_POLICY=filter-secrets` strips secret-looking variables (`*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`, …) from model-spawned commands, with `SUPERQODE_SHELL_ENV_ALLOW` exceptions.
- **Exec policy rules** — declarative allow/deny/ask rules for shell commands in `.superqode/execpolicy.yaml` (project), `~/.superqode/execpolicy.yaml` (user), or `SUPERQODE_EXEC_POLICY` (explicit): glob or `re:` patterns, first match wins. User `allow` skips the prompt but can never override built-in dangerous-command denies.
- **Automatic memory (opt-in)** — `SUPERQODE_AUTO_MEMORY=1` extracts durable preferences/facts/decisions from completed runs in a background task and stores them in the local memory provider (deduplicated, tagged `auto`), where `:memory search` already looks.
- **Automatic memory recall (opt-in)** — `SUPERQODE_AUTO_RECALL=1` completes the loop: at run start the local memory store is searched with the prompt and the top hits (max 4, relevance-floored) ride along as a clearly labeled `<system-reminder>`, once per prompt, never persisted to history. Only the user-level local store is read, so untrusted repository content can never enter the agent's context through recall.
- **`request_permissions`** — the model can make one justified request for session-scoped tool permissions; approval through the normal prompt upgrades those tools from ask-each-time to allowed (hard denies are never overridable, grants clear with the session).
- **`--output-schema`** — headless runs pin the final answer to a JSON Schema: schema embedded in the prompt, lenient extraction + validation, one automatic corrective retry, exit code `2` on validation failure; `--mode json` gains `structured_output`/`schema_errors`/`schema_valid`.
- **`--rubric`** — self-grading quality gate for headless runs (inline text or `@file`): a separate grader judges the final answer and "needs revision" feedback re-enters the loop (`rubric`/`max_rubric_rounds` on `AgentConfig` for programmatic use; grader fails open).
- **HTML session export** — `superqode sessions export <id> --format html` renders a self-contained, dark-mode, shareable transcript page.
- **`tool_call_format: prompt`** — harness model policy now wires through to behavior: tool schemas render into the system prompt and `<tool_call>{…}</tool_call>` blocks are extracted from response text and executed like native calls — for local models with no native tool-calling head (`compact-json`/`strict-json` remain native arg-style hints).
- **TUI live steering** — typing while a builtin (local/BYOK) run is active now steers the *current* run between tool calls (`↪ steering the current run`); non-steerable connections keep the type-ahead queue.
- **Documentation** — five new procedural guides (Inside the Agent Loop, Tools Catalog, Policies & Safety, Multi-Agent Workflows, Headless & CI) plus a complete Environment Variables reference, all in the docs nav.

### Changed

- **Documentation quality pass** — every code fence now carries a syntax-highlighting language tag; em-dashes and typographic ellipses removed site-wide; landing page gains a numbered progressive learning path and a complete runtime table (codex-sdk, claude-agent-sdk); TUI reference documents live steering, `:context`, `:thinking`, `:queue`, `:workspace`, and `:memory`; serve commands reference now covers the MCP server and A2A server API accurately; tools-system page modernized and cross-linked with the Tools Catalog; strict `mkdocs build` passes clean.
- **Documentation redesign** — full-width landing page rebuilt to the Material/FastAPI standard: single compact logo hero with gradient title, badge row, action buttons, a 60-second quickstart, eight icon feature cards, tabbed live examples (TUI/headless/harness/CI), and a guided learning path; custom brand palette (light and dark) via Material's supported hooks; Inter + JetBrains Mono typography; the 1,151-line CSS override sheet replaced by a 151-line brand layer; sidebar no longer force-expands; placeholder Google Analytics and the cookie-consent banner removed.
- **Positioning and completeness** — product positioning updated everywhere (docs landing, site description, README): "the portable coding agent harness framework; define your harness or bring your own; any provider, any model, any runtime, any protocol; optimized for local agentic AI"; the product banner returns to the home page under the hero; dark mode switches to warm amber accents (bright purple was harsh on dark backgrounds); "Three Connection Modes" becomes "Connection Modes" with a fourth SDK mode documented (Codex SDK via ChatGPT subscription, Claude Agent SDK via Claude subscription or Anthropic API key, Antigravity handoff); all 27 previously undocumented `SUPERQODE_*` environment variables added to the reference, bringing code-to-docs coverage of env vars, tools, and CLI commands to 100%.

- **Spill-to-disk tool output** — oversized bash/tool output is saved in full to `~/.superqode/tool-output` (7-day retention, `SUPERQODE_TOOL_OUTPUT_DIR` to relocate); the model gets a head/tail preview plus the file path and can `read_file`/`grep` the rest instead of re-running the command. A loop-level guard applies the same bound to tools that don't self-limit (MCP, web). Spilled paths are always readable by read/search tools.
- **Bounded, numbered reads** — `read_file` returns up to 2000 lines / 50KB by default with `N: ` line-number prefixes, clamps overlong lines (minified JS), rejects binary/image files with a clear message, and tells the model exactly how to continue (`start_line=<next>`); accepts `file_path`/`offset`/`limit` aliases that local models trained on other harnesses emit. Edit matching gains a fallback that strips pasted line-number prefixes.
- **Doom-loop guard** — the Nth consecutive identical tool call (default 3; `doom_loop_threshold` / `SUPERQODE_DOOM_LOOP_THRESHOLD`) is intercepted with corrective feedback instead of executing again; if the model immediately repeats the same call, the run stops with `stopped_reason="loop_detected"`.
- **Tool-argument repair** — malformed tool-call arguments (markdown fences, Python-dict syntax, trailing commas, double-encoded JSON, prose around the object) are repaired; unrecoverable arguments return a corrective error to the model instead of silently executing the tool with `{}`.
- **Rate-limit retry** — transient overload errors (429/503/529/overloaded) retry with exponential backoff, honoring `Retry-After`/`retry-after-ms` headers (`SUPERQODE_RATE_LIMIT_RETRIES`, default 3); long provider-requested pauses surface instead of hanging the session.
- **Tool-output pruning** — a free pre-compaction stage stubs stale tool outputs older than the protected recent window before paying for LLM summarization (the current turn's results are always protected); often avoids the summarization call entirely on local models.

### Changed

- **Mutation-safe parallel tools** — tools now carry a `read_only` flag; a turn's tool calls run concurrently only when every call is read-only. Any batch containing an edit/write/bash/MCP call runs sequentially in call order, so concurrent file mutations can no longer race.
- **Streaming bash drains to EOF** — output beyond the model-sized cap no longer stops the reader (which could deadlock chatty processes on full pipes); streams are drained, the full output (up to 5MB) is spilled, and the preview stays bounded.

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
