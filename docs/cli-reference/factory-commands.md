# Factory Commands

`superqode factory` validates and compiles factory definitions, and manages model,
harness, and route lineage within a SuperQode code factory.

Definition commands are an initial factories-as-code foundation. Harness authoring,
WorkOrders, headless workers, delivery gates, evaluation, and optimization retain
their existing command groups. Start with [Building a Code Factory with
SuperQode](../advanced/software-factory.md) for the broader product model.

The factory layer does not replace sessions. It annotates the durable session graph so work can move
between local OSS models, BYOK models, proprietary runtimes, and different harnesses without losing
history.

## Quick start

The macOS app is the primary Factory interface. The CLI and TUI use the same
engine and can run the whole flow on their own:

```bash
sq factory workflows                          # fix-and-verify, continuous-outcomes,
                                              # build-test-deploy, kanban, scrum, xp, lean
sq factory init --template fix-and-verify     # full FactorySpec; keeps existing routes
sq factory show                               # stages, checks, release rule, recent runs
sq factory describe "build, test and deploy"  # starter draft; no model is required
sq factory describe "We triage bugs, fix them and verify" --model ollama/qwen3-coder
sq factory describe --apply sha256:DRAFT --confirm --reason "Reviewed draft"
sq factory sources inspect
sq factory sources commit --digest sha256:REVIEW --path .superqode/factory.yaml \
  --message "Version the Factory" --confirm
sq factory check --application                # host checks plus build, start and health runs
sq factory trial "Fix the export freeze"      # queues one WorkOrder; no agent runs
sq factory worker WORK_ID --live
sq factory verify WORK_ID --execute
sq factory evidence trace WORK_ID
sq factory decide WORK_ID                     # SuperGauge verdict and release blockers
```

`init` writes `.superqode/factory.yaml` from a template. A route-only policy in
that file is upgraded in place and its `default_route` and `routes` are kept;
an existing FactorySpec is replaced only with `--force`. Every save is kept as a
revision under `.superqode/factory-studio/revisions`, the same store the app uses.

`workflows` lists the seven starters and their stages: Fix and verify,
Continuous outcomes, Build test deploy, Kanban, Scrum, XP and Lean.

`describe` can build those starter settings from the description alone. Words
in the description pick the workflow (kanban, scrum or sprint, xp, lean, or
build plus test or deploy). `--workflow NAME` is used when the description
does not name one. Pass `--model provider/model` to ask that model instead.
The model receives the description and current definition, has no tools, and
cannot change the release authority. A private route that rejects a cloud
drafting model falls back to the same starter. Either way, `describe` writes
nothing to `factory.yaml`. The draft is stored by digest, and
`describe --apply DIGEST --confirm` saves it only if the Factory has not changed
since the draft was made.

`sources inspect` lists the saved definition and its declared components with
diffs against HEAD. `sources commit` creates a local commit of the chosen paths,
only for the exact reviewed digest and only with `--confirm`. It never pushes.

`check` runs the readiness report with emoji status lines and exits with status
2 when a requested application check fails. `decide` prints the release status
and exits with status 2 while release is blocked. `show`, `check`, `trial` and
`decide` accept `--json`.

In the TUI, the same flow is:

| TUI command | Does |
| --- | --- |
| `:factory` or `:factory status` | Factory overview, recent runs and the session route |
| `:factory workflows` | List the starter workflows |
| `:factory init [--template NAME] [--force]` | Create a FactorySpec |
| `:factory describe "<process>"` | Draft a starter with no model, or pass `--model p/m` (runs the CLI) |
| `:factory check [--application]` | Readiness (runs the CLI) |
| `:factory trial "<goal>"` | Queue one WorkOrder; no agent runs |
| `:factory run WORK_ID` | Run it with live agents (`sq factory worker WORK_ID --live`) |
| `:factory evidence WORK_ID` | Checks and requirements by status |
| `:factory decide WORK_ID` | SuperGauge verdict and release blockers |
| `:factory session` | Session model, harness, route and lineage |

Status marks are ✅ passed or covered, ⏸️ held or uncovered, ❌ failed or
rejected, ⛔ blocked and ➖ never ran. Route, mode, switch, fork and lineage
commands are unchanged.

## factory validate

Validate a legacy routing policy or a versioned FactorySpec and its referenced
components without executing agents or checks:

```bash
sq factory validate
sq factory validate --spec examples/factory/fix-and-verify.yaml --json
sq factory validate --project /path/to/customer/repo
```

Paths in a FactorySpec are relative to `--project`, including harness paths. They
cannot escape the project or use symbolic links. Existing routing-only files are
accepted without modification. A full definition requires
`apiVersion: superqode.dev/v1alpha1` and `kind: Factory`.

