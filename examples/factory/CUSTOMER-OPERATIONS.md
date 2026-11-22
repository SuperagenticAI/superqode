# Factory customer operations

**Factory Studio → Manage → Operations** now provides host checks, disabled service
packages, Factory source recovery, selected evidence handover and reviewed
retention of generated archives, encrypted offline runtime checkpoints and
explicit instance retirement. The CLI uses the same engine.

Source/evidence handover and runtime checkpoints have different scopes. Use a
private runtime checkpoint for supported instance recovery, and the smaller
handover format for reviewed sources and selected evidence. Validate each actual
target host before enabling a worker; a generated Linux manifest is not Linux
execution evidence.

## Check a host

Refresh reports the saved Factory/component digest, clean application Git
baseline, supported Python version and available OS sandbox. A structural check
does not certify execution. **Run isolation checks** exercises synthetic output,
denied application writes, denied protected-evaluator reads and denied network
binding through the existing protected-probe supervisor. It calls no model.

```sh
superqode factory operations check --project /srv/customer/project
superqode factory operations check --project /srv/customer/project --probe --require-platform Linux
```

Linux protected probes require Bubblewrap, permitted user namespaces and
`libseccomp.so.2` (Debian/Ubuntu package `libseccomp2`). A syscall filter denies
socket creation, including loopback and Unix sockets, before candidate code runs;
the filter persists across exec. A network namespace alone is insufficient.
Failure exits nonzero. Missing isolation prerequisites or a
failed protected probe cannot establish worker readiness. Passing probes says
nothing about model availability, private network configuration or task quality.
The optional target-host checks in
[the dispatch-only workflow](../../.github/workflows/factory-operations.yml)
exercise both sandbox probes and the fresh gated worker on Ubuntu and macOS.
Creating this workflow does not run it or certify Linux.

## Prepare a bounded worker service

Choose a source run, target OS, absolute target checkout/interpreter paths and
a dedicated Linux service user. **Prepare service package** writes a JSON
manifest and either a launchd plist or systemd unit under
`.superqode/factory-operations/deployments/<id>/`.

```sh
superqode factory operations deploy --project /path/to/source-project \
  --platform Linux --target-project /srv/customer/project \
  --python /opt/superqode/venv/bin/python --reference WORK_ORDER_ID --user superqode
```

The package pins engine version, Factory digest, application commit and goal.
Copy the exact application Git checkout and Factory sources to the target,
then place the manifest at its pinned path. Configure the model route and
credentials separately on that host. Existing queues and approvals are not
portable deployment inputs. Deployment paths currently exclude whitespace and
substitutions; use simple dedicated paths.

An operator must explicitly start the service or invoke its entry point:

```sh
/opt/superqode/venv/bin/python -m superqode.factory.worker_entry \
  /srv/customer/project/.superqode/factory-operations/deployments/DEPLOYMENT_ID/manifest.json --live
```

Starting first checks the actual OS, exact engine/interpreter, current Factory
and application commit and protected probes. It then prepares fresh target-local
work from the pinned goal. One submission receipt per deployment prevents a
second start from creating another run. A source run is provenance, not a
relocated queue. Existing running or uncertain invocations prevent continuation.

The existing WorkOrder worker executes that one target-local order with one
concurrent task, explicit worktree isolation, no implicit retry and a 64-task
ceiling. It drains claimable tasks and exits at a human gate; an operator can
review the target-local gate and explicitly start it again. A completed order
is not replayed on restart. Normal Factory policy, task limits and protected
verification still apply. The worker does not apply, approve or release changes.

Generation neither installs nor starts a service. launchd uses `RunAtLoad=false`
and `KeepAlive=false`; systemd has `Restart=no` and no enable section. Operator
installation, account permissions, model setup, process supervision and target
acceptance remain deployment responsibilities. Generated service files are not
evidence of a working Linux deployment.

## Back up Factory sources and hand over evidence

**Create verified handover** captures the current self-contained Factory
snapshot and optionally up to eight runs and eight improvement plans. Run
exports include their own pinned snapshots, artifacts, events and invocation
metadata from one consistent SQLite read transaction. Improvement exports retain
criteria, baseline, ledger and any final comparison/candidate. Export takes the
same action lease as optimiser execution.

Run artifacts include their embedded content and referenced paths. Referenced
external files, application Git objects and complete model session logs are not
collected implicitly.

```sh
superqode factory operations handover --project /srv/customer/project \
  --run WORK_ORDER_ID --improvement IMPROVEMENT_ID
superqode factory operations verify --project /srv/customer/project \
  HANDOVER_ID --digest sha256:RECEIPT_DIGEST
```

The `.sqfactory` package and receipt live in
`.superqode/factory-operations/packages/`. Preserve the receipt digest separately.
Verification requires that exact outer digest, exact indexed lengths/hashes,
the pinned snapshot and canonical regular entries. It rejects duplicate names,
traversal, links, devices, compressed entries and unexpected authority flags.
Packages are bounded to 64 MB and 512 content entries; a run is bounded to 2,000
events and 500 invocation records. Larger exports fail rather than truncate.

