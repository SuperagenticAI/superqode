# Changelog

All notable changes to SuperQode will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.31] - 2026-07-22

### Changed

- **Product positioning** - Established SuperQode as the Agent Engineering framework for your code, with a concise message centered on reliable coding agents, portable harnesses, context, memory, tools, control loops, and freedom to use any agent or model.
- **Public documentation** - Aligned the README, documentation home page, concepts, getting started, harness engineering, Software Factory, and Omnigent relationship pages around the terminal-first Agent Engineering product theme.
- **Documentation style** - Replaced conversational and promotional wording with direct technical descriptions and expanded the public documentation check to reject en and em dashes.
- **Release metadata** - Bumped the package, runtime, lockfile, ACP registry, package checks, extension compatibility examples, and plugin documentation to `0.2.31`.

## [0.2.30] - 2026-07-22

### Added

- **Durable WorkOrder kernel** - Added repository-scoped WorkOrders with dependency-aware tasks, atomic worker claims, concurrency limits, leases, heartbeats, bounded retries, stale-worker recovery, typed artifacts, append-only events, deterministic acceptance commands, and explicit accept/reject/cancel decisions.
- **Terminal WorkOrder execution** - Added `sq work` commands to create, queue, run, inspect, recover, check, and decide work. Ready tasks execute through their assigned HarnessSpecs in a reusable WorkOrder-scoped Git worktree when available, preserve patch and harness run/session evidence, and keep acceptance decisions in the terminal without requiring a web or mobile control plane.
- **Verified WorkOrder delivery** - Added content-addressed integration candidates, source-drift and file-conflict detection, exact-patch review and approval, crash-recoverable merge intent, post-apply tree verification, guarded rollback, and explicit managed-worktree cleanup. Delivery never stages or commits the user's checkout.
- **Live WorkOrder cancellation** - Running WorkOrder processes now observe durable cancellation and cancel the active harness coroutine instead of only updating task state in SQLite.
- **Parallel isolated WorkOrders** - Added bounded `max_workers` fan-out, one detached Git worktree per task attempt, exact-tree dependency fan-in, process-locked patch integration, deterministic overlapping-file conflict gates, and cleanup across every WorkOrder-owned worktree.
- **Portable WorkOrder state** - Isolated worktrees and their session registry now honor `SUPERQODE_HOME`, allowing terminal workers to run on CI, container, and enterprise hosts where the operating-system home directory is read-only.
- **No-tool runtime compatibility** - Normalized the documented `sandbox: none` spelling through the local capability profile while preserving the HarnessSpec's stricter no-read, no-write, and no-shell execution policy.
- **Offline release smoke provider** - Connected the packaged synthetic passthrough and silent gateways to HarnessSpec execution so CI can exercise complete harness and WorkOrder plumbing without credentials or network access.
- **Workspace-scoped harness sessions** - Relative HarnessSpec session storage now resolves inside the active task workspace, preventing unrelated repositories or repeated test runs from sharing session history.
- **Role-aware WorkOrder pipelines** - Added investigator, implementer, synthesizer, reviewer, tester, and custom task contracts; bounded dependency evidence propagation; evidence-only workspace enforcement; typed review artifacts; structured approval/changes-requested verdicts; and a review gate that low-level completion cannot bypass.
- **Headless worker service** - Added a persistent terminal-first WorkOrder worker with stable identities, duplicate-process locks, bounded global concurrency, per-WorkOrder admission limits, automatic stale-lease recovery, graceful signal draining, ephemeral CI limits, and durable atomic heartbeat snapshots.
- **Live terminal cockpit** - Added `sq work watch` and `sq work workers` for task DAG state, attempts, lease time, budgets, review/check/integration gates, artifact counts, worker health, and the latest append-only lifecycle events, including a JSON snapshot for external monitoring.
- **Enforced WorkOrder accounting** - Added normalized per-run and cumulative token, cost, tool-call, iteration, and latency evidence; fail-closed task-boundary budget gates; role-derived or explicit task risk admission; terminal usage inspection; read-only policy simulation; and observed-versus-limit cockpit visibility.
- **Layered contextual governance** - Added organization, project, HarnessSpec, WorkOrder, and session policy layers with deny-overrides decisions across request, response, tool-call, tool-result, and promotion phases; added read-only terminal explanations and runtime decision evidence.
- **Credential-safe execution** - Added secure WorkOrder shell defaults, project network guardrails, model-supplied credential-header blocking, and symbolic host-bound credential injection for `fetch` and `web_fetch` without exposing secret values in model context or evidence.
- **Reproducible HarnessBench** - Added fixed-model multi-harness manifests, repeated raw runs, variance and Pareto scorecards, source fingerprints, artifact checksums, Markdown reports, and offline tamper verification.
- **Guarded harness delivery** - Added audited staging, digest-addressed rollback snapshots, deterministic WorkOrder canaries, live held-out HarnessBench activation gates, contextual promotion policy, atomic activation, and rollback protection against later human changes.
- **Software Factory product guide** - Reframed the Software Factory as the umbrella over HarnessSpecs, runtime portability, interactive coordination, durable WorkOrders, workers, evidence, verified delivery, evaluation, and guarded optimization; added a complete builder quickstart, operator runbook, plain-language reliability concepts, and a neutral guide to shared and different Omnigent ideas.

