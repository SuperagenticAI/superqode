# Native review workspace

macOS public beta 0.1.11 includes Review in the sidebar and command palette.
Release validation includes the native build, Swift and desktop-engine tests,
and native screen smoke checks with local fixtures.

## Choose what to review

- **This turn** reads the selected coding run's sealed local checkpoint. It shows
  the saved before/after workspace states, including changes that occurred during
  that turn. Concurrent terminal or editor changes may be included. It does not
  attribute every change to the agent. Missing or unfinished checkpoints produce
  an explanation; the view does not substitute today's working-tree diff.
- **Uncommitted** lists Staged, Unstaged and Untracked entries. A file with both
  staged and unstaged edits appears twice, with a separate comparison for each
  layer. Index-only changes remain visible even when the working file matches HEAD.
- **Branch** compares the merge base of the chosen local reference with HEAD,
  through HEAD. It includes committed changes. Enter a different branch or commit
  if the default `main` reference is unavailable. Review does not fetch refs or
  include uncommitted edits in this scope.

Choose a changed file and use Previous hunk / Next hunk to navigate. The diff
shows old and new line numbers, addition/deletion markers, file-mode changes and
missing final newlines. Snapshot and file fingerprints identify the reviewed
states; branch reviews also display the actual Git commit IDs.

## Prepare line feedback

Click a line, then Shift-click another line in the same hunk to select a range.
From and Through controls provide a keyboard-accessible alternative. Each note
can select up to 80 rows and 12,000 source characters, with a feedback message of
up to 4,000 characters.

Add to follow-up appends readable feedback to the current conversation's composer
and opens Agent Space. The existing draft is retained. It includes the scope,
path, revision fingerprints, relevant Git/checkpoint IDs, old/new line coordinates
and quoted source. Review the combined message before pressing Send. Adding a
note does not start an agent or modify project files. With no selected run, the
button reads Add to draft and prepares a new conversation instead.

The engine validates the selected snapshot again before attaching feedback. If
the revision changed, Refresh and select the intended lines again. There is no
automatic reassignment of comments to newer source lines. Already appended
feedback continues to describe its original snapshot; the request asks the agent
to inspect the current files before editing.

Unfinished feedback notes are saved with the conversation's draft recovery data,
keyed by snapshot. Reopening that same snapshot restores the note and selection.
Feedback drafts also offers Copy saved note and Discard saved note, including
notes for revisions that are no longer available. Copying a saved note does not
recreate a missing historical diff or authorize an action.

## Stage a reviewed file

Stage reviewed file is available for complete Unstaged and Untracked text entries
when project work is idle. It stages all reviewed changes in that file, including
tracked deletion and executable-mode changes. It does not stage just the selected
comment range or hunk. Historical turn and committed branch comparisons cannot
be staged through this action.

Staging revalidates the file and index baseline, holds the repository's index lock
and writes the reviewed version through a temporary index. Other index entries
and working files are preserved. Normal Git text normalization and configured
clean filters apply. A busy index or failed update leaves the real index intact;
the app does not remove another operation's lock or retry a mutation elsewhere.

## Limits and validation

Lists expose up to 500 change entries and explicitly report truncation. Known
sensitive paths and checkpoint storage are excluded. Symbolic links, submodules,
binary/non-UTF-8 content, files over 1 MB and excessive line counts require review
with other local tools. Text previews are bounded to 5,000 rows; incomplete
previews cannot authorize comments or staging. Reviewing a rename currently shows
its deletion and addition separately.

Automated checks cover separate index/worktree layers, stale snapshots, line
coordinates, sealed checkpoint evidence, literal filenames, deletion/mode changes,
Git normalization, index-lock failure, linked worktrees, content limits and
preservation of unrelated edits. Swift model and session-state checks also cover
draft recovery and preventing delayed feedback from entering another conversation.

Before shipping, run the native package tests and exercise narrow layouts, hunk
navigation, Shift selection, keyboard range controls, saved notes, light/dark and
Increased Contrast appearances, VoiceOver, project switching and both successful
and rejected staging on a Mac:

```bash
swift test --build-system native --package-path apps/macos -c release
```
