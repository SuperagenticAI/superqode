# Build a Factory in the macOS app

Factory Studio has four primary areas. Only the pages for the selected area are
shown; there is no nine-tab strip to work through.

| Area | Pages | Use it for |
| --- | --- | --- |
| Build | Set up, Workflow, Definition & diff | Create and review the workflow |
| Run & verify | Single trial, Trial suites | Execute bounded work and inspect evidence |
| Improve | Inputs & suite, Candidate & diff, Comparison evidence | Measure one proposed change |
| Manage | Source control, History, Operations | Commit sources and maintain the Factory |

Each area remembers its last page within the project. Previously visited forms
stay mounted. Switching pages keeps unsaved inputs and the Factory source
editor's caret. A delayed operation cannot replace a later navigation choice.
The conversation tabs and thread sidebar are absent from Factory Studio; the
header's project menu switches projects while keeping the Factory context.

## First Factory

1. Open **Build → Set up**. Select a starter and load it into a draft. Loading
   and validation make no model calls.
2. Validate the draft. The configuration fields show the declared or inherited
   model. Edit the name, binding, model and budget, then **Apply controls to
   draft**. Unapplied field edits block saving and new-trial preparation; discard
   them explicitly if you want the current definition instead.
3. Inspect **Workflow** for stages, handoffs, conditions and human gates. In
   **Acceptance & verification**, map requirements to contributing stages and
   final checks. Classify checks as build, startup, health, service, security or
   tests. Apply these edits to the draft, then validate and save the revision.
4. Validate again, enter a revision reason and save. **Manage → Source control**
   reviews and commits the declared Factory sources. The setup checklist checks
   matching saved and source-review evidence; visiting pages does not mark them
   complete.
5. In **Run & verify → Single trial**, enter a concrete goal and prepare a trial.
   Preparation pins inputs and queues work without invoking a model. Starting
   ready stages is a separate explicit action that can consume inference and
   edit isolated worktrees.
6. Review actual stage outcomes and pending human gates. Run protected
   verification against the exact candidate. Authenticated delivery approval and
   applying a patch remain separate actions. Applying updates the local working
   tree; it does not push or deploy.

The checklist's last item is **prepare a bounded trial**. A queued trial is not
shown as a successful execution. The app keeps source validation, observed
execution, protected verification and release authority distinct.

## Configure and inspect acceptance

Under **Build → Workflow → Prepare protected verifiers**, describe the expected
application behavior and explicitly select a drafting model, or prepare explicit
Python probes. Review the definition diff, probe code, assumptions and expected
outputs, mark the expectations reviewed, then save the proposed configuration.
Saving never executes probes or updates existing runs. Changed source invalidates
the proposal. Prepare a fresh trial to measure the saved checks.

The protected runtime supports Python standard-library probes with a read-only
candidate and no sockets. External services, third-party dependencies and other
unsupported requirements need an appropriate execution contract. A check category
alone is not evidence that the service or application was exercised.

**Run & verify → Single trial → Requirements & application checks** connects the
run's pinned requirements to stages, tasks, artifacts and protected check results.
Missing or unbound evidence remains uncovered. This historical trace does not
grant current release approval.

## Improve a harness or skill

Choose **Improve → Inputs & suite**. Pick the surface: harness instructions,
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