### Changed

- **Release metadata** - Bumped package, runtime, lockfile, ACP registry, package checks, extension compatibility examples, and plugin documentation to `0.2.30` for the complete pre-`0.3.0` validation release.

## [0.2.25] - 2026-07-21

### Added

- **RLM Code v0.1.11 integration** - Added an optional `rlm-code` HarnessSpec backend and Harness Protocol adapter that preserve RLM Code as the recursive execution engine while normalizing context selection, REPL steps, root/submodel usage, LID exposure metrics, and native JSONL trajectories into SuperQode evidence.
- **RLM Code LID example and guide** - Added a Docker-first, read-only `rlm-code-lid` HarnessSpec plus installation, configuration, architecture, conformance, evaluation, optimization, safety, demo, and limitations documentation.
### Changed

- **Release metadata** - Bumped package, runtime, lockfile, ACP registry, package checks, extension compatibility examples, and plugin documentation to `0.2.25`.

## [0.2.24] - 2026-07-19

### Added

- **`sq` command shortcut** - Installed packages and standalone archives now expose `sq` as an equivalent, human-friendly shortcut for every `superqode` CLI command while retaining the canonical executable for scripts and agents.
- **Catalog visibility tiers** - Harness catalog records now distinguish recommended, user-owned, specialized, and pinned compatibility entries without changing direct name or path resolution.

### Changed

- **Focused TUI harness picker** - Bare `:harness` and `:harness use` autocomplete now show maintained families, general workflows, and user harnesses; `:harness all` opens the complete keyboard-navigable catalog, while CLI `harness list` remains complete and adds `--recommended`.
- **Release metadata** - Bumped package, runtime, lockfile, ACP registry, package checks, and extension compatibility examples to `0.2.24`.

## [0.2.23] - 2026-07-19

### Added

- **Stable model-family routes** - Added an explicit curated route registry and a `kimi-coding` family harness that tracks the validated stable Kimi release without requiring a new harness name for every model launch.
- **Unified harness catalog** - Made built-in model templates directly selectable alongside Core, Workbench, discovered files, registry entries, and Python adapters; catalog records now expose category, provider, model, and pinned/deprecated state.
- **TUI harness picker and autocomplete** - Bare `:harness` now opens the shared keyboard-navigable catalog, and `use`, `show`, and `customize` complete dynamically from the same source used by CLI listing and resolution.
- **Editable preset copies** - Added `:harness customize <name> [output.yaml]` to safely create a project-owned copy without overwriting an existing file.

### Changed

- **Direct model-aware activation** - `--harness kimi-coding` now supplies its curated provider/model when those flags were not explicitly set, and TUI activation connects the preset's exact target directly.
- **Pinned K3 compatibility** - Retained `kimi-k3-coding` as a frozen reproducibility preset while recommending the maintained `kimi-coding` family route for normal use.
- **Release metadata** - Bumped package, runtime, lockfile, ACP registry, package checks, and extension compatibility examples to `0.2.23`.

## [0.2.22] - 2026-07-18

### Added

