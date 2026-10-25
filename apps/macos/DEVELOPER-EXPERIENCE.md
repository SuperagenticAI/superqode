# Native developer experience: source review and build plan

Reviewed 25 October 2026 against SuperQode checkout `4dcac5c`, with the run-history
changes in this working draft. This is source analysis, not a hands-on competitor
usability study. SwiftUI and AppKit provide useful integration points; writing in
Swift alone does not establish better responsiveness or usability.

## Implemented in this draft

### Evaluation and held-out comparison

Evaluation results now include a native task comparison inspector for every
candidate against the baseline. The same inspector presents optimizer held-out
results. Search by task ID and filter regressions, improvements or incomplete
evidence; expand task rows to inspect recorded reasons. Reported cost and duration
deltas remain Unknown when the input is unknown or invalid.

The Python engine derives this read-only projection for saved runs and imported
reports, including older raw/result/job-result wrappers, without modifying stored
artifacts. Task matching preserves string/numeric identity types. Duplicate IDs,
missing tasks, mismatched splits, missing declared coverage and contradictory
evaluator records are flagged. Non-empty-response smoke checks cannot earn a
task-quality improvement label. Reason previews and the total projection are
bounded; complete evidence remains available in the original report.

This inspector does not authorize adoption or change the existing backend gates.
Imported reports remain self-reported evidence, not authenticated benchmarks.
The [feature checklist](FEATURE-PARITY.md) records the broader coding and harness
engineering gaps, including the remaining quality-gate and recovery work.

### Command palette

Command-K opens a native searchable palette for common actions, twelve recent
runs in the current project, and eight recent projects. Search matches title,
description and aliases, ignores case/accents, and prioritizes title matches.
Up/Down navigates results and Return chooses an enabled action. Disabled actions
remain visible with their prerequisites. Escape or Close restores the previous
first responder; selected actions execute after dismissal so connection sheets
and file choosers do not overlap the palette.

The native Open Project, New Task, navigation, Back, Refresh, Export and learning
menu items use the same command catalog and execution handler. Availability is
rechecked at execution time. Opening the palette does not start an agent, install
a provider, or modify Git state. Recent runs are scoped to the current project.
Eleven XCTest cases cover matching/ranking, selection boundaries, unique IDs and
shortcuts, project scoping, availability and deferred menu execution. These tests have not run here; a
Swift grammar parse is only a syntax check, not compilation or UI validation.

### Run activity

Completed runs could stop loading after the first 500 activity events. The engine
now returns explicit continuation metadata. The native client drains unread pages
even after completion, validates advancing cursors, and limits each refresh to four
pages so input and selection changes can proceed between requests. Replies from a
previous selection remain guarded by the selection generation.

Cancellation can become terminal before the worker's output watcher has drained.
The engine snapshots writer ownership with each page, so the client keeps polling
until that writer closes. A failed fetch retains the cursor and exposes Retry
instead of silently abandoning unread activity or showing repeated alert dialogs.

The existing 1,200-event presentation window stays bounded. The UI now explains
that older events are available through Export; this is not an unlimited in-app
history viewer. Export uses the same validated paging contract. Follow scrolling
tracks the latest sequence instead of the event count, which stops increasing
when the rolling window fills.

Regression coverage includes empty, exact-full, multiple and interleaved pages,
all terminal statuses, and completion while activity is unread. Native XCTest
coverage includes old-engine fallback and malformed/non-advancing cursors. Python
checks can run on Linux; Swift tests and interactive behavior require the existing
macOS CI job or a Mac with Xcode. Do not infer native validation from Python tests.

## Source comparisons

The following references point to actual implementation, not product feature
lists. These are patterns to evaluate, not evidence that a competitor is better
in every workflow. Reuse ideas with a native implementation; do not copy source
without reviewing its license.

