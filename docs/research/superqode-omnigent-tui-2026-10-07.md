# SuperQode and Omnigent: terminal experience and adoption priorities

Review date: 7 October 2026.

SuperQode snapshot: `a96da84887ecabbed071f3fb1c8d72fd2ac52504`.
Omnigent snapshot: `36c94573f86d21410b61ce535e793448131a4784`, downloaded
for this review. This differs from the earlier architecture review's snapshot.

This is source and test inspection, not a hands-on usability study. No live
Omnigent server, authenticated vendor agent, comparative latency test, or
terminal rendering comparison was run. Existing tests were inspected, not run.
Absence claims below concern reviewed paths, not every possible integration.

## Assessment

SuperQode has a substantial repository workspace TUI already. Omnigent's
most useful transferable interactions are visibility into child sessions,
parent-visible approval routing, and a common overview across sessions and
terminals. Adopt those within SuperQode's existing design system and delivery
workflow.

Omnigent has two separate terminal experiences: its own prompt-toolkit chat
REPL and vendor-native TUIs launched through wrappers. Its browser/desktop
terminal surfaces are another experience again. Do not attribute vendor TUI
features or browser collaboration capabilities to its own REPL.

## Comparison

| Area | Omnigent inspected behavior | SuperQode inspected behavior | Recommended change |
| --- | --- | --- | --- |
| Main interaction | Chat REPL, compact toolbar, toggleable tool detail | Textual workspace with repository sidebar, status, compact tool activity | Keep the workspace; improve access to consequential state |
| Overview | Ctrl+O overlay selects main session, child sessions, and terminal targets; renders metadata and event detail | Activity, status, agent/context panels, WorkOrder inspector, diagnostics | Add one Run Overview linking those existing surfaces |
| Child agents | State tree and keyboard selection; navigation into child sessions and back to root | Delegation capabilities exist; reviewed sidebar primarily exposes the connected agent | Add a live task/agent tree with status, blockers, last activity, and evidence links |
| Approvals | Once/session/refuse prompts; mirrored child requests resolve against the child's session identity | Inline and modal approvals; rich permission-preview widgets also exist | Add a persistent approval inbox spanning active work; unify preview and receipt behavior |
| Saved sessions | Keyboard resume picker, pages, metadata and last-message previews | Searchable paginated Session Browser, rename, availability and continuity descriptions | Preserve existing browser; extend project grouping and active-session visibility |
| Input | History search, multiline input, attachments, abstracted large pasted blocks | Draft recovery, attachments, context preview, queue editing/reordering, steering | Add inspectable collapsed paste blocks; make queue/steer controls visible |
| Model/context | Model and effort commands, context usage indicator, explicit compaction | Model/harness controls, context inspection and compaction | Add capability-aware controls and effective-versus-requested labels |
| Local shell | Bang commands; bounded output can be folded into the next model turn | Shell passthrough already exists | Add an explicit Send output to agent action with preview/removal |
| Repository review | Reviewed REPL paths emphasize session/tool visibility | Changes view, task diffs, guarded per-file undo, WorkOrder candidate inspection | Connect changes, tests, acceptance gates and integration into one delivery view |
| Native terminals | Wrapper attachment and terminal inspection; browser has separate reconnect controls | PTY components and terminal facilities exist | Audit actual mounted routes first; add explicit running/stopped/reconnecting states where supported |

## Recommended additions

1. **Run Overview and task/agent tree.** Show root and child identity, runtime,
   current operation, elapsed time, last event, approval waits and completion.
   Link to transcript, tool detail, WorkOrder and terminal. Preserve the root
   draft and viewport during inspection. Unsupported route telemetry must show
   unavailable, not an invented idle/healthy state.
2. **Persistent approvals inbox.** Show which agent is blocked, the exact
   operation, arguments or diff, policy reason and approval scope. Support
   inspection without taking over the composer. Bind approval to current
   invocation evidence and expire stale requests. This depends on fixing the
   underlying approval lifecycle; a better panel alone cannot fix enforcement.