- **Kimi K3 first-party support** - Added Moonshot's global OpenAI-compatible API route, K3 and current Kimi model metadata, API-key aliases, provider discovery, and a `kimi-k3-coding` harness with 1M context, max reasoning, parallel tools, cache-friendly history, and coding-model fallbacks.
- **Complete Kimi K3 guide** - Documented Moonshot API and Kimi Code subscription boundaries, setup, pricing, model IDs, reasoning, streaming, tools, vision and video, structured output, Partial Mode, context caching, open-weight status, benchmark interpretation, supported feature gaps, and troubleshooting.

### Fixed

- **K3 request compatibility** - Preserved `reasoning_content` across tool turns, normalized K3 to its current max-only reasoning contract, removed incompatible sampling overrides, and translated completion limits to `max_completion_tokens` on streaming and non-streaming requests.

### Changed

- **Release metadata** - Bumped the package version, runtime `__version__`, lockfile package entry, ACP registry metadata, release-package check, and extension compatibility examples to `0.2.22`.

## [0.2.21] - 2026-07-13

### Added

- **Harness Protocol v1** - Added a versioned internal lifecycle, canonical durable event envelope, capability contract, portable session export, shared controller, and Core, direct-Python, and ACP reference adapters.
- **Harness adapter conformance** - Added a reusable conformance API and `superqode harness protocol describe|conformance` commands covering ordering, terminal states, message preservation, persistence, export, resume, and checkpoints.
- **Python harness packages** - Added `superqode.harnesses` entry-point discovery, automatic function-to-adapter wrapping, failure isolation, unified list/show/run commands, named conformance checks, and a real install/run/uninstall package fixture.
- **Extensible native Core** - Added the public Python `Extension` API and `superqode.extensions` package entry-point contract for opt-in tools, TUI commands, skills, lifecycle hooks, bounded context, permission rules, and providers while preserving Core's four-tool default.
- **Runtime plugin activation checks** - Added `superqode plugins doctor --runtime` to import trusted contributions and report active capabilities, skipped extensions, compatibility failures, and isolated activation errors.
- **Extension examples and package conformance** - Added manifest-based and Python-package references plus three independent tool, policy, and skill distributions, an upgrade fixture, and a temporary-environment lifecycle checker under `examples/extensions/`.

### Changed

- **Functional plugin manifests** - Existing `plugin.json` contributions now activate in native Core and headless runs instead of remaining declarative-only; project-local executable contributions remain trust-gated and enable/disable changes rebuild the active native runtime.
- **Release metadata** - Bumped the package version, runtime `__version__`, lockfile package entry, ACP registry metadata, and extension package compatibility declarations to `0.2.21`.

## [0.2.20] - 2026-07-13

### Changed

- **Release metadata** - Bumped the package version, runtime `__version__`, lockfile package entry, and ACP registry metadata to `0.2.20`.

### Fixed

- **Clean-install Ollama tool calls** - Bypassed LiteLLM's optional proxy MCP handler for SuperQode-managed tools so standard `uv tool install superqode` environments no longer require the undeclared FastAPI proxy dependency to call Ollama or other tool-capable providers.
- **MLX installation prompt** - Fixed Enter being intercepted by stale local-provider picker state, so the confirmed `mlx-lm` installation now starts; the prompt also explains how to copy the exact command into another terminal and reconnect manually.
- **DS4 managed-server guidance** - Made manual startup the recommended path, documented exactly what the experimental managed start launches and stores, and now shows `:local stop ds4` after SuperQode starts the server.
- **Local server guidance** - Made user-managed servers the preferred workflow across local providers, refreshed Ollama, LM Studio, MLX, DS4, llama.cpp, vLLM, SGLang, and TGI commands from their current vendor documentation, and kept SuperQode-managed startup as a clearly secondary convenience fallback.
- **Commands inside model pickers** - Digits in commands such as `:local stop ds4` are no longer intercepted as numeric model selections, so managed local servers can be stopped directly from the active picker.

## [0.2.19] - 2026-07-13

### Added

- **Guided subscription sign-in** - Added consent-gated Codex and Grok CLI login flows that surface device-auth instructions in the TUI and resume the requested connection after successful authentication.
- **Visible TUI version** - Added the installed SuperQode version beside the product name in the persistent top status line so users can immediately identify the build they are running.

### Changed

