# Shared optimiser metering

**Factory Studio → Improve** now uses one durable usage ledger for a prepared
improvement plan. Reflection, held-in scoring, final baseline/candidate evaluation
and any additional admitted proposal attempts consume that same budget.

## Native workflow

Save and commit the Factory sources, then choose a harness, bound skill, pinned
model route or supported entry-stage goal. Prepare a graded suite with held-in
and held-out cases and an explicit disposable fixture. Choose an optimiser and,
for search, explicitly select its reflection model. The Factory's privacy and
editable-surface policies still apply.

The supported search adapters are:

- **Native evaluator–optimizer:** reuses SuperQode's existing workflow controller.
  A model proposes a change, deterministic held-in grading provides feedback,
  and the controller permits at most one refinement. An unchanged repeated
  proposal reuses its prior score without counting another independent trial;
  the second proposal request is still charged to the ledger.
- **GEPA:** the optional adapter supplies a Factory-owned metered reflection
  callable and the same native scoring callback. Only held-in examples enter
  search. GEPA's own estimated counters do not authorize Factory adoption.
  Its [callable reflection contract](https://gepa-ai.github.io/gepa/api/optimize_anything/ReflectionConfig/)
  allows Factory to own the model calls. No dependency is installed automatically.
- **MetaHarness:** the optional upstream kernel uses a Factory-owned proposer
  and evaluator. Proposals edit one temporary instruction artifact; every
  inference request goes through the same gateway ledger. Its external CLI
  backends are not launched by this adapter.
- **Omni portfolio:** composes native, GEPA and MetaHarness exploration followed
  by GEPA continuation. Each phase receives a finite metric allocation and all
  phases share one ledger. It requires at least four metric calls per held-in
  case. This is a metered composition recipe, distinct from the separate
  external-agent GEPA Omni import path.

Manual proposal import also uses the shared metered final comparison. Search
produces a staged proposal; run the separate final held-out comparison explicitly.
Adoption still requires a strictly higher pass rate, no regressions, exact pinned
grading evidence, a matching completed native job and complete budget evidence.
Nothing activates or releases automatically.

Use **Refresh usage** to inspect operation phases, request identities, model
routes, observed usage, reservations, unknown work and the shared deadline.
Changing the selected plan or project cannot publish an older budget response
into the new selection.

## Limits and evidence

Tokens, optional USD cost and tool ceilings come from the saved Factory.
Preparation can narrow wall time to at most 600 seconds. This is one shared wall
deadline starting with the first admitted operation, including time between
search and comparison. Restarting a worker or moving to comparison does not
reset it. Held-in metric attempts and reflection calls have separate bounded
counts, each limited by the prepared metric-call ceiling.

Before inference, the controller persists request intent and checks remaining
capacity. Native gateway calls record response usage independently of task
summaries. Task coverage, token/cost reconciliation and actual admitted routes
are checked before adoption. Cross-process action ownership prevents search and
comparison from interleaving. Interrupted or unaccounted work remains pending or
uncertain and prevents further admission; it is never silently replayed.

Metered calls disable implicit SDK retries and model-alias failover after errors.
Additional admitted calls have separate durable identities. Streaming evaluation
uses the accounted non-streaming request path. Unmetered gateways or evaluators
cannot establish complete Factory usage evidence.

`observed.tool_calls` records completed operation reports. Admission also reserves
the number of tool calls requested by model responses; `accounted` and
`reserved_tool_calls` expose that conservative charge. An over-limit tool batch
is stopped before forwarding it for execution. Tokens and costs are observed
after a request returns, so one in-flight request can exceed a ceiling. The
overrun remains recorded and stops further work. This is admission control,
not a guarantee about a provider's final bill.

USD values are gateway cost estimates. Unknown, non-finite or unsupported-currency
estimates are held. Positive estimates are preserved even for local provider
names. Recognized loopback on-device endpoints may report zero API fees when
there is no positive estimate; remote endpoints, generic proxies and cloud
model aliases do not acquire free-inference status from a local provider name.
Hardware, electricity, subscriptions and third-party tool charges are outside
these API cost estimates.

The ledger is project-local at
`.superqode/factory-improvements/<plan>/usage.json`. It stores request and
operation metadata, without prompts, responses, credentials or headers. Final
comparison receipts bind its digest. Changed, missing or incomplete ledger data
cannot authorize adoption. Evidence storage is bounded to 256 operations,
4,096 requests and 4 MB per ledger.

Historical plans without the shared ledger remain inspectable. Prepare a fresh
plan for metered execution and adoption. A new plan is an explicit new budget;
earlier ledgers remain recorded. Organization-wide budget pools and opaque
external-agent optimiser accounting remain future adapters.

CLI/TUI users can operate the same contracts with `sq factory improve`. The
optional kernels are pinned by the `optimization` extra and their installed
versions are captured in each new plan. Installing or replacing a kernel requires
a fresh plan. Both the released GEPA callable API and the app's separately
pinned engine-pluggable API are supported. Run `uv sync --extra optimization`
in a source installation; opening Studio does not install packages.

See [bounded automation](AUTOMATION.md) for campaign-wide reservations, event
sources, stopping rules and the sealed automatic final comparison.
