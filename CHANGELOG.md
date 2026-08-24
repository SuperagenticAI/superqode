# Changelog

All notable changes to SuperQode will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.110] - 2026-08-24

The release where the A2A surface became something you can hand to a customer.
It gains a skill that answers without a repository, per-customer API keys,
request limits, and a safety default that changes what a remote bind serves.

### Added

- A2A now serves JSON-RPC alongside HTTP+JSON, and answers A2A 0.3 as well as
  1.0. The Agent Card advertises all three interfaces with JSON-RPC first,
  because that is the default binding for A2A clients and the one host
  platforms document. Gemini Enterprise, Microsoft Foundry and Bedrock
  AgentCore all accept a 0.3 card, so a single published document now satisfies
  every registration path.
- A second skill, `harness-shortlist`, answers questions about which coding
  agents and harnesses to consider. It reads the curated Harness Hub, so it
  needs no repository, no sandbox and no model call for anonymous callers.
  SuperQode entries are held back from the ranking and disclosed separately,
  because published readiness is derived from integration level and would
  otherwise promote our own harnesses on every request.
- Per-customer API keys through `superqode a2a-keys`. A key is signed rather
  than stored, so verifying one is a signature check and a clock comparison
  with no lookup. Keys carry a customer, tier and expiry, and are revoked
  before expiry by adding their key id to `SUPERQODE_A2A_REVOKED_KEYS`. Nothing
  persists, which matters on a host whose filesystem does not survive a deploy.
- Request limits, held in memory, covering a per-caller window and a daily
  ceiling across every caller. A caller over its window receives `429` with
  `Retry-After`. Discovery and health are exempt, so a host platform polling
  the Agent Card cannot be throttled into a failed registration.
- Requests from keyed callers are read by a model before ranking, which turns
  a sentence such as "we can only use models we host ourselves" into
  constraints that substring matching cannot recover. The model is never sent
  the catalogue and never asked to name a harness, so it cannot introduce a
  claim the Hub does not record. A failed call falls back to the keyword
  parser, and the reply metadata carries `superqode_understood`.
- `scripts/check_published_agent_card.py`, run in CI, compares the published
  Agent Card against the checked-in artifact field by field and confirms that
  `iconUrl` resolves to an image. The discovery origin is a static host
  deployed separately from the A2A server, and nothing previously stopped the
  two from disagreeing.

### Changed

- **A remote bind now serves the shortlist skill only.** The harness skill is
  omitted from the Agent Card, and a request that names it is refused. A
  bearer token is shared by everyone holding it, so serving the harness
  remotely gave every holder the same working directory under whatever the
  bound spec permitted, and the default coding template permits shell access
  and writes with `sandbox: local`. To restore the previous behaviour, pass
  `--expose-harness` with both `--spec` and a token. Anyone running
  `serve a2a --allow-remote` today will see the harness skill disappear from
  their card after upgrading.
- A remote bind no longer requires a token when it serves the shortlist alone.
  Authentication is now required in proportion to what a deployment exposes,
  which is also what makes the agent registrable on platforms whose
  registration offers OAuth or nothing and has no field for a bearer token.
- The Agent Card version is a stable value in `superqode.a2a.server` and no
  longer follows the package version. A2A defines that field as the version of
  the agent, and deriving it from the package tied republication of the card to
  the release cadence. The running build is reported at `GET /health` as
  `superqode_version`.
- The exported Agent Card is serialised the way the server serves it. The
  previous protobuf conversion silently dropped the 0.3 discovery fields, so a
  published card promised less than the running server answered.
- HarnessBench records paths relative to its manifest. Absolute paths pinned a
  scorecard to one machine's directory layout, so a published result carried
  the operator's home directory and the same benchmark run from a different
  checkout produced a different fingerprint.

### Fixed

- The DeepAgents backend failed on every Google model with "Unable to infer
  model provider". LangChain names that provider `google_genai`, and SuperQode
  was passing its own provider id through unchanged. Vertex and Mistral had the
  same mismatch.

## [0.2.109] - 2026-08-22

### Added

- The UHP connect screen takes a token cap beside the server address, so a
  task refused for its budget can be fixed without leaving the terminal
  interface. 0.2.108 added the cap but exposed it only on
  `superqode connect uhp --max-output-tokens`, which left the TUI able to
  surface the failure and unable to correct it. The field prefills from the
  saved connection, and clearing it removes the cap.

## [0.2.108] - 2026-08-22

### Added

- `:connect` offers a fourth choice, **Connect to existing agent protocols**,
  for a coding loop that lives behind a wire rather than in a product you name.
  It lists Agent Client Protocol (ACP), Agent2Agent (A2A), and Unified Harness
  Protocol (UHP). MCP is deliberately absent: it extends whatever harness is
  running rather than owning a loop, so it stays on `:mcp`. A2A is discovery
  for now, because operations against a published agent card need a bearer
  token the card does not carry.
- The UHP row opens a screen that takes a server address, lists what the server
  advertises, and switches to the harness you pick, with a mouse or the
  keyboard. The address is prefilled with HarnessRouter Community Edition's
  Docker location, including the path prefix, so a local container needs no
  typing. Discovery runs in a worker, so a server that never answers cannot
  freeze the terminal.
- `superqode connect uhp --max-output-tokens N` caps the token budget for one
  task. Some providers check affordability against the budget a task reserves
  rather than what it uses, and refuse a large reservation outright, so a
  one-word prompt could fail with a number nobody chose. The cap is saved with
  the connection; `SUPERQODE_UHP_MAX_OUTPUT_TOKENS` sets it per shell. Without
  one, no budget is sent and the server's own default applies.

### Fixed

- Switching to a harness the server owns leaves the session able to send.
  0.2.107 stopped asking for a local model on those harnesses, and that prompt
  was also what connected the session, so `:harness switch uhp` went active
  and then refused every message with "Not connected".
- The UHP connect screen paints every surface. Textual gives `Input`,
  `OptionList`, `Button`, and `Footer` their own panels regardless of the
  screen background, so setting only the screen left grey widgets on black.

## [0.2.107] - 2026-08-22

### Fixed

- Switching to a harness the server owns no longer asks for a local model.
  `:harness switch uhp` fell through to the model step because a UHP harness
  declares no local model policy, so it collected a setting the run never
  used. A harness whose spec reports `policy_owner: server` now skips that
  step.
- The harness summary states where a remote harness gets its tools. Switching
  to a UHP harness reported "Tools: none, so it can discuss code but not
  change it", which describes what SuperQode contributes locally rather than
  what the harness can do. The remote agent has its own tools, so the row now
  reads "the server's, along with its sandbox and approvals".

## [0.2.106] - 2026-08-22

### Fixed

- A UHP task runs on the model the server's harness is configured with.
  `superqode harness run` defaults `--model`, and that default was being sent
  to the server, overriding the remote harness's own model with one the
  server had no integration for. The first task on a freshly connected server
  failed with a request for a provider serving a model the user never chose.
  Only an explicit `--model` on the command line now overrides the server;
  `SUPERQODE_MODEL` is a local default for SuperQode's own harnesses and no
  longer reaches a remote harness.

### Changed

- The `model.requested` event reports `(server default)` on a UHP run where
  the server chooses the model, rather than naming a model SuperQode did not
  send.
- The UHP guide states that the workspace belongs to the server. The harness
  runs in its own workspace inside the server and SuperQode does not upload
  local files, so a prompt about "this repository" describes the server's
  workspace. UHP's file input endpoint is not used yet.

## [0.2.105] - 2026-08-22

### Added

- A harness on a UHP server is now a normal SuperQode harness. Once
  `superqode connect uhp` has selected one, `uhp` appears in the harness
  switcher, the Hub, and the catalog, so `:harness switch uhp` and
  `superqode harness run uhp` work like any other route. The TUI and the
  harness kernel run backends rather than protocol adapters, so this adds a
  `uhp` runtime backend beside the existing protocol adapter.
- The `uhp` backend reports itself unavailable, with the command to run, until
  a server address and a harness id are both configured. Availability tracks
  configuration rather than an installed package.

### Fixed

- `:connect uhp` connects instead of only reporting an already-saved
  connection. `:connect uhp <url>` now reaches the UHP path; any argument
  previously cleared the profile lookup and the command fell through to the
  BYOK provider picker, which read `uhp` as a model provider.
- A UHP conversation continues between turns in the TUI. The harness backend
  runs outside the protocol controller, so nothing persisted the response id
  that threads a conversation; it is now stored per session under
  `.superqode/uhp/sessions/`. A first turn no longer fails on a resume that
  has nothing to resume.

## [0.2.104] - 2026-08-22

### Added

- SuperQode speaks the Unified Harness Protocol (UHP) `2026-08-11` as a
  client. `superqode connect uhp --base-url <url>` reads the server's
  discovery document, lists the harnesses it advertises, and selects one.
  A saved connection registers the `uhp` route, so
  `superqode harness run uhp` runs the task on the server and returns its
  work through the same session, event, and evidence model as a local
  harness. `:connect uhp` runs the same discovery from the TUI.
- `superqode.harness.uhp_client` is a standalone UHP client with no
  SuperQode types in its signatures: protocol discovery, harness listing and
  configuration, blocking and streaming task submission, session turns and
  files, file download, and response and session cancellation. Server errors
  raise the six typed classes the specification defines.
- `UHPHarnessProtocolAdapter` normalizes a UHP stream into the canonical
  event vocabulary, including text deltas, reasoning, tool calls and their
  results, and produced files as artifacts. It declares `steer` and
  `checkpoint` unsupported, because UHP has no operation for either.
- Adapters can report durable state through a new `session_state` hook. The
  protocol controller persists it after each turn, so a UHP conversation
  continues across a process restart instead of silently starting over.

### Fixed

- `harness protocol list` and `harness run` reject a UHP route that is not
  ready. A connection without a selected harness reports what to run rather
  than appearing available and failing during the task.
- `superqode connect uhp --harness <id>` exits non-zero and saves nothing
  when the server does not advertise that id, instead of reporting a
  connected server.

### Security

- The UHP connection at `~/.superqode/uhp.json` is created with owner-only
  permissions rather than being widened and then narrowed. A key supplied
  through `SUPERQODE_UHP_API_KEY` is never copied into that file, and
  stripping it does not discard a different key saved earlier with
  `--api-key`.
- Every UHP task submission carries an `Idempotency-Key`, so a retried
  request cannot start a second agent in the same workspace. Every request
  carries `UHP-Version`, so a server cannot silently answer at another
  version.
- A dropped stream no longer abandons a running task. SuperQode re-reads the
  response, which the specification makes the source of truth after a
  disconnect, and cancels the task explicitly when it is still running.

## [0.2.103] - 2026-08-21

### Changed

- Open and Closed harnesses are now the default connect layout. `:connect
  agents` lists Subscriptions, ACP, Open harnesses, and Closed harnesses
  instead of collapsing the last two into a single Other harnesses row. Open
  vs Closed is the harness licence, not the model family. `:connect
  other-harnesses` still works and opens the Open list, and
  `SUPERQODE_CONNECT_MENU=v1` or `"connect_menu": "v1"` in
  `~/.superqode/config.json` restores the previous layout.
- The Warp Agent row states why it stays an Ecosystem watch entry rather than
  an attach. Warp Agent's loop runs server-side and its open client is
  AGPL-3.0, so there is no component to embed and no protocol to speak.
  SuperQode will revisit an attach when an ACP surface or licence terms make
  one clean.

## [0.2.102] - 2026-08-19

### Added

- `:connect fx` attaches Vercel Labs' experimental fx agent over `fx acp`
  after a local `fx login`. The Subscriptions row spends the signed-in
  Vercel team's AI Gateway credits and strips a leftover
  `AI_GATEWAY_API_KEY` so the session cannot divert onto metered key
  billing. `:connect fx-key` on Open injects that Gateway key into the
  fx ACP child only, with no local model and no SuperQode BYOK picker.
  `:connect acp fx` remains available. `:fx`, `:fx login`, `:fx connect`,
  and `:fx status` are the TUI command surface.

## [0.2.101] - 2026-08-19

### Added

- `:connect kimi-code-key` connects instead of printing a setup card. It
  declared a Moonshot key, a BYOK provider, and a local list while sitting on
  the setup-card route, so none of that was reachable. It now attaches over ACP
  on an exported `MOONSHOT_API_KEY` or `KIMI_API_KEY`, and asks for a model
  otherwise.
- `:connect prime-agent-key` runs Prime Agent on the model you pick. Its
  `vendor-key-rpc` route was never implemented, so its declared provider lists
  were unreachable. A cloud provider's key now reaches the Prime process
  through its child environment, and a local pick is registered in Prime's own
  `models.json`, which is the mechanism Prime documents for custom
  OpenAI-compatible endpoints. Its local list is narrowed to the engines
  SuperQode can resolve a base URL for.

### Fixed

- Every attaching row reports whether its agent can actually start. 0.2.100
  added probes for Factory, Junie, Qoder, and Poolside, but the rest still fell
  through to a default that reports ready on any machine, so the list promised
  a connection that failed at the attach. The probe reads the command the ACP
  registry launches rather than the agent's name, because the two differ: Pi
  attaches through `pi-acp` and fast-agent through `uvx`.

## [0.2.100] - 2026-08-18

### Added

- Open rows that end in an ACP attach now connect instead of printing a setup
  card. `:connect opencode-key`, `:connect fast-agent`, and `:connect pi` ask
  for a key or local model and hand it to the agent's own loop.
  `:connect grok-key` and `:connect qwen-code-key` attach straight away when
  the harness's own key is already exported, and ask for a model otherwise.
  Credentials go to the agent process only, never into the SuperQode
  environment, and a key is passed only under a variable that is known to be
  read: the one the catalog records for that harness, or the provider's own
  documented variable for a model-agnostic agent. Picking a local endpoint that
  neither names still attaches the agent and says the model has to be set
  inside it.
- The model step hides a row that offers nothing. Grok Build's key is xAI's
  own, so its screen lists Local without an empty BYOK picker behind it.
- `:connect poolside-key` offers the local endpoint its row already promised.
  Poolside names the variable for a standalone endpoint, so it now takes the
  same attach path: the exported key connects directly, and a local pick sets
  `POOLSIDE_STANDALONE_BASE_URL`.
- Open and Closed rows show the harness licence, so `AGPL-3.0` and `MIT` are
  told apart in the picker. A licence SuperQode has not verified draws no
  badge rather than an empty one.

### Fixed

- Qoder and Poolside report whether their CLI is installed. Every other vendor
  row probes PATH, so those two claimed to be ready on any machine and then
  failed at the attach.
- A key-harness session is no longer dropped when the harness id differs from
  the catalog row id. The session recorded only the row id, while a harness
  switch answers in the harness namespace. Matching also stopped using a
  suffix test, which made a `my-tau` harness match `tau`.
- Six visible rows told the Hub nothing about themselves, so `:hub` and
  `hub list --openness` disagreed with the Open and Closed lists about the same
  harness. A test now requires every drawn row to state its openness in both
  places.

- `:connect muse-key` no longer answers `Unsupported external CLI profile`.
  The Closed key row shares Muse's `external-cli` connector, which matched only
  the account row by id, so `META_API_KEY` was never read. It now asks for the
  key and then states that Muse Code is run directly.
- Open rows are selectable from the shell. `--connect` and tab completion
  validate against the flat profile list, which carried the Closed catalog rows
  but not the Open ones, so `--connect droid-key` worked while
  `--connect tau` was rejected as an invalid choice.
- Vendor key rows find a key stored with `superqode auth login`. Only
  `droid-key` named its provider, so `poolside-key` skipped the credential
  store and asked for `POOLSIDE_API_KEY` again.
- The API Key Required card no longer recommends a login for a provider that
  does not exist. `login_id` was guessed from the variable name, so
  `junie-key` printed `superqode auth login jetbrains` and `qoder-key` printed
  `superqode auth login qoder`, both of which answer `Unknown provider`.