Package verification proves integrity against the supplied digest, not signer
authenticity, task success or release authority. Historical failed, held and
uncertain results remain historical. No missing evaluation is synthesized.
Credential stores and signing keys are not collected. Declared source files and
selected evidence can still contain customer content, evaluator inputs, prompts
and outputs: review and protect the archive before sharing. It is not encrypted.

## Recover sources without replaying history

```sh
superqode factory operations restore --project /srv/customer/project \
  HANDOVER_ID --digest sha256:RECEIPT_DIGEST \
  --destination .superqode/factory-operations/restores/recovery-1
```

Restore verifies before writing, refuses existing destinations and links, and
creates only a new directory in the operations recovery namespace. It resolves
the recovered sources again and checks the original Factory digest. Evidence
stays below `.superqode/factory-recovery/` inside that recovered directory.
There is no imported live queue, active optimiser ledger, session, gate approval
or signing authority. Absolute paths in historical receipts remain historical.
An interrupted copy is not automatically resumed or activated.

This source-only restore does not reconstruct application Git objects, a live
queue or worktrees. To resume at another path, restore a clean application
checkout, review the recovered Factory sources and prepare fresh work. For
same-path recovery of the supported runtime, use a private checkpoint below.

## Encrypted offline runtime checkpoints

Stop workers and other project writers. **Runtime recovery & retirement →
Create encrypted runtime checkpoint** captures the application's Git directory,
tracked/non-ignored application files and supported Factory state, including
WorkOrders, worktrees, optimiser ledgers, campaign state and intake receipts.
SQLite databases use the backup API. A common execution/transaction lease and
before/after inventory checks refuse an inconsistent capture.

```sh
sq factory operations checkpoint --project /srv/customer/project
sq factory operations verify-runtime --archive CHECKPOINT_FILE \
  --key-file KEY_FILE --digest CHECKPOINT_DIGEST
```

The archive is AES-256-GCM encrypted. Its key is a separate private file under
`backup-keys`; preserve the archive, key and receipt digest separately in the
customer's backup storage. A private runtime archive can contain Git history,
task contents and other sensitive project data. Do not use it as a public
evidence export. OS credential stores, signing keys, external model assets,
installed dependencies and external Git object stores are not collected.

The adapter requires a dedicated project-local Factory store, bounds files to
20,000 entries and 256 MiB, and refuses links or linked Git checkouts. Mixed
cross-project WorkOrder stores and larger instances need a dedicated backup adapter.
Restore requires the original canonical project path to be absent and uses the
same pinned engine; it does not overwrite an existing project or migrate paths.

```sh
sq factory operations recover-runtime --archive CHECKPOINT_FILE \
  --key-file KEY_FILE --digest CHECKPOINT_DIGEST --destination /srv/customer/project
sq factory operations acknowledge-recovery --project /srv/customer/project \
  --digest RECOVERY_RECEIPT_DIGEST --probe
```

The restored instance is disarmed. Review uncertain work and restore credential
bindings separately before acknowledgement. Actual protected host checks must
pass. Old release approvals are revoked; remaining human waits need fresh
continuation decisions. Completed evidence and usage are retained, and no worker
starts automatically. An interrupted restore remains marked incomplete and
cannot be acknowledged as complete.

## Retire an instance

```sh
sq factory operations retire-preview --project /srv/customer/project
sq factory operations retire --project /srv/customer/project --digest REVIEWED_DIGEST
sq factory operations reactivate --project /srv/customer/project --digest REVIEWED_DIGEST --probe
```

Stop active workers first. Retirement requires the exact reviewed inventory,
cancels pending Factory orders and blocks new execution/admission. Evidence and
worktrees remain inspectable. Reactivation runs actual host checks; cancelled
orders stay cancelled. This adapter does not uninstall customer-managed services
or revoke credentials that SuperQode did not mint.

## Upgrade and rollback

Stop workers and review uncertain or interrupted work first. Preserve the
application Git baseline, current runtime/environment and checkpoint receipts.
Verify source recovery with the pinned old engine before changing versions.
Install a pinned new engine in a separate environment, copy reviewed sources to
a disposable clean checkout, validate/re-resolve them and run target probes and
an agreed trial suite. Generate new deployment manifests for that engine.

Old engine pins are rejected at worker startup. An old snapshot is not silently
rewritten into a new digest during recovery. No automatic schema migration,
production activation or rollback is performed. Rollback uses the separately
preserved engine/application state and an operator's reviewed procedure; an
archive alone is not a whole-system rollback plan.

## Retention

Preview uses an age cutoff and minimum number of newest verified packages.
Cleanup covers generated handover archives only. It never deletes Factory
sources, live run/optimiser evidence, queues or worktrees. Damaged packages stay
for investigation. At least one newest verified package remains protected.

In the app, inspect **Preview cleanup**, then explicitly **Apply reviewed
cleanup**. The entire inventory and cutoff must still match the review. The CLI
equivalent uses the returned cutoff and digest:

```sh
superqode factory operations retention --project /srv/customer/project --keep 2 --days 30
superqode factory operations retention --project /srv/customer/project \
  --keep 2 --days 30 --cutoff REVIEWED_CUTOFF --apply-digest REVIEWED_DIGEST
```

Each application writes a deletion journal. Partial or interrupted cleanup is
preserved for review, not silently replayed. Customer policies for long-term live
evidence retention, external backup storage and legal holds need a later adapter.