| Workflow | Competitor source | SuperQode opportunity |
| --- | --- | --- |
| Session navigation | [T3 sidebar sections](https://github.com/pingdotgg/t3code/blob/5b35402623d7d1d88eaa472807272a6c2e78012a/apps/web/src/components/Sidebar.logic.ts#L117); [Omnigent stable active-session sorting](https://github.com/omnigent-ai/omnigent/blob/0862ae65df7617217efac2b43a4de51701a23268/web/src/shell/sidebarNav.ts#L291) | Back currently stores section names, and composer drafts are keyed by project. Introduce a destination containing project, conversation, section and inspector selection; store drafts by conversation. Keep the selected session stationary while events arrive. |
| Review scope | [T3 DiffPanel](https://github.com/pingdotgg/t3code/blob/5b35402623d7d1d88eaa472807272a6c2e78012a/apps/web/src/components/DiffPanel.tsx#L254); [Omnigent diff viewer](https://github.com/omnigent-ai/omnigent/blob/0862ae65df7617217efac2b43a4de51701a23268/web/src/shell/MonacoDiffViewer.tsx#L49) | Bring project Git review and checkpoint review together with explicit This turn / Uncommitted / Branch scopes. Add changed-file and hunk navigation, followed by line-range feedback attached to a prompt. Never imply ordinary workspace diffs prove agent ownership. |
| Command access | [T3 palette state](https://github.com/pingdotgg/t3code/blob/5b35402623d7d1d88eaa472807272a6c2e78012a/apps/web/src/components/CommandPalette.logic.ts#L71); [Omnigent command/session search](https://github.com/omnigent-ai/omnigent/blob/0862ae65df7617217efac2b43a4de51701a23268/web/src/shell/CommandPalette.tsx#L182) | Use one typed command registry for native menus and a keyboard-searchable palette. Include recent sessions, project switching, New Task, Changes and Terminal. Availability and shortcuts should come from the same definitions. |
| Streaming and reading | [T3 follow behavior](https://github.com/pingdotgg/t3code/blob/5b35402623d7d1d88eaa472807272a6c2e78012a/apps/web/src/components/chat/useTimelineFollow.ts#L119); [Omnigent anchor restoration](https://github.com/omnigent-ai/omnigent/blob/0862ae65df7617217efac2b43a4de51701a23268/web/src/components/chat/Transcript.tsx#L510) | Pause following when the reader scrolls upward, show Jump to latest, and restore an anchor per conversation. Isolate frequently changing transcript state from project navigation and composer state. |
| Background attention | [T3 Dock badge](https://github.com/pingdotgg/t3code/blob/5b35402623d7d1d88eaa472807272a6c2e78012a/apps/desktop/src/ipc/methods/notificationBadge.ts#L20); [Omnigent notification routing](https://github.com/omnigent-ai/omnigent/blob/0862ae65df7617217efac2b43a4de51701a23268/web/electron/src/main.js#L4508) | Add a session-attention coordinator, optional system notifications and a Dock badge. Notification activation should restore the correct session, not just bring the app forward. Avoid private prompt/code text in notification previews by default. |

The public [Codex app-server implementation](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/app-server/src/lib.rs#L36)
is backend/protocol infrastructure. It does not establish public availability of
the Codex App desktop UI source, so this review does not claim a source-level
comparison of that UI.

## Recommended build order

1. **Session destinations and recovery.** A → B → Back restores the exact session,
   unsent draft and review selection. Recover source-editor drafts after a crash
   with the base revision, and provide Compare / Copy / Save As for conflicts.
   This is foundational for notification routing and multiple windows.
2. **Native command palette: validate the implemented draft.** Search commands
   and recent runs from the keyboard. Verify Escape returns focus to the original
   editor/composer, disabled commands explain their prerequisites, and menu and
   palette actions behave identically. Follow up with file search and a settings
   action once the basic lifecycle is proven on a Mac.
3. **Scoped review inspector.** Display the review scope next to every stage,
   restore and feedback action. Accept tracked deletions and preserve unrelated
   staged/unstaged edits. Reuse checkpoint evidence where it supports the scope.
4. **Reading-position-aware transcript.** Incoming text never moves a user who
   is reading older content. History loading preserves the visible anchor. A
   persistent message projection should keep complete answers independently of
   the bounded low-level activity buffer.
5. **Native background attention and reopening.** Deduplicate approval/completion
   events; route clicks and session URLs through the destination model. Ask for
   notification permission when enabling the feature, not during first launch.
6. **Multiple windows and project-specific layout.** Use scene restoration and
   project/session destinations for independent windows. Keep engine/workspace
   ownership correct across them before exposing concurrent write operations.

Other native advantages to develop deliberately: accessible labeled controls,
VoiceOver order, predictable first-responder behavior, file navigation through
NSWorkspace, standard text services, window restoration and keyboard consistency.
Existing NSTextView editing, native menus and the SwiftTerm terminal are useful
foundations. Measure composer latency during streaming, session switching with
large histories, memory use, and full keyboard-only task completion on a real Mac.

In particular, `Workspace` is one `ObservableObject` with many published fields,
and many screens observe it through `EnvironmentObject`. Publishing transcript
activity can therefore invalidate views whose project/navigation state did not
change. The separate `DraftStore` already demonstrates a smaller ownership
boundary. Extend that approach to session transcript and attention stores, and
profile before and after; avoid assuming a wholesale state-framework migration
will improve performance without measurements.

## Validation before shipping

For the subsequent evaluation comparison inspector, 113 focused Python checks
pass, including 85 comparison cases, long-run paging and package inventory. A
broader desktop check passed 149 cases before the last compatibility/size-limit
refinements. All 32 Swift source/test files pass grammar parsing. Ruff lint/format,
public documentation style and whitespace checks pass. Grammar parsing does not
establish Swift type correctness or native UI behavior.

Local Linux validation for this draft: 89 Python tests passed across desktop
paging, service, connection workflow, queue and remote streaming suites, including
27 paging regressions. Changed Python files pass Ruff lint/format checks; public
documentation style and Git whitespace checks pass. Seven native paging XCTest
cases are added but were not compiled or executed here because Swift/Xcode is
unavailable. The items below remain required native release validation.

For the subsequent command-palette change, a Swift grammar parser checked all
31 source/test files with no syntax findings. It does not type-check SwiftUI or
validate focus and keyboard dispatch. Eleven additional command XCTest cases are
present for macOS CI; they have not been executed locally. The 28 Python packaging
inventory and event-paging checks also pass for this change; those checks do not
exercise the Swift command palette.

- Run `swift test --build-system native --package-path apps/macos -c release` on
  macOS; the existing Native Mac app workflow runs this command.
- Open saved and imported evaluations and optimizer held-out reports. Switch
  candidates, filter/search tasks and inspect unknown cost, smoke checks,
  regressions and incomplete grading. Check narrow window layouts, scrolling,
  selection, keyboard access and VoiceOver on a Mac.
- Open Command-K from the composer and source editor. Search, navigate, cancel,
  and confirm focus returns without changing the draft or document. Test an IME
  candidate selection with Up/Down and Return, plus VoiceOver navigation.
- Choose Connect, Open Project, a recent project and a recent run. Verify only
  one presentation appears and current availability is respected. Compare the
  matching menu actions. Search with no results and while the engine is offline.
- Reopen a completed run with more than 500 events and verify its tail arrives.
  Repeat beyond 2,000 events to cross the four-page refresh budget.
- Switch sessions while pages are loading; no reply may appear in the new session.
- Cancel while output is buffered, then verify the last events arrive. Interrupt
  a history fetch and verify Retry resumes without duplicate or missing activity.
- Keep Follow on beyond 1,200 events, then turn it off and read older text.
- Export and confirm that the file contains all events without duplicates,
  including those omitted by the presentation window.
- Exercise keyboard focus, VoiceOver, light/dark appearance, window closure and
  reduced-motion settings. Source inspection cannot establish these outcomes.

None of these planned features is claimed implemented merely because it appears
in this document. Broad-release preservation and worker-recovery findings from
the earlier audit still need their own fixes.