- **Answer-focused conversation styling** - Replaced the heavy boxed `YOU` prompt with a compact purple `▌ You` transcript row and a restrained aubergine highlight behind only the prompt text, added an explicit accented `✦ Answer · agent` rule, kept the response directly beneath that marker and moved completion metadata after it, deduplicated repeated ACP context updates, and made mode, token, and completion chrome visually quieter.
- **Quieter startup and context chrome** - Moved local-model warmup progress into the transient activity indicator, collapsed successful connection startup into one dim readiness line, kept failures visible as warnings, and moved ACP context usage exclusively into a compact persistent top-line meter.
- **Compact top status header** - Consolidated version, connection/model, specialized runtime, mode, usage, cost, and plan state into one responsive line; disconnected sessions show a quiet `No model` state, while default-runtime noise, the redundant home-screen `SUPERQODE` badge, and the persistent marketing tagline are omitted.
- **Clearer TUI status feedback** - Added a small breathing row above the compact header, switched its session token figure from character-count estimates to exact provider-reported streaming usage when available, and surfaced local connection failures through a persistent error entry, focused recovery prompt, and prominent error notification.
- **Complete TUI command autocomplete** - Kept every matching `:` command keyboard-reachable through the paged completion panel, synchronized dispatcher aliases across both completion surfaces, and added live ACP agent shortcuts—including discovered or custom agents—to suggestions.
- **Release metadata** - Bumped the package version, runtime `__version__`, lockfile package entry, and ACP registry metadata to `0.2.19`.

### Fixed

- **Mouse selection clipboard copy** - Restored Textual's name-based `TextSelected` dispatch after the mixin refactor so dragging across selectable TUI text copies the selection again.
- **Streaming token totals** - Preserved terminal provider usage chunks across LiteLLM, Ollama, MLX, the agent loop, and Pure Mode so the final dim completion line shows the real per-turn token total.

## [0.2.18] - 2026-07-12

### Added

- **First-party Z.AI GLM support** - Added the `zai` BYOK provider on Z.AI's general OpenAI-compatible API, direct CLI/TUI connection surfaces, GLM-5.2 reasoning and streamed-tool-call shaping, current GLM-5.x model metadata, and mocked plus opt-in live protocol coverage. The restricted GLM Coding Plan endpoint is intentionally excluded.
- **GLM-5.2 coding harness** - Added the `glm52-coding` template with first-party Z.AI routing, GLM-family policy tuning, 1M context, max reasoning, parallel native tools, and GLM-5.1/5 fallbacks.

### Changed

- **Maintainable CLI and TUI entry points** - Split the oversized Textual application into focused mixins and moved inline Click command groups into dedicated command modules while preserving existing imports, method signatures, command ordering, options, and help output.
- **Focused helper and harness modules** - Split the remaining TUI helper catch-all into cohesive helper mixins and organized the harness CLI into a small command package whose largest module is roughly 600 lines.
- **CLI compatibility contract** - Added a regression test covering all 208 commands and the byte-identical rendered help tree so future structural changes cannot silently alter the public CLI.
- **Release metadata** - Bumped the package version, runtime `__version__`, lockfile package entry, and ACP registry metadata to `0.2.18`.

## [0.2.17] - 2026-07-12

### Fixed

- **Conservative fast-chat routing** - Only greetings, social openers, and runtime identity questions now disable repository tools. Open-ended questions such as "Which tests are failing?" remain on the tool-capable path, and empty model responses are no longer replaced with a fabricated greeting.
- **Subscription runtime reliability** - Antigravity CLI readiness now validates the minimum compatible version, runtime doctor distinguishes installed from ready, stderr is drained concurrently, SDK resources are closed during switching and shutdown, and Antigravity structured thinking/tool events reach the TUI.
- **Accurate Grok ownership and discovery** - Current help surfaces identify Grok Build as xAI's ACP harness and `:grok api` as the native SuperQode opt-in. CLI model discovery runs off the UI thread, ignores failed command output, and no longer invents capabilities for unknown models.
- **Codex protocol fallback** - Safe Codex metadata reads fall back from a newer incompatible local CLI to the SDK-pinned app-server. Set `SUPERQODE_CODEX_PREFER_LOCAL_CLI=0` to use the pinned server from startup; agent turns are never replayed automatically.
- **Release tag gate** - Tag builds now wait for lint, tests, and packaging, then verify the tag matches all package and ACP release metadata.

