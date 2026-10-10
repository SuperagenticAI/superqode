# Developer trial readiness review: 9 October 2026

Reviewed the 2.10.1 checkout at `45c54302` and the local changes in this review.
These fixes are local and unreleased. Package and publish the reviewed changes
before directing developers to a public install that should include them.
The implementation has a substantial developer workflow already. A successful
local test run establishes an offline regression baseline; it does not certify
every vendor account, operating system, terminal, or future backend release.

## Changes made

| Finding | Result |
| --- | --- |
| Ctrl+C could quit during work and conflicted with prompt selection copy. | Stop active work and pause queued delivery. Keep the draft. Require two idle presses within two seconds to exit. Keep idle selected-text copy and panel copy bindings. A pending decision is interruptible even when its text is selected and the busy indicator is idle. |
| Escape could leave an agent question waiting. Cancellation and teardown did not consistently release approval waiters. | Cancel question futures, deny outstanding approval callbacks, clear pending UI state, and recover the pre-decision draft when stopping, disconnecting, or exiting. |
| A task sent before connecting disappeared from the composer. | Restore the original prompt, including multiline formatting, and point to Ctrl+K / Connect so opening setup keeps it. Also retain prompts when direct chat is unavailable. |
| Searching "connect" ranked BYOK ahead of the exact Connect command. | Rank exact labels and command names before descriptive fuzzy matches. Verify the keyboard path through setup cancellation back to the original draft. |
| The full Hub's language/filter rows displaced the catalog and action buttons at 80×24. | Use readiness and language dropdowns on short/narrow terminals; keep named buttons on larger terminals. Preserve filter values across resize. |
| Hub setup details were rendered in a Static with overflow styling, without a scroll container. | Add a focusable scroll container; Inspect, arrows, and page keys expose long instructions without moving catalog selection. |
| The package accepted Textual 0.47, which lacks `textual.content` and fails to import the TUI. | Raise the dependency floor to the tested Textual 8.2.8 and refresh the lockfile. Verify that dependency resolution rejects the old combination. |
| Quick Start began with optional tuning. | Put installation and connection first; move tuning into evaluation/optimization. |
| Help described :home as disconnecting and Ctrl+C as exiting. | Align help, completion, palette, and keyboard documentation with actual behavior. |
| Release assertions lagged shipped commands, RLM variants, ordering, and guided Copilot setup. | Update the affected contracts to the inspected 2.10.1 surface. Isolate the Codex picker test from the developer's project and startup connection. |

The new mounted journey tests are in the mounted developer trial journey test module and
run in the existing CI keyboard gate and macOS/Linux/Windows connection matrix.
The CI configuration change has not itself run on GitHub during this review.

## Verification in this review

Executed on macOS with Python 3.13.6. This measures this checkout on one host.

| Gate | Result |
| --- | --- |
| Regression suite | 6,020 passed, 30 skipped, 24 explicitly marked integration tests deselected, 139 warnings; 409.16 seconds. The final source includes the palette and pending-decision fixes. |
| Dependency resolution | The wheel rejects Textual 0.47; its TUI imports with Textual 8.2.8. `uv lock --check --offline` passed after regeneration; no locked package version changed. |
| Core-only package install | Built an isolated wheel and installed it into a fresh temporary environment. Both `superqode` and `sq` entry points, CLI help/version, TUI imports, and doctor JSON worked from the installed package. All 80 declared package-data files and LICENSE/NOTICE were present. |
| Real terminal exercise | 48 checks passed across xterm-256color at 80x24 and screen-256color at 120x40. This includes bracketed paste, newline keys, folded large paste, resize, palette/context navigation, draft restoration, and OSC 52 output. Native OS clipboard access was disabled. |
| Responsiveness | All existing probe budgets passed at 80x24 and 120x40. A 1,040,000-character folded paste took 33.06/82.29 ms; maximum measured event-loop delay was 83.334/68.389 ms. These are synthetic headless timings and do not establish input-to-paint latency. |
| Static checks | Ruff lint, formatting, documentation style, and whitespace checks passed. |
| Published interoperability metadata | The published Agent Card matched the local card; its declared icon was reachable. This checks metadata availability, not remote task execution. |

The baseline broad run exposed five stale release assertions, one project/startup
state-dependent Codex picker test, and three localhost tests blocked by the
sandbox. The assertions now match the inspected release; the picker test has
an isolated project. The three localhost tests passed when local sockets were
available. No failing test was removed or marked skipped to obtain a green run.

