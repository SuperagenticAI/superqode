# Harness release readiness — 27 October 2026

**Initial review decision: hold stable publication.** The feature and packaging checks pass,
but the dependency audit and shutdown evidence do not support an unrestricted
stable-release recommendation yet. No tag, PyPI publication, notarized installer
or website upload was part of that initial review.

**Subsequent user decision:** the user explicitly accepted the remaining issues
and requested the website upload anyway. macOS 0.1.12/build 13 has since been
signed, notarized and uploaded as a Public Beta. See the
[publication record](RELEASE-PUBLISHED-0.1.12.md). The outstanding findings below
remain open; publication does not establish that they have been resolved.

Candidate: macOS **0.1.12 / build 13**, Python engine **2.26.0** on
`feat/macos-harness-engineering`, based on feature commit `987d2c8f`.
Python 2.25.0 is already released; the candidate's project metadata, module
version, ACP registry pin, lock metadata and changelog now agree on 2.26.0.
The Mac app retains its Public Beta designation.

## What developers can try

- Run credential-free setup checks, then prepare synthetic tuning practice,
  save judgments and reopen the experiment. These do not measure model quality;
  synthetic practice cannot execute live optimization or authorize adoption.
- Inspect suite diagnostics, select held-in/held-out/all evaluation splits,
  compare multiple candidates and review project experiment history.
- Prepare real project-owned tuning experiments, label uncertain examples plus
  an audit sample, and inspect bounded optimization and sealed-test evidence.
  Live execution requires explicit consent and a configured provider.
- Review candidate acceptance or rejection with coverage, grading, regressions,
  verified candidate hashes and costs. Incomplete or smoke-only evidence cannot
  justify adoption. Acceptance does not activate or overwrite a project harness.

These are workflow capabilities, not a demonstrated claim that optimization
improves every model or project. Frontier analysis and a unified lifecycle
dashboard remain separate native gaps, as described in the feature handoff.

## Checks completed on the candidate

Validation host: Apple Silicon, macOS 27.0, Xcode 27.1, Python 3.13.6.
These local checks supplement, rather than replace, the multi-platform CI jobs.

| Check | Result and limit |
| --- | --- |
| Python publication contracts plus desktop/harness/tuning/runtime suites | **2,901 passed, 1 skipped**; includes the release workflow's test groups and feature-specific suites. The skipped test requires an explicitly enabled real Codex account. Unraisable-exception warnings were fatal; resource warnings were recorded, not suppressed. |
| Native Swift release build and tests | **60 passed**. |
| Actual candidate app smoke | Passed with its bundled Python engine: streaming against a loopback provider, credentials isolation, native navigation, workspace rendering, evaluation/optimization inspectors and saved offline tuning practice. Practice live execution was rejected as expected. This uses fixtures, not an external model quality evaluation. |
| Packaged runtime dependency compatibility | Passed against distributions visible to the bundled interpreter, including the hash-locked overlays. |
| Candidate signature integrity | Ad-hoc signature verified for 33 native files and the outer bundle. This is development validation, not Developer ID signing, notarization or Gatekeeper approval. |
| Python distribution | Wheel and source distribution built; the wheel installed into a fresh Python 3.13 environment using the audited core constraints. `superqode --version`, `sq --help` and harness/tuning imports passed from installed site-packages. This is not a test of every optional extra or unconstrained future resolution. |
| Release metadata | `check_release_metadata.py --tag v2.26.0` passed. This checks a prospective tag; no tag was created. |
| TUI checks | Terminal rendering and responsiveness scripts passed their declared checks/budgets. |
| Static checks | Ruff lint/format and whitespace checks passed for the changes. |
| Existing feature CI | CI, native Mac app and Python compatibility workflows passed on `987d2c8f`. New review fixes require their own CI results after push. |

The exact bundled GEPA revision used for the optimization contracts is
`f919db0a622e2e9f9204779b81fe00cc1b2d808f`. Local reflector and provider fixtures
avoid paid calls. Automated rendering covers the app's own test windows; this
review did not use desktop/browser automation or screen recording.

## Fixes made during the review

- Close the desktop database only after tracked background writers, cancelled
  workers and authentication actions finish; reject new jobs during shutdown.
  Repeated close is safe. If draining times out, keep the database available and
  return an explicit retry error instead of racing final writes against closure.
- Reap older Codex SDK children and close all three subprocess pipes, including
  the SDK's kill fallback; close completed terminal subprocess pipes as well.
  Real-process regression tests cover these cases. Focused desktop/ACP cleanup
  and terminal checks pass with resource warnings treated as errors.