### Changed

- **Release metadata** - Bumped the package version, runtime `__version__`, lockfile package entry, and ACP registry metadata to `0.2.17`.

## [0.2.16] - 2026-07-11

### Added

- **Google Antigravity CLI runtime** - Added a first-class `antigravity-cli` runtime that uses the official `agy` headless interface and its Google Sign-In session. OAuth credentials remain owned by `agy` and the operating system keyring.
- **Google Antigravity SDK runtime** - Added an optional `antigravity-sdk` runtime for API-key users, including normalized text, thinking, tool-call, tool-result, and completion events.
- **Explicit Antigravity harness routes** - Added commands for the signed-in Antigravity harness, the API-key Antigravity SDK harness, and the SuperQode harness with Google BYOK. Provider documentation now identifies harness ownership, authentication, event support, and security boundaries.

### Fixed

- **Antigravity workspace isolation** - SuperQode now passes the exact Antigravity project ID for the active repository and resumes only the conversation ID mapped to that resolved working directory. The adapter no longer uses global `agy --continue`, preventing conversation and tool-path leakage between repositories.
- **Accurate Antigravity connection status** - Antigravity connection panels now report Google Sign-In or Gemini API-key authentication and show Antigravity commands. They no longer display Codex authentication, model resolution, or `:codex` guidance.
- **Picker selection visibility** - Keyboard-driven pickers keep the complete selected block visible after layout. Selecting a connection replaces the picker before rendering its result, so setup guidance and connection details cannot remain below the viewport.

### Changed

- **Codex and Grok CLI integration** - Improved Codex compatibility, active model discovery, completion behavior, Grok subscription model discovery, and connection guidance across the TUI and documentation.
- **Release metadata** - Bumped the package version, runtime `__version__`, lockfile package entry, and ACP registry metadata to `0.2.16`.

### Fixed

- **Grok subscription picker shows the CLI's real model catalog** - The `grok-cli` model list was a hardcoded snapshot, so models the signed-in Grok CLI offers (for example the new `grok-composer` family) never appeared in SuperQode. The picker now sources the catalog from `grok models` (cached per session, in the CLI's own order, with curated metadata for known ids) and falls back to the builtin snapshot when the CLI is missing or logged out.

### Added

- **Connect by model name alone** - `:connect gpt-5.6` now resolves the hosting provider from the catalog and connects. First-party curated providers are preferred over gateway mirrors, so `:connect muse-spark-1.1` goes to Meta, not a reseller; when a model still has several curated routes (e.g. `grok-4.5` via the xAI API or the Grok subscription), the exact `:connect provider/model` commands are listed instead of guessing. Unknown tokens keep the existing provider-models fallback.
- **Auth-store hint in the API-key panel** - The "API Key Required" guidance now also offers `superqode auth login <provider>` (masked prompt, saved to `~/.superqode/auth.json`, 0600) so users can store a key without leaving the TUI workflow or editing shell config.

### Changed

- **Newest models first, everywhere** - BYOK shortlists and full catalogs, the Codex account model picker, and the OpenCode model picker now order entries newest-release-first. Rolling `-latest` aliases stay in the list and win date ties but no longer replace real models — the old exclusive-alias rule hid the brand-new GPT-5.6 family behind stale `gpt-5.x-chat-latest` entries. Realtime audio models are excluded from chat pickers.

### Fixed