Validation does not establish runtime readiness, evaluator independence or
application quality. Compilation performs additional execution-contract checks.

## Acceptance configuration and requirement evidence

`sq factory verifier` configures protected evaluators for the existing final
acceptance checks. `sq factory evidence` reads requirement coverage and records
observed business outcomes. These commands use the shared Factory engine; the
same CLI commands work through the TUI, for example
`:factory evidence trace WORK_ID`.

Declare optional requirements inside the existing data/context layer:

```yaml
data_context:
  repository: .
  requirements:
    export-opens:
      description: Exported documents open successfully
      stages: [implement, verify]
      checks: [regression]
```

Keep existing `data_context.files` alongside this mapping. Requirement stages
must exist, and their checks must be final `orchestration.acceptance_checks`.
Each check can set `category: test`, `build`, `start`, `health`, `service` or
`security`. Categories describe application acceptance coverage; they do not
execute checks or establish readiness by themselves.

```sh
sq factory verifier draft --checks .superqode/checks.json > .superqode/verifier-proposal.json
sq factory verifier generate --description "Verify the export startup behavior" \
  --provider ollama --model qwen3-coder --live > .superqode/verifier-generation.json
sq factory verifier install --proposal .superqode/verifier-proposal.json \
  --digest sha256:REVIEWED_DIGEST --confirm
sq factory evidence trace WORK_ID
sq factory intake receipts
sq factory evidence record-outcome WORK_ID --observation pilot-task-01 \
  --outcome met --human-minutes 12.5 --actor operator
sq factory evidence outcomes
```

The `--checks` file maps existing acceptance check names to protected probe
manifests. For example, for an application whose reviewed startup contract is
printing `READY` and exiting successfully:

```json
{
  "regression": {
    "format": "superqode.factory-probes/1",
    "cases": [{"id": "startup", "argv": ["python", "app.py"], "stdout": "READY\n"}]
  }
}
```

Review the proposed YAML, all evaluator files and expected behavior independently
before installation. Installation also accepts the `proposal` wrapper returned
by `verifier generate`. It checks the reviewed digest and source snapshot,
saves content-addressed evaluator files and updates the configuration. It does
not execute probes, approve a release, commit sources or restart a run. Create a
fresh compiled run after saving and versioning the configuration.

The protected runtime supports Python standard-library probes, a read-only
candidate and writable `TMPDIR`. It denies sockets and network access. Use
project-specific probes for builds and startup/health contracts that fit those
limits. Third-party toolchains, running services and external HTTP dependencies
need an explicit supported execution contract; a generated proposal cannot
certify them. AI drafting returns assumptions and missing capabilities; when no
requested check fits the runtime, it can return no proposal instead of a
substitute passing check. Agent self-check commands retain their existing role and do not
become protected evidence just by adding a category.

`evidence trace` links each requirement to expanded stage tasks, artifacts,
protected check results and the verification artifact. Each acceptance check has
one status:

| Check status | Meaning |
| --- | --- |
| `passed` | Verification ran on the current candidate and every case passed |
| `failed` | At least one case failed |
| `blocked` | Verification ran but could not produce a result, for example a contract error or missing sandbox evidence |
| `never_ran` | No verification exists for the current candidate, or it is stale |

Requirements are `covered` (every linked check passed and a linked stage has
evidence), `failed` (a linked check failed), `blocked` (a linked check is
blocked or never ran, or stage evidence is missing) or `uncovered` (no linked
checks). The report (`superqode.factory-trace/2`) includes a `summary` with these
counts, the reason and failed case ids for each check, and whether the
verification is bound to the current candidate. Verification retains a
`factory_requirement_trace` artifact. The report grants no release authority.

Intake receipts retain the 256 most recently seen decisions with fixed reason
codes for queueing, duplicates, policy filtering, replay, delivery conflicts and
limits. They retain hashes, counts and run references, without raw task content,
signatures or secrets. Requests that fail authentication are counted in one
`authentication_failed` row per source, with no fingerprint of their content.

Outcome recording requires a finished run and a stable observation id. Retries
are idempotent; conflicting observations and double-counting a run are rejected.
Business outcomes are explicitly operator-reported, separate from protected
verification. Reports group runs by pinned Factory revision and page through every
run in the project. Each revision's `cost_usd` adds three parts, also shown under
`cost`: runs with an observed outcome, every other attempt of that revision
(including failed and cancelled runs) and improvement experiments whose plan ran
against that revision. A run that never started counts as zero. If any part is
unknown, the total is unknown rather than a partial sum. Missing human effort
also stays unknown. Infrastructure costs are not included, and these
observations do not establish causal optimization gains.

