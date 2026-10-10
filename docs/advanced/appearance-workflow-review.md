# Appearance and first-task review: 10 October 2026

These changes are local and unreleased, following the published 2.12.0 baseline.
The version has not been bumped and the changes have not been pushed or published.

## Delivered workflows

| Entry point | Behavior |
| --- | --- |
| `:theme` | Preview the real prompt, retained transcript, diffs, header and notifications. F4 leaves a small control strip; arrows continue previewing. Escape restores the original palette and preserves the prompt draft and selection. Catalog previews do not install files. |
| Gallery filters and Ctrl+S | Explicit Light/Dark filters, favorites, recent choices, and favorite toggling. `:theme next` cycles favorites, installing a catalog favorite when required. |
| Undo / `:theme previous` | Restore the previous selection, including automatic modes and appearance pairs. Remember an explicit startup override when saving a later choice. |
| `:settings` / `:appearance` | Central settings for fixed, automatic, terminal-derived and paired themes; compact spacing; reduced animation; simple status icons. Preview live, save together, or cancel. |
| `:theme customize` / gallery F3 | Edit accent, background, panel and text colors; see requested/rendered contrast; retain the last valid preview; save a copy or export private JSON without overwriting existing files. Editing and cancelling never mutates the source palette. |
| `:trial` | Choose the existing connection flow, validate without inference, attach bounded project context, explicitly submit through the normal coding pipeline, and inspect recorded answers and task changes. Draft replacements are recoverable with `:stash`. |
| `:feedback` | Review a bounded, redacted snapshot and explicitly acknowledge it before a private local export. No automatic upload; no transcript, source, configuration dump or session ID collection. |

The centralized appearance controls follow the organizational approach of
[Pi's settings reference](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/settings.md),
which groups theme and terminal display preferences. This implementation uses
SuperQode's existing palette, diagnostics, approvals, prompt and review systems.
This review does not establish a general performance or quality ranking against Pi.

## Issues caught and fixed

- A catalog preview disappeared from discovery after its temporary registry entry was added.
- The customizer shared token dictionaries with its source theme, allowing a cancelled edit to affect the original. It now edits an independent document; tests compare the entire source and restored palette.
- Feedback checkboxes had zero content height because their one-line layout retained a two-line border.
- Reduced animation initially missed the prompt indicator and focus-resume path.
- Selecting automatic modes or restoring pairs through settings could flatten the selection into one fixed theme. Existing pairs with unusual light/dark assignments now remain editable.
- Quoted file references now expand paths containing spaces, quotes and separators to the intended context file.
- Guiding a lazy ACP/SDK client must distinguish client initialization from an actual route switch. Task completion binds to the submitted route and recorded task baseline; stale diagnostics/results are rejected.
- Result and Activity text now uses semantic palette roles for light/dark readability.
- Workspace plan shortcuts could approve a hidden pending plan from the feedback editor. Modal screens now own their key handling; workspace decisions resume only after returning to the prompt.
- The composer swallowed advertised single-key y/n/a approvals. It now forwards those keys to the shared decision handler before inserting text; actual allow/deny/session decisions restore the saved draft and cursor. Escape retains the existing workflow that rejects the request and cancels the run.

## Validation and limits

Validation was performed locally on macOS, Python 3.13.6 and Textual 8.2.8.
The final keyboard, approval, cancellation, recovery and developer workflow pass
completed with **461 tests passing**, including all **51 appearance and guided
workflow tests**. Earlier broader developer, TUI compatibility and theme passes
completed with **559**, **408** and **348** tests passing respectively; these runs
overlap. The theme pass includes full source-palette immutability checks after
the customizer copy fix. Results below should be read with their scope:

The five theme fields fit the 80×24 viewport with live color swatches; the coding
sample and export path remain scrollable.

| Check | Scope |
| --- | --- |
| Mounted interaction tests | Preview/cancel/draft selection; catalog install; favorites/recent/Undo; nested settings; automatic modes and pairs; customizer contrast/save/export/errors; reduced motion; reviewed feedback export/redaction; context validation; guided submission and recorded review. |
| Existing developer regression tests | Connection navigation, approvals, cancellation, queued prompts, draft restart recovery, session browsing and harness session continuity. Live provider access is mocked or excluded. |
| Real terminal probe | **84 checks passed** in macOS PTYs: xterm-256color at 80×24 and screen-256color at 120×40, including light/dark reports, gallery/workspace preview, settings, feedback, guided-task screens, Escape, focus, paste, resize and clipboard sequence emission. Host clipboard writes were disabled. |
| Visual inspection | All six new/updated screens captured at 80×24, 120×40 and 58×20 in light and dark palettes. The smaller modal bodies scroll; action controls remain visible. The full-interface trial baseline remains 80×24. |
| Responsiveness probe | All existing budgets passed at 80×24 and 120×40. These are local headless timings, not remote latency measurements. |
| Package verification | Built a local wheel and matched all 775 Python source files. All five entry screens opened from its extracted package, retaining drafts and showing all 83 catalog choices; nine approval/cancellation regression tests also passed against that package. Existing installed dependencies were used. This is not a fresh network installation or a published release. |
| Static gates | Ruff lint and format, public documentation style and whitespace checks passed. New tests are included in keyboard, cross-platform connection and release gates; those updated remote workflows have not run yet. |

Actual SSH transport, a real tmux server, Windows/Linux terminal rendering,
native clipboard behavior, and signed-in vendor/model accounts still require
hands-on validation. Environment-flag tests cover SSH/tmux diagnostic metadata;
the screen terminal profile is not a tmux session. An offline configured check
does not verify quota, entitlement, tool support or remote cancellation. The
first explicit task provides that route's initial account/inference evidence.

Before distributing a new release to participants, use the
[hackathon guide](../getting-started/hackathon.md) for a short live task, one
approval and rejection, cancellation, and reopening the session in each intended
terminal/connection environment. Review exported feedback before sharing it.