- **Codex subscription compatibility and completion** - SuperQode now retries a bundled Codex app-server that cannot parse a newer global reasoning setting (such as `ultra`) with a process-local compatible `xhigh` override, leaving the user's global config unchanged. The live prompt now pages through every `:codex` subcommand and completes effort values, cached model IDs, and sandbox modes.
- **Current local Codex model catalogue** - When the installed standalone Codex CLI is newer than the Python SDK's bundled app-server, SuperQode now uses it for the subscription runtime. `:codex model` / `:codex models` therefore show the account's current models (including GPT-5.6 where enabled), the active-model badge reflects the model actually resolved by the thread, and newly advertised `max` / `ultra` effort levels are available when supported.
- **`:quit` quits from anywhere** - The harness wizard and pending agent questions consumed typed input before the command dispatcher, so `:quit` mid-wizard became a wizard answer instead of quitting. Typed commands now always win: the wizard passes every `:`/`/`/`!` line through to the dispatcher (keeping only its own `:cancel`/`:back` words), and agent questions pass the quit family through while still accepting free-text answers. Covered by unit tests and a mounted-TUI test that types `:quit` mid-wizard.
- **Feedback is always visible in the TUI** - Picker scroll helpers left the log's follow-mode disabled after arrow navigation, so anything written afterwards (Codex "not installed" errors, the "API Key Required" panel, setup guidance) landed invisibly below the fold and Enter looked dead. The helpers now restore follow-mode, and feedback panels anchor the viewport to the *start* of the message so tall panels on short terminals show their heading first, not just their tail. Covered by mounted-TUI regression tests for the Codex profile and BYOK key-guidance flows.

## [0.2.14] - 2026-07-10

### Fixed

- **Picker feedback messages always visible** - Selecting a needs-setup profile (e.g. "Grok subscription" without a `grok login`) wrote its error and guidance lines below the picker while the viewport stayed pinned to the picker top — Enter looked dead. `add_error` / `add_info` / `add_success` / `add_system` and shell output now re-enable follow-scroll and force the log to reveal the message. Covered by a mounted-TUI regression test that drives the real key flow.
- **`add_warning` implemented** - Five call sites (DS4 health, live-model notices) referenced a `ConversationLog.add_warning` that did not exist and would have crashed with `AttributeError` when reached.

### Changed

- **Release metadata** - Bumped the package version, runtime `__version__`, lockfile package entry, and ACP registry metadata to `0.2.14`.

## [0.2.13] - 2026-07-10

### Added

- **Meta listed under US Labs** - Meta now has a curated Tier 1 registry entry (`META_MODEL_API_KEY`, `https://api.meta.ai/v1`) so it appears with the other US labs in the provider picker instead of the auto-synthesized models.dev tail (which defaults to Model Hosts / Tier 2). Routing is unchanged: OpenAI-compatible per-request, model list follows models.dev.

### Fixed

- **CI lint gate green again** - `ruff format` applied to eleven files that had drifted from the formatter (harness self-improvement modules, provider registry/models, Grok tests, and completion surfaces); `ruff format --check` failed the lint job on `main` since 0.2.12.

### Changed

- **Release metadata** - Bumped the package version, runtime `__version__`, lockfile package entry, and ACP registry metadata to `0.2.13`.

## [0.2.12] - 2026-07-10

### Fixed

- **`:acp grok` connects ACP again** - Bare agent names after `:acp` (e.g. `:acp grok`, `:acp opencode`) route to the ACP connect path, same as `:connect acp grok`, instead of printing "Unknown".
- **Model-identity questions no longer force the full tool path** - Prompts like "which coding model are you using" skip tool schemas (word-boundary keyword check so "coding" is not treated as "code"), and the system prompt states the active SuperQode provider/model so the answer is fast and accurate on the subscription harness.
- **Subscription "Hello" no longer multi-minute repo scans** - The fast chat path (short system prompt, no tool schemas, no repo reminders) now applies to cloud providers including `grok-cli`, not only local models. Expanded greeting detection (`Hello there`, etc.) and a hard guard ignores hallucinated tool calls on fast-chat turns so a coding model cannot invent a list_directory storm after a greeting. Plan mode, prompt-format tool calling, and hook processing keep their own tool-call flow (the guard applies only to fast-chat turns), and identity questions that name code artifacts (e.g. "which model file defines the user class") still take the full tool path.

### Changed

- **Release metadata** - Bumped the package version, runtime `__version__`, lockfile package entry, and ACP registry metadata to `0.2.12`.

## [0.2.11] - 2026-07-10

### Changed

- **`:connect grok` is SuperQode harness on subscription** - The Grok subscription profile now imports the official CLI `grok login` session and connects the `grok-cli` provider so SuperQode owns the agent loop (tools, memory, harness). Grok Build as an external agent remains available via `:connect acp grok` (`grok agent stdio`). `:grok connect` / `:grok api` share the harness path.
- **Grok CLI chat proxy version header** - `grok-cli` requests now send `x-grok-client-version` from the installed Grok CLI (or a minimum floor), fixing HTTP 426 responses that reported version `(none)`.
- **Release metadata** - Bumped the package version, runtime `__version__`, lockfile package entry, and ACP registry metadata to `0.2.11`.