3. **Unified delivery view.** Reuse the existing Changes, Activity and WorkOrder
   components to show candidate patch, recorded test outcomes, acceptance
   checks, review status and integration actions. Bind review to the candidate
   digest and show when later edits invalidate it. Keep ordinary chat diffs
   distinct from a WorkOrder candidate eligible for integration.
4. **Visible queue and steering controls.** Keep existing commands; add a
   compact queue indicator with inspect/edit/reorder actions, and explicit
   Send next versus Steer current actions only on supported routes.
5. **Composer improvements.** Fold large paste into an inspectable block,
   retain exact bytes and allow removal. Offer explicit staging of local
   command output for the next message. Reuse context preview and draft
   recovery instead of creating another attachment store.
6. **Usage and integration evidence.** Present reported/estimated/unavailable
   usage, applicable budget scope, and observed capability status. Show
   requested and effective model/effort separately when the route provides
   confirmation. Readiness is not behavioral certification.
7. **Persistent split editing.** Extend the current modal editor into a
   resizable optional split with retained drafts and file tabs. This is a
   SuperQode workspace improvement, not an established Omnigent REPL advantage.

## Branding and layout

Reuse `design_system.py` and the theme bridge: purple focus/selection, magenta
accent, black background, subtle gray surfaces, existing diamond glyphs and
purposeful animation. Keep amber for waiting/warnings, emerald for successful
checks, and rose for failures. Pair every state color with text or a symbol.
Use themed tokens rather than adding hard-coded component palettes.

One reviewed modal approval path currently uses white/gray borders and buttons;
bring it into the common theme while retaining semantic warning/error colors.

At wide sizes, use the existing sidebar for Runs/Files/Changes, the center for
conversation, and an optional inspector for approvals or review. At 80x24,
show one primary pane and short status counters; open inspection on demand.
Returning from any inspector must preserve draft, cursor and reading position.

## Delivery sequence and verification

First deliver the Run Overview/tree and approvals inbox after governance
receipts work. Next unify delivery evidence and expose queue/steering controls.
Then add composer and split-editor improvements based on measured use.

Acceptance scenarios: a child waits for approval and the parent shows it;
approval resolves only that current request; switching inspection targets
preserves the draft; a stale candidate cannot be approved for integration;
unknown usage stays unknown; a 10,000-message session remains navigable; narrow
resize and SSH/tmux keyboard behavior preserve input. Measure p95 input-to-paint
and selection-to-ready rather than inferring speed from framework choice.

## Sources

