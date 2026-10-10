# Theme reliability review: 9-10 October 2026

The follow-up audit reproduced and fixed additional theme bugs in the
SuperQode 2.10.1 checkout. The earlier passing tests did not cover these cases.
Each fix has a regression test; this review describes the behavior developers
can expect from the current implementation.

## Bugs fixed

| Developer action | Failure found | Current behavior |
| --- | --- | --- |
| Select an edited catalog theme | The picker attempted installation again and rejected the edit. | Selecting an installed theme applies the developer's version. |
| Reinstall a palette after editing its description | Metadata changes were reported as conflicting colors. | Description changes are retained; conflicting colors still prevent overwriting. |
| Launch or save with deeply nested preferences | JSON recursion could crash theme loading or saving. | Loading falls back with a warning; saving reports the error and retains the file. Preference reads also reject non-regular files and files exceeding 1 MiB. |
| Use a middle-gray terminal background | System mode rejected some gray backgrounds; text on hover/active surfaces could be unreadable. | Surface shades preserve one readable foreground, and hover/active backgrounds participate in contrast validation. |
| Open the picker with an appearance pair | The cursor started on SuperQode rather than the resolved palette. | The current light/dark palette is highlighted. |
| Change terminal appearance with a preview open | The preview stayed stale; repaint hooks omitted other screens. | Repaint hooks run across the screen stack and refresh the preview. |
| Launch `--theme light` in a project containing a file named `light` | Startup treated the project file as JSON before checking the theme name. | An installed name takes priority; `./light` explicitly selects the file. |
| Edit a theme linked from dotfiles | Resolving the link lost its user-directory provenance and disabled hot reload. | File/directory links keep their watch path, including repointed links and atomic replacements retaining size and timestamp. |
| Receive delayed or interrupted terminal color responses | A 100 ms timeout leaked RGB fragments into the composer; unfinished reports could swallow typing and control keys. | Recognized RGB framing survives transport delays, while interrupted headers/payloads recover keys, navigation and paste. Standalone Escape retains its timeout. ANSI reply indices are normalized. |
| Import JSON containing an exceptionally long integer | Python's JSON integer limit raised an uncaught exception. | The CLI reports a theme error and the import dialog stays open with an inline message. |
| Type immediately after startup or use a picker before the delayed focus callback | The sidebar view watcher could focus the hidden file tree, dropping the first composer character or picker key. | The primary screen autofocuses the composer, and hidden sidebar views no longer request focus. |
| Save a palette loaded through a project-file startup override | Only its name was saved, so the next launch could not rediscover it. | Explicit Save installs a native user copy, including palettes in appearance pairs; collisions retain the existing file and preference. The original project file is retained. |
| Switch themes while reading older output on Windows | A pending tail scroll or feedback reveal could execute after a reading lock and move the transcript to the bottom. | Deferred scrolls recheck the reading lock; locking also cancels pending feedback reveals. Deterministic regressions reproduce both callback orderings. |
| Close the UI while a file completion is loading | A late completion could query a composer already removed during teardown. | Results require a running app and mounted composer; the original regression raises `NoMatches`, and the fixed worker exits safely. |

The audit also corrected test isolation. The theme preference path was captured
before tests changed `HOME`, so mounted tests could load the developer's own
installed palettes and alter later gallery expectations. Tests now redirect
that path into their temporary home.

The broader regression run exposed an unreliable connection-return scroll
test. Markdown soft line breaks had collapsed its supposed long transcript
into one paragraph, putting the saved position near a changing viewport
boundary. The test now creates a genuinely scrollable transcript and waits for
the draft layout before saving its position. Both terminal sizes retain the
transcript, draft, runtime and exact reading position in that check.

A model-picker check failed intermittently in broad runs while isolated runs
passed. Additional diagnostics exposed the startup focus race above: typing
could become `raft` instead of `draft`, and a deterministic test found the file
tree focused when the delayed callback was disabled. Primary-screen autofocus
and the hidden-sidebar focus guard remove that initial dependency on the timer. The picker test
also now runs in a temporary project, disables unrelated startup/catalog jobs,
and waits for its model-list worker. It verifies typing during the pending RPC
and immediate Down/Enter selection afterward. Live provider startup remains a
separate validation requirement.

## Validation

Preparing 2.11.0 exposed the deferred-scroll issue above in the Windows CI
matrix. The queued-scroll regression fails against the earlier implementation;
the release fixes the callback ordering before publishing the version tag.
Release validation also settles the initial welcome before capturing a
conversation, waits for appearance refresh completion rather than a fixed
timer delay, and checks late completion results after composer removal.

The pre-release theme audit passed 6,256 tests, with 30 skipped, 24 integration
tests deselected and 139 warnings. The focused theme, navigation, model-picker
and developer-workflow run passed all 330 tests. No failures remain in these
verified runs; the exclusions and terminal/platform limits below remain part of
the release assessment.

The installed core wheel was checked against the source: all 765 packaged
Python modules matched, and the wheel contained the 71 catalog palettes, JSON
schema and upstream license. Its gallery and import dialog were exercised at
80×24 and 120×40; install/apply/save, cancellation, draft retention and repeated
installation of the complete collection passed.

The wheel also passed 556 system-background cases (all 256 grays plus 300 seeded
RGB samples), 5,419 delayed RGB fragmentation cases, 20 interrupted-report
input cases, and native export/import round trips for all 71 catalog themes.
The final watch guard also verifies that launching from the themes directory
does not try to reload built-in palettes as files.
Real macOS PTYs exercised delayed fragments and interrupted headers in addition
to typing, paste, resizing and command routing: 62 checks passed for source,
and the same 62 passed for the installed package. Source and installed-package
results, full regression logs, responsiveness measurements and the strict docs
build are recorded under `validation/pi-theme-implementation/theme-audit-*`.

These checks establish the tested paths, rather than a guarantee that no bug
can occur. Real Windows/Linux terminal appearance reporting, SSH transports
and live provider workflows still need participant testing. See
[Themes](themes.md) for supported behavior and [Hackathon readiness](../getting-started/hackathon.md)
for the broader developer trial.
