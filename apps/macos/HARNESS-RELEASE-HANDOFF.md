# macOS 0.1.12 validation handoff

Target: 0.1.12, build 13. Branch: `feat/macos-harness-engineering`.
Do not reset or replace the other agent's local work. Use its existing checkout
and preserve local changes before fetching. Record `git rev-parse HEAD` for the
exact source under test; do not package a different revision silently.

## Scope

The branch adds native suite diagnostics, split selection, multiple candidates,
project experiment history, direct advanced harness workflows and a stricter
Omni held-out acceptance/save gate. It preserves the 0.1.11 session recovery and
review features. Python package version remains 2.25.0; the packaged source-tree
hash must reflect this branch's modified engine sources. Do not substitute the
published PyPI wheel for the checked-out backend.

The [audit](HARNESS-ENGINEERING-AUDIT.md) distinguishes implemented controls from
remaining native workflow gaps. Interactive tuning annotation remains terminal-only;
frontier analysis and a unified lifecycle dashboard are not included. Release
notes must not promise full TUI parity.

## Build and automated validation

Run from the repository root on a Mac with full Xcode and the macOS SDK:

```sh
uv sync --locked --python 3.13 --extra dev
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 uv run --locked --no-sync pytest -p pytest_asyncio.plugin \
  tests/test_desktop_*.py tests/test_harness_acceptance.py tests/test_harness_omni.py \
  tests/test_harness_eval_splits.py tests/test_harness_promotion.py \
  tests/test_systemone_tune.py tests/test_macos_runtime_inventory.py -q -rs
swift test --build-system native --package-path apps/macos -c release
```

Follow the existing README's runtime bundling/build instructions, retaining the
pinned GEPA source, runtime checksums and TLS verification. Then run:

```sh
python3 apps/macos/scripts/smoke-test.py
```

The native smoke now checks suite diagnostics and project experiment history in
addition to all workspace screens. Its ordinary evaluation is a setup check,
not proof that live evaluation or optimization succeeds. Confirm current report
files belong to this build, inspect the underlying command exit codes and retain
both successful and failed evidence. Run the real GEPA local-reflector test with
the pinned overlay if it is skipped by the standard dev environment (the bundled
runtime must also pass its own API availability checks).

## Native acceptance checks

1. In Evaluations, choose a custom suite with both held-in and held-out tasks.
   Confirm counts/hash, invalid YAML errors, an empty selected split and smoke-only
   warnings. Switch projects during diagnostics; stale results must not appear.
2. Evaluate a baseline and at least two candidate specs. Compare all three splits;
   verify task counts, wins/regressions and unknown cost display. Validate malformed
   candidates and the eight-file limit before any live call. Setup checks must
   remain labeled as skipped execution.
3. Use a fixture or an explicitly approved small local/provider budget for live
   tasks. Confirm a failing grader is recorded as failure even if the job completes.
   Retain exact suite/configuration hashes, route, model and task evidence.
4. Run a bounded Omni experiment with explicit live consent, compatible reflection
   and optimizer routes, held-in training and sealed held-out graders. Record actual
   usage and any unknown/overshoot cost. Verify stop/cancel and provider failures.
5. Verify missing tasks, smoke-only grading, ungraded/error outcomes, contradictory
   grades and regressed baseline successes cannot authorize saving a candidate.
   Inspect a legitimate candidate, save a new harness, then modify the staged spec
   and verify stale digest rejection. The original harness must remain unchanged.
6. Close/reopen experiments from history; generate enough coding jobs to push old
   experiments outside the shared recent-job list. Check project isolation and
   imported reports. Imported flags must not enable adoption.
7. Open every More harness workflows entry. Check actual command selection, path
   pickers and budgets. Test labeled-data tuning with explicit live consent; confirm
   unlabeled data explains the terminal annotation requirement. Do not run promotion,
   rollback or any live form merely by opening it.
8. Build a harness and configure RLM routing/budgets from the experiment page. Check
   peer allowlists, invalid limits, unsupported routes and no model calls on save.
9. Check narrow layouts, keyboard navigation, VoiceOver, light/dark and increased
   contrast. Check that tuning/advanced forms fit the window and errors are readable.
10. Recheck 0.1.11 session recovery, scoped review, project switching and cancellation.
    Run clean-user installation and upgrade tests with preserved prior user state.

## Known local warning to investigate

The complete Linux desktop backend suite passed 269 tests with one
`PytestUnraisableExceptionWarning` from `BaseSubprocessTransport.__del__` after
its event loop had closed. Pytest attributed collection of this transport to
`test_codex_rejected_subscription_does_not_fallback_to_api_billing`. That test
passed alone with this warning promoted to an error. Reproduce the full suite
on macOS and investigate any transport/process cleanup warnings; the isolated
pass does not explain or resolve the full-suite warning.

## Return evidence before publication

Report source commit, macOS/Xcode/Python versions, Swift build/test results, Python
pass/skip/fail counts, native smoke report, live experiment evidence and costs,
known issues, and packaged native/backend source hashes. Stop on unexplained
failures; do not disable tests or weaken grading to pass.

The GitHub push reported 98 default-branch dependency advisories (6 critical,
43 high, 40 moderate, 9 low). Triage the actual advisory details and identify which
apply to the packaged runtime versus development/optional dependencies before
public release. This count alone does not prove the Mac bundle is affected;
GitHub API access here was blocked, so advisory details remain unverified.

Only after those checks pass, use the project's existing signing, notarization,
Gatekeeper and upload workflow. Verify app 0.1.12/build 13, packaged backend
provenance, archive checksum, stapled ticket and clean-Mac launch before publishing.
This handoff does not certify those checks or itself create a release.