SuperQode: [TUI guide](../advanced/tui.md),
[design system](https://github.com/SuperagenticAI/superqode/blob/main/src/superqode/design_system.py),
[theme bridge](https://github.com/SuperagenticAI/superqode/blob/main/src/superqode/app/theme_bridge.py),
[sidebar](https://github.com/SuperagenticAI/superqode/blob/main/src/superqode/sidebar.py),
[Session Browser](https://github.com/SuperagenticAI/superqode/blob/main/src/superqode/widgets/session_browser.py),
[Activity](https://github.com/SuperagenticAI/superqode/blob/main/src/superqode/widgets/outcome_screen.py),
[WorkOrder inspector](https://github.com/SuperagenticAI/superqode/blob/main/src/superqode/widgets/workorder_inspector.py),
[permission previews](https://github.com/SuperagenticAI/superqode/blob/main/src/superqode/widgets/permission_preview.py),
[approval dialog](https://github.com/SuperagenticAI/superqode/blob/main/src/superqode/app/mixins/dialogs.py),
[queue/steering/fork/compact commands](https://github.com/SuperagenticAI/superqode/blob/main/src/superqode/app/mixins/slash_commands.py),
[shell dispatch](https://github.com/SuperagenticAI/superqode/blob/main/src/superqode/app/mixins/events.py).

Omnigent, immutable reviewed snapshot:
[REPL and overview](https://github.com/omnigent-ai/omnigent/blob/36c94573f86d21410b61ce535e793448131a4784/omnigent/repl/_repl.py),
[terminal UI host](https://github.com/omnigent-ai/omnigent/blob/36c94573f86d21410b61ce535e793448131a4784/sdks/ui/omnigent_ui_sdk/terminal/_host.py),
[resume picker](https://github.com/omnigent-ai/omnigent/blob/36c94573f86d21410b61ce535e793448131a4784/omnigent/repl/_resume_picker.py),
[child-session overview test](https://github.com/omnigent-ai/omnigent/blob/36c94573f86d21410b61ce535e793448131a4784/tests/e2e/omnigent/test_repl_overview_subagent_visibility.py),
[shell-output context test](https://github.com/omnigent-ai/omnigent/blob/36c94573f86d21410b61ce535e793448131a4784/tests/e2e/omnigent/test_repl_bang_e2e.py),
[browser/native terminal distinctions](https://github.com/omnigent-ai/omnigent/blob/36c94573f86d21410b61ce535e793448131a4784/feature-map/terminals.md).

## Implementation follow-up

The first three additions are now implemented: `Ctrl+O` / `:runs`, the persistent
`:approvals` inbox, and `:delivery` with an existing WorkOrder inspector. The
status strip also links to the existing queue. Scope remains the local session,
reported child-agent state and project WorkOrders; it does not add shared-session
infrastructure or replace vendor-native approval prompts.

Approval resumption now carries invocation, argument-digest and policy-revision
receipts. Changed requests require fresh consent, DENY remains final, and missing
original policy scope blocks resumption. Dynamic MCP tools use the governed
call/result boundary. WorkOrder candidate review remains digest-bound; merge and
rollback are separate, confirmed operations using existing backend checks.

Validation: 345 existing and new focused tests passed, with two optional tests
skipped. A final 25-test run includes two additional checks for corrupt stores
and visible command arguments. Responsiveness checks passed for 10,000-message
histories at 80x24 and 120x40. Offline PTY checks cover xterm-256color and
screen-256color, including opening and closing the overview with draft recovery.
Rendered fixture previews were inspected at both terminal sizes. This evidence
does not establish live vendor-agent or Omnigent usability parity.

Reproduce the TUI-specific checks from the repository root:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -p pytest_asyncio.plugin tests/test_tui_supervision.py tests/test_governed_approval_receipts.py -q
.venv/bin/python scripts/benchmark_tui_responsiveness.py --check
.venv/bin/python scripts/check_tui_terminal.py
```

See the [TUI guide](../advanced/tui.md#runs-approvals-and-delivery) for controls,
refresh intervals, approval scope and delivery behavior. Composer folding and output staging were subsequently implemented; persistent
split editing remains a later recommendation.

### Composer follow-up

Large pastes now fold in place with bounded inspection and removal. Exact text
is expanded only when sending a normal message, and folded payloads recover
through the existing private draft store. Local shell output has an explicit
preview-and-stage action; only the selected or edited page excerpt enters the
next draft. Inspecting or staging does not send a message. Transcript display
and queue previews are bounded while full message evidence is retained.

Validation: 274 affected TUI tests passed, followed by 65 tests covering final
selection, limits and transcript changes. Offline PTY checks verify folding,
draft preservation and navigation in xterm and screen terminal modes. The local
responsiveness probe now exercises a 1,040,000-character paste, bounded preview,
continued typing and large-message display against 10,000-message history.

Reproduce:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -p pytest_asyncio.plugin tests/test_tui_composer_blocks.py tests/test_tui_draft_recovery.py tests/test_tui_image_voice.py -q
.venv/bin/python scripts/benchmark_tui_responsiveness.py --check
.venv/bin/python scripts/check_tui_terminal.py
```