- `docs/assets/harness-hub.json` includes the Junie record. The published
  snapshot was exported before that profile landed, and a test now compares it
  against the generated index.

### Changed

- `connect_menu` is read once per config file rather than on every picker row,
  keyed by modification time and size so an edit still takes effect. The TUI
  and the flag now resolve `~/.superqode/config.json` through one helper.
- Connect helpers are called directly instead of through `getattr` probes.
  The indirection let a rename silently no-op at some call sites and fall back
  to inline state clearing at others.

## [0.2.99] - 2026-08-17

### Added

- Open and Closed connect lists for existing harnesses. Subscriptions stay
  sign-in plans; Open is OSI-licensed harnesses with a key or local model;
  Closed is proprietary harnesses with that vendor's key. `Other harnesses`
  remains the v1 label. Set `SUPERQODE_CONNECT_MENU=v2` to use the new
  categories, or `"connect_menu": "v2"` in `~/.superqode/config.json`.
- Visible Open rows for Tau, DeepSeek Harness, DeepAgents SDK, OpenCode,
  Prime Agent, jcode, Grok Build, Qwen Code, fast-agent, Pi, Goose, Cline,
  OpenHands, Mistral Vibe, Hermes Agent, Letta Code, Warp Agent, and Kimi Code.
- Visible Closed rows for Factory Droid, Junie, Muse Code, Qoder CLI,
  Poolside, and ZCode (inspect only).
- Letta Code (`:connect letta`) and Warp Agent CLI (`:connect warp`) as Open
  setup cards. Junie is on Subscriptions (`:connect junie`) and Closed
  (`:connect junie-key`).

### Fixed

- Selecting an Open/Closed setup-card row no longer crashes. The card used a
  missing theme color.
- Picker rows no longer emit OSC-8 `superqode://pick/` links, so terminals
  stop covering the list with a ⌘-click tooltip. The ↗ stays as the click cue;
  a click still selects the row by its `[n]` header.

## [0.2.98] - 2026-08-16

### Added

- Added support for Gemini 3.7 Flash (`gemini-3.7-flash`) in the Google BYOK catalog, default model constants, and TUI model pickers.
- Dynamic models.dev Gemini model discovery so newly fetched Gemini models from `models.dev` are preserved instead of filtered out.

### Improved

- Upgraded calm mode tool activity presentation in TUI:
  - Tool arguments (e.g. bash commands, file paths, search patterns) are preserved across execution so tool completion lines always show their target (e.g., `✓ run pytest...` or `✓ edit src/app.py`).
  - Clear checkmark (`✓`) and failure (`✗`) indicators replace repeating ambiguous `✷` symbols.
  - Live bottom status throbber displays active tool verb and target details (e.g., `⚡ Run: pytest tests/...` or `📄 Read: models.py…`).

## [0.2.97] - 2026-08-16

### Added

- First-party support for LangChain DeepAgents, through the two routes it
  actually ships as. `deepagents` is a selectable harness backed by the
  DeepAgents SDK, so the runtime adapter that already existed is now visible in
  `:hub`, in the harness picker, in `:connect other-harnesses`, and in
  `superqode hub list` instead of being reachable only by hand-writing a spec
  with `runtime.backend: deepagents`. `deepagents-code` connects the prebuilt
  `dcode` terminal coding agent over its own ACP server, placing it in the Hub
  next to Codex and Claude Code. `superqode harness init <name> --template
  deepagents` starts a repository-owned spec from the same preset.
- The Harness Hub can filter to open-source harnesses. Openness describes the
  harness implementation rather than SuperQode's route to it, so OpenCode over
  ACP, Codex as a vendor connection, DeepAgents as an optional runtime, and
  Aider on the ecosystem watchlist all answer the same question without leaving
  the category that explains how to connect them. Press `o` in `:hub`, or use
  `superqode hub list --openness open`. Records gained `openness`, `license`,
  and `repository` fields, taking the Hub index to schema 1.5.
- Openness resolves from four sources in precedence order: a license verified
  against the project's published metadata, the `open-source` tag already
  carried by the bundled ACP catalog, the `harness_openness` field already
  curated on vendor connection profiles, and SuperQode's own Apache-2.0 source.
  Anything none of them can answer stays blank and reads as "Not published".
  A source-available license is not reported as open source, and a repository's
  own HarnessSpec is never given a license SuperQode has no way to know.

### Fixed

- The DeepAgents backend could not drive a local Ollama model. It treated any
  colon in a model name as a provider separator, but Ollama writes its version
  tag that way, so `qwen3.5:2b` lost its prefix and LangChain reported
  `Unable to infer model provider`. Since SuperQode splits provider from model
  before a request reaches a backend, only an exact `<provider>:` prefix now
  counts as already qualified. Verified end to end against a live local model.

### Changed

- The welcome screen headline reads "THE HARNESS LAYER FOR CODING AGENTS",
  matching the README, the website, and the PyPI description. It was the last
  surface still saying "unified", so the product described itself one way on
  first launch and another way everywhere else. The narrow-terminal fallback
  drops to "THE HARNESS LAYER" for the same reason.
- Vendor rows on the Subscriptions screen are named for the product alone.
  `Codex subscription`, `Cursor subscription`, `Amp subscription`,
  `Grok subscription`, `Factory Droid subscription`, and `Kiro subscription`
  become `Codex`, `Cursor`, `Amp`, `Grok`, `Factory Droid`, and `Kiro`. Nine of
  the fifteen rows already read that way, so the screen was inconsistent, and
  the heading above them already says these are subscriptions. Profile ids and
  every `:connect <id>` command are unchanged. The plan-menu route `plan-grok`
  keeps the name `Grok subscription`, which now also removes a collision where
  two different profiles answered to the same label.
- The `deepagents` extra now requires `deepagents>=0.7.0,<0.8.0`. An
  out-of-range install reports a version problem naming the required range
  rather than claiming the package is missing.

## [0.2.96] - 2026-08-15

### Added

- `superqode harness drift` checks whether a harness does what its spec
  declares. `doctor` answers whether a harness can run; drift answers whether
  the harness that resolved is the one the spec described. Seven declarations
  are compared against what actually resolves: the runtime backend, the sandbox
  provider, every declared tool, the shell and write stances against the tools
  that need them, the event store behind declared observability, and whether a
  checks block promising to fail a run has any step to fail on. Exits non-zero
  on drift so it can gate a pipeline, with `--json` for automation and
  `:harness drift` in the terminal.
- Tools published by an MCP server are reported as supplied at run time rather
  than counted as drift, because a static check cannot see a server that has
  not connected yet.
- Aider, Crush, Plandex, and Roo Code are indexed in the Harness Hub under
  Ecosystem watch, taking the public catalog to 94 entries.

### Fixed

- A HarnessSpec declaring a tool that cannot be resolved was silently losing it.
  `ToolRegistry.filtered` keeps only the names that exist and drops the rest
  without complaint, so a typo removed a tool with no warning anywhere. Drift
  now reports it.

### Changed

- The Omnigent comparison page states where each project is stronger instead of
  declining to compare them. It covers the distinction between conformance
  benchmarking, which asks whether a harness is honest, and outcome
  benchmarking, which asks whether it is good.

## [0.2.95] - 2026-08-15

### Added

- The Harness Hub, a full-screen terminal browser for every harness SuperQode
  can run, opened with `:hub` or the `⚓ Hub` button in the top toolbar. It
  supports search, filters (Ready, Needs setup, Your harnesses, Coming soon),
  and a details pane covering runtime, provenance, continuity, declared tools,
  policies, installation and authentication steps, and the TUI and shell
  commands for each entry. Clicking a row selects and previews it; activating a
  harness requires the explicit Use button or Enter on the highlighted row, so
  browsing with a mouse never switches harness by accident.
- Every HarnessSpec entry also carries the commands that measure and improve
  it, shown as Evaluate and Optimize blocks beside the commands that run it.
  Vendor and ACP entries show neither, because the connected agent owns its own
  loop.
- `sq hub`, `sq hub list`, and `sq hub show` expose the same inventory to
  scripts and documentation builds. `--json` emits a versioned index and
  `--public` produces a publication-safe snapshot whose readiness is structural
  rather than measured on the exporting machine.
- `:activity` and focused result screens, so a consequential outcome no longer
  depends on the bottom of the transcript. Results remain revisitable for the
  session with their primary recovery or next-step action.
- Cursor, Amp, Muse Code, Prime Agent, Devin, Factory Droid, Kiro, and the GLM
  Coding Plan appear as vendor entries in the harness picker.
- ZCode and jcode are indexed under Ecosystem watch. Neither is runnable from
  SuperQode, and each entry states why: ZCode documents no ACP server, headless
  CLI, or external SDK, while jcode documents a headless `jcode run`, a
  TypeScript SDK, and a versioned harness API, so a route is buildable once one
  is implemented and tested.

### Fixed

- Streamed tool calls are merged back into whole calls. Providers that send a
  tool call's name and id in the first delta and then dribble the arguments
  JSON across later deltas (llama.cpp) produced one usable call plus a run of
  nameless ones, which executed, failed, and returned a null name that the
  server rejected outright. Deltas are now grouped by `index`, falling back to
  `id` and then to the previous append behaviour, so providers that send a
  finished call per chunk (Ollama, Gemini) are unaffected and parallel tool
  calls stay separate.
- Tool-call normalization preserves the streamed `index` and omits null `name`
  and `id` values instead of writing them into the message sent back to the
  provider.
- Opening the harness picker or the Hub no longer blocks the terminal for
  seconds. Checking whether one optional Python package was installed went
  through a probe of every runtime, which shelled out to each vendor CLI.

### Changed

- `:hub` opens the Harness Hub. Model search has the explicit name
  `:local search <model>`, with `:hub model <model>` kept as a migration alias.

### Added

- DeepSeek Harness runs as an optional harness backend
  (`runtime.backend: deepseek-harness`, installed with
  `uv tool install "superqode[deepseek-harness]"`). DeepSeek keeps ownership of
  its agent loop, tools, prompts, compaction, and sandbox; SuperQode launches
  the runtime and normalizes its JSON-RPC stream into harness events. The
  `deepseek-harness-sdk` distribution ships DeepSeek's compiled TypeScript
  runtime as a Python platform wheel, so the route needs no Node.js. The
  dependency is marked for the three platforms DeepSeek publishes wheels for
  (macOS arm64, Linux x86_64/aarch64) and reports as missing elsewhere.
- A `deepseek-harness` preset in the harness catalogue and
  `harness list-templates`, selectable from `:connect` under Other Harnesses or
  with `:harness switch deepseek-harness`. It needs no harness file and no
  Cordis composition, because the SDK injects DeepSeek's own bundled
  composition. `dsh` and `deepseek` resolve to the same preset, and
  `runtime.backend: dsh` keeps working.
- A connected local or OpenAI-compatible route is bridged onto the runtime's
  endpoint configuration, so connecting to `ollama/qwen3.5:9b` and switching to
  this harness runs on Ollama. The DeepSeek route name is preserved because the
  bundled composition registers only `deepseek-official`. Providers with their
  own wire format, such as Anthropic and Google, are left alone.

### Notes

- DeepSeek Harness executes its own tools, so SuperQode approval profiles do not
  gate them. Use `DSH_PERMISSION_MODE` for the control the runtime enforces. The
  preset defaults it to `workspace-write` and carries a selection warning.
- DeepSeek Harness is an upstream developer preview; the SDK pin
  (`>=0.1.0rc6,<0.2.0`) should move deliberately.

## [0.2.93] - 2026-08-12

### Added

- The Grok headless subscription runtime (`:runtime grok-cli`) now projects
  SuperQode allow/deny patterns onto Grok's `--allow`/`--deny` rule DSL when
  a permission manager is available (TUI PureMode, headless, and harness
  backend). Unknown globs are dropped rather than guessed.

### Changed

- Grok routes are named as four distinct products: Grok Build over ACP
  (`:connect grok`), the headless vendor loop (`:runtime grok-cli`), SuperQode
  harness on the plan (`:grok api`, the `grok-cli` provider), and xAI BYOK.
  Subscriptions still open ACP. The `grok-cli` runtime is print/CI only.
- The Grok subscription catalog prefers `~/.grok/models_cache.json` when it
  is a recent session cache, then the CLI chat-proxy `/models` endpoint, then
  `grok models`. The shipped fallback default is grok-4.6. `grok-build`
  remains a CLI alias. `:grok models` names the source it actually used.

### Fixed

- `:runtime grok-cli` now renders the full `grok -p --output-format
  streaming-json` stream: tool calls, tool results, plans, usage, errors,
  and spend fields on `end`. Previously only text, thought, and end survived,
  so Grok appeared to think and then answer with no tools. SIGINT/SIGTERM
  (exit 130/143) is cancelled, not failed.
- SuperQode `deny` maps to Grok `dontAsk`. The old `plan` mapping was a
  documented no-op. `ask` maps to Grok's classifier (`auto`) rather than
  `acceptEdits`. The first-turn notice says rules bind, not per-tool prompts.
- `:grok api` reads the current `~/.grok/auth.json` schema
  (`{issuer}::{client_id}` plus the legacy sign-in URL), prefers `expires_at`
  (hours, not a 7-day mtime guess), never copies `refresh_token`, and
  re-reads the CLI file only to refresh a snapshot that `:grok api` already
  imported. Status and models cannot silently re-import a token after
  `:grok api off`.
- `:grok status` no longer probes the live catalog on the TUI event loop.

## [0.2.92] - 2026-08-12

### Added

- The Docker and Monty execution profiles ship as built-in harness templates.
  `rlm-docker` and `rlm-monty` are selectable with `:harness switch`, so an
  isolated RLM kernel no longer requires hand-authoring a harness
  specification. Repository-owned specifications remain the way to tune the
  limits each profile enforces.

### Changed

- The RLM sandbox status names the profiles that exist rather than only the
  one in use, and `:rlm sandbox <profile>` points at the built-in template
  that selects it instead of describing a file to edit.
- The built-in RLM harness description names its host, Docker and Monty
  execution profiles.

### Fixed

- The missing-Monty error suggested an installation command that cannot reach
  a `uv tool` environment, which is how the documented installation path
  installs SuperQode.

## [0.2.91] - 2026-08-11

### Added

- The native RLM example now includes a checked-in Pydantic Monty HarnessSpec
  for restricted, read-only repository analysis with persistent Python context
  and bounded semantic subcalls.

### Changed

- The RLM example guide now separates Monty analysis from Docker coding and
  documents the public TUI commands for inspecting and managing resident RLM
  sessions without including recording-specific instructions.

## [0.2.90] - 2026-08-11

### Added

- Native RLM root sessions now run in a resident Python worker. The terminal
  can detach without cancelling the turn, then replay and follow the same
  command after reconnecting. One root worker owns the complete recursive
  agent tree and its global depth, child and parallelism limits.
- `:rlm status`, `:rlm attach`, `:rlm detach` and `:rlm stop` expose the
  resident lifecycle in the TUI. An RLM demo fixture documents the
  one-tool workflow, Docker profile and operational commands.

### Changed

- Product framing now describes SuperQode as the unified harness layer for
  coding agents. The README, documentation, package metadata, ACP listing and
  TUI distinguish SuperQode's open-source layer from the native, open-source,
  proprietary, local and hosted agents it can run or connect.
- Docker Python cells now enforce their configured deadline against the real
  in-container kernel process. A timed-out kernel is replaced and restores the
  last completed checkpoint. Kernel output and checkpoint payloads are bounded
  before crossing the runtime protocol.
- Semantic subcall usage and quota consumption persist beside the RLM session,
  so restarting a resident worker cannot reset host-enforced limits.
- Resident worker manifests contain only portable public configuration; live
  control-plane objects and private metadata never cross the process boundary.