Skipped tests include optional SDK/evaluation modules, unavailable MCP servers
or CLIs, and checks needing live account/provider opt-in. The 139 warnings
include plugin-marker registration, dependency deprecations, LiteLLM logging,
and Pydantic fixture serialization; they remain recorded rather than suppressed.
The lock resolver also reported the existing optional `claude-agent-sdk==0.2.91`
as yanked for publisher storage cleanup. Refresh and validate that SDK route
before promoting it; the core-only install does not include that extra.

## Developer journey coverage

| Journey | Evidence and practical limit |
| --- | --- |
| Install, alias, help, packaged data | Build a wheel, install it with only core dependencies into a fresh environment, inspect entry points and bundled data, and run the installed CLI/TUI. The network installer and every optional extra need separate install trials. |
| First launch and connection discovery | Render home, connection picker, sessions, and full Hub at 80×24 and 120×40; investigate 60×20. The full-interface trial baseline remains 80×24. |
| Vendor plans, BYOK, local models, ACP | Existing connection, billing, diagnostics, and catalog contracts plus mounted navigation tests. Provider sign-in and actual model inference are not established by offline tests. |
| Composer, multiline paste, folded blocks, file/image/MCP references | Mounted productivity, composer, draft recovery, and context tests; real PTY paste/newline checks. Physical clipboard images and terminal-specific modifiers still need hands-on checks. |
| Streaming and long conversations | Existing responsiveness probe with 10,000 history messages, 37,015 streamed characters, and a 1,040,000-character folded paste. These are local synthetic measurements, not provider or competitor latency measurements. |
| Approvals, questions, interruption, queued prompts | Mounted keyboard tests and actual Event/Future release checks. These do not prove that every remote agent obeys a cancellation request. |
| Tool errors, changes, checks, review, editor conflicts | Existing task-review, workspace reliability, recovery, and tool-history suites. Agent-reported checks remain distinct from recorded checks. |
| Sessions, restart, switching, fork, project identity | Existing session persistence, staged handoff, browser, and harness tests. Exact native resume versus context replay must be checked per live runtime. |
| Codex protocol and MCP OAuth callbacks | Actual isolated Codex app-server attachment and localhost callback tests, without model inference. Temporary local ports require execution outside this sandbox. |
| Harness authoring and protocol interoperability | Existing harness, ACP, A2A, UHP, MCP, and examples coverage. Public endpoint availability and third-party SDK upgrades are separate checks. |
| Cross-platform terminals and accessibility | CI already has a three-OS connection matrix, now including the new journey regressions. This review's interactive execution is macOS/Python 3.13; Windows, Linux, SSH/tmux, screen readers, and light-background terminals need live acceptance. |

## Comparison with current agent interfaces

This is a workflow comparison against current primary documentation and source,
not a ranking based on a head-to-head usability study.

