# Factory definition foundation

`fix-and-verify.yaml` is an initial FactorySpec for investigation, implementation
and verification. It uses the existing native Core harness and WorkOrder roles.
It supports draft compilation and explicit execution through WorkOrder workers,
with a human continuation before verification. Protected Python CLI acceptance
is available once application-specific evaluator probes are declared.
Authenticated release uses pinned P-256 signatures; the native Factory Studio
provides explicit enrollment, review, signing and working-tree application.

The macOS flow is **Build → Run & verify → Improve → Manage**. Start with
[the developer walkthrough](DEVELOPER-FLOW.md).

From the SuperQode repository root:

```bash
sq factory validate --spec examples/factory/fix-and-verify.yaml --json
sq factory resolve --spec examples/factory/fix-and-verify.yaml
```

For a customer repository, copy the example to `.superqode/factory.yaml`. Adjust
the model, acceptance command, permissions and budget before preparing a trial.
Existing route settings remain at the top level; routing-only policies continue
to work and are not automatically upgraded.

The seven layers are Factories-as-code, Data and context, Compute, Inference,
Improvement, Orchestration and Access. Governance applies across them. The
`orchestration.stages` array describes a job's workflow within that stack.

## Composition

Harness bindings reference a built-in template or a project-relative file:

```yaml
inference:
  harnesses:
    coder:
      path: .superqode/components/coder.yaml
      model: ollama/qwen3-coder
```

Harness inheritance is resolved and captured. Explicit additional files can be
declared under `data_context.files`; check definitions can reference their ids:

```yaml
data_context:
  repository: .
  files:
    regression-suite:
      path: evals/regression.py
      purpose: evaluator
```

These declarations pin file contents. They do not install skills or run checks,
and declaring an evaluator does not establish its independence from the candidate.

### Explicit skill instructions

**Factory Studio → Improve → Create skill & bind to draft** creates a project
`SKILL.md` and adds an explicit binding to the current draft. Review and save the
definition before preparing an experiment. The equivalent declaration is:

```yaml
data_context:
  repository: .
  files:
    review:
      path: .superqode/skills/review/SKILL.md
      purpose: skill
inference:
  harnesses:
    coder:
      template: core
      model: ollama/qwen3-coder
      skills: [review]
```

The skill needs YAML frontmatter and a nonempty Markdown body:

```markdown
---
name: review
description: Check the requested output
---
Check the requested output format before responding.
```

Only explicitly bound skill bodies are appended to the native agent's system
instructions, in binding order. Declaring an asset alone does not activate it.
The shared compiler and improvement evaluator use the same binding function.
Captured skill contents and their digests travel with the Factory snapshot;
existing snapshots and trials keep their original instructions. Bindings support
up to eight Markdown skills on a single native agent. Disabled skills, missing
frontmatter, empty instructions and evaluator aliases are rejected.

This is an always-on instruction binding. It does not discover personal skill
directories, grant tools, execute scripts or implement skill-trigger matching.
Frontmatter fields other than the validated name/description/enabled metadata
do not activate runtime capabilities. No optimizer is required to use a bound skill.

## Draft compilation

With a clean, committed application repository:

```bash
sq factory compile --goal "Fix the export freeze"
sq factory compile --goal "Fix the export freeze" --write-snapshot
```

The first command only prints a plan. The second also persists the configuration
snapshot and compiled stage harnesses. Neither admits or executes a WorkOrder.
The application baseline commit is recorded separately from the factory digest.
Admission and worker recovery use the same durable WorkOrder contracts.
Use Factory Studio or the signed release CLI after protected verification.
Release signing keys must be declared before the trial snapshot is created.

## Execute a bounded trial

After reviewing the model, acceptance commands, permissions and budget:

```bash
sq factory compile --goal "Fix the export freeze" --write-snapshot \
  > .superqode/factory-plan.json
sq factory submit --plan .superqode/factory-plan.json \
  --request-id export-freeze-001 --actor operator

# Copy the admitted WorkOrder id, then explicitly start agent execution:
sq factory worker WORK_ID --live
sq factory inspect WORK_ID
```

The example waits before `verify`. Inspect the implementation and its evidence,
then continue using the gate digest shown by `inspect`:

```bash
sq factory gate WORK_ID verify --digest sha256:INSPECTED_GATE_DIGEST \
  --decision approve --actor owner --reason "Inspected implementation evidence"
sq factory worker WORK_ID --live
```

