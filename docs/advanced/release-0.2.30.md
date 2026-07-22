# 0.2.30 Validation Release Contract

Version 0.2.30 is the full feature candidate for the 0.3.0 launch. It is intentionally a minor validation release: builders can exercise the complete product surface before the same proven surface graduates to 0.3.0.

Release and CI smoke tests can use `--provider synthetic --model passthrough`
with the built-in runtime. This deterministic fixture never contacts a model
provider; it exists to validate harness and WorkOrder plumbing, not to measure
agent quality.

No major feature is scheduled to appear for the first time in 0.3.0. The major release is earned by validation, fixes, documentation, migration confidence, and reproducible evidence.

## Required gates

| Gate | Release requirement |
| --- | --- |
| Durable execution | WorkOrder DAGs, roles, isolated workers, leases, recovery, review, checks, merge, and rollback. |
| Accounting | Normalized cost/token/tool/latency evidence and fail-closed task-boundary budgets. |
| Governance | Organization/project/harness/WorkOrder/session policy with explain and simulation paths. |
| Credentials | Secret-filtered shells and host-bound credential injection that keeps secret values outside model context. |
| Measurement | Reproducible HarnessBench packages with raw runs, variance, Pareto scorecards, fingerprints, and verification. |
| Improvement delivery | Candidate audit, negative ledger, held-out gates, deterministic canary routing, activation policy, and guarded rollback. |
| Terminal operations | Builder workflows are complete from `sq`; web/mobile parity is not a release gate. |
| Compatibility | Existing harness, runtime, extension, ACP, Omnigent import, RLM Code, and local-model paths remain green. |
| Release proof | Full tests, strict docs, package lifecycle checks, metadata consistency, and no unreviewed release publication. |

## Graduation rule

After 0.2.30 ships, issues found by real WorkOrders and HarnessBench reruns are fixed on the 0.2.x line. The 0.3.0 release can proceed when:

- no release-blocking data-loss, credential-exposure, policy-bypass, or rollback defect remains
- WorkOrder recovery and budget gates pass kill/restart testing
- at least one public HarnessBench package independently verifies
- candidate canary, activation, and rollback have been exercised on a non-demo harness
- installation and extension lifecycle checks pass from built wheels
- the public documentation matches the shipped CLI

The 0.3.0 release may improve wording and defaults, but it must not bypass this validation by adding an untested platform or UI surface.
