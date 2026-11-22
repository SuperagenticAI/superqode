# Build and operate a Factory in the macOS app

Factory Studio uses a dedicated sidebar. Every tool has a named page, and the
main workspace shows one task at a time. Home returns to the rest of SuperQode.

| Section | Pages |
| --- | --- |
| Build | Describe, Configuration, Workflow, Acceptance checks, Definition & diff |
| Test | Single trial, Trial suites |
| Improve | Set up experiment, Candidate & diff, Comparison evidence, Workflow experiment |
| Export | Portable package |
| Manage | Source control, History, Operations |

Advanced tools remain visible in the sidebar. Forms and source-editor drafts
survive page changes. A background completion cannot replace a newer selection.

## First Factory

1. In **Build → Describe**, describe the outcome and choose a drafting model, or
   use a starter. Model generation creates a proposal; loading and checking a
   starter make no model calls.
2. In **Configuration**, choose the model, budget and permissions. Apply edits
   to the draft. Unapplied fields block saving and new trials.
3. Review the stages in **Workflow** and map requirements to protected checks
   in **Acceptance checks**. **Definition & diff** provides direct source editing.
4. Choose **Check definition**, then **Save changes** and give a revision reason.
   **Manage → Source control** versions the declared Factory sources.
5. In **Test → Single trial**, prepare a concrete goal and explicitly run ready
   stages. Review human gates, protected results and exact candidate evidence.
   Source validation does not establish execution quality or release authority.
6. Use **Export → Portable package** to take the saved definition and components
   to your environment. The desktop app can be closed. See [portability](PORTABILITY.md)
   for runtime requirements and other-platform adaptation.

## Configure and inspect acceptance

Under **Build → Acceptance checks → Prepare protected verifiers**, describe the expected
application behavior and explicitly select a drafting model, or prepare explicit
Python probes. Review the definition diff, probe code, assumptions and expected
outputs, mark the expectations reviewed, then save the proposed configuration.
Saving never executes probes or updates existing runs. Changed source invalidates
the proposal. Prepare a fresh trial to measure the saved checks.

The protected runtime supports Python standard-library probes with a read-only
candidate and no sockets. External services, third-party dependencies and other
unsupported requirements need an appropriate execution contract. A check category
alone is not evidence that the service or application was exercised.

**Test → Single trial → Requirements & application checks** connects the
run's pinned requirements to stages, tasks, artifacts and protected check results.
Missing or unbound evidence remains uncovered. This historical trace does not
grant current release approval.

## Improve a harness or skill

Choose **Improve → Set up experiment**. Pick the surface: harness instructions,
bound skill instructions, a primary model choice, or an eligible entry-stage
goal. **Create skill & bind to draft** adds an optional reusable instruction
asset; review/save/commit that draft before preparing its experiment.

Provide meaningful held-in and held-out cases plus a disposable fixture.
Prepare the plan, then edit/import a candidate or explicitly run the selected
native evaluator–optimizer, optional GEPA, MetaHarness or Omni portfolio search. Keep final held-out comparison
separate from search. Adoption requires native comparison evidence, strict
improvement, no regressions and complete required accounting. It proposes a
draft; it never activates a Factory automatically.

**Improve → Bounded automation (advanced)** operates opted-in campaigns without
adding a primary navigation tab. Prepare a saved policy, review an event source
and queue it, then run one experiment or start its finite worker. Inspect the
campaign evidence before any draft adoption. See [automation](AUTOMATION.md).

The displayed time is a **shared experiment deadline**, including time between
admitted actions. It is not a fresh allowance for each button press. See
[metering](OPTIMIZER-METERING.md) for admission and in-flight overrun semantics.

### MetaHarness and GEPA Omni proposals

The methods disclosure distinguishes Factory-metered search from external
proposal sources. The repository's existing MetaHarness exporter/runner and
GEPA Omni engine remain separate tools. They are not launched from this import
flow and their external spending is not included in a Factory plan's ledger.

For a prepared **harness instructions** plan, use **Candidate & diff → Import a
MetaHarness or Omni proposal**. Keep output artifacts inside the project,
normally under an ignored `.superqode/external-optimizers/` directory so they do
not dirty the pinned application baseline.

- MetaHarness: select its run directory. Import reads the bounded leaderboard,
  chosen candidate manifest and that candidate's `harness.yaml`.
- GEPA Omni: select its result JSON. Import reads the `staged_spec_path` artifact
  inside the report directory.

Candidate workspaces may use absolute paths inside that run/report directory or
paths relative to it. Traversal, external paths and symlinks are refused. The
normal Factory surface audit rejects changes to routes, tools, permissions,
context, graders and workflow. Source and metadata digests are recorded as
provenance. External scores cannot authorize adoption; a fresh native metered
comparison remains mandatory. This is proposal interoperability, not complete
shared-budget integration of external search.

## Observe outcomes

**Improve → Observed outcomes & costs** records one attributed observation for a
finished run and groups observations by Factory revision. Reusing an observation
id with identical values is safe; changing it is rejected. Unknown human effort,
tokens or costs remain unknown. Recorded run usage excludes optimizer experiments
and infrastructure spending and must not be presented as total engagement cost.
Comparisons are descriptive and do not establish causal improvement.

## Maintain the Factory

**Manage → Operations → Intake decisions** shows bounded authenticated event
dispositions and reason codes, with links to queued runs. Payload content,
signatures and secrets are excluded. An empty list is not proof that the external
webhook connection has been tested.

**Manage → Operations** puts host readiness and source recovery first. Deployment
and archive retention are collapsed advanced sections. Receipts can be expanded
and collapsed normally. Generated services remain disabled until explicitly
started on a passing target host. See [operations](CUSTOMER-OPERATIONS.md) for
source-recovery scope and the outstanding whole-runtime recovery work.
