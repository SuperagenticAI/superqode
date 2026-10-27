# 0.1.12 development checks

For the subsequent local Mac validation, Python 2.26.0 candidate, security audit
and current stable-publication decision, see
[the release readiness review](RELEASE-READINESS-0.1.12.md). The notes below
record the earlier cloud development checks and are not the final release verdict.

27 October 2026. Branch: `feat/macos-harness-engineering`. Target: 0.1.12/build 13.
The user deferred the Mac handoff checks. Work recorded here runs in the cloud
checkout; native compilation, signing and publication are not certified.

## Developer onboarding follow-up

Setup checks no longer require a model selection in the native evaluation form.
The real setup worker is tested with empty provider/model fields and records
skipped cases without a quality claim. The first-run and learning screens now
provide a direct harness path and match the actual Enter/Shift-Enter send controls.

The tuning screen can prepare an offline synthetic practice batch without a data
file, credentials or model calls. Practice persists in private app state, supports
annotation/resume and cannot start a live run or authorize adoption. Preparing real
examples is an explicit next step. The onboarding-focused suite passed 34 tests, including actual credential-free
setup execution and offline practice persistence/adoption rejection. The native
changes still require compilation and interaction validation; Python tests
validate the backend contracts.

## Additional implementation

The Optimization page now opens a dedicated native tuning screen. It prepares
project-owned experiments without calls, reopens saved rounds, selects uncertain
examples with a random audit sample, collects labels and rationales, runs bounded
optimization, and records accept/reject judgments. It uses the same `systemone.tune`
service as the TUI, including sealed test examples and verified candidate hashes.
The screen deliberately does not enable experimental acceptance of unverified
candidates. Accepting a candidate advances this experiment; it does not overwrite
or activate the user's project harness.

Native requests enforce project isolation, current-round revision fingerprints,
valid labels, explicit live consent and the project writer lease, including
cancelled workers still being reaped. Review state uses the shared atomic/private
manifest storage. Selecting and preparing an experiment does not start execution.
Jev acquisition, reflection, retries and final-test usage retain their separate
cost semantics. Force-killed interrupted workers can require lock inspection;
there is no automatic replay of a budget or deletion of another process's lock.

ACP shutdown now closes stdin before waiting for a shell-launched agent, waits for
force-killed children and closes the input stream. Codex shutdown also waits for
already-exited processes and stdin closure. Real-process tests cover shell children
waiting for input and children ignoring termination. A separate worker contract
fix rejects a successful process exit without a result object rather than labeling
it completed with an error-shaped result.

## Dependency audit and patch

The locked core dependency export was audited using `pip-audit` with the PyPI
vulnerability service and TLS verification. A second audit applied the versioned
Mac runtime overlays to that export. This is a manifest-level audit, not an
inspection of a signed Mac bundle, optional extras or every base-interpreter
package. It does not establish vulnerability reachability in the app.

| Package | Bundled source configuration | Disposition |
| --- | --- | --- |
| Authlib | New hash-verified overlay: 1.9.1 | Addresses CVE-2026-96760 / GHSA-6v38-4h7w-rj9h. The wheel was checked against PyPI's SHA-256 and includes its license. |
| certifi | Existing overlay: 2026.10.19 | Addresses the advisories reported against locked 2026.1.4. |
| fsspec | Existing overlay: 2026.6.0 | Addresses the advisory reported against locked 2026.2.0. |
| FastMCP | 3.4.4 | GHSA-7xgj-8392-5q4r remains reported; fixed in 3.4.10. Authorization after server transforms needs exposure assessment. |
| OpenTelemetry API | 1.44.0 | CVE-2026-114603 remains reported; fixed in 1.45.1. Assess untrusted inbound tracestate parsing. |
| LiteLLM | 1.91.5 | CVE-2026-114612 remains reported. The advisory concerns LiteLLM proxy administrative/API-key paths; do not infer exploitation of SDK-only calls without checking exposure. |

The overlaid core export still reports three advisories in three packages. Do not
report the dependency audit as clean or treat the earlier GitHub aggregate count
as an audit of this particular bundle.

A targeted FastMCP patch update was attempted without disabling verification.
Resolution failed: patched FastMCP Slim 3.4.10 requires OpenTelemetry API 1.45.1,
while the supported Google ADK extra caps that API at 1.44. The current published
Google ADK 2.13.0 metadata confirms that cap. The attempted incompatible pin was
reverted; the lockfile and ADK support were preserved. A supported dependency plan
or an isolated SDK environment is needed to upgrade both safely. Do not force
installation with incompatible requirements or silently remove ADK support.

Authlib's overlay is compatible with the existing core dependency declarations;
the interpreter-visible dependency check validates 149 packages and 266 active
requirements with no compatibility errors. A prefix-only `uv pip check` scan
reported zero packages in the ephemeral overlay and was not counted as evidence.
The new checker follows the interpreter's distribution paths, honors transitive
extras and rejects empty scans. Packaging runs it after applying overlays. The app packaging script already
installs these overlays using `--require-hashes` and records their manifest hash.
The source lock still describes the CLI/default developer environment, so the
Mac-specific overlay is not a claim that every installation path is patched.

## Validation

The current broader run passed 544 tests with cleanup warnings promoted to errors;
one installed-ACP-agent integration test was skipped. Three additional dependency
checker tests passed. The real GEPA local-reflector test ran in the broader suite;
it was not skipped. No paid provider calls were made. The broader run uses
Authlib 1.9.1, certifi 2026.10.19, fsspec 2026.6.0 and the exact bundled GEPA revision
`f919db0a622e2e9f9204779b81fe00cc1b2d808f`, with local reflector/client fixtures
and no paid provider calls. Cleanup warnings are promoted to errors. The tuning
installer unit test explicitly selects its failed-import branch, so it no longer
incorrectly assumes that GEPA is absent from the test environment.

The remaining release work includes native compilation/interactions, actual
provider integrations, clean installation and upgrade testing, and documented
disposition of the remaining dependency advisories. Frontier analysis and a unified
lifecycle dashboard remain separate native gaps. This work does not certify a
bug-free public release or publish an installer.