The shared desktop backend exposes `factory.verifier.draft`,
`factory.verifier.install`, `factory.evidence.trace`, `factory.evidence.outcomes`,
`factory.evidence.record-outcome` and `factory.intake.receipts`. Model drafting
uses the existing background-job mechanism with `factory_action: verifier-generate`
and explicit confirmation. The project-scoped Factory MCP server exposes the
same operations; model generation additionally requires startup execution opt-in.
Native visual controls depend on the macOS client consuming these interfaces.

## factory resolve

Print a content-addressed configuration snapshot as JSON:

```bash
sq factory resolve --spec examples/factory/fix-and-verify.yaml
```

The snapshot contains the definition, resolved harnesses, engine version and
captured component files. It includes referenced harness inheritance, declared
context/skill/evaluator files and existing harness instruction/skill/role files.
Resolution reads those project files, without model calls, registry discovery,
downloads or writes. Routing-only files cannot resolve into a workflow.

Snapshots contain project content. Apply the customer's evidence retention and
sharing policy before exporting them.

## factory compile

Prepare a draft WorkOrder plan using the existing delivery contracts:

```bash
sq factory compile --spec examples/factory/fix-and-verify.yaml \
  --goal "Fix the document export freeze"

# Explicitly persist the pinned harnesses and source snapshot:
sq factory compile --goal "Fix the document export freeze" --write-snapshot
```

Compilation requires a clean Git repository with a committed starting state. It
prints JSON containing a **draft** WorkOrder, stage harnesses and the baseline
commit. It does not submit, queue, execute, approve, merge or activate work.
Without `--write-snapshot`, the paths in the draft describe a proposed bundle;
the bundle is not created. With that option it is written under
`.superqode/factory/snapshots/<digest>/`. Existing bundles are verified rather than
overwritten.

The initial compiler supports dependency-ordered, single-agent native `builtin`
harness stages and the local worktree runner. A stage can declare
`human_gate: true` to wait for an explicit continuation before it runs. Advanced
runtime integrations, conditional transitions, loops and automated optimization
are not implemented by this compiler. Unsupported configuration is
rejected. A final human delivery decision remains required; the draft's metadata
does not authenticate an approver or authorize a release.

Factory permission ceilings narrow harness permissions. Non-implementation roles
also have agent file writes disabled. These tool controls do not provide OS-level
isolation or establish independent verification. Factory-level shell permission is
required for acceptance commands. Private-route constraints apply to primary and
fallback inference bindings.

The configuration snapshot and application starting commit are separate
identities. A snapshot does not capture running services, provider internals,
installed dependencies or external-system state. Model identifiers are pinned as
configured; provider aliases may still change upstream.

See the [Fix and verify example](../../examples/factory/README.md) for the current
foundation and its boundaries.

## factory submit

Save a compiler plan with its materialized snapshot, then explicitly admit it to
the existing WorkOrder queue:

```bash
sq factory compile --goal "Fix the export freeze" --write-snapshot \
  > .superqode/factory-plan.json
sq factory submit --plan .superqode/factory-plan.json \
  --request-id export-freeze-001 --actor operator
```

Submission validates the pinned snapshot, compiled contract and application
starting commit. It queues work without starting agents. Reuse the request id
after a lost response: matching retries return the existing run, including its
current progress. A different contract cannot reuse that id. Snapshot files must
remain available for reopening the plan.

Keep generated snapshots, WorkOrder storage and worktrees ignored by Git. If you
track selected `.superqode` definitions, ignore their runtime neighbors explicitly:

```gitignore
.superqode/factory/snapshots/
.superqode/factory/worktrees/
.superqode/workorders/
.superqode/factory-plan.json
```

## factory worker

```bash
sq factory worker WORK_ID --live
sq factory worker WORK_ID --live --follow --id builder-01 --concurrency 2
```

`--live` explicitly permits agent execution and possible provider charges. The
default drains currently ready work and exits at a human gate; `--follow` keeps
polling. Execution reuses WorkOrder workers, leases, usage accounting and recovery.
Factory worktrees and their registry stay inside the project under
`.superqode/factory/worktrees/`. These are Git isolation boundaries, not OS sandboxes.

Ordinary `sq work worker` commands also enforce factory snapshot integrity,
application-baseline checks and human gates. Worker inference overrides and
disabling worktree isolation are rejected for factory runs. Harness promotion
selection cannot replace a pinned stage harness. Integrity is checked before
execution and after the outcome is recorded, before task integration. Unrecorded
changes to the integration workspace block continuation.