- Move compatible Authlib, certificate trust, DNS and filesystem security fixes
  into the Python dependency graph as well as the existing Mac overlays. The
  resolved versions are Authlib 1.9.1, certifi 2026.10.19, dnspython 2.9.0 and
  fsspec 2026.6.0. The optional datasets dependency resolves to 5.0.1. The locked
  environment syncs without changing the lock.
- Extend the packaged native smoke test to prepare offline tuning practice,
  persist a judgment, reject live practice execution and render the reopened
  native tuning screen.

## Remaining stable-release gates

### Dependency audit: four advisories in three packages

The final audit covers the locked core export with the Mac runtime overlays.
It does not cover every optional extra or certify arbitrary future dependency
resolution. Fixing dnspython removed one advisory; four remain:

| Package | Finding | Required disposition |
| --- | --- | --- |
| FastMCP 3.4.4 | [GHSA-7xgj-8392-5q4r](https://github.com/PrefectHQ/fastmcp/security/advisories/GHSA-7xgj-8392-5q4r), patched in 3.4.10 | Review the server-transform authorization exposure and upgrade through a compatible dependency plan. Current harness/router servers do not configure those transforms, but the installed vulnerable package remains present. |
| OpenTelemetry API 1.44.0 | [GHSA-xcq7-p3pf-p88h / CVE-2026-114603](https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-xcq7-p3pf-p88h), patched in 1.45.1 | Untrusted tracestate parsing needs remediation. FastMCP telemetry calls the extractor on incoming MCP metadata, so this cannot simply be dismissed as an unused HTTP-only path. |
| LiteLLM 1.91.5 | CVE-2026-114612 and GHSA-g5ff-637f-6q2m; auditor reports fixes beginning at 1.100.4 and 1.95.0 respectively | These concern proxy administrative/API-key paths. Source inspection found SDK usage, not a launched LiteLLM proxy. Record an explicit exposure disposition and test a supported upgrade before claiming the dependency audit is clean. |

Patched FastMCP requires OpenTelemetry API >=1.45.1, while the supported optional
Google ADK 2.13.0 dependency caps that API at 1.44. Do not force incompatible
requirements or silently remove ADK support. A coherent dependency update or
isolation of conflicting SDK environments is needed. A Mac-only update would
not by itself fix the Python distribution's dependency graph.

### Resource lifecycle follow-up

The final combined run exited successfully but emitted **372 warnings**, including
unclosed SQLite connections, transports and a GEPA evaluation-server socket.
Interpreter shutdown also reported a still-running subprocess and unclosed
output streams. Warning attribution can occur when garbage collection runs in a
later test; it does not establish that the named test created the resource.
The exact leak source still needs isolation. A focused SDK run also passed its
70 assertions but failed strict teardown on an unclosed event loop/socket.
These runs are not evidence of a warning-free lifecycle, despite the targeted
cleanup fixes. Reproduce with allocation tracing and close the owning resources
before calling this gate complete.

### Distribution and real-user validation

- Complete a clean Mac install and upgrade from the public 0.1.11 app, including
  persisted projects/settings/experiments, permissions and data recovery. Test
  the supported minimum macOS version; building for macOS 14 does not validate it.
- Validate a real local model coding task and bounded real-provider harness
  evaluation/tuning with saved results, cancellation, review and failure recovery.
  Fixture success does not substitute for provider integration or measured quality.
- Review accessibility, keyboard navigation, empty/error states and novice
  onboarding with a human tester. Native screenshots are only partial UI evidence.
- After fixes and green CI on the final commit, merge the reviewed branch and
  build from that exact source. Developer ID sign, notarize, staple and verify
  the production app/DMG. Generate SHA-256 checksums, upload versioned and latest
  downloads via the existing external-credentials FTPS tooling, then verify
  public hashes. Publish the Python tag only when its publication gates pass.

The initial development candidate was kept separate from the previously released
app. The later website upload is recorded separately; no PyPI version was spent.

## Local evidence

Logs live outside the source tree and are not release artifacts:

- `/tmp/superqode-2.26.0-contracts-confirm.log` and `.exit`
- `/tmp/superqode-0.1.12-swift-final.log`
- `/tmp/superqode-0.1.12-smoke-confirm.log`
- `apps/macos/artifacts/candidate-0.1.12-confirm/smoke-report.json`
- `/tmp/superqode-0.1.12-candidate-confirm.log`
- `/tmp/superqode-2.26.0-build.log`, `-clean-install.log`, `-clean-help.log`
- `/tmp/superqode-0.1.12-audit-final.json` and `.log`
- `/tmp/superqode-0.1.12-strict-cleanup.log`
- `/tmp/superqode-2.26.0-sdk-cleanup.log`, `-terminal-cleanup.log`
- `/tmp/superqode-0.1.12-terminal.json` and `-responsiveness.json`
