# TUI developer experience review

SuperQode should make returning to a project dependable before adding more UI
surfaces. Preserve the purple/pink branding, welcome animation, thinking
indicators, and harness identity. The product contract should be: reopen the
project, choose a saved session, see the correct harness and model, and continue
with the same context. Inspecting and editing files must leave that conversation
available.

## Implemented in this pass

| Area | Finding | Change |
| --- | --- | --- |
| Custom harness resume | Metadata retained a harness name without the explicit YAML location. | Persist the resolved spec path and use it when restoring. Existing records without a path retain name-based resolution. |
| Failed resume | Harness selection disposed the active runtime before checking credentials. | Check credentials, working directory, and referenced external transcript before replacing the runtime. |
| Switchboard | The active marker changed before resume, and exceptions were suppressed. | Mark the target active only after successful resume; report errors. Block resume during an active turn. |
| Fresh-launch resume | Resume bypassed normal connection setup for tool/approval callbacks and mode indicators. | Reinstall tool and approval callbacks before runtime creation and restore connection controls. |
| Transcript isolation | Clearing rendered lines did not clear copy and tool-history buffers. | Reset conversation buffers before replaying another session. |
| Persistence | Metadata was written directly to the final file. | Write a temporary record and atomically replace the previous one. This protects against partial replacement, not every possible power-loss scenario. |
| File preview | Entire files were read and laid out; cached contents could outlive edits. | Read previews on a worker, cap previews at 400 lines / 64 KB, reject stale selection results, and provide reload. |
| File editing | Edit launched a platform default application; terminal editors could compete with the TUI. | Add a focused in-app editor with save/discard handling, conflict detection, atomic saves, permission and CRLF preservation. |
| Sidebar sizing | Fixed limits could leave little room for the main conversation. | Share terminal-aware limits between drag, keyboard, startup, and terminal resize. |
| Streaming | Every paragraph boundary recounted all earlier code fences. | Count each span once per boundary scan. |
| Session browser | Resume picker capped at ~12 transcript rows. | Dedicated searchable, paginated Session Browser with availability, Continue last, and per-project UI state. |
| Resume contract | Browser and runtime checks described continuity differently. | Use one descriptor for SessionManager, FileHarnessStore, and PiPy rows: exact resume, context replay, or unavailable with recovery guidance. ACP adapter resume is exact-or-fail. |
| Runtime handoff | Resume mutated the active `PureMode` before replacement setup completed. | Stage a replacement runtime, commit only after successful resume, then close the previous runtime. Failed candidates leave the active session intact. |
| Browser latency | Session discovery and harness probes ran on the Textual event loop. | Open immediately with a loading state; discover sessions and probe only the visible page on background workers. |

The editor accepts UTF-8 text files up to 1 MB. Binary, invalid UTF-8, and larger
files remain outside its editing scope. A modal keeps the conversation mounted
but is not a split editor; a persistent split is a follow-up.

## Validation and measurements

Regression coverage lives in `tests/test_tui_workspace_reliability.py`, alongside
existing session, streaming, launch, and mounted-TUI tests. It covers a new
runtime instance restoring a custom harness, failed prerequisites retaining the
active runtime, transcript isolation, switchboard failure, interrupted metadata
replacement, preview refresh, actual sidebar-to-editor keyboard interaction,
external edits, discard handling, and narrow layouts.

A local microbenchmark used a 112,015-character fenced code block containing
4,000 paragraph boundaries. The previous boundary scan took about 90.48 ms;
the revised scan took about 0.37 ms (best of three repeats, three scans each).
This measures one parser operation. It does **not** establish end-to-end input
latency, rendering speed, idle CPU, or performance against another product.

## Next priorities

These are proposed acceptance targets, not measured product guarantees.

1. **Finish the cross-runtime resume service.** The shared descriptor now covers
   SessionManager, FileHarnessStore, and PiPy rows; `PureMode` uses a staged
   handoff, and ACP adapter resume is strict exact-or-fail. Remaining work is to
   surface ACP's SQLite rows in the same browser descriptor and verify actual
   backend process restarts, not only stored-text replay, in end-to-end tests.
2. **A searchable workspace session panel.** Partially done: `:sessions` /
   `:resume` open a dedicated Session Browser (search, pagination, availability,
   preview, rename, Continue last) instead of the capped transcript picker.
   Welcome exposes Continue last session. Selected session and sidebar width
   persist per project in `.superqode/ui-state.json`. Discovery and visible-page
   probes now run off the UI thread. Remaining follow-up: richer project column
   grouping across multi-root workspaces and ACP SQLite rows.
3. **Incremental transcript rendering.** Resume still replays all turns
   synchronously, and streaming still scans the pending tail as chunks arrive.
   Add an indexed transcript model, bounded visible history, load-earlier
   navigation, and frame-coalesced streaming updates. Keep copy/export attached
   to the complete session. Preserve the viewport when a reader scrolls away
   from the live tail. Test 10,000-turn histories and long unfinished code blocks.
4. **A persistent file workspace.** Evolve the modal into a split editor with
   retained drafts and cursor positions, search-result line navigation, file
   tabs, and changes/diff views. Detect filesystem changes and expose conflict
   recovery. Preserve permissions and encoding; do not overwrite agent changes.
5. **Measure interaction latency.** Instrument event-loop stalls, input-to-paint,
   first frame, session selection-to-ready, and preview selection-to-paint.
   Benchmark narrow terminals, SSH, large repositories, and bursty tool output.
   Target p95 input-to-paint under 50 ms and eliminate UI-thread tasks exceeding
   100 ms in those fixtures. Run animations only where visible and useful;
   retain branding while profiling their actual cost.

## Reference experience

Warp documents [workspace restoration](https://docs.warp.dev/terminal/sessions/session-restoration),
[command/output blocks](https://docs.warp.dev/terminal/blocks), and
[editor-style input](https://docs.warp.dev/terminal/editor). The transferable
ideas are persistent context, independently navigable output, and familiar
editing. SuperQode can apply those interaction patterns within its existing
Textual architecture. A terminal-emulator rewrite would be a separate product
and is not required for these improvements.