A worker interruption uses the existing recovery rules. Uncertain external side
effects still require reconciliation; running a factory does not make arbitrary
model or tool requests safe to repeat.

## factory inspect and gate

```bash
sq factory inspect WORK_ID
sq factory gate WORK_ID verify --digest sha256:INSPECTED_GATE_DIGEST \
  --decision approve --actor owner --reason "Reviewed the implementation evidence"
sq factory worker WORK_ID --live
```

Inspection is read-only and exposes stage status, evidence and pending gate
digests. Gate decisions are `approve` or `hold`. Waiting state is durable, has no
worker lease, and survives client/worker restarts. A continuation binds to the
stage, factory identity and completed-run evidence. New recorded evidence
invalidates an earlier continuation; inspect and decide again.

Gate actors provide **local audit attribution**. They are not an authenticated
release authority. A gate continuation permits a workflow stage to run; it does
not approve an application release or satisfy acceptance checks. Elapsed-time
budgets continue to include time spent waiting.

Existing `sq work` inspection, cancellation, recovery and cleanup remain available
against the same project store. Cleanup after a terminal outcome removes owned
worktrees while preserving the factory snapshot, database and evidence.

## factory verify

Run deterministic application acceptance against a fresh copy of the exact
candidate, using criteria pinned in the factory snapshot:

```bash
sq factory verify WORK_ID --execute --timeout 120
```

`--execute` permits application probe execution. This command makes no model
calls, runs no optimizer and grants no release approval. It exits with status 2
when acceptance is held. A missing/unusable OS sandbox records missing evidence;
the verifier never falls back to an unconfined command.

Declare a protected evaluator alongside the existing self-check command:

```yaml
data_context:
  repository: .
  files:
    cli-probes:
      path: evals/cli-probes.json
      purpose: evaluator
improvement:
  checks:
    regression:
      command: python -m pytest -q
      evaluator: cli-probes
```

The referenced file uses this initial probe format:

```json
{
  "format": "superqode.factory-probes/1",
  "cases": [
    {"id": "export-regression", "argv": ["python", "app.py", "--export"],
     "stdin": "", "stdout": "expected application output\n", "returncode": 0}
  ]
}
```

Replace the example with the application's actual behavioral requirements.
All required acceptance checks must reference an evaluator. Command-only checks
remain self-checks and cannot substitute for protected acceptance. Invalid probe
definitions fail during snapshot resolution.

The controller never imports application code. It invokes the development
Python with `-S` and compares bounded UTF-8 stdout, optional stderr and return
codes outside the candidate process. The first version supports standard-library
Python CLI applications. Shell commands, provider credentials and package setup
are not inherited. General application runtimes require additional adapters.

Candidate files are read-only; each case has separate writable scratch. Declared
evaluator files are omitted from the candidate copy.

### Evaluators are hidden from workers

Evaluator files (every `data_context.files` entry with `purpose: evaluator`, plus
`.superqode/evaluators`) are removed from each task's Git worktree before an
agent starts, so they are not on disk in the worker's checkout. With
`SUPERQODE_SANDBOX` enabled, the worker sandbox also masks those paths in the
project and integration folders (Bubblewrap mounts an empty folder or file over
them; Seatbelt denies reads and writes). Tool arguments that name an evaluator
path are denied by a governance rule and recorded. Edits a worker makes to a
protected path are dropped during integration and recorded.

Each run records provenance: whether evaluators were hidden in every task
workspace, which paths were hidden, whether sandbox masking was active, and any
`factory_protected_access` (read attempt) or `factory_protected_write` artifacts.
Without the OS sandbox, the hiding is the worktree removal plus the governance
rule; a process that reads the original project folder directly is not blocked.
Verification also checks the candidate for copies of evaluator content. Network and host-data reads
are denied by a dedicated macOS Seatbelt or Linux Bubblewrap profile. Interpreter
and OS library roots remain readable. Metadata access is permitted on macOS;
this is not a claim that all host information is hidden. Symlink candidates,
oversized artifacts and Git export rules that omit candidate files fail closed.
Probe output is capped at 64 KB per stream, with a shared wall-clock deadline,
CPU limits, a 16 MiB per-file write limit and 64 open descriptors. This initial
profile does not impose a total memory or aggregate scratch-storage quota.

The durable result binds the factory and harness revisions, evaluator digests,
application tree, exported artifact digest and exact candidate artifact id.
Concurrent verification is fenced; a cancelled or superseded verifier cannot
publish acceptance. After a crash, an expired verifier can be replaced by a new
bounded attempt. Receipts and discarded results remain evidence.

Results also emit a SuperGauge record bound to the Factory revision
(`subject.factory_digest`) and the exact candidate (`subject.candidate` with id,
digest and tree). Its verdict is one of:

| Verdict | When |
| --- | --- |
| **ship** | Every held-out case passed, evaluators were hidden from every task workspace, the worker had no protected access, and no evaluator copy was found |
| **hold** | Evidence is missing, evaluators were not hidden, a protected read was attempted, or a model judge asked to hold |
| **reject** | A case failed, a worker wrote to an evaluator path, an evaluator copy was found, or a model judge rejected |

The task set is sealed only when evaluators were hidden from every task
workspace. Model judges may hold or reject; a judge that tries to approve is
refused. The record measures acceptance of one candidate. It does not measure
harness reliability across many runs or certify production readiness.

Ordinary `sq work check` cannot replace this verifier for factory runs.
`sq work prepare` reuses the exact verified candidate rather than creating a new
identity. Factory delivery requires the separate signed authorization below;
an actor label cannot approve it.

A stdlib watchdog also kills the probe group if its controlling worker exits.
Native isolation can be checked without models using
`python scripts/check-factory-verification-sandbox.py`. The smoke test uses only
generated repository fixtures, including a denied loopback connection.

## Release decision

A Factory release needs both a SuperGauge verdict and a human signature. The
gauge requirement is set at the Factory level:

```yaml
governance:
  release_gauge:
    level: L2          # L1 to L4; default L2
    require_ship: true # always true; a hold or reject never releases
```

Before a release challenge is issued, the engine checks that a SuperGauge record
exists for this run, reaches the required level with a **ship** verdict, and is
bound to the same Factory revision, candidate id and candidate digest as the
verification. A missing, stale, held or rejected record blocks release. The
record id and digest are included in the signed challenge.

```bash
sq factory decide WORK_ID
sq factory decide WORK_ID --json
sq gauge gate RECORD.json --level L2 --require-ship \
  --factory-digest SNAPSHOT_DIGEST --candidate-digest SHA256_DIGEST
```

`decide` lists every blocker (no verification, verification held, gauge
missing, stale or not ship, no signer configured) and whether the run is ready
for a human signature. The gauge never signs; a person with a configured key
still has to authorize the exact candidate.

## factory release-challenge, authorize and apply

Declare a P-256 signing authority **before** preparing a trial. Keys are pinned in
its immutable snapshot; changing the current policy does not change existing runs.

```yaml
governance:
  # Keep the other required governance fields.
  release_authority:
    method: p256-signature
    keys:
      owner:
        public_key: BASE64_UNCOMPRESSED_X963_P256_PUBLIC_KEY
    challenge_ttl_seconds: 120
```

```bash
sq factory release-challenge WORK_ID --key owner
# Sign the base64-decoded `message` using ECDSA P-256 / SHA-256.
# Write {"challenge_id":"release_...","signature":"BASE64_DER_SIGNATURE"}
# to a project-relative proof file, without placing any private key there.
sq factory authorize WORK_ID --proof .superqode/release-proof.json
sq factory apply WORK_ID --candidate-id ARTIFACT_ID --candidate-digest SHA256_DIGEST
```

The challenge binds this project, WorkOrder, factory revision, candidate artifact,
patch digest, candidate/target/expected trees and protected verification artifact.
It is short-lived (30 to 300 seconds), consumed atomically and safe to acknowledge
again after a lost response. A changed candidate or verification invalidates it.
Starting application also requires an unexpired approval, unchanged target and
remaining budget. Persisted application intent can recover after expiry only for
the same authorization and expected tree. Cancellation revokes continuation.

`apply` changes the local working tree; it does not commit, push or deploy.
An already completed application can be acknowledged without applying it again.
The SuperGauge record is the quality decision; the authenticated release
decision is recorded separately and requires it.

The native **Factory Studio** can enroll a user-presence protected Secure Enclave
key, add its public key to the draft policy, authenticate an exact candidate
approval and apply it. Enrollment and signing happen only after explicit actions.
Private key material stays with macOS. The engine verifies the pinned signature;
it does not claim remote attestation of Touch ID, key hardware or signer identity.
Other customer-managed P-256 signers can use the same CLI challenge protocol.

## Native Factory Studio

Open a project and select **Factory Studio** in the Harnesses navigation group.
The Stack view exposes all seven layers and crosscutting governance. Start from
a workflow: **Fix and verify**, **Continuous outcomes**, **Build test deploy**,
**Kanban**, **Scrum**, **XP** or **Lean**. A description can draft starter
settings with no model. Words in the description pick the workflow. A model can
still draft a proposal; it receives the description and definition, has no
tools, and cannot change the release authority. A private route that rejects a
cloud model falls back to the same starter. Applying a proposal, validating
and saving are separate actions. Nothing runs until the revision is saved and
a trial is started.

