# Upstream TUI and theme review: 11 October 2026

Pi's released version and the Awesome Pi Themes collection have not changed
since our theme review. The useful new work is schema validation, terminal
input behavior and runtime reliability. SuperQode 2.13.0 already covers live
workspace preview, appearance settings, theme favorites, automatic pairs,
customization, the guided task and reviewed diagnostic export.

The next improvements should make configuration and terminal behavior easier
to diagnose, and make connections and task reviews easier to control.

## Baselines and dates

The SuperQode baseline is version 2.13.0 at `4eed5b33c5a081533bc707a103a7e280d4df6583`.
Public release metadata, pinned source files and commit comparisons were fetched
directly from GitHub. Cached search results showed older releases, so they were
not used to establish the current versions.

| Project | Latest release verified | Source examined | Change since our review |
| --- | --- | --- | --- |
| [Pi](https://github.com/earendil-works/pi/releases/tag/v1.1.0) | v1.1.0, 7 October | `ea448f454af474f3e2fe9733b331e17b0662f5d6` | Same released baseline; 22 commits ahead of it, including eight dated 10 October. |
| [Awesome Pi Themes](https://github.com/isashi/awesome-pi-themes/blob/a268b1aca442d348705e7733dc3db9af927079e0/package.json) | 1.2.19 | `a268b1aca442d348705e7733dc3db9af927079e0` | Identical to our pinned collection: 71 palettes. |
| [Hermes](https://github.com/NousResearch/hermes-agent/releases/tag/v0.21.6) | v0.21.6, 8 October | `0aa764feddf00aed631019763ef777d38faf4335` | Frontend unchanged since 8 October; gateway and CLI changes on 10 and 11 October include prompt-edit safety, reasoning retention and update-channel behavior. |
| [OpenCode](https://github.com/anomalyco/opencode/releases/tag/v1.19.0) | v1.19.0, 11 October | Release notes | New TUI update controls; installation is explicit rather than automatic. |

Our previous theme comparison used released Pi v1.1.0. Changes relative to that
tag include work from 8 and 9 October, not only work after our 10 October appearance
review. That review records a date rather than an exact upstream commit/time;
the recent-history window above therefore starts at 10 October 00:00 UTC.

## Pi's changes and their relevance

| Upstream change | What it means for SuperQode |
| --- | --- |
| Published settings and theme schemas, with stricter theme validation, 8 October. Unknown theme properties and color roles now fail validation on unreleased `main`. | Publish editor-addressable schemas for exported themes and appearance preferences. Add an explicit compatibility report for current Pi; retain supported SuperQode extension data. |
| Hardware cursor mode uses the native terminal cursor without also drawing an inverse-video caret. | Consider a cursor preference with IME and selection checks. Our appearance screen currently exposes spacing, animation and icon preferences, rather than cursor or mouse policy. |
| Nested-worktree context discovery handles symlinked `AGENTS.md`, 9 October. | Add this specific case to project-context acceptance checks. File references and the guided context attachment already handle project paths; this upstream fix does not by itself prove a SuperQode bug. |
| MCP callback issuer validation rejects an issuer when authorization metadata was unavailable, 10 October. | SuperQode already rejects missing or mismatched expected issuers in `mcp/oauth.py`. Keep this as a regression contract; it is not a missing security control in the inspected checkout. |
| Durable scheduling bounds ownership indexes and avoids repeatedly traversing every live task, 10 October; remote codemode sandbox support also landed. | Benchmark long-lived WorkOrder/worker workloads before adapting scheduler ideas. These are runtime changes, not new theme features, and do not establish a performance advantage over SuperQode. |

Sources: the [pinned changelog](https://github.com/earendil-works/pi/blob/ea448f454af474f3e2fe9733b331e17b0662f5d6/packages/coding-agent/CHANGELOG.md),
[release-to-main comparison](https://github.com/earendil-works/pi/compare/v1.1.0...ea448f454af474f3e2fe9733b331e17b0662f5d6),
[theme schema](https://github.com/earendil-works/pi/blob/ea448f454af474f3e2fe9733b331e17b0662f5d6/packages/coding-agent/schemas/theme.schema.json),
and [settings reference](https://github.com/earendil-works/pi/blob/ea448f454af474f3e2fe9733b331e17b0662f5d6/packages/coding-agent/docs/settings.md).

## Theme compatibility measured here

The current Pi dark and light documents both import successfully into SuperQode.
Their names were changed for the probe to avoid reserved built-in names.

| Check | Result |
| --- | --- |
| Current Pi dark/light documents against Pi's new schema | Both valid. |
| Current Pi dark/light documents through SuperQode's importer | Both valid. |
| Our 71 catalog documents through SuperQode's importer | All valid. |
| The same catalog documents against Pi's unreleased strict schema | 70 valid; `codex-slate` rejected for extra color roles. |
| Catalog `$schema` references | All 71 still reference the previous schema path, which was removed on Pi `main`. |
| SuperQode theme discovery after normal theme-bridge initialization | 87 distinct choices, including six classified as light. |

`codex-slate` contains additional roles for its status line, links and Python
mode. SuperQode preserves these as extension data and reports them without
executing upstream extensions. Pi's stricter schema rejects those fields under
`colors`. This is an interoperability difference, not an import failure in
SuperQode. The [original palette](https://github.com/isashi/awesome-pi-themes/blob/a268b1aca442d348705e7733dc3db9af927079e0/themes/codex-slate.json)
and the [new schema](https://github.com/earendil-works/pi/blob/ea448f454af474f3e2fe9733b331e17b0662f5d6/packages/coding-agent/schemas/theme.schema.json)
show the difference.

The useful next feature is a compatibility panel with two explicit export
targets: SuperQode native JSON and Pi-compatible JSON. Show which fields would
be omitted from the Pi export, retain the original/native document, and include
a working schema reference in generated files. The current customizer exports
SuperQode native JSON; it does not claim a Pi export format.

The probe validates documents and parsing. It does not exercise every theme in
a mounted UI, certify a live Pi installation, or measure rendered readability.
Those concerns remain covered by SuperQode's separate palette and TUI tests.
The schema snapshots, probe results and source manifest are saved locally in
`validation/upstream-dx-2026-10-11/`; that directory is ignored by Git.

## Other useful developer-experience references

Hermes' current TUI documentation describes an immediate startup surface,
queued input before initialization finishes, a dock for active workers and
background processes, session switching, mouse tracking presets, and terminal
setup helpers. Its skins can also customize prompts and activity labels. These
are useful design references, but the inspected frontend history does not show
new implementations after 10 October. See its [pinned TUI guide](https://github.com/NousResearch/hermes-agent/blob/0aa764feddf00aed631019763ef777d38faf4335/website/docs/user-guide/tui.md)
and [skin guide](https://github.com/NousResearch/hermes-agent/blob/0aa764feddf00aed631019763ef777d38faf4335/website/docs/user-guide/features/skins.md).

Hermes v0.21.6 also describes model favorites, quota visibility and review-scope
controls, primarily for Desktop. Its release explicitly leaves Desktop and
Termux bundles on their preceding versions. Those statements should not be
presented as newly released Hermes TUI features. [Release notes](https://github.com/NousResearch/hermes-agent/releases/tag/v0.21.6).

Hermes' backend has fresh changes on 11 October. Deep prompt edits now count
the durable user turns represented by merged/archived message rows and support
an explicit deep-truncation confirmation. The captured head intentionally logs
a warning rather than enforcing refusal for one release; enforcement is planned
for a later release. This is not a new frontend confirmation dialog.
[Verified rollout commit](https://github.com/NousResearch/hermes-agent/commit/10cf19374542c7a9bf0a8b5b144c9105adf09162).

Its steering/branching fixes also preserve reasoning metadata, including
`reasoning_content`, and adjust replay handling around tool/steering messages.
These are valuable session-continuity contracts for our different harnesses.
[Verified reasoning commit](https://github.com/NousResearch/hermes-agent/commit/df3c21400d598684be57e2229d85e2270baf6031).
CLI changes on 10 and 11 October further distinguish stable/main update channels,
an ahead or offline source checkout, and rate-limited update lookups.

OpenCode v1.19.0 makes `/update` an explicit installation/major-upgrade action.
SuperQode already has a background `:update` check and an installation-aware
`superqode update` CLI. A possible enhancement is one update panel with release
notes, install guidance, and session/draft recovery before restart.
[OpenCode release](https://github.com/anomalyco/opencode/releases/tag/v1.19.0).

## Confirmed local recovery defect

The comparison led to a concrete SuperQode finding in
`src/superqode/app/mixins/helpers.py::_perform_rewind`. After a persistent-session
rewind raised an error, the method still trimmed the in-memory transcript,
replaced the draft and emitted a success notice.

A simulated store failure reproduced this: three original transcript records
became zero even though the stored rewind failed. No real session was changed
by the probe. The local fix now returns after reporting the store error, retaining
the transcript and draft. A mounted regression check exercises the command and
verifies the message history, draft, cursor and lack of a success notice.
The change is unreleased.

The follow-up [developer experience verification](dx-findings-verification-2026-10-11.md)
records the implemented command, automation, startup, model-selection, diagnostics
and recovery improvements, together with their validation scope.

Deeper rewind confirmation, branch/archive recovery and steering-context parity
remain separate follow-ups; this small fix does not implement those features.

## Recommended next changes

These are recommendations from the source comparison, not implemented features.

| Priority | Enhancement | Acceptance condition |
| --- | --- | --- |
| P0 | Safe deep rewinds and branch continuity. | Show how many later conversation turns will be removed; offer a recoverable branch/archive; cancellation retains the original session. Failed stored rewinds retain UI state, as fixed here. Test steering/branching across native, SDK and ACP routes with their required context metadata. |
| P0 | Theme compatibility, schema completion and export targets. | Validate against a pinned Pi schema; show the `codex-slate` extension difference and stale references; native export retains all data; Pi export explains omissions and validates. Existing installs remain usable. |
| P0 | An interactive terminal diagnostics page linked from appearance settings and the first task. | Explain detected color depth, NO_COLOR, encoding, modifier keys, clipboard and SSH/tmux signals. Add a short key/paste check. Offer tested cursor/mouse settings and shortcut alternatives; preserve the draft. |
| P0 | A live MCP connections screen. | Open immediately; update individual rows as servers connect or fail; provide login/retry/logout and an explicit cancel action for sign-in. Test a slow server alongside a fast one and cancellation during discovery, browser wait and token exchange. |
| P1 | Model-specific favorites and recent selections, with capability and account-state hints. | Preserve exact provider/model identity and optional effort. Keep unavailable favorites visible with a reason. Separate provider-reported quota information from local estimates. Connection favorites already exist. |
| P1 | Clear review scopes and a compact live-work dock. | Label task/turn, uncommitted and branch diffs explicitly; preserve unrelated work. Summarize workers and background processes with open/stop actions. Task-specific review and steering already exist. |
| P2 | Terminal program-status reporting. | On supported terminals, report working/blocked/finished/failed and distinguish cancellation, without exposing prompts or credentials. Pi's OSC 7501 support is a reference; this requires capability and lifecycle tests. |

SuperQode's MCP backend already connects servers concurrently and exposes state
callbacks. Its TUI currently renders command/status output and reports reload
results after awaiting the connection batch. The proposed screen can use those
existing primitives. This review did not measure an event-loop freeze or prove
that current authentication cancellation fails.

External prompt editing (`Ctrl+E`), connection favorites, queued follow-ups,
explicit steering, session browsing, and update checks are already present.
They should be refined and tested with developers rather than reimplemented.
Voice input and a framework migration have lower priority than the controls
above for the developer trial.

## Scope of this review

Product source was inspected and upstream JSON was validated. The one local
code change fixes the failed-rewind path, with a mounted regression test and
existing TUI smoke/developer workflow checks. Competitor applications were not
installed or benchmarked. Actual SSH/tmux, IME, native clipboard and signed-in
harness behavior still need live acceptance checks.

Use this review with the [appearance workflow review](appearance-workflow-review.md)
and the [earlier Pi comparison](pi-theme-comparison.md). The immediate next patch
should focus on safe rewind/recovery, compatibility diagnostics, terminal
diagnosis and live MCP control, followed by model favorites and review scopes.
