# ACP v2 implementation and validation

This change implements the reviewed ACP v2 Preview plan in both directions.
The protocol baseline is the vendored official **schema-v2.0.0-beta.4**. Client
connections in macOS default to Auto (prefer v2), with per-agent/project v1
and strict v2 overrides. CLI/TUI defaults remain v1. The agent accepts v1 and v2
on one stdio entry point. The Python ACP SDK dependency remains unchanged because its published
experimental v2 types do not match this Preview baseline.

## Implemented scope

| Area | Delivered behavior |
| --- | --- |
| Shared protocol | Strict version selection and JSON-RPC framing; schema validation; object-valued capability markers; credential redaction; separate v1 and v2 encoders |
| Client | Opt-in v2, bounded v1 fallback with restored capabilities, insertion acknowledgement separated from foreground completion, explicit cancellation and uncertain-outcome handling |
| Retained state | Per-session message replacement/chunks/null clearing, metadata patches, tool upserts and content chunks, plans, compaction records, base64 display terminals, nested child ownership and mutation restrictions |
| Recovery | Resume and replay markers, current-state synchronization, original submission keys, explicit same-session retry, optional private SQLite outbox; no automatic resend of uncertain work |
| Agent | All seven baseline session operations, durable session metadata/history, atomic message/key insertion, restart deduplication, ordered held prompts and coalesced retries, semantic error states and unique tool IDs |
| Task ownership | Foreground cancellation and join, close stopping owned work and descendants, permission cancellation, independent background task handles and capability-gated item cancellation |
| Desktop service | Authoritative response events, typed boolean configuration, persistent outbox, session/item controls, continued connection while background work remains |
| Desktop host tools | Authenticated loopback HTTP MCP bridge with the native approval flow and project-path checks; removed v1 host methods cannot cause side effects on v2 |
| TUI | Replacement-aware response and child rows, display terminal output, plan updates, attributed child activity and advertised cancellation commands |
| macOS | Saved Auto/v1/strict-v2 policy per agent/project; protocol-aware setup checks; actual negotiation badges and fallback explanation; safe session switching; typed config toggles; child transcripts, terminals and foreground/background controls; Swift regression tests added |
| Diagnostics and rollback | `superqode acp doctor AGENT --live --protocol-version 2 --json`; requested/negotiated version reporting; server `--protocol-version auto|1|2` |

The older inline handshakes and `AgentStreamClient` stay explicitly v1. The SDK
connection manager uses the primary client when the v2 opt-in is selected.
Optional agent-side client-supplied MCP transports, additional roots, custom
system prompts, remote transports, forks, steering and draft extensions are not
advertised. The generic background-task API advertises cancellation only when
the server owns an actual task handle. Normalized delegated-agent events are
exposed as children; unsupported child cancellation is not advertised.

## Executed checks

The implementation was made on workspace commit
`b7458b90569dac331acf32a9d8e7aa50080c8c5b` (engine 2.32.3). The newer upstream
snapshot was integrated before publication: the ACP commit was rebased onto
`61d292f0628141be66332efcd9c0ee30161d6ffd` (engine 2.33.3), preserving the newer
Factory, onboarding, model-control and native layout changes.

- Final integration regression run on the rebased main tree: **1,335 passed,
  5 skipped**, covering ACP,
  desktop service, TUI smoke/resource lifetime and CLI/environment references.
- Subsequent ACP, TUI and CLI reference regression run after the display changes:
  **774 passed, 2 skipped**. These runs overlap; their counts must not be added.
- Focused v2 suite after the final cancellation and client restriction fixes:
  **48 passed**. It uses real stdio subprocesses as well as deterministic state and scheduling checks.
- Final focused v1/v2, desktop setup and client/server regression run:
  **141 passed, 1 skipped**.
- Ruff lint, public documentation style and whitespace checks passed.
- Wheel build succeeded and included the vendored schema and v2 implementation.
- The actual `superqode serve acp --spec ...` command completed a synthetic,
  model-free prompt and resumed its durable session after process restart.

An additional integration run for the upstream Pydantic Coder catalog/setup and
Factory onboarding passed **20 tests**, with **4 isolated-runtime tests skipped**.
The 2.33.3 wheel was built and checked against the integrated source.

The macOS protocol-control follow-up adds **16 passing policy contract tests**
and a final targeted run of **58 passing tests** covering setup, protocol
selection, session continuity and CLI documentation. These overlap the broad
suite. The checks exercise explicit Auto/v1/strict-v2 selection, negotiation-only
fallback, failure without resend, protocol-aware setup IPC, live negotiated
metadata, fresh-session handoff on a changed policy, and preservation of an
existing v1 session under unchanged Auto.

All eight changed Swift app/test files passed Swift grammar parsing. Native
XCTest coverage was added for preference persistence/isolation, readiness
invalidation, actual-version badges and foreground/background presentation.
Native compilation and live interactions are reserved for the user's Mac;
grammar parsing is not a replacement for that build. The wheel was rebuilt and
verified against the current protocol and desktop-service source. See the
[macOS protocol guide](acp-macos-protocols.md) for the machine-check steps.