Review the workflow, model bindings, warnings and definition diff; save a revision
with a reason. Revisions can be loaded back into the draft and explicitly saved
after review. Prepare a trial from the saved, validated definition and a clean
committed application baseline. Preparation makes no model calls. Existing runs
keep their pinned snapshots when the draft changes.

Runs expose stages, human gates, budget, candidate diffs and recorded evidence.
Run ready stages, execute protected verification, authenticate approval and apply
delivery explicitly. Jobs use the existing desktop engine lifecycle and survive
navigation. Native approval is disabled for truncated diffs. A missing protected
probe manifest or signing authority holds verification or delivery respectively.
The starters intentionally require customer acceptance criteria before delivery.
Continuous outcomes is a workflow preset; it schedules work only through a
declared intake schedule that you tick (see Campaigns and event intake).
Optimization remains available through existing harness experiments and never
activates a factory revision automatically.

### Commit saved Factory sources

In native Factory Studio, **Source control** reviews the saved definition and its
declared components, including ignored source files under the supported
`.superqode` source folders. Choose files, inspect their diffs against HEAD and
explicitly create a local commit. New dependencies must accompany the definition.
Unrelated staged application changes, runtime state and credentials are excluded.
The engine rejects stale source, branch or HEAD reviews and uses the existing
durable job lifecycle. It does not push or deploy. Commit sources before preparing
a trial so its application baseline includes that commit.

