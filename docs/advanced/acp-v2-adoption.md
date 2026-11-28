# ACP v2 adoption research and implementation plan

Research snapshot: **27 November 2026**. Status: **implemented with macOS Auto preference, explicit v1/strict-v2 overrides and CLI opt-in**.

SuperQode implements ACP v2 in both directions: a client with bounded v1
fallback, and a dual-version agent server on the existing stdio entry point.
The implementation uses the pinned Preview schema and keeps the existing SDK
for v1. New macOS ACP connections default to Auto (prefer v2); CLI/TUI defaults
remain v1. macOS also offers compatibility v1 and strict v2 policies. See
[usage](../cli-reference/acp-commands.md) and [verification results](acp-v2-validation.md).

This review covers both directions: SuperQode as a client of external agents, and `superqode serve acp` as an agent used by editors. It reviews the supplied research, official documentation, published SDK artifacts, public implementation evidence, and current upstream SuperQode code.

## Release status and evidence

The [official announcement](https://agentclientprotocol.com/announcements/acp-v2-preview) dates Preview to **20 November 2026**, following the July Draft and 17 alpha schema releases. Preview is ready to build on but is not frozen. The [migration guide](https://agentclientprotocol.com/protocol/v2/migration) explicitly recommends keeping v1, negotiating once per connection, and making client use of v2 opt-in during Preview.

The verified v2 schema reference for this implementation is [schema-v2.0.0-beta.4](https://github.com/agentclientprotocol/agent-client-protocol/releases/tag/schema-v2.0.0-beta.4), published on 23 November. Wire protocol `2`, a schema release tag, and a language SDK version are different version numbers. A Python SDK numbered `1.1.0` can contain experimental protocol v2 and still lack the current v2 contract.

The announcement reports working end-to-end implementations using Claude and Codex adapters. The [Codex adapter changelog](https://github.com/agentclientprotocol/codex-acp/blob/main/CHANGELOG.md) provides concrete evidence: Preview alignment in 2.9.0, further v2 fixes in 2.11.0, and latest observed release 2.12.1 on 26 November. Those fixes are useful interoperability cases, rather than evidence that a handshake alone is sufficient.

There is a reason to prioritize the agent server as well as the client. Zed's [12 November Delta announcement](https://delta.dev/blog/claude-agent-in-delta) says external agents in Delta will require ACP v2 and be individually tested before availability. Implementing v2 would address that protocol prerequisite; it would not automatically secure a Delta listing. That article predates Preview, so its description of v2 as Draft is historical.

[JetBrains AI Assistant documentation](https://www.jetbrains.com/help/ai-assistant/acp.html), last updated 7 October, confirms ACP installation and custom agent configuration. It does not establish which released JetBrains builds negotiate v2. The joint protocol announcement establishes collaboration, not a verified product compatibility matrix. Record actual Zed and JetBrains build numbers during interoperability testing.

Remote HTTP/WebSocket transport and explicit prompt steering/queue-management APIs remain separate work. They are not prerequisites for stdio v2 adoption. Protocol v2's requirement to accept or hold a prompt while busy already applies.

## Review of the supplied research

The central recommendation is sound: two version-specific wire implementations sharing product logic, v1 preserved, client opt-in, and no blind SDK upgrade. The implementation sequence needs these changes:

| Supplied recommendation or claim | Revised assessment |
| --- | --- |
| Ship negotiation, idempotency and state handling first; add subagents later | Add minimum child-session registration, attribution and method restrictions before exposing the opt-in. Dedicated child views can follow. Every v2 client must handle child sessions. |
| Resume belongs after client UI features | Move resume, replay boundaries and current-state synchronization into the first client recovery work. Lost-response retry depends on resuming the same session. |
| A fresh key for each prompt, reused if its response is lost | Generate once per user submission and retain it with the input. Every retry reuses that submission's key. The first TUI release can keep this in memory if it does not offer retry recovery after client restart; products offering restart recovery must persist the original input and key together. |
| Retry lost-response prompts using idempotency | Retention has limits, especially for live-only commands. When duplicate side effects matter and retention cannot be established, report the uncertain outcome instead of automatically resending. |
| Wait for Python SDK 1.2.0 before server work | Use verified schema and runtime behavior as the dependency gate. Start the server session ledger, scheduling and event mapping now. A future version number is not a compatibility guarantee. |
| Client first, then all UI, then server | Start both client and server foundations after shared protocol fixtures exist. Release whichever complete path meets its gates first. Server baseline support need not wait for rich UI. |
| Registry results show the fleet is v1-only | The registry probe explicitly requests protocol 1. It establishes the need to retain v1, but does not measure v2 support. |
| Include zero support for `session/stop` in the adoption assessment | `session/stop` is not a required v2 baseline method. Its probe result says nothing useful about v2 readiness. |
| Current config-option support helps migration | Yes, but `configOptions` also exists in v1. Current comments referring to v2 do not establish wire-v2 support. IDs, discriminators and boolean handling still need adaptation. |

The original report's eight cross-version stabilized features agree with the official announcement. Some benefits, including opt-in subagent sessions, can be delivered on v1 while v2 is being completed. That is an optional delivery opportunity, not a reason to make the v2 migration depend on a separate v1 feature project.

## What people and implementers are saying

The strongest verifiable feedback is implementation activity. The ACP maintainers describe Preview as the time to build and report remaining design problems. Claude/Codex adapter work and Delta's use of v2 support the practical value of asynchronous work, child-session visibility and recoverable submissions.

Public coverage on 27 November, including [MODEL](https://readmodelmag.com/stories/zed-jetbrains-acp-v2-preview) and [AlphaSignal](https://alphasignal.ai/news/zed-and-jetbrains-rebuild-acp-v2-so-coding-agents-never-block-your-work), emphasizes background cancellation, subagents and retry handling. These are announcement summaries, not independent reliability measurements. Earlier [technical commentary](https://javatask.dev/blog/the-agent-client-protocol-part-4-what-the-draft-changes/) explains the architectural benefits and warns about schema movement; its alpha.13 pin predates Preview and should not be an implementation reference.

The supplied X post could not be read directly in this review. Exact engagement counts, named individual endorsements, the reported Bub implementation, and the claimed SDK 1.2.0 timetable were not independently established. They should not determine dependency or release decisions. The available evidence supports developer interest and active adoption, not a broad user consensus or a claim that migration has no risk.

The [27 November registry matrix](https://github.com/agentclientprotocol/registry/blob/main/.protocol-matrix/latest.md) reports 42 agents probed, 41 initialized and 26 session-creation responses requiring authentication. Its [probe source](https://github.com/agentclientprotocol/registry/blob/main/.github/workflows/protocol_matrix.py) sets `PROTOCOL_VERSION = 1`. Run an explicit version-2 probe against selected adapter releases to establish a v2 compatibility matrix.

## Source baseline before implementation

The workspace is at **b7458b90569dac331acf32a9d8e7aa50080c8c5b**, engine version 2.32.3. GitHub `main` was **61d292f0628141be66332efcd9c0ee30161d6ffd**, engine version 2.33.3, when checked. It is 29 commits ahead. The [commit comparison](https://github.com/SuperagenticAI/superqode/compare/b7458b90569dac331acf32a9d8e7aa50080c8c5b...61d292f0628141be66332efcd9c0ee30161d6ffd) was reviewed, and changed ACP files were read at that exact upstream commit. The workspace was not rebased or updated.

| Area | Behavior in the reviewed baseline | Consequence for v2 |
| --- | --- | --- |
| [Primary client](https://github.com/SuperagenticAI/superqode/blob/61d292f0628141be66332efcd9c0ee30161d6ffd/src/superqode/acp/client.py) | Requests and accepts only version 1; uses `clientCapabilities`, `agentCapabilities`, `session/load`, and prompt-response `stopReason` | Needs negotiation and version-specific encoding, state, authentication and resume handling |
| Primary client updates | One message buffer; whole messages append; tool patches omit null values; session IDs do not partition transcripts | Cannot correctly apply v2 replacement, clearing or child-session semantics |
| Current upstream config support | Model config options take precedence over legacy models; reasoning effort support expanded | Reuse product controls, but adapt v2 `configId`, required setter `type`, and boolean values |
| [SDK client](../../src/superqode/agents/client.py) | `ACPAgentManager` uses the official v1 SDK; backs the connect command path | A change to the primary client does not automatically upgrade every CLI path |
| [Live doctor](../../src/superqode/acp/doctor.py) | Calls model/mode getters that can probe legacy `session/models` and `session/modes` when cached values are absent | Make diagnostics version-aware; on v2 derive controls from config options and report requested versus negotiated version |
| Other transports | `AgentStreamClient` and inline handshakes in `agent_run.py` and `codex.py` explicitly request 1 | Migrate callers incrementally or keep them explicitly v1; do not advertise a global opt-in before it reaches them |
| [Desktop worker](https://github.com/SuperagenticAI/superqode/blob/61d292f0628141be66332efcd9c0ee30161d6ffd/src/superqode/desktop_service/acp_worker.py) | Reuses the primary client, emits append-style UI events, then stops the client and closes host terminals in `finally` | Needs update/replace/session-aware events and a connection lifetime that can preserve background work |
| [Agent server](../../src/superqode/acp/server.py) | Official SDK v1; new/close/prompt/cancel; no list or resume; prompt spans the harness turn | Cannot advertise the v2 session capability until the entire session baseline works |
| Agent lifecycle | Close only removes live state; errors are text plus `end_turn`; tool tracker restarts for each prompt | Needs task cancellation/join, semantic error states and IDs that remain unique across turns and replay |
| Agent persistence | Harness run/session records exist, but live agent state is an in-memory dictionary | Store support is a foundation, not an existing ACP replay or restart-safe deduplication implementation |
| [MCP configuration](../../src/superqode/mcp/config.py) | Stdio entries omit `type`; commands may be relative | Add a v2 serializer with `type: "stdio"`, absolute executable paths and capability filtering |
| Agent MCP integration | `new_session` accepts `mcp_servers` but does not pass them into harness setup | Do not advertise a v2 MCP transport until the session actually connects it |
| [Optional Pydantic Coder runtime](https://github.com/SuperagenticAI/superqode/blob/61d292f0628141be66332efcd9c0ee30161d6ffd/src/superqode/pydantic_coder/__init__.py) | Added upstream; isolated environment pins ACP SDK 0.11.1 and uses the harness library's ACP server | Preserve v1 fallback for this bundled agent. Updating the engine SDK alone would not upgrade it |

The engine dependency remains `agent-client-protocol>=0.10.0,<0.12` in both source snapshots. The workspace environment has 0.10.0 installed.

### Direct verification

The published [Python SDK 1.1.0](https://github.com/agentclientprotocol/python-sdk/releases/tag/1.1.0) tracks experimental v2 **alpha.7**, according to its release notes and [versioned v2 guide](https://github.com/agentclientprotocol/python-sdk/blob/1.1.0/docs/experimental-v2.md). The published wheel was downloaded without installing it and its PyPI SHA-256 verified: `41c0860f28eee5dcc32c1e22d451008eb8280872dad5f938360a252021e52fd1`.

Its experimental v2 schema lacks `idempotencyKey`, `replay_complete` and background-work fields. It does contain some newer-looking types such as subagent and terminal updates. Importing `acp.experimental.v2` therefore does not establish Preview compatibility. Keep the engine pin until a dedicated SDK migration verifies the required APIs and existing v1 consumers.

Deterministic, in-process probes against the exact upstream primary client produced:

| Input | v2 result needed | Observed current result |
| --- | --- | --- |
| Whole-message content `old`, then `new`, for the same message | `new` | `oldnew` |
| Parent chunk, then child-session chunk | Separate transcripts | `parentchild` in one buffer |
| Tool title `old`, then explicit null | Cleared title | `old` retained |
| Idle state update with error stop reason | Error completion recorded | Stop reason unchanged |
| Initialize result with protocol version 2 | Select v2 handlers | Rejected as unsupported |

These are expected incompatibilities in a v1 client; they demonstrate why changing only its version constant would be incorrect.

Existing workspace checks completed successfully: **150 passed, 1 skipped** across `test_acp_client.py`, `test_acp_server.py`, `test_acp_session_store.py`, `test_acp_permission_store.py`, `test_acp_parent_tool_linking.py` and `test_desktop_acp_setup.py`. These are v1 regression checks on the workspace snapshot, not execution of the complete newer upstream tree or certification of v2 support.

## Required implementation contracts

### Connection and message state

The primary client orchestration now uses separate v1/v2 codecs and a
session-aware state reducer. The implemented boundaries are `acp/protocol.py`
for version and capability handling, `acp/state.py` for retained entities,
`acp/client_v2.py` for client lifecycle and `acp/server_v2.py` for the agent.
The contracts below remain the acceptance criteria for future changes.

Key messages, tool calls, plans and terminals by session and entity ID. Apply updates in wire order. Whole-message content replaces; chunks append; omission preserves a field; explicit null clears it. Top-level `_meta` patches individual keys. Plans replace by `planId`. Preserve unknown values for safe generic rendering or forwarding. Do not carry v1 compatibility heuristics that discard nulls into the v2 reducer.

Capability markers require object/presence checks: `{}` means supported even though an empty Python dictionary is false. Check `capabilities.session`, prompt input types, MCP transports and cancellation controls accordingly.

The [initialization rules](https://agentclientprotocol.com/protocol/v2/initialization) require `info` and version-specific capability shapes. If a legacy agent selects 1 after a v2 request, reopen it with a v1 handshake when the product needs capabilities lost during fallback. A v2-aware agent permits repeated initialization before any other request, but legacy peers may not. Bound fallback attempts and never retry or downgrade a failed accepted prompt as if it were merely a handshake failure.

A server pre-router must select the highest implemented version at or below the requested version, rather than branch only on equality with 1 or 2. With implementations `[1, 2]`, a request for version 3 selects 2; version 0 gets `-32022`; malformed, boolean or out-of-range versions get `-32602`. Inspect the version before validating the remaining version-specific parameters. Preserve legal repeated initialization and give one transport reader ownership of stdin so initial framing or buffered messages are not lost between handlers. Keeping the existing v1 handler is a compatibility strategy, not proof of zero regression.

Validate JSON-RPC envelope rules: string/integer IDs with booleans excluded, no null request IDs, no batches, independent request IDs in each direction, no responses to notifications, and required error codes. Implement `-32601` for unsupported methods, `-32002` for unknown/inactive sessions, `-32600` before initialization, and `-32022` with version data when no supported version can be selected.

### Prompt lifecycle and recovery

Separate `submit_prompt()` acceptance from session activity observation. Keep a compatibility wrapper for existing callers that need to wait for foreground completion. `state_update` describes aggregate session activity, not completion of one particular prompt. It can arrive before the prompt response, and work can start without any prompt. An initial or resume idle snapshot is not a new completion.

Keep `cancel_prompt_with_grace()` attached to that foreground-completion wrapper, not the acceptance RPC task. For active work, a returned `messageId` cannot confirm cancellation; observe the relevant final foreground state. Handle work that completed before cancellation and already-idle sessions without requiring a new cancellation snapshot that the protocol does not promise.

Follow the [prompt lifecycle](https://agentclientprotocol.com/protocol/v2/prompt-lifecycle): acknowledge only actual insertion; echo the inserted user message with the agent-owned ID; report active and idle transitions; distinguish pre-insertion RPC failures from failures after insertion; preserve `unknown` as lost observability rather than success. Even locally handled slash commands use a foreground lifecycle.

Create one random key and retain the original input per submission. Reuse that key only for attempts of that submission in the same session. Resume before retrying after reconnect. A response means insertion, not that side effects succeeded. A recognized retry returns the original message ID without starting duplicate work. Live-only commands may lose key recognition after disconnection, so uncertain consequential submissions must not be automatically replayed.

The first opt-in TUI release may hold pending submissions in memory and recover connections only while that client process remains alive. It must not advertise recovery of unanswered submissions after process restart, manufacture a replacement key for an earlier submission, or reconstruct unresolved work for automatic resend. A disk-backed outbox and crash-recovery UI belong with the first product path that offers those recovery guarantees, including headless, Factory or desktop workflows that require them. When restart recovery is offered, the original prompt and key must survive together. This client scope reduction does not relax the agent's durable key-retention obligations for messages it retains.

For replay requested with `replayFrom: {"type": "start"}`, require exactly one `replay_complete` before the successful resume response, including empty history. Resume without replay has no marker. Every successful resume delivers current foreground state before its response, after replay if requested. Reconstruct entities by stable IDs; do not replay old foreground states as live activity. Follow the [session setup rules](https://agentclientprotocol.com/protocol/v2/session-setup) for child replay and current background-item synchronization.

### Permissions, child sessions, tools and UI

Every v2 client registers announced children and routes their updates, permission requests and session-directed messages correctly. It cannot prompt, resume, close or reconfigure a child. Child `session/cancel` requires the child's cancel capability; stopping an individual child tool or terminal requires that item's own capability. Rich nested UI is optional; correct attribution is required by the [subagent specification](https://agentclientprotocol.com/protocol/v2/subagents).

Permission handling must understand required `title`, optional `description`, and optional typed `subject`. A missing or unknown subject is not a grant. Cancelled dialogs and `$/cancel_request` dismissals resolve safely. Reject decisions remain binding. Do not infer approval from an RPC error or a disconnected UI.

Update permission-store key derivation and the callback adapter in the first client release. The current code reads top-level `toolCall` and derives keys from its title or `rawInput.tool_name`; a v2 request carrying `subject.toolCall` would fall into the shared `unknown` key. Use versioned keys based on supported subject semantics with the intended agent/workspace scope. Do not automatically reinterpret a v1 title-based grant as a v2 grant without equivalent scope, and do not reuse persistent approvals when a stable key cannot be derived. Render the actual request title and description separately from tool state.

Support tool upserts, content chunks, structured diff changes, plan operations and agent-owned display terminals in the data model. Terminal output snapshots replace decoded bytes; chunks append. Recorded commands are display data and must never cause client execution. Generic displays are sufficient initially, provided state is retained correctly.

Drive existing model/mode controls through v2 config options. Preserve booleans through the desktop RPC path instead of coercing every value to a string. The v2 setter requires its `type` discriminator; the existing setter omits it.

The [security model](https://agentclientprotocol.com/protocol/v2/security) says ACP itself is not a sandbox. Removing client `fs/*` and terminal execution methods must not silently weaken SuperQode's host-tool approval policy. If host tools are needed, supply them through an explicit, permission-preserving MCP bridge. Filter configured servers by advertised transports, keep credentials out of history and logs, and retain workspace-root checks. A client release that does not yet provide host tools should state that limitation when the connection requires them.

Before enabling desktop v2 for an agent, verify its actual execution path. `DesktopACPClient` currently scopes file access, blocks sensitive project paths and asks for write approval; `DesktopTerminals` asks before launching commands. Those checks mediate calls through these client APIs, not every operation an agent process can perform. Agent-owned v2 tools must honor permission requests and the relevant sandbox policy, or use an explicitly gated MCP bridge. Do not assume that displaying `session/request_permission` supplies the filesystem restrictions previously applied by a host callback.

### Agent persistence and task ownership

The v2 `capabilities.session` marker commits the server to new, list, resume, close, prompt, cancel and update. Non-empty auth methods also require both `auth/login` and `auth/logout`. Only advertise optional MCP, config or cancellation features that are implemented.

Reuse `HarnessKernel`, harness events and existing stores, but add server-owned ACP session metadata and retained entities. The client `ACPSessionStore` indexes remote session metadata; it is not an agent transcript store. Persist original working directory, harness identity/configuration reference, model and stable ACP entity IDs. Scope discovery to the applicable user and permitted roots. Do not persist MCP credentials with those records.

`HarnessInputRecord` and `admit_input()` provide useful inbox primitives. They do not by themselves prove ACP conversation insertion. For the first implementation, hold prompts while busy in receive order, then persist the user message and deduplication mapping when inserting it, acknowledge, and schedule work. Coalesce simultaneous retries of a held key. Do not acknowledge mere receipt into a queue.

Persist accepted message/key mappings together using a transaction-capable store API or equivalent single-record commit. Retained messages require key recognition across server restarts for their full retention period. Tool IDs must stay unique across turns; the current per-prompt counter needs a run/session namespace. Replayed entities must keep their original IDs.

`FileHarnessStore` uses temporary-file replacement for individual JSON records. That does not make several separate writes a transaction. A file-backed ACP ledger must commit a message and its key mapping in one authoritative record and serialize admissions, or use a store transaction that provides the equivalent invariant. Reusing the existing store does not remove this work.

Own an explicit task registry per session. `session/cancel` stops foreground work and drops uninserted held prompts; `session/close` also stops background work and descendants, resolves pending interactions, frees resources, and delivers required final foreground state before responding. Removing an entry from `_sessions` is not sufficient cancellation. Failures after insertion end activity through an error state rather than a successful-looking text message and `end_turn`.

Exposing SuperQode's delegated agents and independent background tools is an optional server enhancement after this baseline. A server can initially keep execution in the foreground and omit optional child exposure. That lets the server become useful sooner without claiming unsupported cancellation controls.

## Revised delivery sequence

The table records the reviewed delivery sequence. Stages 1 through 3 are implemented; their remaining external verification gates are recorded in the validation report. Stage 4 is intentionally deferred during Preview.

| Stage | Concrete change | Release gate |
| --- | --- | --- |
| 1. Shared contracts | Pin beta.4 fixtures; add version codecs and session/entity reducer; define submission and task ownership APIs; audit launch paths; verify server router integration with the pinned SDK | Existing v1 tests pass; deterministic tests cover replacement/null/chunk semantics, ordering and session separation; no user-facing version change |
| 2A. First v2 client | Opt-in on the primary TUI client; bounded v1 fallback; acceptance/state lifecycle; child routing; permissions and store keys; typed config; resume/replay; in-memory submission keys; generic terminal/plan/diff handling; version-aware live doctor probe | Exact adapter-version tests against Claude and Codex, deterministic cancellation/reconnect races, and v1-only fallback including terminal auth. No claimed crash recovery or automatic uncertain resend; doctor distinguishes v2 from fallback |
| 2B. First v2 agent | Start alongside 2A after shared contracts. Build durable session ledger, ordered held prompts, insertion acknowledgement, baseline list/resume/close, semantic states and a dual-version stdio router | All seven baseline session operations work; restart deduplication and replay order pass; same command serves v1 and v2; auth baseline works; pinned-schema validation and both-version transport/lifecycle tests pass |
| 3. Desktop, recovery and richer features | Preserve connections across foreground idle; add session-aware replace/update events and boolean config handling; verify each agent's host-tool policy; expose delegated children and per-item cancellation; consolidate callers or leave them explicitly v1; add durable outbox where restart recovery is offered | UI preserves background work and approval scope; advertised controls stop the intended item; recovered submissions retain their original keys; native and headless recovery claims match tested behavior |
| 4. Broader default | After v2 leaves Preview, consider requesting 2 by default, preserving fallback and a v1 override | Product compatibility matrix passes, engine and isolated runtimes are verified, and no insertion/retry/approval/lifetime defects remain unresolved. Leaving Preview is necessary under this rollout policy, not sufficient by itself |

Do not put a future Python SDK release on the server's critical path. During stage 1, check for a release that demonstrably matches the pinned Preview schema and passes SuperQode's v1 migration checks. If the SDK still has the verified alpha.7 gap, implement a narrow beta.4 schema-backed v2 transport behind the version router while retaining the existing v1 SDK path. Validate actual JSON payloads against the pinned official schema in CI, and separately test scheduling, persistence, ordering and cancellation. JSON Schema validates payload structure; it cannot establish lifecycle correctness or zero regression.

An official SDK can replace that v2 transport once its behavior is verified against the same contracts; it need not wait for protocol v2 to become stable. Keep the transport adapter isolated so that replacement does not rewrite session logic. Never run Preview payloads through alpha.7 validators or translate all v2 traffic into v1 semantics. The extra adapter has maintenance cost, but it avoids waiting indefinitely on a release number.

`superqode acp doctor AGENT --live --protocol-version 2` is implemented. It
reports requested and negotiated versions and uses config options on v2 rather
than probing legacy model/mode methods. A fallback to 1 is successful fallback,
not verified v2 compatibility. The diagnostic sends no coding task; controlled
test scenarios exercise prompts and recovery separately.

Full registry adoption is not a requirement for an opt-in client or a dual-version server. Actual compatibility, retained fallback and complete contracts are the release gates. Defer unstable session forks, cursors, archive/options, MCP-over-ACP, remote transports and steering controls until their separate negotiation and product behavior are needed.

## Verification and rollout gates

Use fixtures for both versions on one entry point, including a v1-only agent, a dual-version agent and a v2-only agent. Add real stdio subprocess coverage so reader-loop ordering, pending-request cancellation and shutdown are exercised beyond mocked method calls.

Required failure and race cases include:

1. Updates arriving before prompt acceptance; completion before the acceptance response is delivered; idle snapshots during initialization/resume; unsolicited agent work after idle.
2. Busy-agent prompts held in order; two requests with one held key; pre-insertion cancellation; cancellation after insertion; closing during approval; a later prompt arriving while cancellation is finishing.
3. Lost response after insertion; same-client-process reconnect with the original key; agent restart with retained message/key; live-only command with lost retention; explicit retry versus a new submission of identical text. Verify durable client restart recovery only in product paths that offer it, and verify that the initial in-memory TUI does not silently resend after restart.
4. Empty replay, truncated replay, replay followed by live chunks, repeated whole-message snapshots, and resume without replay while background work remains.
5. Nested child attribution and restricted methods; ID collisions across sessions and turns; null and empty-value patches; unknown enum variants and unknown permission subjects.
6. Base64 terminal snapshots/chunks; cancellation capability withdrawal; foreground cancel preserving independent background work; close stopping descendants and background work.
7. Version fallback with host-tool/terminal-auth capabilities restored; higher requested versions selecting the highest supported lower version; version 0 and malformed version errors; legal repeated initialization; absent versus empty-object capabilities; removed methods returning method-not-found; invalid IDs and batches.
8. Typed config booleans, permission-store key isolation and migration, callback cancellation, credential redaction, MCP command normalization, transport filtering and per-agent desktop workspace/permission boundaries. Doctor must not send legacy model/mode probes on v2 or report v1 fallback as v2 support.

Run the [ACP Test Compatibility Kit](https://agentclientprotocol.com/libraries/testing) for both versions against `superqode serve acp`, pinned to a known TCK commit or tag. Select its v2 suite explicitly with `--protocol-version 2`. Check the TCK's vendored schema and optional-feature applicability against the chosen protocol baseline. Its coverage is incomplete and its own documentation says a passing run is not official conformance certification; keep the targeted race tests above.

For external-agent interoperability, record adapter release, negotiated version, authentication path, session recovery and exercised capabilities. Include Claude, Codex, the bundled Pydantic Coder v1 fallback, and representative v1-only registry agents. For the agent server, verify a model-free fixture first, then a controlled harness run in identified Zed/JetBrains builds. Real provider-authenticated interoperability and native macOS UI testing remain release work; they were not performed in this research review.

During opt-in rollout, expose the actual negotiated version in connection diagnostics, retain a per-connection v1 override, and collect bounded/redacted lifecycle failures. Turning off future v2 connections is the rollback; never switch an active negotiated connection's wire version. Do not relaunch and resend an accepted task as part of rollback.

Stages 1, 2A, 2B and the stage 3 implementation are now present in the workspace.
The validation report distinguishes exercised contracts from remaining native
and provider-authenticated interoperability checks. Stage 4 remains a future
rollout decision for CLI/TUI clients. The macOS Auto default is implemented
with negotiation-only fallback, explicit overrides and no automatic task resend.
The existing SDK pin remains unchanged.
