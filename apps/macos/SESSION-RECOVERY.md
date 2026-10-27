# Session continuity and draft recovery

Session continuity and draft recovery ship in macOS public beta 0.1.11.

## Moving between tasks

Each conversation has its own composer draft, file attachments and staged-image
references. Follow-up runs in the same conversation share that draft. New
conversation has a separate draft for each project.

Back and Forward restore the selected project, run, page, file, details inspector
and checkpoint selection. Use the toolbar, Command-[ and Command-], or the command
palette. Choosing another destination after Back starts a new navigation path.
Opening a recent project restores its last recorded destination.

The first upgrade imports the old project-wide draft into New conversation once.
It does not place that draft into existing conversations. The old saved source is
retained during migration.

## Returning to the app

SuperQode reopens the last recorded project and destination. It restores local
interface state without starting a task or terminal. Interrupted work is not
automatically replayed. An unavailable project can be selected manually when it
becomes accessible again; its drafts remain in recovery storage.

The transcript remembers whether Follow was enabled and a message-level reading
anchor for each run. Scrolling upward pauses Follow; Jump to latest resumes it.
Restoring a position can load up to four earlier history pages automatically.
If the message is still unavailable, the app offers a clear fallback; earlier
messages can be loaded manually. A reading anchor is not a character or pixel
offset within a long response.

## Recovering file edits

File drafts keep the original text, base digest and edited text. Files includes a
Recovered drafts menu, including drafts for files that were removed from disk.

If the disk revision changed, the app preserves the draft and disables normal
Save until the conflict is resolved. Compare shows the original revision, current
disk text and draft. Copy draft and Save As keep the edited text. Save As refuses
the original file path; normal Save always uses the existing revision check.
Reload explicitly discards the draft after confirmation when edits are unsaved.

Save As exports a copy and retains the recovered draft. Save or explicitly discard
the original draft when it is no longer needed. No automatic merge or overwrite
is performed for changed, missing or renamed files.

## Storage and failures

Recovery is local at:

```text
~/Library/Application Support/SuperQode/Recovery/workspace-v1.json
```

The directory is private to the local user and the recovery file uses permissions
0600. It contains unsent prompts and source text; it is not an encrypted vault.
Image recovery stores references and display names rather than additional image
copies. Missing staged images must be attached again. Credentials and transient
authentication state are not included in recovery records.

Editor changes schedule a save after 350 milliseconds of inactivity. Composer
changes are captured after 300 milliseconds and then schedule a recovery save.
Serialization and autosave writes run on a serial background queue. Navigation
and quitting synchronously save pending composer state and flush recovery.
Typing immediately before a crash can precede the next completed write.

Writes are atomic and capped at 32 MB. The app does not silently evict drafts to
make room. Save or discard unnecessary drafts if the limit is reached. Save
failures remain visible, with a retry action and a quit warning.

Unreadable, oversized or unsupported saved files are preserved and block new
writes. Reset recovery explicitly preserves the previous file under a new name,
then writes current drafts to a fresh file. Invalid storage locations remain an
error until corrected. A recovery snapshot supplements normal project backups.

## Validation

The native test suite includes conversation isolation, shared follow-up drafts,
Back/Forward, legacy migration, delayed submission acceptance, restart recovery
and original-project transcript keys. Recovery-store tests cover actual disk
round trips, file permissions, failed/oversized writes, preserved unreadable data,
symlink rejection, explicit reset and background/final-write ordering.

The engine suite verifies stable conversation identity for historical runs outside
the recent list, project boundaries and missing parents. Release validation on
macOS includes the full native build, 60 Swift tests, 261 desktop and release
checks, and a native smoke test with local model fixtures across all ten workspace
screens. These automated checks supplement manual accessibility and interaction
testing.

Before shipping, run the native package tests and exercise switching, recovery,
Compare, Save As, keyboard navigation and VoiceOver on a Mac. Linux checks do not
establish native UI behavior.

```bash
swift test --build-system native --package-path apps/macos -c release
```