### Fixed

- Provider failures in PiPy-backed harnesses now emit a visible protocol error
  instead of ending as an empty successful run.

## [0.2.89] - 2026-08-11

### Added

- Native RLM Python observations are bounded before entering the root model's
  history. Large values remain available when assigned in the persistent
  namespace and can be inspected through smaller slices.
- Detached Docker workers publish their real container identity. Session
  recovery verifies both the worker request and the live container before
  reattaching, and reports the child as interrupted when either cannot be
  verified.

### Changed

- Docker RLM sessions start without network access unless `allow_network` is
  explicitly enabled. Setting `allow_write: false` mounts the repository
  read-only, which also blocks direct Python writes that bypass `workspace`.
- RLM capability metadata, `:rlm help`, and `:rlm sandbox doctor` now report the
  implemented host, Docker, and Monty profiles rather than the original
  host-only state. Docker read, shell, and command rules are described as
  guardrails because unrestricted container Python can call `open` and
  `subprocess` directly.

### Fixed

- `context.read()` can no longer bypass context include, exclude, binary, or
  file-count policy by naming a repository path directly.
- A detached worker with zero remaining recursion depth no longer resets to the
  default depth of three.
- Failed and timed-out semantic subcalls count against the host-owned call
  quota, and `:rlm usage` measures the context policy configured for the active
  session.

## [0.2.88] - 2026-08-11

### Fixed

- Local models outside a hardcoded family allowlist were silently denied tool
  definitions, so an agentic request came back as prose describing the command
  the model would have run, with nothing executed. Tool gating now asks the
  running provider what a model supports, falls back to the model registry, and
  only withholds tools on an explicit denial. A model the runtime cannot
  describe is sent tools and allowed to fail loudly, because a false negative
  here is invisible while a false positive is a diagnosable server error.
  Ollama reports this through the capability list on `/api/show`; providers that
  forward tool definitions verbatim are recorded once, as providers, rather than
  as the models they happen to serve today.
  This affected every harness built on the shared runtime, including Core and
  Workbench. Harnesses with their own runtimes, such as RLM, PiPy and Tau, were
  never involved, and hosted models were never gated this way.
- `vllm`, `sglang` and `tgi` refused to probe tool support for any model whose
  name was unfamiliar, and reported the same guess in their model listings.
  These runtimes pass tool definitions through to the model, so the probe now
  runs and the listing reflects the server contract.

### Added

- `SUPERQODE_CAPABILITY_TIMEOUT` bounds how long a local runtime is given to
  answer a capability question. It defaults to 2 seconds, and a timeout leaves
  the model treated as tool-capable rather than silently downgraded.

## [0.2.87] - 2026-08-10

### Fixed

- The DwarfStar (ds4) model picker listed the same model twice. ds4-server
  advertises both `deepseek-v4-flash` and `deepseek-v4-pro` whatever shape the
  build actually loaded, stamping each entry with the loaded shape's name, so
  one of the two rows was a phantom pointing at weights that were not there.
  The reported name now resolves which shape is real. Aliases that only toggle
  thinking, such as `deepseek-chat` and the GLM and Laguna variants, share a
  name legitimately and are still listed in full.
- Models Ollama serves in its native non-GGUF format were degraded to a
  4096-token, tool-less, text-only listing. Their `/api/tags` entries carry
  empty family, size and quantization fields and no context length, so the
  name-based heuristics fell through to their defaults. Such entries are now
  filled in from `/api/show`, which reports the truth for any architecture.
  Self-describing GGUF entries are untouched and cost no extra request.
- `get_model_info()` guessed from the model name while holding the `/api/show`
  payload, so a model could list with its real context window and then resolve
  at 4096 tokens on connect. It now reads the declared capabilities and the
  architecture-scoped context length, with a Modelfile `num_ctx` taking
  precedence because that is what the server will apply.
- Tool-calling support was refused without being tested for any architecture
  missing from a hardcoded family allowlist, which no model released after that
  list was written could join. Ollama's declared capabilities are now
  authoritative, and the probe runs; the name heuristic remains the fallback
  for older Ollama builds that omit the field.

## [0.2.86] - 2026-08-10

### Added

- Semantic subcalls in the RLM Python namespace: `llm_query(prompt, context=...)`
  asks a model one bounded question about text the environment already holds,
  and `llm_query_batched(prompts)` runs several concurrently while preserving
  input order. Answers are handles with a compact representation, so a long
  answer stays in the environment as data instead of being copied into the root
  conversation. This is distinct from `rlm.run`, which starts a full child
  coding session.
- `:rlm usage` reports the costs the RLM layer owns: subcalls against their
  quota, child agents by status with their tokens and cost, and the size of the
  corpus in scope. It states that root conversation usage is reported by the
  harness rather than silently omitting it.
- A `context` object in the RLM Python namespace holding the repository as data:
  `len(context)` sizes the corpus from directory metadata without reading it,
  `select()` narrows a view without disturbing the original, and `chunk()`
  returns slices that carry their file, index and offsets so answers over chunks
  can be traced back to their source. Discovery respects `.gitignore` when git
  can answer and skips binaries, bounded by `context_*` keys under
  `runtime.config`. Under the `docker` profile the sandbox is served by the
  host, which reads the same bind-mounted files, so discovery and chunking have
  one implementation rather than two that can drift.
- Subcall limits are owned by the host rather than the namespace, since the
  model writes the Python that calls them: one shared quota per session covering
  both single calls and batches, plus batch size, concurrency, prompt and
  response size, timeout, token budget and a model allowlist, configured under
  `runtime.config` with `subcall_*` keys. Subcall usage is accounted separately
  from root and child-agent usage. Under the `docker` profile the query leaves
  the boundary because provider credentials never enter it, and the host
  enforces the same quota.

- A `monty` sandbox profile, the research and evaluation tier, running the
  persistent interpreter inside Monty: no subprocess, no real filesystem and no
  third-party imports. Persistent Python state, `context`, `llm_query` and
  `workspace.read` all work, while `shell.run`, `workspace.write` and
  `workspace.edit` refuse by name with the reason. Completion gates refuse
  rather than escaping to the host, since a gate outside the profile would
  verify the wrong machine, and recursion is absent rather than half-wired
  because Monty has no processes. Checkpoints are Monty snapshots, so restoring
  one never has the host deserialize anything. Needs `superqode[monty]`.
- The built-in `rlm` harness is now named as the production recursive route in
  the README, the harness catalogue and the RLM routes comparison, which
  previously described three routes without mentioning it at all. RLM Code is
  described by the job it is better at, research and evaluation, rather than as
  a competing coding harness, and stays available and addressable exactly as
  before.
- `size()` on context, chunks and subcall responses, which behaves identically
  under every profile. Monty does not dispatch `len()` to a user class, so code
  meant to run everywhere uses `size()` instead.

### Fixed

- The tools catalog listed the Monty tool as `monty_python_repl`; it registers
  as `python_repl`. The inventory check that would have caught this only runs
  when the optional dependency is installed.
- The Monty `python_repl` tool works again. `pydantic-monty` changed shape:
  `Monty` is now a worker-pool context manager rather than something
  constructed with the code, so every call raised
  `Monty.__new__() takes 0 positional arguments`. The tool now uses
  `Monty()`, `checkout()` and `feed_run()`, and the optional dependency floor
  moves to the version that API exists in. The break was invisible because
  those tests skip whenever the optional dependency is absent, which is the
  default.

## [0.2.85] - 2026-08-10

### Added

- The native RLM harness is addressable from the connect flow with
  `:connect harness-rlm`, listed directly after Core.
- The RLM kernel honours a sandbox profile resolved from `runtime.config` over
  the harness execution policy. `workspace` and `shell` enforce read, write and
  shell permissions, a command allowlist, compound-command rules and an
  environment allowlist. Child agents inherit the profile, and it travels in the
  detached worker request so a child rebuilds it in its own process. These are
  guardrails against mistakes, not isolation: unrestricted Python can still
  reach the host, so `host` remains the only profile this build runs and
  requesting another refuses to start the session instead of silently
  downgrading it.
- `:rlm sandbox` reports the active boundary and `:rlm sandbox doctor` probes
  for Docker.
- A `docker` sandbox profile that runs the persistent Python interpreter inside
  a container instead of in the SuperQode process. One container per root
  session with a separate kernel per agent, the repository bind-mounted, the
  kernel server mounted read-only, non-root with a read-only root filesystem,
  all capabilities dropped, `no-new-privileges`, memory, CPU and process limits,
  no Docker socket, no host environment beyond `env_allowlist`, and networking
  off unless the profile allows it. Completion gates run inside the same
  boundary, checkpoints are written and restored only inside it so the host
  never unpickles sandbox state, and `rlm.run` reaches the supervisor over the
  kernel channel so provider credentials and recursion limits stay on the host.
  Reopening a session reattaches to its container by label and restores each
  kernel before the first execution.
- Explicit `WorkerIdentity`, `SandboxIdentity` and `KernelIdentity` records. A
  host worker and the sandbox owning its Python kernel fail independently, so
  recovery now asks the subsystem that owns an execution whether it survived
  rather than trusting a process id. Journals written before this release
  recover unchanged and need no migration.

### Fixed

- Harnesses that execute on the host now state their permissions on every
  activation route. The warning was attached to the harness picker only, so
  `:harness switch` and the new `:connect harness-*` rows activated RLM, PiPy
  and Prime Agent Python without repeating it.

## [0.2.84] - 2026-08-09

### Added

- A first-party `rlm` harness with exactly one model-facing tool: a persistent
  Python environment. Repository reads, searches, edits and commands are
  performed through Python objects rather than separate model tool schemas.
- Native RLM Harness Protocol streaming, process-lifetime Python state,
  workspace-scoped JSONL sessions, TUI/catalog selection, explicit host
  permission warnings, and independent state under `~/.superqode/rlm/`.
- Live child RLM sessions created through `rlm.run()` and `rlm.run_batch()`,
  with parent/child ancestry, handles, bounded parallelism and recursion,
  follow-up messages, steering, waiting, cancellation, deletion, Harness
  Protocol lifecycle evidence, and `:rlm` TUI commands.
- Durable RLM child journals recover completed results and mark unfinished work
  as interrupted after a process restart. Persisted goals and bounded
  autonomous completion gates can retry a native RLM turn from real host
  verification while preserving `python` as the only model-facing tool.
- Automatic RLM kernel checkpoints restore independently serializable Python
  variables after restart while safely skipping live handles, modules, locks
  and corrupt values that cannot cross a process boundary.
- Real-provider child RLMs run in detached Python workers with atomic request,
  result and control files. Supervisor journals reattach live workers after a
  TUI restart, validate worker identity before trusting a PID, preserve global
  recursion depth and model overrides, and route follow-up, steer and cancel
  operations across the process boundary.

## [0.2.83] - 2026-08-08

### Changed

- The Prime Agent subscription entry and `:prime connect` now use
  `prime-agent-python-client` over native RPC. The independent ACP route
  remains available with `:connect acp prime-agent`.
- Prime Agent Python RPC sessions show a `PY RPC` badge in the TUI and preserve
  pinned model, goal, autonomous-gate, and recursion-depth launch settings.

### Fixed

- `superqode --harness prime-agent.yaml` now connects the selected HarnessSpec
  before the first TUI prompt instead of reporting `Not connected`.
- `:harness switch ./prime-agent.yaml` now activates the Python RPC backend
  immediately rather than routing the spec's provider/model through BYOK.

## [0.2.82] - 2026-08-08

### Changed

- SuperQode now requires `prime-agent-python-client` 0.2.x, bringing the
  hardened Python RPC lifecycle, cancellation, capability, event-helper, and
  structured-logging APIs into the Prime Agent harness integration.
- Release metadata is aligned at 0.2.82 after the invalid 0.2.81 tag was
  rejected by the release tag gate.

## [0.2.80] - 2026-08-08

### Fixed

- `superqode harness run --stream` prints normalized `model_delta` output from
  the Prime Agent RPC backend and other rich streaming backends. The command
  previously rendered only the legacy `delta` event name, so a successful live
  Prime run appeared as a blank line.

## [0.2.79] - 2026-08-08

### Added