## [0.2.9] - 2026-07-09

### Added

- **Grok subscription profile (`:connect grok`)** - New connection profile that runs xAI's official Grok Build coding agent through its native ACP server (`grok agent stdio`) on an eligible SuperGrok/X Premium+ account. Includes agent-registry and discovery entries, a `:grok` command surface (`connect`, `status`, `login`, `help`), completion/suggestion wiring, and docs across the provider, CLI-reference, connection-profiles, and TUI pages.
- **Opt-in direct API on the Grok subscription (`:grok api`)** - Explicitly imports the local `grok login` session token into SuperQode's 0600 auth store and connects the new `grok-cli` provider against the CLI chat proxy xAI documents (`https://cli-chat-proxy.grok.com/v1`), sending the required `X-XAI-Token-Auth` and `x-grok-model-override` headers. `:grok api off` removes the token; `:grok status` reports token state. The default ACP path still never reads the CLI's credentials.
- **Grok 4.5 in the xAI BYOK catalog** - Added `grok-4.5` (500K context, reasoning efforts, vision), `grok-4.3` (1M context), and `grok-build-0.1` with current pricing; refreshed registry example models, base URL, and docs links.
- **`ProviderDef.extra_headers`** - Curated providers can now declare required HTTP headers (with a `{model}` placeholder) applied per-request by the LiteLLM gateway, and can opt into per-request `api_base`/`api_key` routing without env mutation.

### Fixed

- **Stale models.dev cache hiding new models** - A months-old on-disk models.dev cache no longer replaces newer curated builtin model lists (it previously hid day-one models like `grok-4.5` and mispriced lookups via fuzzy matching). Live provider lists now only override builtins when they are at least as new by release date.
- **Retired xAI models removed** - Dropped `grok-3`, `grok-3-mini`, `grok-2`, and `grok-beta` from the BYOK pickers to match xAI's current catalog; video-generation models are now excluded from chat model lists.

### Changed

- **Release metadata** - Bumped the package version, runtime `__version__`, lockfile package entry, and ACP registry metadata to `0.2.9`.

## [0.2.8] - 2026-07-07

### Added

- **Self-improving harness loop** - Added `harness mine-failures`, `harness logbook`, and `harness improve` workflows for mining failures, maintaining repo-local harness memory, exporting bounded improvement projects, and feeding evidence into candidate generation.
- **Candidate audit and ledger** - Added `harness audit-candidate` plus `harness candidates list/show/export` to record accepted and rejected harness candidates, detect protected-surface edits, permission widening, weakened checks, duplicate rejected edits, and missing held-out gates.
- **Held-in / held-out eval splits** - Added split-aware eval tasks and `harness eval --split {all,held-in,held-out}` so candidate improvements can be gated separately from training/proposal tasks.
- **Harness usage metrics** - Harness runs and eval scorecards now aggregate token, latency, and cost metrics where providers expose them.
- **Self-improvement docs** - Documented the end-to-end loop, optimization policy fields, candidate audit gates, candidate ledger, and logbook pruning.

### Changed

- **Release metadata** - Bumped the package version, runtime `__version__`, lockfile package entry, and ACP registry metadata to `0.2.8`.

## [0.2.7] - 2026-07-05

### Fixed

- **Fresh installs with agent-client-protocol 0.11** - `superqode serve acp` failed to start on new installs after the `agent-client-protocol` library released 0.11.0, which removed `session/set_model` and its schema types from the protocol. The ACP server now works on both 0.10 and 0.11, and the dependency is capped at `<0.12` so future protocol changes cannot break released artifacts.

### Changed

- **Release metadata** - Bumped the package version and runtime `__version__` to `0.2.7`.

## [0.2.6] - 2026-07-04

### Added

