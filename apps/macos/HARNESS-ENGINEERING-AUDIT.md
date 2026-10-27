# Harness engineering audit

27 October 2026. Source baseline: `49f40530`; changes on
`feat/macos-harness-engineering` target macOS 0.1.12 (build 13).
This is an implementation audit, not a native release certification.

## Product conclusion

SuperQode's strongest distinction is the loop from a versioned harness, through
matched evaluation, to bounded optimization and reviewed adoption. The Mac app
already had meaningful parts of that loop, but it did not expose all the TUI's
controls or guided workflows. Showing an engine command in Tools does not make
its interaction model equivalent to the terminal UI.

Keep evaluation, optimization and Harness Hub prominent. Demonstrate a specific
regression caught on a held-out task and a candidate retained or rejected with
reproducible evidence. Do not market a setup check as quality measurement, a
reported cost threshold as a provider billing cap, or a gate pass as proof of
superiority over another agent.

## Source comparison

| Capability and TUI/CLI source | Mac app before this change | Current source and remaining limitation |
| --- | --- | --- |
| Harness discovery, capabilities, revision identity (`harness/catalog.py`, `app/mixins/harness_hub.py`) | Hub inspection, readiness and route selection | Retained; advanced diagnostics also accessible from experiment pages. |
| Harness authoring (`harness/wizard.py`, `app/mixins/build_harness.py`) | Native configuration through Connect | Direct entry from evaluation/optimization; uses the same wizard. |
| Evaluation suites and explicit evaluators (`commands/harness/evaluation.py`, `harness/eval.py`, `harness/evaluators.py`) | Suite picker, custom file, setup/live choice | Suite hash, split counts, smoke warnings and validation before starting. |
| Development versus validation splits | Worker supported a split; native form always used all | Native all/held-in/held-out picker now reaches the real worker. |
| Multiple candidate comparisons | One optional explicit candidate | Up to eight explicit candidate files; suite-defined variants still apply. Per-task comparison retains regression, improvement and incomplete-evidence filters. |
| Provenance, cost, latency and missing grading (`desktop_service/evaluation_review.py`) | Comparison inspector and full evidence | Retained; no claim of completeness when usage or grading is unknown. |
| Experiment discovery | Shared recent job list could bury experiments behind coding runs | Separate project-filtered history, most recent 100 experiments, reopen without reexecution. Full pagination and cross-run frontier remain gaps. |
| Whole-harness optimization (`commands/harness/optimization.py`, `harness/omni.py`) | Bounded staged Omni, reflection and optimizer model inputs | Retained. Additional optimizer forms now reachable directly. Automatic route credentials and external runtimes still require their normal setup. |
| Held-out acceptance and candidate saving | Aggregate scores and regression flags could accept incomplete/smoke outcomes | Recompute acceptance from matched, complete, consistently graded held-out tasks. Smoke checks, missing tasks, contradictory grades and regressions reject adoption. Both engine and desktop save enforce it. |
| Candidate inspection and import/export | Candidate diff, immutable new-harness save, report import/export | Retained. Imported evidence is explicitly read-only; it cannot authorize a save. Older records without grading evidence require revalidation. |
| Example-driven routing tuning (`commands/harness/tune.py`, `systemone/tune.py`, `widgets/systemone_tune.py`) | Generic Tools form, no native annotation wizard | Direct tuning form with machine-readable output and explicit labeled-data guidance. TUI active-learning annotation, uncertainty review and guided labeling are still terminal-only. |
| Failure mining and meta-harness improvement (`commands/harness/optimization.py`, `harness/self_improve.py`) | Typed Tools forms | Direct links from experiment pages; external backend support varies. No dedicated failure triage dashboard. |
| Reproducible benchmarks (`commands/harness/bench.py`, `harness/bench.py`) | Typed forms | Direct benchmark entry. Manifest, dataset and external runner prerequisites remain explicit. |
| Promotion/canary/activation/rollback (`commands/harness/promotion.py`, `harness/promotion.py`) | Typed forms | Direct lifecycle entries. They retain existing backend gates; no automatic activation or unified native lifecycle dashboard. Omni evidence hardening is not a rewrite of all promotion policy semantics. |
| RLM routing, peer allowlists and budgets (`rlm/delegation_policy.py`, `desktop_service/configuration.py`) | Native Connect configuration | Direct routing and budget configuration from experiments; save a new harness without starting work. |
| Mid-session route switching and continuity (`desktop_service/connect_workflow.py`, `conversations.py`) | Native route selection and handoff | Retained; protocol-native resume varies. ACP subscription routes are not supported by the dedicated evaluator, and the UI still disables those routes there. |
| Skills, memory, observation hooks and other optimizers (`commands/optimize.py`, `skillopt`, harness observability commands) | Typed Tools workflows | Retained. Specialized dashboards and optimizer-specific interactive experiences are not complete native parity. |

## Acceptance defect addressed

Previously, the final Omni gate accepted an audited candidate when its aggregate
score was at least the baseline score and its recorded regression flag was false.
Two zero-score, ungraded runs or two passing smoke checks could satisfy that
comparison. The desktop save also trusted the stored `accepted` flag plus the
candidate digest.

The shared gate now requires a live held-out report, a positive declared task
count, exact matching coverage and identities, supported non-smoke grading for
every task, consistent inner/outer statuses, and no lost baseline successes.
Scores and regressions are recomputed from task records. The prior policy audit
and candidate digest checks remain required. Equal quality may pass the
non-regression gate; it is not labeled as a measured improvement.

These checks validate consistency, not the authenticity of an externally edited
report. The application runs with the local user's permissions. Promotion forms
retain their separate policy/audit contracts and should receive their own review
before claims about universal promotion guarantees.

## Competitor evidence and positioning

The official [T3 Code repository](https://github.com/pingdotgg/t3code) README was
retrieved on 27 October 2026. It describes an agent harness control surface with
mobile, web and Electron clients and multiple agent subscriptions. Its remote
experience is a useful comparison for convenience; matching its mobile/remote
scope is not required to make SuperQode's harness engineering useful.

The official [Codex repository](https://github.com/openai/codex) README was also
retrieved. It distinguishes CLI, IDE, desktop and cloud surfaces. The official
Codex app documentation request was blocked by this environment's network policy.
These README reviews are not a hands-on audit of either competitor's current
applications and do not establish the absence of evaluation or optimization in
those products. There is no defensible feature-superiority or benchmark claim
from this evidence alone.

SuperQode can demonstrate its own differentiation with repository-owned harness
specs, explicit task graders, held-out comparisons, bounded candidate search and
revision review across supported runtimes. A comparative product claim needs
matched tasks, runtime versions, source/configuration hashes, repeats, all attempt
costs, uncertainty and failure disclosure.

## Validation and release boundary

Local focused suite: 123 passed. Broader harness, promotion, tuning and desktop
suite: 127 passed, 1 skipped because GEPA was absent in the standard dev install.
The real GEPA test was then run separately with the exact revision used by the
Mac runtime, `f919db0a622e2e9f9204779b81fe00cc1b2d808f`: 1 passed, using a local
reflector and fake decision client, with no paid provider calls. These suites
overlap and their counts must not be added as unique tests.

Native Swift compilation, interaction checks, clean-Mac installation, paid/local
provider integration, signing, notarization and publication are not validated by
these Python results. See the release handoff. Full native TUI parity and a
bug-free public release cannot be confirmed from this Linux environment.