| Reference | Relevant expectation | SuperQode position |
| --- | --- | --- |
| [Hermes CLI](https://hermes-agent.nousresearch.com/docs/user-guide/cli) | Multiline editing, collapsed paste, command completion, interrupt controls, persistent status, and session browsing. | Much of this exists. This review closes interruption and small-terminal browsing gaps. Setup and resume should be timed with unfamiliar users. |
| [Claude Code interactive mode](https://code.claude.com/docs/en/interactive-mode) | Ctrl+C interrupts work; searchable commands and prompt editing reduce the effort to learn the interface. | Interrupt now follows that expectation. SuperQode retains its own shortcuts and accepts both colon and slash command routes; a complete key-for-key match is not claimed. |
| [OpenCode TUI](https://opencode.ai/docs/tui/) | File references, shell commands, provider setup, sessions, and explicit undo/redo. | SuperQode offers similar entry points and a shared multi-harness catalog. Recovery and task-diff semantics should be described explicitly to avoid assuming another agent's undo behavior. |
| [Codex developer commands](https://learn.chatgpt.com/docs/developer-commands?surface=cli) | Saved-session selection and clear working-directory handling when resuming. | SuperQode has a shared Session Browser and continuity descriptors. Live proof of backend restart and resumption is still needed for each advertised connection. |

The subsequent [Pi theme comparison](pi-theme-comparison.md) led to implemented
appearance improvements: complete repainting, retained semantic transcript
colors, live syntax/export palettes, light/system/custom JSON themes, safe
Pi imports and hot reload, and readable text across decorative presets.
The follow-up passed 6,091 regression tests (30 skipped, 24 integration tests
excluded), 58 real-PTY checks, final focused theme/mounted checks, responsiveness
budgets, and an isolated installed-wheel check. See [Themes](themes.md).
Cross-platform terminal appearance and live vendor workflows still require
the developer/pre-release checks below.

## Reusing Hermes

Hermes' [MIT license](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE)
allows code reuse subject to retaining its copyright and permission notice.
Check the exact files and dependencies before importing a component. Its
[CLI source](https://github.com/NousResearch/hermes-agent/blob/main/cli.py)
uses prompt_toolkit and Hermes-specific lifecycle modules, whereas this
project's interactive app uses Textual. Importing the whole terminal layer
would introduce a second UI lifecycle and substantial adaptation work.

Prefer small, isolated helpers and regression scenarios with a clear interface:
terminal key decoding, interrupted-session recovery, resume summaries, and
status presentation. Port the interaction into the existing Textual widgets,
then test it against SuperQode's own runtimes. This review implements the
interactions locally and copies no Hermes source.

## Experience work after the pilot

Prioritize measured friction from the developer trial:

| Priority | Acceptance target |
| --- | --- |
| First task and setup recovery | An unfamiliar developer reaches a reviewed task using their existing agent. Record time, failed attempts, and requests for help; prioritize the failures before expanding the catalog. |
| Native session continuity | Every promoted connection demonstrates restart/resume in the same repository and an actionable repository-mismatch failure. Label context replay explicitly. The earlier [TUI review](tui-experience-review.md) identifies ACP SQLite discovery as remaining work. |
| Change review and recovery | Users can identify the files changed, the command actually checked, and the effect of undo without relying on habits from another coding agent. Exercise failure and conflict recovery with real tasks. |
| Terminal and accessibility coverage | Run keyboard-only trials on the promised terminals and OSes, SSH/tmux, light backgrounds, and a screen reader. Record unsupported modifier and clipboard behavior. |
| Performance at the user interface | Measure startup-to-ready and input-to-paint under real tool output. Existing synthetic probes are a useful regression gate but cannot establish the earlier 50 ms p95 input-to-paint target. |

## Release decision and live acceptance

Invite a small, supported pilot after the local gates pass. Complete the live
matrix below before describing the product as broadly ready for new developers. A claim
of zero bugs would not be supported by these checks.

For each advertised route, record a versioned result for:

1. A clean install on the promised OS, with no optional SDK already present.
2. Missing runtime, expired login, incorrect key, unreachable endpoint, and successful setup; each must give a usable next action.
3. A repository-understanding prompt, one approved file change, one rejected tool request, and one recorded test command.
4. Cancellation during streaming and while waiting for permission; preserve drafts and do not deliver queued tasks automatically after cancellation.
5. Exit/restart/resume in the same repository, then a repository mismatch; show the correct model, harness, project, and continuity type.
6. Switching to another harness; keep reviewable context, report unsupported controls, and do not silently change billing routes.
7. Review and copy of changes and results at 80×24, including keyboard-only navigation.

Suggested first matrix: Codex CLI, Claude Code over ACP, OpenCode over ACP,
and one Ollama model on macOS and Linux; add Windows if it is promised to
developers. This is a proposed pilot scope, not a statement of live results.
Use [Developer Trial](../getting-started/developer-trial.md) for the developer
exercise and feedback fields. Record time to first task, setup failures, lost
drafts, incorrect session restoration, and the number of times a user needed
help. Broaden support after those results are satisfactory.

## Reproduce the local checks

```bash
uv sync --frozen --extra dev
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run --frozen pytest -p pytest_asyncio.plugin -m 'not integration' -q
uv run --frozen python scripts/check_tui_terminal.py --output /tmp/tui-terminal.json
uv run --frozen python scripts/benchmark_tui_responsiveness.py --check --output /tmp/tui-responsiveness.json
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen python scripts/check_public_docs_style.py
```

The regression run excludes explicitly marked live integration tests; some
tests additionally skip when their optional runtime or explicit live opt-in is
absent. Review those counts with the results instead of interpreting a green
run as coverage of every advertised service.