This continues verification; it does not release the application. Actors are
local audit labels. Required application checks and a separately authorized
delivery decision still apply. No model calls happen during compile or submit;
worker execution can incur provider charges. Reuse the original request id when
retrying a submission, so it returns the same run instead of creating another.

For deterministic protected acceptance, configure `evaluator` references as
described in the [command reference](../../docs/cli-reference/factory-commands.md#factory-verify),
then run `sq factory verify WORK_ID --execute`. The starter's command-only
regression check must be supplemented with criteria for the customer's actual
application; it is not silently treated as independent verification. Delivery
requires the [signed release protocol](../../docs/cli-reference/factory-commands.md#factory-release-challenge-authorize-and-apply)
and a pinned signing authority. An actor label cannot authorize delivery.

All factory worktrees live under `.superqode/factory/worktrees/`. Keep generated
snapshots, plans, WorkOrders and worktrees ignored by Git; a changed application
starting checkout blocks further factory execution. The
[command reference](../../docs/cli-reference/factory-commands.md) describes the
integrity checks and recovery boundaries.

## Version sources from the native app

Save the definition, then open **Factory Studio → Manage → Source control**. Refresh the
review, inspect each diff, enter a commit message and explicitly commit selected
sources. An ignored `.superqode/factory.yaml` can be committed here without a
Terminal command. The app discovers declared context, evaluators, harnesses,
inherited harness files, skills and roles; it also offers deletion of previously
declared tracked files that have been removed from disk. Removing a reference
alone never deletes a file that still exists.

New declared sources must be committed with their definition so a fresh checkout
has the inputs it needs. Unrelated staged work stays outside this commit. Review
checks the saved source bytes, resolved dependency snapshot, branch and HEAD
again before creating the local commit. Unsaved Studio drafts are not included.
Runtime stores, sessions, generated snapshots, revision archives and credentials
remain excluded. The normal Files commit flow keeps its existing private-state
rules; only this declaration-bound Factory flow permits the reviewed source files.

Inside `.superqode`, source folders currently supported are `components`,
`harnesses`, `skills`, `roles`, `context`, `evals` and `evaluators`, plus the
canonical `factory.yaml`. Declared sources elsewhere inside the project are also
supported, subject to sensitive-path and file checks. Symbolic links, hard links,
private keys, common inline credential fields, oversized or truncated diffs, and
external Git filters are refused. Review contents yourself; this is not a general
secret scanner. The repository needs an initial application commit and a branch.

The operation uses the existing background job engine and project writer lease.
It prepares a local Git commit using an isolated index and a temporary detached
Git worktree, then advances the reviewed branch only if HEAD still matches the
review. A concurrent Git writer cannot have its newer history overwritten.
Unrelated staged changes are preserved. Configured Git hooks and commit signing
still run. A failed or interrupted
Git operation may need inspection before a fresh attempt; do not assume it can be
replayed. Finish other Git writers before committing. Source commits do not push,
deploy, or grant release approval.

Commit Factory sources **before preparing a trial**. A commit advances HEAD;
existing trials retain their original application baseline and may require a new
trial. CLI users can still explicitly version an ignored definition with
`git add -f .superqode/factory.yaml` while keeping runtime state ignored.

## Reusable Trial Suites

Open **Factory Studio → Run & verify → Trial suites** to author a paired suite, prepare its
isolated projects, run whole workflows, review gates and inspect the scorecard.
The shared engine is also exposed by `factory suite-prepare`, `suite-run`,
`suite-inspect` and `suite-gate`. See [trial-suite.yaml](trial-suite.yaml) for a
starting manifest. Native history lists suites prepared in that desktop state;
CLI operations accept the core suite ID directly.

### Failure inbox and reviewed experiments

Open **Trial suites → Failures & proposals**, select a prepared suite and choose
**Scan selected suite**. The inbox collects recorded task failures and verified
protected-acceptance mismatches, retaining exact event or receipt references.
Rescanning the same source is idempotent. Earlier failures remain visible after
a successful explicit retry; reused outcomes are counted separately from recorded
observations. Neither count establishes independent model failures. Sources that
cannot be verified are reported rather than converted into application regressions.

Suggested classifications are tentative rules, not root-cause diagnoses. Record
an operator classification and note, or dismiss a finding. Infrastructure,
evaluator, budget, recovery and unknown findings require source repair. Only a
reviewed application-defect or model-protocol finding permits a tuning proposal.
Review saves use a digest to reject stale writes. The canonical failure record
and fingerprint reuse the existing failure-mining contract; no model is called
to scan evidence, classify it or create an operator-authored proposal.

Select one observation and change either its stage goal or its harness binding's
primary model route. The proposal pins the executed baseline snapshot, candidate,
original case goal, acceptance criteria and application-seed digest. Factory
editable/protected policies still apply. A stage goal may belong to a dependent
or gated stage; its gate, role, graph, permissions and tools remain fixed. A model
change affects every stage using that binding and still passes the Factory
privacy and route checks. No tools, permissions,
gates or acceptance criteria can be weakened. Proposal creation changes neither
the application nor the current Factory draft.

Choose **Load proposal into suite editor**, review the paired suite, then prepare
and execute it explicitly using the normal Trial Suite controls. A changed or
dismissed review prevents loading its old proposal through this view. Previously
prepared suites retain their own immutable execution contracts. Preparing from
a changed application seed can run a different experiment, but cannot produce a
matching evidence link for the original proposal.

After execution, select that suite and choose **Link selected suite's results**
on the proposal. Links require the exact proposed manifest, original application
seed and both snapshot revisions; unrelated results are refused. Measurements
are revalidated when inspected, with ties, regressions, incomplete results and
holds preserved. A proposal allows three linked evaluations; a finding allows
three distinct proposals. These are local workflow bounds, not a statistical
search protocol. Nothing starts automatically. No proposal or linked result
grants draft-adoption, promotion or release authority. The separate Improve and
signed-release workflows keep their own evidence requirements.

The inbox lives under `.superqode/factory-feedback`; immutable proposal sources
live under `.superqode/trials/proposals`. Common credential patterns and secrets
already loaded in the desktop service are redacted from scanned error text.
This is not a general secret scanner; retain access controls on project-local
evidence.

Each suite pins the selected project's clean Git commit, committed application
files, case goals and both resolved Factory revisions. Up to eight cases share
the same application seed. `baseline` and `candidate` reference project-relative
Factory definitions, definition archives, or resolved snapshot JSON files. A
case may override either reference explicitly. Use resolved snapshots for exact
historical component replay: an archived YAML definition alone still resolves
its referenced component files at preparation time. Materialized snapshots at
`.superqode/factory/snapshots/<digest>/snapshot.json` are supported as read-only
inputs with their path and content digest checked.

Preparation creates fresh Git projects under `.superqode/factory-trials`, pins
their source contracts and queues WorkOrders without model calls. The initial
adapter executes runs and their stage workers sequentially. The initial
fixture adapter accepts at most 2,000 regular committed files and 16 MB. It
rejects symlinks, submodules, sensitive paths and external Git filters. Files
under `.superqode` are excluded from the application seed; only declared Factory
sources are reintroduced. Sources elsewhere must match the committed seed.

Paired revisions must preserve governance, release authority, protected checks,
evaluator revisions, graph structure, roles, stage permissions and human gates.
They can compare instruction, skill, model-binding and stage-goal changes while
running the complete supported workflow. This is not a graph search adapter.

**Run / continue suite** uses the existing durable workers, self-check controller
and required OS-sandboxed protected verifier. It pauses at the first human gate.
Select that entry to inspect its patch, task results and evidence, then explicitly
hold or approve continuation. Continue the suite separately. A known failed
stage can be explicitly retried within its original attempt and budget limits;
stale retry requests and uncertain invocations are refused. A retry gets a fresh
invocation identity, while ordinary recovery continues to reuse committed
outcomes. Prior failures and all recorded attempt usage remain in the ledger.
Interrupted invocations may require the existing WorkOrder reconciliation flow.

Suite token, tool and optional USD budgets are divided among paired runs without
widening Factory limits. Wall time is a shared ceiling; individual WorkOrder
budgets also apply and include time waiting after preparation. Prepare when ready
to run. The desktop job watchdog bounds the suite process group. In-flight model
calls can overshoot a usage limit and then be held. Unknown required usage holds
the comparison and is displayed as unknown, never zero.

Scorecards show verified workflow counts, recorded model tokens/tool calls/cost
and latency, operator gate decisions, missing evidence and regressions. A tie is
reported as a tie. Different outcomes from identical Factory snapshots are
labelled variation. A higher observed pass count is descriptive evidence, not
statistical reliability or a promotion decision. Failed provider requests may
have incomplete usage reports; API costs exclude hardware, electricity and human
operating costs. Completed suite durations are frozen for historical inspection.

Suite execution never approves a gate automatically, signs, applies, commits or
deploys a candidate. Evidence is rechecked when reopening; modified fixtures,
snapshots or verification receipts hold the comparison. Source suites may be
saved under `.superqode/trials` and declared as Factory context for versioning;
runtime trial projects and ledgers remain excluded from source commits.

## Export and optimizer contracts

`FactorySnapshot.to_dict()` exports the `superqode.factory-snapshot/1` envelope.
`FactorySnapshot.from_dict()` verifies its digest and component records without
reading the original files. The serialized payload is immutable; decoded copies
can be inspected without modifying the stored revision. This supports definition
handover, not universal execution compatibility with other factory platforms.

The `improvement.optimization` section defines editable and protected surfaces.
Native **Factory Studio → Improve** provides bounded adapters for one harness,
explicitly bound skill, primary model binding, or ungated entry-stage goal at a time.
Harness proposals permit changes to system
instructions, role text and description. Skill proposals permit Markdown body
edits only (up to eight diff hunks, 50 KB); all frontmatter metadata is fixed.
Use a dedicated skill asset for the selected binding before optimizing it;
shared asset IDs across different harness bindings are held to avoid changing
unmeasured bindings. For harness and skill proposals, model routes and workflow
also stay fixed. Every adapter preserves tools, context paths, permissions,
acceptance criteria and release authority. Both Factory protections and the
harness's own protected instruction surfaces are checked before evaluation.

Use **Inputs & suite** to load or edit an evaluation suite under `.superqode/evals`.
The current adapter supports deterministic `contains` and `decision` output
graders, with at least one held-in and one held-out case, and at most 24 cases.
Starter cases demonstrate the format; replace them with meaningful labels before
drawing conclusions. Select a bound harness and a disposable fixture directory,
or use `@empty` for output tasks that need no application files. Prepare the
experiment from a saved Factory and clean committed application baseline.
Preparation pins the definition, components, criteria and fixture without models.

Choose **Harness instructions**, **Bound skill instructions**, **Primary model
route**, or **Workflow entry-stage goal** in the experiment
inputs. Edit a resolved HarnessSpec or the pinned `SKILL.md` in **Candidate & diff**, import a project-relative
candidate from another optimizer, or explicitly run native evaluator–optimizer,
optional GEPA, MetaHarness or Omni portfolio search. These metered adapters use Factory-owned model requests and the
shared evaluation runner. Only pinned held-in examples enter search; the final
held-out set is not passed as a search/test dataset. Unsafe proposals receive no
rollout. Search stages a candidate and never overwrites the live harness.
The base installation does not need GEPA for manual candidate import/comparison.
Both released callable GEPA and the app's pinned modern API are supported.
No dependency is installed automatically by Studio.

### Model-route and workflow-stage proposals

For **Primary model route**, explicitly select one to eight `provider/model`
choices, including the baseline. The saved binding and route preferences supply
editable starting choices; preparation neither discovers models nor installs
them. Each choice must satisfy the saved Factory's cloud/subscription policy
and harness protections. Experiments require a direct native provider,
binding-owned model selection and no model fallbacks. The proposal format is:

```yaml
model: lmstudio/candidate-model
```

Only a pinned choice can be proposed. Each variant executes its own pinned
provider/model; the receipt binds the actual inference routes as well as the
effective harness digests. Background jobs receive only the selected providers'
credentials (plus the explicitly selected reflection provider during search).
Tools, instructions, skills, context, permissions, route policy and workflow
stay fixed. Eligibility still requires strictly better graded output with no
regressions; lower cost or latency alone does not qualify a tied candidate.
Model availability is established by execution, not by preparation.

For **Workflow entry-stage goal**, choose a stage without predecessors or a
human gate. The initial adapter supports investigator, implementer and tester
roles, plus typed reviewer experiments with labelled review graders and a pinned
read-only fixture. The proposal is:

```yaml
stage: investigate
goal: Reproduce the requested behavior and report concrete repository evidence.
```

Only this goal can change, up to 8 KB. Stage identity, role, harness, dependencies,
permissions, acceptance checks, human gates and graph remain fixed. Each case's
suite prompt becomes the overall WorkOrder goal, while the selected stage goal
enters the normal shared WorkOrder prompt builder. Its compiled stage permission
limits also apply. Evidence-only stages must leave the copied fixture's bounded
file manifest unchanged; modifying it fails grading even with matching output.
Receipts bind the exact rendered prompts and this fixture-integrity evidence.

This measures an entry stage's output behavior. It does not execute the other
stages, run controller acceptance commands, fabricate predecessor evidence,
approve human gates or establish whole-workflow quality. Those actions remain
part of an explicitly prepared and executed Factory trial.

Both targets use the same manual editing/import, optional metered held-in search,
one final held-out comparison, receipt checks, history and deliberate draft
adoption as harness and skill experiments. Route adoption changes only
`inference.harnesses.<binding>.model`; workflow adoption changes only the selected
stage's `goal`. These are inline definition edits, so adoption creates no extra
component file. The saved definition stays unchanged until explicitly saved.

### Comparison evidence and adoption

Review the candidate diff, then explicitly compare baseline and candidate on the
same pinned held-out tasks in independent fixture copies. A plan permits one
final comparison attempt, including failed or cancelled attempts once started.
Reusing held-out cases across new plans weakens independence; replace them
deliberately. Criteria and captured context are not automatically exposed to the
optimizer. This is input separation, not a claim of OS-isolated evaluator secrecy.

Eligibility requires a strictly higher held-out pass rate, no lost baseline
successes, exact task coverage, pinned harness/fixture identities, matching
criteria and complete evidence for required budgets. Ties, regressions, unknown
required usage, source drift, tampered artifacts and incomplete jobs hold
adoption. Imported optimizer reports do not count as comparison authority. The
controller requires the exact completed native job and its receipt digest.
Recorded comparisons can be reopened; historical evidence does not approve a
changed current Factory.

Metric-call limits bound optimizer scoring attempts (1–20). Native
evaluator–optimizer, GEPA, MetaHarness and Omni portfolio search share one durable request ledger
with the final held-out comparison. Reflection, scoring, additional attempts,
tokens, API cost estimates, tool reservations and the wall deadline are accounted
under the prepared plan. Unknown or interrupted work prevents further admission;
modified ledger evidence prevents adoption. One in-flight request can overrun a
limit, with its usage retained. Existing job ownership, cancellation and process
watchdogs still apply. See [shared optimiser metering](OPTIMIZER-METERING.md) for
the supported engines, local-fee rules, deadline semantics and evidence limits.
Organization-wide budget pools remain future work.

**Adopt into draft** writes the exact harness component under `.superqode/components`,
or skill under `.superqode/skills/improved-<digest>/SKILL.md`, and loads a proposed
Factory definition into Studio. Harness adoption preserves its skill bindings.
Skill adoption changes only the selected asset's source path and leaves the
original file intact. Draft resolution is checked before creating the artifact.
Review its diff, save a revision,
commit the sources and prepare a new trial explicitly. The saved definition,
existing runs, application and release decision are not activated by adoption.
The component remains usable without an optimizer process or GEPA dependency.

This milestone measures selected-harness **output behavior**, not whole-Factory
reliability or production readiness. Fixture copies are not an OS sandbox.
Explicit handoffs, typed review, whole-workflow instruction experiments,
conditional stages and finite revision loops are described in
[Workflow composition](WORKFLOW-COMPOSITION.md).
Repository-command grading, skill-trigger/script optimization, automatic workflow-topology
and dependent-stage search, and opaque external-agent engine metering need
further adapters. Protected application probes
and signed working-tree delivery remain separate, already implemented actions.

## Customer operations

The native **Operations** tab and shared `factory operations` commands provide
host readiness, disabled worker manifests, Factory source recovery and selected
evidence handover, plus reviewed retention of generated archives. Deployment
prepares fresh target-local work; recovered historical evidence grants no
execution or release authority. See [the operator runbook](CUSTOMER-OPERATIONS.md).

For supported same-path instance recovery, use the separate encrypted runtime
checkpoint. Restore is disarmed until reconciled and checked on the actual host.
Retirement cancels pending Factory work and retains its evidence. Optional
[bounded automation](AUTOMATION.md) and [signed intake](INTAKE.md) share the
existing compiler, workers and evidence contracts.