- **Harbor / Terminal-Bench compatibility for the ACP agent** - The ACP server now honors Harbor's `HARBOR_ACP_REQUESTED_MODEL` environment variable when resolving the session model and implements ACP `session/set_model`, so `harbor run --agent acp` can drive SuperQode on Terminal-Bench using the benchmark's `--model` flag with no wrapper code.
- **Harness template selection over ACP** - `SUPERQODE_ACP_SPEC` (and `serve acp --spec`) now accepts `template:<name>` to pin any built-in harness template for a session without a spec file, enabling harness-variant comparisons in benchmark containers.
- **`benchmark-coding` template** - An autonomous variant of the coding harness for unattended benchmark runs: yolo approvals, and a system stance that never asks the user questions, investigates recoverable state exhaustively (reflog, stashes, backups), always applies a concrete attempt, and verifies before finishing.
- **ACP Agent Server documentation** - Added the ACP Agent Server guide covering editor setup, harness and model resolution, template selection, and running SuperQode on Terminal-Bench with Harbor, plus `serve acp` CLI reference coverage.

### Changed

- **Release metadata** - Bumped the package version and runtime `__version__` to `0.2.6`.

## [0.2.4] - 2026-07-04

### Added

- **ACP agent server** - `superqode serve acp` runs SuperQode as an Agent Client Protocol agent over stdio, so ACP clients such as Zed, JetBrains IDEs, and Neovim can drive SuperQode as their coding agent. Each session resolves a HarnessSpec from `--spec`, the session directory's `superqode.local.yaml` / `harness.yaml`, the conventional harness directories, or the built-in coding template; provider/model resolve from flags, `SUPERQODE_ACP_PROVIDER` / `SUPERQODE_ACP_MODEL`, or the spec's `model_policy.primary`. Prompt turns stream harness model deltas, thinking, and tool calls as ACP session updates, harness tool approvals are relayed as ACP permission requests (allow once / always / reject), and `session/cancel` stops the running turn. The initialize response advertises a terminal auth method that runs `superqode local init --repo .` as the setup experience, as required for ACP registry listing.
- **ACP registry submission assets** - Added `install/acp-registry/superqode/` with the `agent.json` manifest (uvx distribution), monochrome 16×16 icon matching the SuperQode logo, and registry README, ready to copy into a fork of `agentclientprotocol/registry`.
- **Scalable brand logo** - Added `assets/superqode-logo.svg`, a compact vector version of the SuperQode logo with the brand gradient, for docs, README, and website use.

### Changed

- **Release metadata** - Bumped the package version and runtime `__version__` to `0.2.4`.

## [0.2.3] - 2026-06-24

### Added

- **TUI harness wizard** - Added a step-by-step `:harness wizard` flow for creating starter HarnessSpec files from the TUI, plus `:harness init` / flag shortcuts using the same wizard builder as the CLI.
- **TUI CLI parity** - Exposed the remaining CLI command surface in the TUI command list and routed unsupported subcommands through the CLI runner so CLI-only workflows can be launched from the TUI.
- **First harness documentation** - Documented the TUI and CLI wizard path for creating, loading, checking, and running a first HarnessSpec in a few steps.

### Fixed

- **Smoke script source checkout support** - Made the Omnigent agent-session smoke script import SuperQode reliably when run directly from a checkout.
- **Harness model routing** - Made `model_policy.primary` override the active TUI connection for harness runs while preserving valid Ollama model tags such as `*-mlx`.
- **Harness wizard defaults** - Made Enter-through defaults in the TUI wizard create a runnable Qwen local harness with an explicit `ollama/qwen3-coder` model policy.
- **Harness wizard final prompt** - Treated `yes`/`no` typed on the output-file step as the final load answer so the wizard no longer stores `yes` as a filename and loops back to the output prompt.
- **Harness wizard output paths** - Picked the next available default output path such as `harness-2.yaml` when `harness.yaml` already exists, preventing default runs from bouncing back to the output prompt.
- **Harness wizard loading** - Fixed the final “Load this harness now?” step so loaded harnesses remain visible after reconnect/disconnect state changes, and stale `SUPERQODE_HARNESS` paths no longer crash Pure Mode startup.
- **Harness streaming** - Forwarded builtin harness `model_delta` events through Pure Mode so TUI harness runs no longer report `chunks=0` when the model did stream content.

### Changed

- **Release metadata** - Bumped the package version and runtime `__version__` to `0.2.3`.

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