See the [source-control contract](../../examples/factory/README.md#version-sources-from-the-native-app)
for supported paths and limits. Existing CLI workflows remain available; no global
exception for `.superqode` was added to the general commit flow.

### Guarded improvement in native Studio

**Factory Studio → Improve** prepares pinned experiments for one harness, bound
skill, primary model binding or ungated workflow entry-stage goal.
Use its suite editor, a project fixture (or `@empty`), and a proposal for the
selected surface. Optional GEPA search uses held-in examples only. Run the separate final
held-out comparison before proposing adoption. Harness instruction/role/description
edits and bound skill Markdown body edits are supported; skill frontmatter,
Factory protections and harness policy remain enforced. Route experiments pin
one to eight explicit model choices and execute baseline/candidate on their
respective models. Workflow experiments edit only an entry-stage goal using the
shared WorkOrder prompt and compiled permissions; graph, gates and checks stay
fixed. Evidence-only stage writes fail grading. Use **Create skill & bind
to draft** to author a project skill, then review and save its explicit binding.
Declared skill assets apply only when listed in `inference.harnesses.<id>.skills`.

Adoption requires the exact completed engine comparison job, unchanged criteria
and source, a strictly higher pass rate, no regressions, and complete required
budget evidence. Imported result claims are insufficient. Adoption loads a draft;
harness and skill proposals also create an immutable component. Saving, source commit, new trial, application
verification and signed release are separate actions. Historical comparisons can
be reopened without applying them to a changed Factory.

See [improvement contracts](../../examples/factory/README.md#export-and-optimizer-contracts)
for the graded-suite format, optional engine requirements, wall-time enforcement
and current limits. Workflow-topology/dependent-stage search, typed reviewer
experiments and skill-trigger/script optimization need further Factory adapters.

### Whole-workflow trial suites

```bash
sq factory suite-prepare --project . --suite .superqode/trials/reference.yaml
sq factory suite-run --project . SUITE_ID --live
sq factory suite-inspect --project . SUITE_ID
sq factory suite-gate --project . SUITE_ID --entry CASE--baseline \
  --stage verify --digest GATE_DIGEST --decision approve --reason "Reviewed patch and evidence"
sq factory suite-run --project . SUITE_ID --live
```

For a known failed stage, inspect its evidence, then explicitly authorize another
attempt within the original limits. Execution is a separate action:

```bash
sq factory suite-retry --project . SUITE_ID --entry CASE--candidate \
  --stage verify --attempt 1 --reason "Reviewed the recorded provider failure"
sq factory suite-run --project . SUITE_ID --live
```

Preparation makes no model calls. Execution uses the same paired WorkOrders,
protected verifier and scorecard as native **Factory Studio → Trial suites**.
Human gates pause the suite and require explicit decisions. No suite operation
signs or applies a candidate. See the [suite contract](../../examples/factory/README.md#reusable-trial-suites)
for supported revision inputs, fixture limits, budgets and evidence semantics.

## factory status

Show factory metadata for the active or selected session. Use `sq factory show`
for the FactorySpec itself.

```bash
superqode factory status [SESSION_ID] [--json]
```

## factory routes

List built-in route presets.

```bash
superqode factory routes [--json]
```

Routes include `private`, `local`, `cheap`, `best`, `review`, `long-context`, and
`no-subscription`.

## factory init-policy

Create `.superqode/factory.yaml` as a full FactorySpec (the `fix-and-verify`
template) that also carries the local-first `default_route` and `routes`, so
route commands keep working. An existing file is kept unless `--force` is given.
`--routes-only` writes the older route-only policy file.

```bash
superqode factory init-policy
superqode factory init-policy --force
superqode factory init-policy --routes-only
```

## factory policy

Show the project policy path and merged policy.

```bash
superqode factory policy
superqode factory policy --json
```

## factory resolve-route

Resolve a route through built-in defaults plus `.superqode/factory.yaml`.

```bash
superqode factory resolve-route no-subscription
superqode factory resolve-route review --json
```

## factory mode

Set the factory route/mode for a session.

```bash
superqode factory mode no-subscription [SESSION_ID]
superqode factory mode private [SESSION_ID]
superqode factory mode best [SESSION_ID]
```

Use `--reason` to record why the mode changed.

## factory switch-model

Record that a session moved to another model/provider/runtime.

```bash
superqode factory switch-model ollama/qwen3-coder [SESSION_ID]
superqode factory switch-model byok/openai/gpt-5 [SESSION_ID]
```

Options:

| Option | Description |
|--------|-------------|
| `--runtime` | Runtime/backend label |
| `--reason` | Why this model was selected |
| `--json` | Emit JSON |

## factory switch-harness

Record that a session moved to another harness.

```bash
superqode factory switch-harness coding [SESSION_ID]
superqode factory switch-harness review [SESSION_ID]
```

## factory fork-model

Fork a session to a worker tagged with a different model/provider.

```bash
superqode factory fork-model [SOURCE_SESSION_ID] --model local/deepseek-coder --role coder
```

Options:

| Option | Description |
|--------|-------------|
| `--model` | Provider/model reference |
| `--role` | Factory worker role |
| `--session-id` | New fork session id |
| `--title` | Fork title |
| `--goal` | Handoff goal appended to the fork |

## factory fork-harness

Fork a session to a worker tagged with a different harness.

```bash
superqode factory fork-harness [SOURCE_SESSION_ID] --harness review --role reviewer
```

## factory lineage

Show recorded factory events for a session.

```bash
superqode factory lineage [SESSION_ID] [--json]
```

Events include mode changes, model switches, and harness switches.

## factory operations

Shared with the native Factory Studio Operations tab:

| Command | Purpose |
| --- | --- |
| `sq factory operations check [--probe] [--application] [--timeout N] [--require-platform Darwin\|Linux]` | Inspect host readiness; protected probes execute only with `--probe`, project build, start and health checks only with `--application` |
| `sq factory operations deploy --platform OS --target-project PATH --python PATH --reference ID` | Generate an inert, pinned one-shot worker package |
| `sq factory operations handover [--run ID] [--improvement ID]` | Archive Factory sources and selected inspection evidence |
| `sq factory operations verify ID --digest SHA256` | Verify package integrity against the supplied receipt |
| `sq factory operations restore ID --digest SHA256 --destination PATH` | Recover into a fresh operations recovery folder; no live queue |
| `sq factory operations retention --keep N --days N` | Preview archive-only cleanup |

### Readiness labels

Every readiness finding carries one label and, when something is missing, a
next action:

| Label | Meaning |
| --- | --- |
| `configured` | The setting or tool is present; nothing was run |
| `execution_tested` | The check was actually run on this host |
| `quality_evaluated` | A protected verification of the same Factory revision passed |

With `--application`, the project's own acceptance checks with category
`build`, `start` or `health` run in a temporary detached worktree of HEAD (inside
the OS sandbox when available), each with `--timeout` seconds (default 300). The
worktree is removed afterwards. A missing build, start or health check is a
finding with an action. The report gives counts per label and
`application_passed`; it has no overall score, and readiness is not a release
decision. `sq factory check` prints the same report with status marks.

Each command accepts `--project`. Cleanup application additionally requires the
reviewed `--cutoff` and `--apply-digest`. Deployment startup is a separate explicit
`python -m superqode.factory.worker_entry MANIFEST --live` action on the target.
It prepares fresh target-local work; it never imports source-machine queues or
approvals. Nothing installs or enables a service automatically.

See [operations contracts, upgrade procedure and limits](../../examples/factory/CUSTOMER-OPERATIONS.md).
Runtime images use the separate encrypted checkpoint protocol described below.
Validate Linux execution on the actual Linux host before enabling its worker.

## Factory improvement

The same engine is available outside Studio:

| Command | Purpose |
| --- | --- |
| `sq factory improve capabilities` | Inspect supported kernels and optional availability |
| `sq factory improve prepare --binding ID --tasks PATH --fixture PATH` | Pin an experiment without inference |
| `sq factory improve inspect PLAN` | Inspect plan, baseline and cumulative usage |
| `sq factory improve stage PLAN --file PATH` | Audit and stage a project-relative proposal |
| `sq factory improve import PLAN --engine metaharness --artifact PATH` | Import an external proposal without trusting external scores |
| `sq factory improve preview PLAN CANDIDATE` | Inspect the protected diff |
| `sq factory improve search PLAN --digest DIGEST --live` | Run bounded held-in search |
| `sq factory improve compare PLAN CANDIDATE --digest DIGEST --live` | Consume the single final comparison |
| `sq factory improve draft PLAN CANDIDATE --receipt DIGEST --confirm` | Emit an eligible draft and any immutable component; never save/activate it |
| `sq factory improve mcp` | Serve project-scoped tools over stdio |

Each command except `capabilities` accepts `--project`. Preparation supports
`--engine evaluator-optimizer|gepa|metaharness|omni`, `--reflection-model`,
`--target-kind harness|skill|route|workflow`, `--skill`, `--stage`, repeated
`--route-model`, `--max-evals` and `--max-seconds`. Optional engines never install
themselves. Source installations can use `uv sync --extra optimization`.
See [shared accounting](../../examples/factory/OPTIMIZER-METERING.md).

MCP startup makes no model calls. Live search, comparison and bounded workers
require both `--allow-execution` at startup and confirmation of the specific
tool call. The server is fixed to its selected project. It exposes compile,
explicit submission, inspection and bounded execution; it does not expose human
gate approval or signing/release authority.

## Campaigns and event intake

`sq factory campaign create`, `sq factory campaign inspect`,
`sq factory campaign enqueue`, `sq factory campaign run`,
`sq factory campaign worker` and `sq factory campaign stop` operate saved,
opted-in policies. Queuing makes no model calls. Execution requires `--live` and
the exact campaign digest. See [automation](../../examples/factory/AUTOMATION.md)
for aggregate reservations, cooldowns, deduplication and stopping rules.

`sq factory intake receive` authenticates a project-local body/header pair.
`sq factory intake serve` provides a loopback receiver for a customer HTTPS
proxy. GitHub, Linear and generic monitoring adapters only queue work. See
[signed intake](../../examples/factory/INTAKE.md) for scope/signature contracts.

Schedules are a local intake source:

```yaml
orchestration:
  intake:
    enabled: true
    max_pending: 2
    max_per_hour: 4
    sources: {}
    schedules:
      - id: nightly-upkeep
        goal: Update dependencies and fix any failing tests
        interval_minutes: 1440   # 5 to 10080
```

`sq factory intake tick` queues each schedule at most once per interval, under
the same pending and hourly limits and admission ledger as webhooks, and records
a receipt. It does not start agents and does not run by itself; call it from
cron, a launchd timer or a CI schedule, then run a worker.

## Runtime recovery and retirement

`sq factory operations checkpoint` captures a stopped, encrypted instance.
`sq factory operations verify-runtime` verifies the exact digest and key.
`sq factory operations recover-runtime` restores only to the absent original
path, with execution disarmed. `sq factory operations acknowledge-recovery`
requires the recovery digest and actual host probes via `--probe`.

`sq factory operations retire-preview` reviews the inventory;
`sq factory operations retire` requires its exact `--digest` and cancels pending
work while retaining evidence. `sq factory operations reactivate` requires that
receipt and `--probe`; it does not restart cancelled orders. See the
[operator contract](../../examples/factory/CUSTOMER-OPERATIONS.md).

## Current Behavior

Factory commands record durable intent and lineage. The active session graph records
`factory.next_turn`, which runtime and picker flows can consume safely on the next turn.

Continue with [WorkOrder Commands](work-commands.md) when work needs a durable task graph, worker leases, isolated delivery, checks, review, and a final merge decision.

## Portable source export

`superqode factory export` creates an editable source ZIP, resolved snapshot,
checksum manifest and operating instructions. Use `--project PATH` and optionally
`--digest SNAPSHOT_DIGEST` to require a previously reviewed definition. The command
writes only the generated package under `.superqode/factory-operations/exports/`;
it starts no agents, workers or services.

The macOS app is optional for operation. The target still needs a reviewed
SuperQode CLI runtime, the application checkout, provider access and protected
host setup. Other platforms require explicit adapters and fresh validation.
Runtime sessions, credential stores, history and release approvals are excluded.