- The independently reusable
  [`prime-agent-python-client`](https://github.com/SuperagenticAI/prime-agent-python-client),
  consumed by SuperQode as a published dependency, provides a native async
  Python host for Prime Agent RPC mode with strict JSONL
  framing, correlated requests, typed high-level session operations, streamed
  events, UI responses, bounded diagnostics, version compatibility metadata,
  cancellation, and robust subprocess shutdown.
- A `prime-agent` HarnessSpec backend that makes the RPC client available to
  SuperQode's CLI/TUI and normalizes Prime model, reasoning, tool, lifecycle,
  usage, and error events without discarding their original payloads.

### Fixed

- ACP clients retain Prime Agent's `session_info_update` metadata so downstream
  consumers can observe the session identity and Prime-specific capabilities.

## [0.2.78] - 2026-08-07

### Fixed

- The vendor model picker keeps the highlighted row on screen and accepts a
  click anywhere on the row. Both were fine for a vendor with a handful of
  models and broke on a longer catalog.
- ACP sessions report the connected agent as the active harness in the status
  bar instead of the native profile.

### Added

- `:prime local` registers the local model servers SuperQode can see with Prime
  Agent, leaving providers it did not discover untouched.
- `:prime login` hands the terminal to Prime Agent for its own sign-in.
- `:prime models` opens the model picker, and `:prime model <provider/id>` sets
  one directly.

## [0.2.77] - 2026-08-07

Fixes the Prime Agent connection shipped in 0.2.76. Connecting without first
choosing a model launched the agent with a model literally named `auto`, which
sent the session to a provider the user had never selected and failed on a
missing key. Prime Agent also now appears in the Subscriptions group of
`:connect`, because what its login buys is a model on a plan you already pay
for.

### Fixed

- Prime Agent connects when no model has been chosen. `auto` is SuperQode's
  internal marker for "no model selected", and the Prime route forwarded it as
  a real model id, so every default connection ran
  `prime-agent --mode acp --model auto` and reported "No API key found" for
  whichever provider Prime resolved that against. The marker now resolves to
  unset in `split_selector`, so a bare `:prime connect` starts Prime on its own
  default and a pinned selection is still honored. `default` and `none` are
  treated the same way, and a provider with an unset model keeps the provider.

### Added

- Prime Agent is listed under `:connect` in Subscriptions alongside Codex,
  Cursor, Muse Code and Grok. It reaches the same ACP route as `:prime connect`,
  and readiness detects the binary together with any credential, whether that is
  Prime's own auth file, a provider key in the environment, or a local provider
  in `models.json`.
- Documentation states that this login cannot be run from SuperQode. Prime Agent
  has no `login` subcommand and exposes `/login` only inside its own interactive
  terminal, so the flow is to run `prime-agent`, sign in there, and return.
  SuperQode then detects the stored credential.

### Notes

- Prime Agent is deliberately excluded from the subscription key-stripping
  policy. That policy exists for vendors like Muse Code, where an environment
  key silently overrides an account session. Prime Agent's auth file takes
  priority over environment variables, so there is no billing diversion to
  prevent, and stripping keys would break its documented environment-key route.

## [0.2.76] - 2026-08-07

Prime Intellect's Prime Agent is a supported coding agent. It connects over ACP
with no adapter, and `:prime` gives it the same command surface the other vendor
agents have. Prime Agent is a Recursive Language Model harness: a persistent
IPython kernel is the model's only tool, and sub-agents are spawned from code.
It joins RLM Code and the recursive tools as a third RLM route, with different
tradeoffs rather than as a replacement for either.

### Added

- Prime Intellect's [Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent)
  is a connectable ACP agent. It ships in the agent catalog as
  `prime-agent --mode acp`, so `:connect acp prime-agent` and the agent picker
  reach it without an adapter. Prime Agent is an RLM harness whose only
  model-facing tool is a persistent IPython kernel.
- `:prime` command surface: `connect`, `models [search]`, `model`, `status`,
  `login` and `help`, with `:prime-agent` as an alias. `:prime models` reads the
  installed CLI's catalog and groups it by provider; `:prime status` reports the
  binary, version, which provider logins exist, and any local providers, without
  reading credentials.
- `:prime model` pins a selection and reconnects. Prime Agent fixes its model at
  process startup and advertises no `availableModels` over ACP, so the selection
  travels as `--provider` and `--model` launch arguments rather than through
  `session/set_model`.
- `:prime agents` shows Prime's live sessions with the RLM subagent tree,
  indented by recursion depth. `:prime schedule`, `:prime packages`,
  `:prime doctor` and `:prime update` cover the rest of its background surface.
- `:prime depth`, `:prime goal` and `:prime autonomous` pin the RLM settings
  Prime only accepts at process start. Goal and autonomous become launch
  arguments; depth has no flag and is passed as `RLM_MAX_DEPTH` on the agent
  process. `:prime depth 0` disables recursion, which drops the sub-agent
  instructions from Prime's system prompt.
- ACP connections accept per-agent environment overrides, so a setting an agent
  reads only at startup no longer requires changing SuperQode's own environment.
  The value is part of the client cache key, so changing it starts a fresh
  process instead of reusing one launched with the previous value.
- Prime Agent provider documentation covering install, authentication, GitHub
  Copilot model entitlement, local Ollama models that need no API key, the
  unsandboxed execution model, and how the route compares with RLM Code and the
  recursive tools.
- RLM routes comparison covering recursion model, context strategy, execution
  safety, self-modification and instrumentation across RLM Code, Prime Agent and
  the recursive tools.

### Fixed

- ACP JSON-RPC errors keep the detail the agent supplied. Only `error.message`
  was surfaced, so an agent reporting "No API key found for the selected model"
  in `error.data.details` reached the user as "Internal error". Every ACP agent
  benefits.
- `ACPStats.stop_reason` is populated. The field existed but was never assigned,
  so callers reading stats saw an empty string even after a clean `end_turn`.

## [0.2.75] - 2026-08-07

Meta's Muse Code is a supported connection. It sits under `:connect` →
Subscriptions alongside Codex, Cursor and Copilot, and SuperQode reads the
credential Muse already stores rather than managing Meta's authentication
itself.

### Added

- Muse Code connection profile, reachable as `:connect muse` or from the
  Subscriptions screen. Muse Code 0.1.0 exposes no ACP server, so it connects
  as an external CLI: SuperQode reports what is installed and signed in, and
  hands off to `muse` rather than claiming to drive its tool loop.
- `:muse` reports readiness (`:muse status` is the same screen), and
  `:muse login` runs Meta's own `muse login`. Sign-in is detected first, so an
  existing session is never disturbed, and the browser only opens after an
  explicit confirmation.
- Readiness distinguishes owning Muse Code from being able to run it. The
  binary alone files it as one step away; a credential is either a stored
  `muse login` session or `META_API_KEY`.
- `META_API_KEY` is registered with the subscription billing policy. Muse
  reads it ahead of any account login, so a key left in the environment
  silently moves an account session onto per-token billing, and SuperQode now
  says so. `META_MODEL_API_KEY` is deliberately excluded: it belongs to the
  `meta` BYOK provider, which Muse never reads.
- Muse's credential store is resolved the way Muse resolves it, through
  `MUSE_AUTH_PATH` and `XDG_CONFIG_HOME` before `~/.config`. Reading only the
  last of those reported a signed-in user as unauthenticated.

### Notes

- Meta requires a payment method before a Muse session survives. Without one,
  Muse removes the credential it just stored and signs the user back out on
  the next run, which reads as a login that silently did nothing. The connect
  screen states this up front rather than leaving it to be discovered.
- Muse Code ships for macOS and Linux, so the profile reports as unavailable
  on Windows instead of offering an installer that cannot run there.
- SuperQode never implements Meta's OAuth and never copies a Muse token. The
  vendor CLI owns its credential store throughout.

### Changed

- Connect screens open on a clean view for every transition, back returns to
  the list a choice was made from, and picker rows carry a clickable arrow.

## [0.2.74] - 2026-08-05

SuperQode runs on native Windows. Every change is guarded by a platform check,
so the POSIX code paths are the ones that already shipped: no macOS or Linux
behaviour changes in this release.

### Fixed

- SuperQode did not start at all on native Windows. `superqode.main` imports
  the WorkOrder queue, which imported `fcntl` at module scope, so every
  command including `--help` failed with `ModuleNotFoundError: No module named
  'fcntl'`. The import is now guarded, as are the POSIX-only `pty`, `termios`
  and `fcntl` imports in the TUI slash commands and the PTY shell widget.
- Advisory file locking works on Windows through `msvcrt.locking`. This covers
  the WorkOrder worker lock, the channels daemon lock, WorkOrder integration
  and harness promotion. Integration previously refused to run on Windows and
  promotion silently skipped locking.
- `os.uname()` in the subscription login flow raised `AttributeError` on
  Windows. It now reads `sys.platform`.
- Stopping a local model server used `os.killpg` and `signal.SIGKILL`, neither
  of which exists on Windows.
- The PiPy bash tool ran `/bin/bash -c`, which does not exist on Windows. The
  default now falls back to the platform command processor. An explicitly
  passed shell still wins.

### Known limitations

- The embedded PTY shell widget needs `pty.openpty()` and `os.fork()`, so it
  is unavailable on Windows and reports that rather than failing obscurely.
  Run shell commands with the `>` prefix, or use WSL for an inline terminal.
- The `curl | sh` installer remains POSIX only. Install with uv on Windows.

## [0.2.73b1] - 2026-08-05

Pre-release used to validate the Windows fixes above on a real Windows machine
before they reached the stable channel. Same changes as 0.2.74.

## [0.2.72] - 2026-08-05

### Added

- Once a session is running, the bar under the prompt offers what to do with
  it: `:memory`, `:eval`, `:skills` and `:harness`, all clickable. Evaluating
  and optimising had no entry point anywhere in the TUI.
- Clickable text is purple, so a link is distinguishable from ordinary text.
  Controls that end something keep their own colour.
- The SuperQode wordmark goes home when clicked, the way a site logo does.

### Fixed

- Clicking a row in a provider or model picker typed its number into the
  prompt box instead of selecting it. Those pickers buffer typed digits so
  multi-digit indexes can be entered, and clicks were being buffered too.
- The Copilot models row connected through the legacy BYOK route, which lists
  what the catalogue believes Copilot offers in general rather than what a
  plan may use. Both Copilot rows now ask the signed-in account.

### Changed

- The home screen drops the next-step block and the keyboard list. The prompt
  placeholder names the first command and the bar under it carries the same
  commands as controls, so the home screen was repeating its own chrome.

## [0.2.71] - 2026-08-05

### Fixed

- The Copilot models row in the subscription menu connected through the legacy
  BYOK route, which lists what models.dev believes Copilot offers in general
  rather than what a plan may actually use. Both Copilot rows now take the
  vendor route, which asks the signed-in account.

### Changed

- Once a session is running, the bar under the prompt offers what to do with
  it: `:memory`, `:eval`, `:skills` and `:harness`, all clickable. Evaluating
  and optimising had no entry point anywhere in the TUI. The bar keeps
  offering only `:connect` until something is connected, and trims from the
  middle on a narrow terminal so the way out and `:help` always survive.
- The home screen is the product and one line on how to drive it. The next
  step block and the keyboard list left it: the prompt placeholder names the
  first command and the bar under it carries them as clickable controls, so
  the home screen was repeating its own chrome.
- The SuperQode wordmark in the status bar goes home when clicked, the way a
  site logo does.
- TUI update. Connect, disconnect, back and exit are controls in the status
  bar, picker rows are clickable across their width with a click dot to aim
  at, long lists keep a uniform two-line rhythm, and the home screen and
  prompt box were tidied. Session commands are offered as `:compact`,
  `:fork`, `:tree`, `:resume` and `:sessions`; the slash forms still run.

## [0.2.70] - 2026-08-04

### Added

- Connect/disconnect and exit controls lead the status bar, where a browser
  puts its toolbar, with the identity, model and session state following.
  Clicking either during a run asks before cancelling it; neither asks when the
  agent is idle. On a crowded row the labels shorten and then the controls
  drop, session control last.
- Session commands are offered with a colon only: `:compact`, `:fork`,
  `:tree`, `:resume` and `:sessions`. The slash forms still run, but they are
  no longer suggested, because `/` opens a search in Vim mode and the same
  word meant two things depending on the mode.
- Every option in a picker carries a click dot in a fixed column, so there is
  somewhere deliberate to aim rather than a row to discover. The whole row
  still works. The provider list keeps its own status glyphs instead, where a
  second circle would be ambiguous.
- The hints bar sits tight under the prompt and carries connect/disconnect,
  home and help. Mode, harness, work and memory left it, and every remaining
  entry is clickable; previously mode, work and memory silently ignored clicks
  while their neighbours did not.
- The home screen says both input styles work in one line, and the
  `:home`/`:explore` reminder is gone: both are reachable from the bar under
  the prompt, so repeating them on the home screen was noise.
- The mode and Vim badges no longer render as filled colour blocks. Reverse
  video reads as an alert; the row already uses colour to carry state.
- Browser-style back. Screens record where the user came from, and a `← Back`
  control appears in the status bar while there is somewhere to return to.
  Unlike Esc, which follows a screen's declared parent, this walks the path
  actually taken.
- Picker rows are clickable across their whole width, not just the bracketed
  number, and the footer says so. Long lists keep a uniform two-line rhythm:
  only the highlighted row spends more than one line on its description.
- The hints bar and the status bar connection are clickable. The connection
  slot shows `:connect` when nothing is connected and `:disconnect` once
  something is, so ending a session is as findable as starting one. Clicking
  `:disconnect` during a run asks before cancelling it; typing the command is
  unchanged. The connected home screen offers `:disconnect` too.
- The home screen mentions Vim mode, which was only discoverable from the docs.
- `:pipy` command surface for the PiPy harness, alongside `:tau`, `:agy` and the
  rest: `:pipy help`, `session`, `compact`, `tree`, `fork`, `resume`, `new`,
  `name`, `model`, `export`, `skill` and `prompt`. The catalogue, the help text
  and the completions are all generated from PiPy's own declared command table,
  so they cannot drift apart. `:pi` is an alias. `:pipy export` writes beside the session rather
  than into the working directory.

### Changed

- The `:connect` pickers show every option's description, not only the
  highlighted one, so the choices can be compared without arrowing through
  them. The highlighted row is marked `← SELECTED` again, alongside the arrow.
- Picker numbers are right-aligned, so a list running past `[9]` keeps its
  labels in one column.

### Fixed

- PiPy started a new session on every turn, so a conversation lost its history
  one prompt at a time while the catalog advertised exact resume. The kernel
  builds a fresh backend per request, and nothing in the request carried a
  session path, so every turn fell through to creating a session. A SuperQode
  session id now maps to its PiPy session on disk.
- Long descriptions in the `:connect` pickers wrapped back to column zero,
  where they collided with the next row. They now hang-indent under the row
  they belong to, wrapped to the width of the conversation log rather than the
  terminal.
- `LICENSE` was missing the Apache appendix, so no copyright holder was named
  in it. The boilerplate is now present and filled in.
- `LICENSE` and `NOTICE` are declared through `license-files` instead of
  relying on setuptools' default glob, so the MIT attribution that
  `superqode.pipy` requires cannot silently stop shipping.
- The PiPy lazy-import test ran its subprocess without the parent's
  `sys.path`, so on a checkout with no install it failed with
  `ModuleNotFoundError` and read as a litellm regression. It now passes the
  path through and fails with a message naming the real cause.

## [0.2.69] - 2026-08-03

### Added

- **PiPy harness** - a native Python harness inspired by
  [pi](https://github.com/earendil-works/pi): event-first agent loop with
  parallel tool execution, mid-run steering, an append-only session tree, and
  pi's tool surface and prompt shape. Select it with `--harness pipy` (aliases
  `pi`, `pi-python`) or from the TUI harness picker.
- PiPy sessions are byte-compatible with pi's version 3 JSONL format and are
  stored separately under `~/.superqode/pipy/sessions/`, so switching harnesses
  never disturbs another harness's history. PiPy also reads an existing
  repository's `.pi/skills`, `.pi/prompts`, `AGENTS.md` and `CLAUDE.md`, and
  never writes to `~/.pi/`.
- `SUPERQODE_PIPY_DIR` and `SUPERQODE_PIPY_SESSION_DIR` relocate PiPy state.
- `SUPERQODE_PURE_PERMISSIONS_HEADLESS` gates unattended runs of a harness that
  has no approvals or sandbox.

### Changed

- PiPy runs tools with the permissions of the process, with no approval
  prompts, no sandbox and no network policy, matching pi. This is the opposite
  posture to every other native harness, so the harness picker warns before it
  is selected. `core` remains the default harness and is unchanged.

### Documentation

- [PiPy](docs/advanced/pipy.md) covers the permission posture, session layout,
  switch behaviour and commands.

## [0.2.68] - 2026-08-01

### Added

- **A2A 1.0 harness server** - `superqode serve a2a` exposes a versioned
  HarnessSpec over the official A2A HTTP+JSON protocol (discovery Agent Card,
  tasks, streaming, cancellation, subscriptions, and bearer auth).
- **Durable A2A task store** - Completed A2A task records use the SDK SQLite
  `DatabaseTaskStore` (`--task-store`), separate from SuperQode harness evidence
  (`--harness-store` / `--store`).
- **Path-aware A2A client** - Discovery routes operations to the Agent Card
  `supportedInterfaces` URL, including path-prefixed deployments such as
  `/superqode/a2a`.
- **Agent Card export** - `--export-agent-card` writes the exact runtime card
  for static publication; the checked-in publication artifact lives under
  `examples/a2a/`.
- **Experimental QM packaging** - Copy-ready tool/skill bootstrap for YC QM
  agent computers, plus an independent TypeScript A2A interop client under
  `examples/qm-deployment-layer/`.

### Fixed

- **A2A interface URL routing** - Clients no longer post to the discovery origin
  when the card advertises a different operational path.
- **Agent Card product metadata** - Runtime skill and bearer text stay aligned
  with the public SuperQode card (product-facing skill name/description).
- **Node interop test skip** - The TypeScript A2A client test requires Node 22+
  for native type stripping instead of failing on older Node.

### Documentation

- **A2A provider guide** - Public preview status, durability model, publishing
  workflow, and experimental multiplayer-computer packaging notes.
- **`SUPERQODE_A2A_TOKEN`** - Documented for remote A2A binding and operation
  auth.

## [0.2.67] - 2026-08-01

### Added

- **Progressive TUI discovery** - `:tour` tracks the path from connection to
  evaluation, while `:explore` reports agents, models, harnesses, tools,
  memory, safety, evaluation, optimization, and delivery without crowding the
  normal coding screen.
- **Ownership-based connection flow** - `:connect` now starts with three
  outcome-level choices: use an existing harness, run a SuperQode harness with
  a chosen model, or build a repository-owned HarnessSpec.
- **Repository harness onboarding** - Existing AGENTS.md, CLAUDE.md, Cursor
  rules, Copilot instructions, and agent YAML can become an inspectable local
  HarnessSpec. Presets, the existing wizard, and a minimal scaffold are
  available from the same flow.
- **TUI evaluation entry point** - `:eval` explains the task and rubric
  contract or runs the existing harness evaluation command.

### Fixed

- **Harness creation preserves existing work** - Imports, preset clones, and
  blank scaffolds refuse to overwrite an existing HarnessSpec.
- **Discovery state follows real usage** - Commands already used are no longer
  suggested, and successful evaluations complete the evaluation milestone.
- **Capability counts reflect actual inventory** - Agent totals use vendor
  profiles rather than category rows, MCP servers are included with tools, and
  ready built-in capabilities contribute to active totals.
- **Connected TUI screens stay compact** - Returning users receive an
  operational home instead of repeated onboarding, connection pickers explain
  only the highlighted choice, and `:explore` keeps one category open at a
  time.
- **Grok subscription credentials are verified before connection** - Selecting
  `grok-cli` through the BYOK picker now refreshes the local CLI session token
  before reporting success, and expired sessions produce actionable login
  guidance instead of an OpenAI API-key error.

## [0.2.66] - 2026-07-30

### Fixed

- **The home screen buried its own footer.** A blank line only appears
  between two rendered blocks when the preceding block's text ends with a
  trailing newline, and one section ended with two, stacking three blank
  lines between "Next step" and the `Ctrl+K` footer. Every section now ends
  with exactly one, so spacing is consistent throughout and the whole screen
  dropped from 34 lines to 27, with the footer visible without scrolling on
  a normal terminal.
- **"Terminal-first · Any agent or model" and "Interoperability: ..." had no
  gap.** Every other tagline pairing had one; these were the only two lines
  running directly into each other. Fixed to match.
- **The status bar did not use the terminal's width.** Identity and
  connection state sat at the left edge and the mode badge sat right next to
  it, leaving the rest of a wide row empty. Session state (mode, plan,
  context usage, cost) is now a second cluster right-aligned to the far edge,
  so the row uses the full width instead of stopping partway across it.

## [0.2.65] - 2026-07-30

### Fixed

- **Secondary text is now readable in every theme.** The palette bridge mapped
  the flat render-time colours onto the wrong rungs of each theme's text scale:
  prose used the `text_dim` step and faint text used `text_ghost`, while
  `text_muted`, the step meant for prose, went unused. On the SuperQode theme
  secondary text measured 4.35:1 against the background, below the 4.5:1 WCAG
  needs for body text, and faint text measured 2.72:1. On Dracula the same bug
  put faint text at **1.56:1**, effectively invisible. Each rung now shifts up
  one, which fixes every theme at once. The brand gradient is untouched, and a
  test asserts it verbatim so contrast work can never dilute the identity.
- **`:theme` looked like it did nothing.** It correctly replaced all 21 palette
  colours, but `refresh()` cannot recolour text whose styles were resolved when
  it was written, so the screen kept the old palette. The home screen is now
  rebuilt from source, so a theme change is visible immediately. A conversation
  is never cleared for a cosmetic command: when a transcript is present the
  command explains that earlier output keeps its original colours and that
  `:home` repaints in full.

### Added

- **`scripts/show_theme_contrast.py`** prints a theme's text colours as real
  terminal swatches with their measured contrast ratio, because a colour change
  is hard to judge from a diff.

## [0.2.64] - 2026-07-30

Hotfix for 0.2.63, which shipped a GitHub Copilot CLI route that could not
serve a turn.

### Fixed

- **The Copilot CLI subscription route could not answer anything.**
  `copilot-cli` and `grok-cli` were missing from the set of self-contained
  runtimes, and that set is what decides whether a runtime auto-connects.
  `:connect copilot` therefore reported `Already on runtime 'copilot-cli'` and
  returned without connecting, so the next message failed with
  `Not connected. Call connect() first.` Both runtimes are now declared
  self-contained, because the vendor login supplies auth and model.
- **The runtime rejected the registry's arguments.** Once it did try to connect,
  it failed with `unexpected keyword argument 'gateway'`. The runtime registry
  passes shared plumbing to every runtime, which a vendor CLI does not need; it
  is now accepted and ignored, as the other runtimes already did. The required
  `run()` and `run_streaming()` methods were also missing.
- **Sign-in notifications never fired.** Passing a keyword through the UI
  thread helper raised `TypeError`, because it forwards positional arguments
  only. Every success and failure notification would have failed.
- **Mouse-drag copy stopped working.** A duplicate clipboard helper shadowed the
  existing one. The duplicate is gone.
- **The Copilot entry described a route it no longer uses.** Its description
  still said it falls back to "the official CLI over ACP".
- **Subscription entries now state the route they actually take.** The Grok
  entry read "via the official CLI" while the profile runs `grok agent stdio`,
  which is ACP; Cursor and Kiro named the sign-in but no transport, which read
  the same way. Users choose from this text, so every entry now says whether it
  connects over ACP, a vendor SDK, or a vendor CLI, and a test keeps the wording
  and the connector in step.

### Added

- **You can see whether the Copilot CLI is signed in.** There is no
  `copilot whoami`, and the token is held in the OS credential store, so the
  only honest check is a short handshake with the CLI. It runs in the background
  after connect and reports signed in, needs sign-in, or, when nothing could be
  established, says so rather than guessing. `:copilot login` is offered inline
  when sign-in is needed. `SUPERQODE_COPILOT_AUTH_PROBE_TIMEOUT` bounds it.
- **The one-time device code copies itself.** The code is pulled out of the
  vendor CLI output, placed on your clipboard, and confirmed, instead of having
  to be transcribed by hand from a scrolling log. Works over SSH through OSC 52.
- **Sign-in raises a notification.** Completing or failing a sign-in now shows a
  toast, so the result is not something you have to scroll back to find.

## [0.2.63] - 2026-07-29

### Added

- **`superqode update`** - Upgrade SuperQode from inside SuperQode. The command
  detects how it was installed rather than assuming one package manager:
  `uv tool upgrade superqode` for a uv tool install (which keeps the extras it
  was installed with), a targeted `uv pip install --upgrade` for a virtual
  environment, pip when uv is absent, and a refusal that points at `git pull`
  when running from a checkout. `--check` reports without installing,
  `--version` pins or rolls back, and `-y` skips the prompt.
- **Subscription CLI runtimes** - `copilot-cli` and `grok-cli` drive the
  vendor's own non-interactive mode with structured output, so a subscription
  runs on the vendor's CLI instead of ACP. `SUPERQODE_VENDOR_CLI_TIMEOUT`
  (default 900s) bounds one turn.

### Changed

- **Subscriptions never route through ACP** - The ACP channel is a separate
  connection source, so listing the same vendor in both duplicated it.
  `:connect copilot` now prefers the Copilot SDK and otherwise uses the Copilot
  CLI directly. `:copilot cli` means the plain CLI; ACP now needs `:copilot acp`
  or `:connect acp copilot` by name.
- **Subscriptions never spend an API key** - Vendor CLIs generally prefer an
  exported API key over their own login, so a key left in a shell could quietly
  move a subscription session onto per-token billing. Subscription routes now
  start the vendor process without those variables and report which ones were
  ignored. **Your own environment is never modified**: only the copy handed to
  that one subprocess omits them, so BYOK and every other tool keep working
  unchanged. `COPILOT_GITHUB_TOKEN` is honoured, since it is supplied on purpose.
- **Approval mode maps to the vendor's own permission setting** - A headless
  CLI cannot prompt per tool call, so the mode is translated into the vendor's
  vocabulary for the whole turn and stated on the first turn instead of being
  applied quietly. Grok maps `auto`/`ask`/`deny` to `bypassPermissions`,
  `acceptEdits`, and `plan`. Copilot's CLI requires `--allow-all-tools` for
  non-interactive use and offers no gradation, so it says so and points at the
  SDK or ACP routes for per-tool prompts.

### Removed

- **Gemini CLI is no longer a subscription profile** - It is an enterprise and
  API-key route, and Google has moved consumer plans to Antigravity. A
  subscription entry must never put the user on metered API billing. The agent
  stays reachable through the ACP channel with `:connect acp gemini`.

## [0.2.62] - 2026-07-29

### Fixed

- **Connected ACP agents no longer answer "integration coming soon"** - Three
  separate hardcoded lists decided which agents could actually run: a set of 19
  short names in the message dispatch, a tuple of 23 in the unified runner, and
  a command chain naming each agent individually. The registry ships 46 agents,
  so half of them connected successfully, reported a ready ACP session, and
  then refused the first prompt. Depending on which list was missed, the agent
  answered "integration coming soon", was silently executed as the **opencode**
  CLI, or was rejected as "Unsupported ACP agent type". GitHub Copilot, Cursor,
  Droid, Kiro, GLM, Qwen, Cline, Kilo, and 15 others were affected. Routing now
  keys off the ACP protocol the agent declares, and the launch command comes
  from the agent's own registry entry, so a newly added agent works without
  editing the dispatch.

## [0.2.61] - 2026-07-29

### Added

- **One GitHub Copilot entry that picks the installed route** - The
  Subscriptions screen offers a single Copilot choice. It prefers the official
  Python SDK when the extra is installed and otherwise uses an installed
  Copilot CLI over GitHub's ACP server, so a CLI-only account is usable
  immediately instead of being blocked behind an SDK setup prompt. When both
  are present the SDK reuses the installed CLI, which skips its first-use
  runtime download and shares the same `copilot login` state.
- **`:copilot login`** - Runs GitHub's official OAuth device flow after an
  explicit confirmation, shows the URL and code inside the TUI, does not open a
  browser automatically, and reconnects on success.
- **`:copilot mode`** - Picks the Copilot CLI session mode (Agent, Plan, or the
  experimental Autopilot) from the modes the CLI advertises. Short names, full
  ACP mode URIs, and displayed names are all accepted. Session modes work on
  every Copilot plan, including Free, where model selection is unavailable.

### Fixed

- **Headless runs no longer hang on an inherited stdin** - `superqode -p` read
  stdin whenever it was not a TTY, and `read()` blocks until EOF. CI runners,
  process supervisors, editors, and agent harnesses routinely hand a child an
  open pipe nobody ever closes, so the process waited forever. Readability is
  now polled first (`SUPERQODE_STDIN_WAIT`, default 0.2s): a real pipe such as
  `cat file | superqode -p "review"` still works, while an idle inherited stdin
  returns in well under a second instead of never.
- **A failed headless run explains itself** - `run_headless` reports failure by
  returning a response carrying the reason rather than raising, so the reason
  was never printed. The run ended with a blank line and a bare exit code 1.
  The error is now written to stderr.
- **An ACP profile no longer answers as a different vendor** - `--connect` sets
  an environment hint read only by the TUI, so a one-shot `--connect
  copilot-cli` silently fell through to the default provider and model and
  answered from OpenAI. Headless use of an interactive ACP profile now exits
  with a usage error naming the profile.
- **`:copilot model` no longer reports a selection that never happened** - The
  Copilot CLI answers `session/set_model` with success even for an id the
  account cannot use, and the guard against that was skipped when the account
  advertised no catalog at all. A plan with no selectable models (Copilot Free)
  now reports that Copilot chooses the model itself, instead of confirming a
  change that had no effect.
- **`:copilot models` explains an empty catalog** - Reporting "no models were
  returned" read like a failure on plans where Copilot always picks the model.
  It now says so and points at the session controls that do apply.
- **`:copilot sessions` and `:copilot resume` name their requirement** - Both
  are SDK features and failed on a CLI-only install with an internal runtime
  error. They now report that the SDK extra is required and print the install
  command.
- **`:copilot version` tolerates a missing stream** - Reading the CLI version
  raised `AttributeError` when the process reported no stderr.
- **Corrected the documented ACP connect command** - `superqode --connect acp
  copilot` exited with "No such command"; the working form is `superqode
  connect acp copilot`.

### Changed

- **Claude Pro and Max are no longer connection profiles** - Anthropic
  documents those subscriptions for its own first-party clients and bills API
  usage separately, so Claude is reached through BYOK or the
  `claude-agent-sdk` runtime with an API key. `:harness switch claude` resolves
  only to the API-key runtime.
- **External installers are manual-only in the connection flow** - Only
  SuperQode's own Python extras install automatically, and the executor
  regenerates the command from an allow-list rather than trusting UI state.
  npm, curl-to-shell, and vendor-agent installers show their exact command
  instead of running it.

## [0.2.60] - 2026-07-29

### Fixed

- **GitHub Copilot SDK no longer freezes the terminal** - Three separate calls
  blocked the UI event loop, and each one looked like a hang rather than an
  error. The first prompt built `CopilotClient` inline, and that constructor
  downloads the pinned Copilot CLI through a blocking request with a 120 second
  timeout and three retries: roughly 13 seconds of frozen terminal on a fast
  link, and minutes behind a corporate proxy. The client is now built off the
  event loop, and the first turn says the download is happening instead of
  showing nothing.
- **Copilot permission prompts no longer deadlock** - The SDK awaits its
  permission handler on the event loop, while SuperQode's approval bridge
  blocks until you answer the prompt. Deciding inline meant the approval card
  could never render and the keypress could never be read, so every request
  froze until the bridge timed out and denied it. Decisions now resolve on a
  worker thread, matching the Claude Agent SDK runtime.
- **`GH_TOKEN` and `GITHUB_TOKEN` are no longer sent to Copilot** - Both are
  normally plain git PATs with no Copilot entitlement, and `gh`, CI, and most
  enterprise setups export one. Forwarding it made the SDK start its runtime
  with `--no-auto-login`, bypassing a working `copilot login` and stalling on
  an account that could not authenticate. Only `COPILOT_GITHUB_TOKEN` is
  forwarded now, and `:copilot status` reports when the others are present and
  ignored.
- **A failed turn explains itself** - A Copilot turn that could not start,
  timed out, or errored ended with an empty response and no message, which is
  indistinguishable from a hang. Failures now end the turn with the reason and
  the command that addresses it. This applies to every self-contained runtime,
  not only Copilot.

### Added

- **The GitHub Copilot CLI route is back in the Connect picker** -
  `:connect copilot-cli` and `:copilot cli` run the official CLI over ACP, so
  the vendor CLI owns authentication and its own agent loop. It was previously
  reachable only as a hidden compatibility alias. This is the route to use on
  Copilot Business and Enterprise seats, on networks that block the SDK runtime
  download, and anywhere `copilot login` already works but the SDK does not.
  `:connect copilot-acp` and `:copilot acp` still work as older aliases.
- **`SUPERQODE_COPILOT_TIMEOUT`** is documented and validated. It sets the
  per-turn idle wait in seconds and defaults to `600`.

## [0.2.59] - 2026-07-28

### Changed

- **`:connect` opens on five options instead of twelve** - The connect screen
  listed every method and every vendor product in one flat list, which is a lot
  to read before your first connection. It now opens on `Local`, `ACP (Agent
  Client Protocol)`, `BYOK (Bring Your Own Key)`, `Subscriptions`, and `Other
  harnesses`. Enter on `Subscriptions` opens the vendor screen, and Esc there
  returns to the root screen instead of leaving the connect flow. Arrow keys,
  number keys, and typed names work the same as before, and every product is
  still reachable directly, so `:connect codex` never needs a detour through
  the submenu. Completion order, the command suggester, and the palette entry
  follow the same order as the screen.

### Added

- **Gemini CLI, Devin, and GLM CLI are first-class connection profiles** -
  `:connect gemini-cli` starts `gemini --acp`, `:connect devin` starts
  `devin acp`, and `:connect glm-cli` starts the community `glm-acp-agent`.
  All three were reachable only through the generic ACP picker before. Each
  shows live install status on the Subscriptions screen with the exact command
  that fixes a missing CLI, and each has its own provider guide.
- **`:connect subscriptions`** opens the vendor screen directly, and
  `superqode --connect subscriptions` opens it at startup.

## [0.2.58] - 2026-07-28

### Fixed

- **`:connect acp devin` reported "integration coming soon" on the first
  message** - Connecting succeeded, because the connect path reads the agent
  catalog generically, but sending a message did not. Message dispatch is
  gated by three separate hardcoded agent lists in `agent_run.py`, and Devin
  was in none of them: the dispatch allowlist fell through to the
  "coming soon" notice, the unified-runner tuple would have dropped Devin to a
  legacy subprocess path, and the command-resolution chain ends in an
  "Unsupported ACP agent type" error rather than a generic fallback. Devin now
  resolves to `devin acp` with a binary check and install hints, and reads no
  API key, since the official CLI owns sign-in through `devin auth login`.

  This gap is not specific to Devin. The agent catalog ships roughly 45 ACP
  entries while these lists cover 22, so other catalog agents can still
  connect and then report the same notice. Consolidating the three lists into
  a single lookup against the registry's `run_command` is left as separate
  work.

## [0.2.57] - 2026-07-27

### Added

- **`devin-cli` runtime** - Cognition's Devin CLI can now be used as a
  SuperQode harness for unattended work (`:runtime devin-cli`,
  `superqode --runtime devin-cli`), driving Devin's documented single-turn
  print mode. The ACP route (`:connect acp devin`) remains the better choice
  for interactive use: `devin acp` surfaces structured tool calls, diffs, and
  permission requests, while `--print` emits prose only. Pick the runtime when
  you want Devin behind `superqode run`, benchmarks, or scripted turns.
  Sessions carry across turns: the runtime pins the id reported by
  `devin list --format json` and resumes it with `--resume`, falling back to
  `--continue` when that listing is not in a recognised shape. The official CLI
  owns sign-in (`devin auth login`) and SuperQode never reads or copies its
  credentials.

  Because a `--print` turn is unattended, an approval prompt would block with
  nobody to answer it, so the runtime starts Devin in `bypass` mode and pairs
  it with `--sandbox` wherever Devin supports sandboxing - macOS, and Linux
  with `bubblewrap` and `socat`. Windows never receives the flag, since Devin
  refuses to start rather than run unsandboxed. Override with
  `SUPERQODE_DEVIN_CLI_PERMISSION_MODE` and `SUPERQODE_DEVIN_CLI_SANDBOX`;
  setting the latter to `1` never forces sandboxing onto a platform that
  cannot honour it.

### Changed

- **Devin's ACP catalog entry is no longer a stub** - The agent picker showed
  no install line for Devin at all, because the entry carried an empty install
  command. It now declares the official installer, documents `devin auth login`
  as a prerequisite for the ACP handshake, and covers model selection
  (`--model opus|sonnet|gpt|codex|gemini|swe`), permission modes, and the
  three-level config precedence (`~/.config/devin/config.json`,
  `.devin/config.json`, `.devin/config.local.json`). Devin's `mcpServers` block
  shares Claude Code's schema shape, so MCP servers generally transfer between
  them. Devin also picked up a catalog icon and colour instead of falling back
  to the generic agent glyph.

## [0.2.56] - 2026-07-27

### Fixed

- **`:connect byok <provider> <model>` with a namespaced model id** - The
  `provider/model` form was resolved before the `provider model` form, so a
  model id containing a slash was split at the wrong place:
  `:connect byok baseten moonshot-ai/Kimi-K3` read the provider as
  `baseten moonshot-ai` and failed with a misleading "not available from the
  current models.dev catalog". This affected most open-weight ids, including
  every Kimi K3 route and anything under `meta-llama/` or `zai-org/`.
  Whitespace is unambiguous, so it is now resolved first; the single-token
  `provider/model` form is unchanged.

### Changed

- **The provider picker no longer lists the whole models.dev catalog** -
  models.dev synthesizes a definition for every provider it knows and they all
  default to the Model Hosts category, so 16 curated hosts were buried under
  roughly 140 long-tail entries. The default view now shows the curated hosts,
  led by Baseten, Fireworks AI, Together AI, Modal, and OpenRouter, and
  collapses the rest behind `:connect byok all`. This is display grouping only:
  the catalog is still pulled from models.dev, every provider stays connectable
  by name, and a refresh continues to add new providers and models with no
  manual curation. Any collapsed host whose API key is already set in the
  environment is shown regardless, so a provider you already use never looks
  unsupported.

## [0.2.55] - 2026-07-27

### Added

- **Kimi K3 across every host serving its open weights** - Moonshot published
  the K3 weights on 2026-07-26, so the same model is now served by several
  providers under a different id each. SuperQode offers the verified id for
  `moonshot`, `baseten`, `fireworks`, `together`, `openrouter`, `siliconflow`,
  and self-hosted `vllm` / `sglang`. Whichever route is used, the existing
  `kimi` model pack still applies, so maximum reasoning and parallel tools
  follow the model rather than the provider.
- **Baseten provider** - First-class OpenAI-compatible host (`BASETEN_API_KEY`,
  `https://inference.baseten.co/v1`), a day-0 host for Kimi K3 with 1M context
  and native vision. Previously reachable only as a models.dev long-tail entry
  with no curated metadata or example models.
- **Modal provider** - Serverless GPU platform. Modal gives you your own
  deployed endpoint rather than a shared inference API, so it ships without a
  default base URL: point `MODAL_BASE_URL` at the deployment you created.
- **Install a missing ACP agent from the picker** - Selecting an agent that is
  not installed now offers to run its installer. SuperQode runs named
  package-manager installs (`npm`, `cargo`, `go`, `uv tool`, `pipx`, `brew`)
  and never runs installers that pipe a remote script into a shell, because
  agreeing to install an agent is not agreement to execute an unreviewable
  remote script. Failures print the installer's own output and stop, with no
  retry, no sudo, and no changes to the user's toolchain.
- **Keyboard selection for vendor model lists** - `:agy models`, `:claude
  model`, `:copilot models`, and `:tau models` printed plain lists that
  required retyping an id; `:claude model` printed numbers that did nothing.
  All four now share one picker with arrows, Enter, and number selection.

### Changed

- **`:connect acp` lists the whole registry** - The default view showed only
  featured agents, hiding roughly two thirds of the catalogue behind
  `:connect acp all`. The full list is now the default, with
  `:connect acp featured` and `:connect acp enterprise` to narrow it.
- **Choosing to install a runtime yourself links the vendor's documentation** -
  The manual choice now notes that SuperQode's command can go out of date and
  links the vendor's own install documentation where one is known.
- **Release metadata** - Bumped package, runtime, lockfile, ACP registry,
  installer example, and package checks to `0.2.55`.

### Fixed

- **The ACP picker kept its view while navigating** - Arrow keys redrew the
  list with default arguments, so moving the highlight inside a filtered view
  silently reverted it to the default one.
- **`pip install` in an agent's registry entry is reported, not run** - A bare
  `pip install` targets whichever pip is first on PATH. SuperQode names the
  `uv pip install` equivalent instead of running it or rewriting the command
  the registry declared.

## [0.2.54] - 2026-07-27

### Changed

- **Leaving the install prompt goes to the connection screen** - Declining an
  install returned to the runtime picker, which only re-offered the runtime
  that had just been declined, and choosing to install manually printed the
  command and stopped there. Cancel, Esc, and "I will install it myself" now
  all land on `:connect`. The manual choice writes its command after that
  screen, so the command stays on view to copy.
- **Release metadata** - Bumped package, runtime, lockfile, ACP registry,
  installer example, and package checks to `0.2.54`.

## [0.2.53] - 2026-07-27

### Fixed

- **Keyboard navigation on the missing-runtime install prompt** - The arrow
  keys did nothing and Enter could be swallowed before reaching the prompt.
  The prompt input routes arrow keys and Enter through its own per-picker
  dispatch chains, which the new prompt was not part of, so only the number
  keys worked. Both chains now delegate to the prompt registry, so every
  prompt registered there gets arrows and Enter without a further branch.
- **Typing a runtime name selected the wrong runtime** - Enter on the runtime
  picker acted on the highlighted row and discarded whatever name had been
  typed, so `claude-agent-sdk` would connect to the first entry in the list
  instead, and an uninstalled runtime never opened its install prompt. Typed
  text is now resolved instead of being thrown away.
- **Esc on the install prompt** - It dismissed the prompt without running the
  prompt's cancel behavior, so it did not return to the runtime picker the way
  the Cancel option does. Both paths now behave identically.

### Changed

- **Release metadata** - Bumped package, runtime, lockfile, ACP registry,
  installer example, and package checks to `0.2.53`.

## [0.2.52] - 2026-07-27

### Added

- **Install a missing runtime without leaving the TUI** - Choosing a runtime
  whose Python extra is not installed now opens a keyboard-navigable prompt
  (install for me / install it myself / cancel) instead of printing a command
  and stopping. Choosing to install runs it against the interpreter SuperQode
  is running from, verifies the package is importable afterwards, and connects
  without a restart.
- **Transcript search without Vim mode** - `Ctrl+F` and `:search <text>` reuse
  the existing Vim search engine, which was previously reachable only through
  `/` in Vim normal mode. A bare `:search` advances to the next match.
- **`:keys` keyboard reference** - Generated from the app's own bindings, so it
  cannot drift from the keys that are actually bound.
- **Reword the previous prompt** - `Ctrl+P` and `:edit` load your last message
  back into the input. `:retry` still resends it unchanged.
- **`high-contrast` theme** - An accessibility palette for low vision and bright
  rooms, held to WCAG AAA (7:1) for every text tone and AA (4.5:1) for the
  semantic colours by test. `NO_COLOR` is documented and now covered by a
  regression test.

### Changed

- **`:disconnect` disconnects** - It previously only reset the view: BYOK,
  local, and self-contained SDK sessions live on a separate object that was
  never torn down, so the badge cleared while the runtime stayed connected. It
  now cancels and closes the runtime, detaches the harness, clears the runtime
  and harness environment variables, and returns to a freshly launched state.
- **`:home` no longer looks disconnected** - It deliberately keeps the session
  warm, so it now leaves the live model and provider on screen instead of
  blanking a badge that described a connection still running. It also stops
  resetting the session execution mode out from under that live session.
- **Modal prompts declare their behavior once** - New prompt registry holding
  the Enter, typed-answer, Esc, arrow, and number-key behavior of a prompt in a
  single registration, replacing five hand-edited dispatch sites per prompt.
  The missing-dependency prompt is migrated; the remaining prompts continue to
  use the previous path.
- **Release metadata** - Bumped package, runtime, lockfile, ACP registry,
  installer example, and package checks to `0.2.52`.

## [0.2.51] - 2026-07-26

### Fixed

- **`codex-sdk` extra installed an old SuperQode** - `openai-codex` published
  only pre-releases below `0.2.0` and then jumped to its first stable release,
  `0.144.4`, which tracks the Codex CLI version line. The previous
  `>=0.1.0b2,<0.2.0` pin therefore matched pre-releases only, and uv does not
  accept pre-releases for transitive dependencies. Rather than failing,
  `uv tool install "superqode[codex-sdk]"` backtracked past every current
  release and installed `0.1.37`. Both the `codex-sdk` and `vendor-sdks` extras
  now require `openai-codex>=0.144.4,<1.0.0`, so the extra resolves against the
  stable SDK without a `--prerelease` flag.

### Changed

- **Welcome screen** - The welcome panel offers a single next step, `:connect`,
  in place of the previous three-row `:connect` / `:harness` / `:work` block.
- **Release metadata** - Bumped package, runtime, lockfile, ACP registry,
  installer example, and package checks to `0.2.51`.

### Added

- **SuperQode website links** - Linked <https://super-agentic.ai/superqode/>
  from the README header, badges, and footer, the documentation home page and
  its badge row, the MkDocs footer icons, and the PyPI `Homepage` metadata.

## [0.2.50] - 2026-07-26

### Added

- **GEPA Omni harness optimization** - Added guarded complete-HarnessSpec
  exploration across GEPA, AutoResearch, and GEPA MetaHarness, followed by a
  fresh continuation phase, candidate policy audit, and sealed held-out gate.
- **Subscription-plus-local experiment** - Added a reproducible runner, pinned
  GEPA commit, local `qwen3.5:9b` harness, bounded evaluation contracts, and a
  detailed release experiment showing 24 optimizer evaluations and a held-out
  improvement from `0.0` to `1.0` without an Anthropic API key.
- **GEPA Omni field report** - Added a personal, reproducible account of the
  integration, the bounded subscription-plus-local experiment, its measured
  results, and the limitations that keep the feature experimental.

### Changed

- **Omni accounting** - Aggregate evaluation counts and proposer cost across
  all explorers and the continuation phase instead of reporting only the final
  continuation engine.
- **Release metadata** - Bumped package, runtime, lockfile, ACP registry,
  installer example, and package checks to `0.2.50`.

## [0.2.40] - 2026-07-25

### Added

- **One place for coding agents** - Discover and switch between SuperQode harnesses, vendor agents, ACP agents, optional integrations, and model presets from the unified TUI.
- **Kimi Code and Qwen Code** - Connect to both first-party coding agents directly, alongside Codex, Claude, Antigravity, Grok, GitHub Copilot, and Z.AI.
- **Broader model access** - Added first-class NVIDIA and Poolside BYOK routes while retaining the complete models.dev provider catalog.

### Changed

- **Clearer agent discovery** - Organized the Connect experience into US Coding Agents, China Coding Agents, and Other Integrations, with improved navigation and session continuity.

## [0.2.39] - 2026-07-25

### Added

- **Discoverable optional harnesses** - Added a visible Other Harnesses entry to the Connect picker, with Hugging Face Tau, live setup status, keyboard access, and command completion.
- **Complete harness discovery** - Added direct access from Connect and the Harness Switcher to recommended, optional, project, registry, and installed Python harness integrations.
- **Native Tau commands** - Added `:tau login`, `:tau use`, status, provider, model, session, logout, and retry commands so SuperQode users can configure, connect, and operate Tau without leaving the TUI.

### Changed

- **GitHub Copilot connection** - Made the official Copilot SDK the single primary Copilot entry, retained ACP as an advanced route, and kept legacy shortcuts compatible but hidden.
- **Connection ordering** - Moved GitHub Copilot to the bottom of the Connect picker and placed Other Harnesses immediately above it.
- **Unified harness picker** - Made `:harness` and `:harness switch` open the complete keyboard-driven inventory of vendor coding agents, HarnessSpecs, optional integrations, model presets, and project harnesses, with direct aliases such as `:harness switch codex`.
- **README presentation** - Improved the opening banner, product introduction, documentation calls to action, badges, and installation visibility.
- **Release metadata** - Bumped package, lockfile, ACP registry, installer example, and package checks to `0.2.39`.

## [0.2.38] - 2026-07-25

### Added

- **Tau harness backend** - Added Tau as an optional selectable harness backend with adapter, templates, discovery, and catalog availability status in the TUI, plus the `tau` install extra.
- **One-line POSIX installer** - Added a sudo-free installer that bootstraps `uv` when missing, installs SuperQode into an isolated tool environment, and supports upgrades, extras, and version pins.

### Changed

- **Calmer thinking animation** - Slowed the TUI thinking bars and spinner, made every turn begin with `Thinking` exactly once, and shuffled the remaining slower progress phrases independently for each turn.
- **Installer URL** - Moved the hosted installer to `https://super-agentic.ai/superqode.sh` and updated the README and documentation to match.
- **macOS install fix** - Constrained `litellm` below 1.92 so macOS installs resolve, since 1.92+ dropped macOS wheels.
- **Release metadata** - Bumped package, runtime, lockfile, ACP registry, and package checks to `0.2.38`.

## [0.2.37] - 2026-07-24

### Added

- **Runnable MCP harness example** - Added a local stdio MCP documentation server and HarnessSpec that demonstrate MCP tool discovery and execution without an external service.
- **MCP compatibility documentation** - Documented the separate MCP client, harness bridge, and harness-serving surfaces, including their current runtime ownership and protocol support.

### Changed

- **Standalone FastMCP server** - Migrated `superqode mcp` and `superqode serve harness` from the FastMCP 1.0 copy bundled in the MCP Python SDK to Prefect's stable standalone FastMCP 3.4.4 framework.
- **MCP dependency safety** - Bounded the direct MCP Python SDK dependency below v2 while its breaking protocol stack remains prerelease, preventing an unplanned production upgrade.
- **Release metadata** - Bumped package, runtime, lockfile, ACP registry, and package checks to `0.2.37`.

## [0.2.36] - 2026-07-24

### Added

- **Google-hosted Antigravity runtime** - Added `:antigravity managed` and the `antigravity-managed` runtime for the Gemini Interactions API, including typed SSE events, hosted environment and conversation continuation, model selection, system instructions, and per-interaction token budgets without using `agy` account credentials.
- **Antigravity runtime controls** - Added model and thinking-effort selection for CLI and SDK turns, plus custom-agent selection for signed-in CLI turns through `:antigravity model`, `:antigravity effort`, and `:antigravity agent`.
- **Native `:agy` command family** - Added discoverable TUI commands and contextual completion for Antigravity CLI agents, models, changelog, version/update/install, plugin management, runtime controls, and external interactive-session launch/resume handoffs.
- **Antigravity SDK parity** - Added SuperQode approval policy bridging, backend cancellation, exact token usage, SDK thinking levels, project skill discovery, and stdio or Streamable HTTP MCP configuration.
- **Antigravity no-tool enforcement** - Model-only headless profiles now disable the Antigravity SDK's built-in tools and subagents at the SDK capability layer.

### Changed

- **Antigravity ecosystem support** - Updated the optional local SDK to `google-antigravity` 0.1.8, documented the July 2026 CLI, SDK, Antigravity 2.0, and Managed Agents capability map, and corrected the Google managed-harness interaction request to the current API schema.
- **Antigravity SDK compatibility** - Selected protobuf 7.35 or newer for the 0.1.8 SDK's generated descriptors and declared incompatible optional-extra combinations so uv rejects them during resolution instead of installing an SDK that fails to import.
- **Managed runtime identity** - The TUI now clears stale BYOK identity when connecting to a self-contained runtime, identifies the Antigravity-owned harness and managed agent in the status bar, labels hosted approval ownership accurately, and supplies an explicit identity contract so the remote agent does not probe its sandbox to answer runtime questions.
- **Google BYOK model catalog** - Curated the Google picker to show current coding and agent models newest first, led by Gemini 3.6 Flash, and removed deprecated, superseded, alias, embedding, image, and other non-chat entries.
- **Documentation coverage** - Added a product capability reference, surfaced Poolside Laguna S 2.1 on the documentation home page, and linked public capabilities to their implementation guides.
- **Connection documentation** - Added one connection reference for Local, ACP, BYOK, SDK, MCP, and A2A methods, with direct product shortcuts and complete built-in provider, local engine, and bundled ACP agent inventories.
- **Documentation style** - Replaced generic marketing headings with technical headings and expanded the public documentation check to reject selected formulaic marketing phrases.
- **Release metadata** - Bumped the package, runtime, lockfile, ACP registry, package checks, extension compatibility examples, plugin documentation, and generated product images to `0.2.36`.

## [0.2.35] - 2026-07-24

### Added

- **Poolside Laguna S 2.1 local inference** - Added first-class support for the official `laguna-s-2.1-Q4_K_M.gguf` through DwarfStar and llama.cpp, including standard Hugging Face cache discovery, a portable model alias, runtime-specific launch settings, model policy, tool guidance, and local setup documentation.
- **Laguna connection variants** - Added distinct DwarfStar entries for the request-controlled, chat, and reasoner behaviors so the TUI exposes each API mode with a clear name while sharing one downloaded GGUF.

### Changed

- **Local model connection flow** - Moved llama.cpp discovery into its own model selection screen, aligned DwarfStar and llama.cpp managed launches around the shared Laguna artifact, and documented the current llama.cpp compatibility requirement.
- **Release metadata** - Bumped the package, runtime, lockfile, ACP registry, package checks, extension compatibility examples, plugin documentation, and generated product images to `0.2.35`.

### Fixed

- **DwarfStar Laguna startup** - Rebuilds an existing DwarfStar checkout when requested, detects stale or incompatible binaries, and avoids presenting the same server model as indistinguishable duplicate TUI entries.
- **Portable model paths** - Removed reliance on a user-specific model directory. Laguna now resolves from the standard Hugging Face cache, configured cache roots, `SUPERQODE_LAGUNA_GGUF`, or an explicit GGUF path.

## [0.2.34] - 2026-07-23

### Changed

- **Product positioning** - Defined SuperQode as Agent Engineering for an organization-owned code factory. Added concrete Code Engineering and Code Factory concepts, retained Harness Engineering as the technical discipline, aligned the README, documentation, package metadata, and TUI, and documented the problem SuperQode solves without removing existing technical guidance.
- **Release metadata** - Bumped the package, runtime, lockfile, ACP registry, package checks, extension compatibility examples, and plugin documentation to `0.2.34`.

## [0.2.33] - 2026-07-23

### Added

- **Subscription runtime integration** - Added optional SDK and ACP paths for GitHub Copilot, including account-scoped model discovery, streamed runtime events, permission handling, session controls, terminal connection profiles, and technical documentation.

### Changed

- **Release metadata** - Bumped the package, runtime, lockfile, ACP registry, package checks, extension compatibility examples, and plugin documentation to `0.2.33`.

## [0.2.32] - 2026-07-23

### Added

- **Unified TUI transition feedback** - Added responsive notifications, persistent transcript receipts, deduplication, focus restoration, and status synchronization for model, agent, provider, local runtime, harness, session, and interaction mode changes. Connection failures now provide prominent recovery guidance, and local models report selected and ready states separately.
- **Optional vendor SDK bundle** - Added the `vendor-sdks` extra for Codex, Claude Agent, and Antigravity SDK runtimes, plus environment-aware `superqode runtime setup` and `:runtime setup` guidance. The default installation remains lightweight, and external Grok and Antigravity subscription CLIs retain their own installation and authentication flows.
- **Durable harness switching** - Added `:harness switch <name>` with same-session context replay, persistent harness transition history, explicit `--fork` branching, harness continuity states, `superqode harness current`, and a harness-aware `:sessions switch` picker.
- **Interactive Harness Switcher** - Added a responsive `:harness` and `:harness switch` picker with active-harness state, readiness and continuity details, keyboard and Vim navigation, direct switch or fork actions, complete-catalog toggling, inspection, cancellation, and fresh-runtime confirmation.
- **ACP registry and runtime catalog** - Connected the official ACP Registry to a durable local cache and bundled offline catalog, corrected current ACP launch commands, expanded automatic discovery, added Devin, Kilo, Harn, Cortex Code, DeepAgents, GLM Agent, CodeBuddy Code, and Dirac definitions, and grouped the TUI into installed, featured, enterprise, and complete catalog views.

### Changed

- **Release metadata** - Bumped the package, runtime, lockfile, ACP registry, package checks, extension compatibility examples, and plugin documentation to `0.2.32`.

## [0.2.31] - 2026-07-22

### Changed

- **Product positioning** - Established SuperQode as the Agent Engineering framework for your code, with a concise message centered on reliable coding agents, portable harnesses, context, memory, tools, control loops, and freedom to use any agent or model.
- **Product surfaces** - Aligned the README, documentation home page, concepts, getting started, harness engineering, Software Factory, and Omnigent relationship pages around the terminal-first Agent Engineering product theme. Reworked the TUI home screen with current workspace state, context-aware next steps, a concise task prompt, WorkOrder navigation, and an explicit interoperability summary for Local, ACP, MCP, A2A, BYOK, and SDK integrations.
- **Vim-like terminal navigation** - Expanded the optional Vim mode into persistent Normal, Insert, Command, and Search states with visible mode status, transcript and pane navigation, `j` and `k` picker control, search traversal, leader access, command history, repeat, and an in-product tutor.
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
- **Complete TUI command autocomplete** - Kept every matching `:` command keyboard-reachable through the paged completion panel, synchronized dispatcher aliases across both completion surfaces, and added live ACP agent shortcuts, including discovered or custom agents, to suggestions.
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

- **Newest models first, everywhere** - BYOK shortlists and full catalogs, the Codex account model picker, and the OpenCode model picker now order entries newest-release-first. Rolling `-latest` aliases stay in the list and win date ties but no longer replace real models - the old exclusive-alias rule hid the brand-new GPT-5.6 family behind stale `gpt-5.x-chat-latest` entries. Realtime audio models are excluded from chat pickers.

### Fixed

- **Codex subscription compatibility and completion** - SuperQode now retries a bundled Codex app-server that cannot parse a newer global reasoning setting (such as `ultra`) with a process-local compatible `xhigh` override, leaving the user's global config unchanged. The live prompt now pages through every `:codex` subcommand and completes effort values, cached model IDs, and sandbox modes.
- **Current local Codex model catalogue** - When the installed standalone Codex CLI is newer than the Python SDK's bundled app-server, SuperQode now uses it for the subscription runtime. `:codex model` / `:codex models` therefore show the account's current models (including GPT-5.6 where enabled), the active-model badge reflects the model actually resolved by the thread, and newly advertised `max` / `ultra` effort levels are available when supported.
- **`:quit` quits from anywhere** - The harness wizard and pending agent questions consumed typed input before the command dispatcher, so `:quit` mid-wizard became a wizard answer instead of quitting. Typed commands now always win: the wizard passes every `:`/`/`/`!` line through to the dispatcher (keeping only its own `:cancel`/`:back` words), and agent questions pass the quit family through while still accepting free-text answers. Covered by unit tests and a mounted-TUI test that types `:quit` mid-wizard.
- **Feedback is always visible in the TUI** - Picker scroll helpers left the log's follow-mode disabled after arrow navigation, so anything written afterwards (Codex "not installed" errors, the "API Key Required" panel, setup guidance) landed invisibly below the fold and Enter looked dead. The helpers now restore follow-mode, and feedback panels anchor the viewport to the *start* of the message so tall panels on short terminals show their heading first, not just their tail. Covered by mounted-TUI regression tests for the Codex profile and BYOK key-guidance flows.

## [0.2.14] - 2026-07-10

### Fixed

- **Picker feedback messages always visible** - Selecting a needs-setup profile (e.g. "Grok subscription" without a `grok login`) wrote its error and guidance lines below the picker while the viewport stayed pinned to the picker top - Enter looked dead. `add_error` / `add_info` / `add_success` / `add_system` and shell output now re-enable follow-scroll and force the log to reveal the message. Covered by a mounted-TUI regression test that drives the real key flow.
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

- **`apply_patch` (patch envelopes)** - native support for the `*** Begin Patch` envelope format that GPT-5.x and local gpt-oss models are trained to emit: Add/Delete/Update File, `*** Move to:` renames, `@@` locators, EOF anchors, multi-file patches with all-or-nothing validation, fuzzy context matching (exact → trailing-whitespace → trimmed), markdown-fence/prose stripping, and workspace + post-edit-verification integration. Bash invocations of `apply_patch <<EOF` heredocs are intercepted and routed to the real tool. Registered in every tool profile.
- **`shell_session` (interactive processes)** - open persistent PTY-backed processes (REPLs, dev servers, debuggers, prompts), `write` to stdin, `poll` new output, `list`, `kill`. Bounded per-call waits with early return on settled output, 2MB rolling buffers with spill-to-disk on return, session reaping, and atexit cleanup so no orphan processes outlive superqode.
- **`view_image` (multimodal context)** - attach local png/jpg/gif/webp files to the conversation as OpenAI-style `image_url` parts for vision-capable models (including local multimodal models like Gemma 4). Image attachments are token-counted at a flat charge instead of their base64 length, stripped before LLM summarization, and pruned (pixels only) once they age out of the protected context window.
- **In-run steering** - `AgentLoop.steer()` injects user messages between iterations of a *live* run (and keeps the run going if a message arrives as the model finishes), instead of waiting for the whole run to complete. Thread-safe; peers and UIs share the same mechanism.
- **Auto-continue on token-limit cuts** - when a response stops with `finish_reason="length"`, the loop asks the model to continue from exactly where it stopped (default 2 continues, `max_auto_continues`), joining the parts into one answer; streaming continues seamlessly.
- **System reminders** - synthetic `<system-reminder>` notes attached to outgoing requests only (never persisted): files changed externally since last read (each change announced once), and stale-todo nudges (rate-limited). `SUPERQODE_REMINDERS=0` disables.
- **Deferred tool loading + `tool_search`** - `SUPERQODE_DEFERRED_TOOLS=auto|all|<names>` hides heavy tool schemas (web, images, sessions, LSP, MCP, agents) from the prompt until the model activates them via a lexical `tool_search`; activated schemas appear on the next call. `auto` applies only to local providers, where schema budget matters most.
- **Peer agents** - long-lived multi-agent suite: `spawn_agent`, `send_input` (steers a busy peer's live run; `interrupt=true` cancels and redirects), `wait_agent`, `list_agents`, `close_agent`. Peers are long-lived AgentLoops with their own context; one level deep (peers cannot spawn peers).
- **Background bash** - `bash` gains `run_in_background`: starts the command as a persistent session and returns its `session_id` immediately for later `shell_session` poll/write/kill.
- **Turn diff** - per-turn aggregate of file changes ("Turn changed 3 file(s) (+45/-12): …") emitted to the thinking trace; the combined diff is retained on `AgentLoop.last_turn_diff` for UIs and hooks.
- **Shell env policy** - `SUPERQODE_SHELL_ENV_POLICY=filter-secrets` strips secret-looking variables (`*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`, …) from model-spawned commands, with `SUPERQODE_SHELL_ENV_ALLOW` exceptions.
- **Exec policy rules** - declarative allow/deny/ask rules for shell commands in `.superqode/execpolicy.yaml` (project), `~/.superqode/execpolicy.yaml` (user), or `SUPERQODE_EXEC_POLICY` (explicit): glob or `re:` patterns, first match wins. User `allow` skips the prompt but can never override built-in dangerous-command denies.
- **Automatic memory (opt-in)** - `SUPERQODE_AUTO_MEMORY=1` extracts durable preferences/facts/decisions from completed runs in a background task and stores them in the local memory provider (deduplicated, tagged `auto`), where `:memory search` already looks.
- **Automatic memory recall (opt-in)** - `SUPERQODE_AUTO_RECALL=1` completes the loop: at run start the local memory store is searched with the prompt and the top hits (max 4, relevance-floored) ride along as a clearly labeled `<system-reminder>`, once per prompt, never persisted to history. Only the user-level local store is read, so untrusted repository content can never enter the agent's context through recall.
- **`request_permissions`** - the model can make one justified request for session-scoped tool permissions; approval through the normal prompt upgrades those tools from ask-each-time to allowed (hard denies are never overridable, grants clear with the session).
- **`--output-schema`** - headless runs pin the final answer to a JSON Schema: schema embedded in the prompt, lenient extraction + validation, one automatic corrective retry, exit code `2` on validation failure; `--mode json` gains `structured_output`/`schema_errors`/`schema_valid`.
- **`--rubric`** - self-grading quality gate for headless runs (inline text or `@file`): a separate grader judges the final answer and "needs revision" feedback re-enters the loop (`rubric`/`max_rubric_rounds` on `AgentConfig` for programmatic use; grader fails open).
- **HTML session export** - `superqode sessions export <id> --format html` renders a self-contained, dark-mode, shareable transcript page.
- **`tool_call_format: prompt`** - harness model policy now wires through to behavior: tool schemas render into the system prompt and `<tool_call>{…}</tool_call>` blocks are extracted from response text and executed like native calls - for local models with no native tool-calling head (`compact-json`/`strict-json` remain native arg-style hints).
- **TUI live steering** - typing while a builtin (local/BYOK) run is active now steers the *current* run between tool calls (`↪ steering the current run`); non-steerable connections keep the type-ahead queue.
- **Documentation** - five new procedural guides (Inside the Agent Loop, Tools Catalog, Policies & Safety, Multi-Agent Workflows, Headless & CI) plus a complete Environment Variables reference, all in the docs nav.

### Changed

- **Documentation quality pass** - every code fence now carries a syntax-highlighting language tag; em-dashes and typographic ellipses removed site-wide; landing page gains a numbered progressive learning path and a complete runtime table (codex-sdk, claude-agent-sdk); TUI reference documents live steering, `:context`, `:thinking`, `:queue`, `:workspace`, and `:memory`; serve commands reference now covers the MCP server and A2A server API accurately; tools-system page modernized and cross-linked with the Tools Catalog; strict `mkdocs build` passes clean.
- **Documentation redesign** - full-width landing page rebuilt to the Material/FastAPI standard: single compact logo hero with gradient title, badge row, action buttons, a 60-second quickstart, eight icon feature cards, tabbed live examples (TUI/headless/harness/CI), and a guided learning path; custom brand palette (light and dark) via Material's supported hooks; Inter + JetBrains Mono typography; the 1,151-line CSS override sheet replaced by a 151-line brand layer; sidebar no longer force-expands; placeholder Google Analytics and the cookie-consent banner removed.
- **Positioning and completeness** - product positioning updated everywhere (docs landing, site description, README): "the portable coding agent harness framework; define your harness or bring your own; any provider, any model, any runtime, any protocol; optimized for local agentic AI"; the product banner returns to the home page under the hero; dark mode switches to warm amber accents (bright purple was harsh on dark backgrounds); "Three Connection Modes" becomes "Connection Modes" with a fourth SDK mode documented (Codex SDK via ChatGPT subscription, Claude Agent SDK via Claude subscription or Anthropic API key, Antigravity handoff); all 27 previously undocumented `SUPERQODE_*` environment variables added to the reference, bringing code-to-docs coverage of env vars, tools, and CLI commands to 100%.

- **Spill-to-disk tool output** - oversized bash/tool output is saved in full to `~/.superqode/tool-output` (7-day retention, `SUPERQODE_TOOL_OUTPUT_DIR` to relocate); the model gets a head/tail preview plus the file path and can `read_file`/`grep` the rest instead of re-running the command. A loop-level guard applies the same bound to tools that don't self-limit (MCP, web). Spilled paths are always readable by read/search tools.
- **Bounded, numbered reads** - `read_file` returns up to 2000 lines / 50KB by default with `N: ` line-number prefixes, clamps overlong lines (minified JS), rejects binary/image files with a clear message, and tells the model exactly how to continue (`start_line=<next>`); accepts `file_path`/`offset`/`limit` aliases that local models trained on other harnesses emit. Edit matching gains a fallback that strips pasted line-number prefixes.
- **Doom-loop guard** - the Nth consecutive identical tool call (default 3; `doom_loop_threshold` / `SUPERQODE_DOOM_LOOP_THRESHOLD`) is intercepted with corrective feedback instead of executing again; if the model immediately repeats the same call, the run stops with `stopped_reason="loop_detected"`.
- **Tool-argument repair** - malformed tool-call arguments (markdown fences, Python-dict syntax, trailing commas, double-encoded JSON, prose around the object) are repaired; unrecoverable arguments return a corrective error to the model instead of silently executing the tool with `{}`.
- **Rate-limit retry** - transient overload errors (429/503/529/overloaded) retry with exponential backoff, honoring `Retry-After`/`retry-after-ms` headers (`SUPERQODE_RATE_LIMIT_RETRIES`, default 3); long provider-requested pauses surface instead of hanging the session.
- **Tool-output pruning** - a free pre-compaction stage stubs stale tool outputs older than the protected recent window before paying for LLM summarization (the current turn's results are always protected); often avoids the summarization call entirely on local models.

### Changed

- **Mutation-safe parallel tools** - tools now carry a `read_only` flag; a turn's tool calls run concurrently only when every call is read-only. Any batch containing an edit/write/bash/MCP call runs sequentially in call order, so concurrent file mutations can no longer race.
- **Streaming bash drains to EOF** - output beyond the model-sized cap no longer stops the reader (which could deadlock chatty processes on full pipes); streams are drained, the full output (up to 5MB) is spilled, and the preview stays bounded.

## [0.1.40] - 2026-06-09

### Added

- **Multi-repo search** - `:workspace add|remove|list` registers repositories (persisted in `~/.superqode/workspace.json`); grep/glob gain an `all_repos` fan-out that searches every registered repo in one ripgrep pass, labeling matches by repo. Absolute paths are honored inside the workspace and permission-gated outside it (`SUPERQODE_ALLOW_EXTERNAL_SEARCH`).
- **Harness over MCP** - `superqode mcp` (stdio, or `--http`) exposes HarnessSpec workflows as MCP tools (`list_harnesses`, `describe_harness`, `run_harness`) for any MCP client, alongside the existing A2A and ACP servers.
- **Adaptive context compaction** - compaction threshold and kept-recent window now auto-scale to the model's real context window and run by default (`SUPERQODE_AUTO_COMPACT=0` to disable).
- **Local context-window detection** - probes the live server for the *loaded* window per backend (Ollama `/api/ps`, llama.cpp `/props`, LM Studio `/api/v1/models`, vLLM/DS4 `/v1/models`). New `:context` command to show/pin/re-detect the window.
- **Post-edit verification** - fast per-file diagnostics (ruff/py_compile, eslint, gofmt, JSON/YAML) run after the agent edits a file, with findings fed back so it self-corrects (`SUPERQODE_VERIFY_EDITS`, `SUPERQODE_FORMAT_ON_EDIT`).
- **Dangling tool-call repair** - synthesizes a tool result for any unanswered tool call (interrupted/cancelled/malformed/resumed), keeping the message history provider-valid.
- **Thinking-log verbosity** - `:thinking normal|verbose|off` (Ctrl+T cycles); calm default folds iterations into a live status with a tidy per-tool trace.
- Documentation: new *Local Context & Compaction* and *Multi-Repo Search & Edit Safety* guides; harness-over-MCP docs.

### Changed

- **Search tools** - grep/glob now spawn ripgrep directly with structured `--json` output (no shell), report truncation/partial results, and steer the model toward subagents for open-ended search.
- **Welcome screen & input box** - responsive centered layout, refreshed messaging, thicker titled prompt box, and trimmed hints bar.

### Fixed

- Streaming agent loop now compacts context - local/BYOK sessions no longer overflow the window (the streaming path previously never compacted).

## [0.1.39] - 2026-06-06

### Added

- **Plan mode** - new `plan_mode` config flag that blocks tool execution in the agent loop, allowing side-effect-free planning and review before any action is taken.
- **Memory system overhaul** - new provider-based memory architecture with `LocalAgentMemoryProvider`, `SpecMemProvider`, `Mem0Provider`, `CogneeProvider`, and `SupermemoryProvider`. Configurable via `memory:` section in `superqode.yaml` with provider-specific settings.
- **Project trust system** - per-user trust store (`~/.superqode/trust.json`) for project workspaces, with risk signal detection for plugins, MCP configs, and hooks. Mark projects trusted/safe via `set_project_trust()`.
- **Transcript export** - conversation transcripts can now be exported to portable JSON/text formats via `transcript_export.py`.
- **Session share artifacts** - new `share_artifacts` module for sharing session context across agents.
- **Pure mode** - `pure_mode.py` for restricted/safe agent operation.
- **Developer workflow documentation** - new `docs/developer-workflows.md` guide.
- **Plan mode tests** (`test_agent_loop_harness.py`), **memory tests** (`test_agent_memory.py`), **project trust tests** (`test_project_trust.py`), **developer workflow doc tests** (`test_developer_workflow_docs.py`), and expanded runtime tests.

### Changed

- `AgentLoop` now checks `config.plan_mode` before executing tools, returning a denied result when active.
- Memory `__init__.py` exports a unified `create_memory_provider()` factory and `available_memory_providers()` discovery function.
- Slash completions, TUI widgets, and QE commands updated for plan mode awareness.

## [0.1.38] - 2026-06-06

### Added

- **OpenAI Codex SDK runtime** (`codex-sdk`) - drive OpenAI Codex from SuperQode using your ChatGPT/Codex login (`~/.codex`), no API key required. A self-contained runtime that owns its own model and auth, with streamed harness events, tool cards, and approval prompts. Models `gpt-5.5` / `gpt-5.4` / `gpt-5.4-mini`. Install with `pip install "superqode[codex-sdk]"`.
- **`:codex` command surface** - `status`, `models`, `model`, `effort`, `sandbox`, `review`, `compact`, plus full thread/session management (`thread`, `sessions`, `resume`, `fork`, `rename`, `archive`, `account`).
- **Claude Agent SDK runtime** (`claude-agent-sdk`) - drive Claude Code from SuperQode using your Anthropic API key (`ANTHROPIC_API_KEY`); the adapter maps the SDK's message/block and permission shapes to SuperQode's harness, with tool cards and approvals. Install with `pip install "superqode[claude-agent-sdk]"` (plus the Claude Code CLI).
- **`:claude` command surface** - `status`, `model`, `permission`, `sessions`, `commands`, `review`.
- **Connection profiles in `:connect`** - product/account-first connection sources (ACP agent, BYOK provider, Local model, Codex subscription, Claude Agent SDK, Antigravity CLI, Advanced runtime) with per-source availability detection, so picking *what* to connect to is separated from the underlying execution engine (`providers/connection_profiles.py`).
- **Antigravity CLI handoff** (`:antigravity` / `:agy`) - `status`, `migrate`, `launch` for Google's local `agy` CLI, offered as a recommended Gemini CLI migration path.
- **Programmatic SDK helpers** - `superqode.codex` (`run_codex`, `stream_codex`, `codex_session`) and `superqode.claude` (`run_claude`, `stream_claude`, `claude_session`) for running Codex/Claude one-shot, streaming typed harness events, or in multi-turn sessions without hand-building an `AgentConfig`. See `examples/codex_sdk_quickstart.py`.
- **Runtime + model status badges** in the TUI status bar, so the active runtime (e.g. `codex-sdk`) and model are always visible.

### Changed

- **`:connect` is now product-first** - the menu leads with the connection source (ACP → BYOK → Local → Codex → Claude → Antigravity → Advanced); the raw runtime/engine picker moved under *Advanced runtime*.
- **`:runtime`** extended to select the new self-contained runtimes (`codex-sdk`, `claude-agent-sdk`) alongside `builtin` / `openai-agents` / `pydanticai` / `adk`, with `:runtime list` reporting availability.
- Prompt completion and slash-command surfaces updated for the new `:codex`, `:claude`, `:antigravity`, and `:connect <source>` commands.
- Dependencies: `openai-codex` pinned to `>=0.1.0b2,<0.2.0`; added `claude-agent-sdk>=0.2.9,<0.3.0` (under the `claude-agent-sdk` extra).

## [0.1.36] - 2026-06-03

### Added

- **Local OS command sandbox** confining shell commands with the operating system's own isolation - macOS Seatbelt (`sandbox-exec`) and Linux Bubblewrap (`bwrap`). Modes via `SUPERQODE_SANDBOX` (`off`, `workspace-write`, `read-only`, `danger-full-access`) and the `:sandbox` command. See [Safety & Permissions](docs/advanced/safety-permissions.md#local-command-sandbox-os-level).
- **Command safety classification** that auto-runs known read-only commands (no prompt), gates writes/network, and blocks destructive ones. Obfuscation-aware: commands are canonicalised before analysis, and dynamic constructs (`$(...)`, backticks, `eval`, pipe-to-shell) can never be classified safe.
- **Network destination allowlist** so trusted installs (PyPI, npm, crates, GitHub, …) run without prompts while arbitrary egress is gated. Extendable via `SUPERQODE_NET_ALLOW`; `SUPERQODE_NET_STRICT` denies untrusted destinations.
- **Rewind & transcript overlay** (`Ctrl+R`, double-`Esc`, or `:rewind`) that truncates the agent's stored history to an earlier message and reloads it for editing.
- **`@` file mentions** - a live fuzzy file picker in the prompt that inlines referenced file contents on submit.
- **Live streaming markdown** so assistant responses render formatted as they stream.
- **`:theme`** picker with multiple accent themes (persisted to `~/.superqode/config.json`).
- **`:export`** to write the conversation to a self-contained HTML file.
- **`:compare <models>`** to re-run the last message across several models/runtimes concurrently and read the answers side by side.
- **`create_skill` tool** making the agent self-extensible - it can author a new `SKILL.md` that is hot-loaded and immediately invocable.
- **BYOK via models.dev** - a dynamic provider catalog and on-the-fly provider synthesis (`providers/catalog.py`, `providers/dynamic.py`) so any models.dev provider can be connected with an API key, with new models appearing without manual edits. Live `/v1/models` discovery (`providers/live_models.py`) lists a provider's currently-available models.
- **Hugging Face model toolchain** (`providers/huggingface/fetch.py`, `convert.py`) - Hub search, dry-run size preview, resumable downloads, local cache scan/delete, and MLX convert + upload. The converter auto-detects text (mlx-lm) vs multimodal (mlx-vlm) models.
- **`superqode models` command group** - `hub`, `download`, `show`, `providers`, `convert-mlx`, `cached`, `rm`, plus `connect setup` guidance.
- **In-process MLX engine** (`providers/local/mlx_engine.py`, `_mlx_worker.py`) with a family-aware tool-call parser (`mlx_tools.py`) for Qwen / Gemma / generic-JSON formats.
- **Gemma-optimized harness profiles** - the model policy routes the whole tool-capable Gemma family (Gemma 3 and 4) to a Gemma-tuned profile (minimal system prompt, strict-JSON tool calls).

### Changed

- Unified the product tagline to **"Your Portable Coding Agent Harness"** across the TUI welcome screen, README, docs, and package metadata, with a refreshed welcome subheading.
- Updated the README header image and documentation logo.
- **Family-based local tool gating** - Gemma 3/4, Qwen 2.5/3, and Llama 3.1+/4 get tools; Gemma 1/2 and Llama 3.0 do not. The agent loop falls back to family detection for custom local tags not in the model registry.
- **Gemma context windows** - modern Gemma (3/4) now use a practical 32K `num_ctx` (matching the Llama/Qwen treatment) instead of the legacy 8K, and Ollama reports their true 128K capability; Gemma 1/2 stay at 8K.
- Dependencies: `mlx-lm` pinned to `>=0.31` (adds Gemma 4 support) and `mlx-vlm` added for multimodal models.

### Fixed

- Rewrote the optional `python_repl` (Monty) tool against the real `pydantic-monty` API; it previously targeted a non-existent API and failed at runtime. Each call now runs in a fresh, fully isolated sandbox (no host filesystem, network, or third-party imports), and the `pydantic-monty` version constraint was corrected.
- **Ollama models not listing** in the TUI - model parsing crashed on `"families": null` (returned by many Ollama models), making model discovery silently return an empty list.
- **Could not exit the TUI from selection pickers** (local LM Studio / MLX / Ollama, BYOK, ACP) - `:exit` / `:quit` / `:q` now work from any picker, and a command/shell line typed inside a picker is no longer swallowed by item selection.
- **TUI freeze on quit** - the exit sequence cancelled Textual's own message pump (via `asyncio.all_tasks()`), freezing the app so it had to be killed; it now shuts down cleanly.

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

- Local code search for DS4/local models: `SUPERQODE_SEARCH_ROOTS` allowlists extra **read-only** repo roots (outside the working directory, `os.pathsep`-separated) that search/read tools (`repo_search`, `grep`, `glob`, `code_search`, `read_file`, `list_directory`) may access - so a local model can search a downloaded/cloned repo. Writes, edits, and shell stay confined to the working directory. See [Local Code Search](docs/providers/local.md#local-code-search-no-web-access).
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