The focused suite verifies busy-input ordering/coalescing, insertion before
acknowledgement, completion before acknowledgement delivery, replay boundaries,
restart key retention, child isolation and nested ownership, cancellation before
the execution coroutine starts, v1 routing without initializing v2 storage,
context-safe v1 stream ownership, actual CLI prompts in both versions,
cancellation during approval, new prompts arriving while cancellation or close
is finishing, per-item task ownership, MCP authentication/path/approval controls, typed booleans, and UI
replacement without losing interleaved tool rows. CI runs these tests; the
existing macOS workflow also runs the new Swift tests and native build.

## Upstream compatibility kit

The upstream [ACP TCK](https://github.com/agentclientprotocol/acp-tck) was pinned
to commit `7c71c4d1af0994e73bdc100c9f7f6b98f2319cda` (0.5.0), using an isolated
Python 3.14.8 environment. Its vendored schema revision is
`3ea94133bb4e7cfdb1105df75660ff83e66acf62`, the older alpha.16 unstable schema.
It supplements our beta.4 payload validation; it does not replace it. The kit
describes itself as experimental and does not issue official certification.

| Target | Protocol | Test results | TCK verdict |
| --- | --- | --- | --- |
| Real dual-version transport with deterministic harness fixture | 2 | 175 passed, 140 skipped, 0 failed | Conformant |
| Actual `superqode serve acp`, builtin synthetic harness | 2 | 142 passed, 173 skipped, 0 failed | Conformant |
| Deterministic fixture and actual CLI, separate runs | 1 | Each: 63 passed, 86 skipped, 1 advisory failure | Conformant; no mandatory/capability failures |

The v1 advisory failure is **ACP-SESSION-004**: the existing agent accepts a
client-supplied stdio MCP configuration without connecting that MCP server to
the harness. This baseline gap is explicitly excluded from v2 advertisement.
Skipped checks include unsupported optional features and cases the synthetic
model cannot trigger. The deterministic fixture exercises slow cancellation and
child traffic that the passthrough provider does not generate.

After the final cancellation-race change, the selected prompt, cancellation,
idempotency and replay checks were repeated: **57 passed, 33 skipped,
225 deselected, no failures**. A filtered TCK run leaves other requirements
untested and is not a separate whole-suite conformance verdict. The final
admission/cancellation change also passed a targeted TCK rerun: **20 passed,
11 skipped, 284 deselected, no failures**. Machine-readable run summaries are retained in [the validation artifact](acp-v2-validation.json).

To reproduce the deterministic runs from the repository root, install the pinned
TCK, then run each protocol separately with a scratch working directory and a
fresh ledger:

```bash
uv tool install --python 3.14 \
  git+https://github.com/agentclientprotocol/acp-tck@7c71c4d1af0994e73bdc100c9f7f6b98f2319cda

acp-tck --protocol-version 2 --agent-cwd /tmp/acp-work \
  --cancel-prompt slow --subagent-prompt child --report-json /tmp/acp-v2.json \
  -- /absolute/repo/.venv/bin/python \
  /absolute/repo/tests/fixtures/acp_v2_agent.py /tmp/acp-work/v2.sqlite3
```

Create `/tmp/acp-work` first. Repeat with protocol 1 and another ledger/report
path. For the production entry point, replace the command after `--` with
`/absolute/repo/.venv/bin/superqode serve acp --spec /absolute/harness.yaml`.
Use a builtin-runtime harness with `model_policy.primary: synthetic/passthrough`
for a run without accounts or provider calls. Keep `SUPERQODE_HOME` in a scratch
directory so discovery and state do not depend on the developer's own sessions.

## External adapters and remaining rollout gates

| Adapter | Exact release | Observed result |
| --- | --- | --- |
| Claude Agent ACP | `@agentclientprotocol/claude-agent-acp@0.113.0` | Initialized and negotiated protocol 2 |
| Codex ACP | `@agentclientprotocol/codex-acp@2.12.1` | Launch reached Codex, then failed because the environment's Codex state directory was read-only; protocol compatibility was not established |
| V1-only agent | Deterministic fixture using the installed official SDK | V2 request fell back through one fresh v1 connection; normal prompts worked |

Adapter initialization checks sent no model prompt and performed no login.
Provider-authenticated prompts/recovery in those adapters, installed Zed and
JetBrains build compatibility, and a native macOS build/UI session remain
external rollout checks. Swift source and tests are included, but could not be
compiled in this Linux environment. The optional Pydantic Coder runtime exists
in the integrated upstream snapshot. Catalog/setup tests passed; the four
provider/runtime integration tests still require its isolated interpreter. V1
compatibility remains the intended path.

ACP is not an operating-system sandbox. Desktop host MCP tools retain the
existing host approval/path policy; an external agent's own tools still follow
that agent's permission and sandbox policy. A successful handshake or TCK run
does not establish that every provider and editor combination is safe.

Use the opt-in controls in the [ACP command reference](../cli-reference/acp-commands.md).
Rollback restricts future connections to v1. It never changes the wire version
or automatically resends accepted work on an active connection. The macOS Auto default is now implemented; a broader CLI/TUI default change
remains separate. The [macOS protocol guide](acp-macos-protocols.md) covers the
completed controls and the live checks reserved for your machine.
