# Self-Improving Harnesses

SuperQode treats self-improvement as an auditable harness loop, not as an agent silently rewriting its own
safety policy. The loop mines weaknesses, gives the proposer bounded context, validates candidates on held-in
and held-out tasks, keeps the evaluator outside the proposal path, records negative results, and only applies
candidates that do not regress.

## Loop

```bash
# 1. Run a baseline eval and preserve the JSON.
superqode harness eval --spec harness.yaml --tasks tasks.yaml --live --json > eval.json

# 2. Mine structured failures from eval/test/benchmark artifacts.
superqode harness mine-failures \
  --eval-result eval.json \
  --output .superqode/self-improve/failures.json

# 3. Merge recurring patterns into durable repo-local memory.
superqode harness logbook update \
  --from-failures .superqode/self-improve/failures.json

# 4. Export or run a bounded improvement project.
superqode harness improve \
  --spec harness.yaml \
  --tasks tasks.yaml \
  --from-failures .superqode/self-improve/failures.json \
  --export-only

# 5. Gate a proposed candidate on held-out tasks.
superqode harness eval \
  --spec harness.yaml \
  --variant candidate.yaml \
  --tasks tasks.yaml \
  --split held-out \
  --live \
  --json > heldout.json

# 6. Audit and record the accept/reject decision.
superqode harness audit-candidate \
  --base harness.yaml \
  --candidate candidate.yaml \
  --tasks tasks.yaml \
  --eval-result heldout.json \
  --require-heldout \
  --record
```

## What Is Persisted

| Artifact | Path | Purpose |
| --- | --- | --- |
| Failure report | `.superqode/self-improve/failures.json` | Rich failure records from `harness test`, `harness eval`, Harbor-style JSON/JSONL, or Terminal-Bench-style result directories |
| Logbook | `.superqode/self-improve/logbook/failure_patterns.yaml` | Persistent failure-pattern memory with count, confidence, status, first/last seen, source refs, and negative-result slots |
| Candidate ledger | `.superqode/self-improve/candidates.jsonl` | Accepted and rejected candidate attempts, including changed surfaces, violations, eval gates, and notes |
| Trace evidence | `trace-evidence.md` in the improvement project | Bounded proposal context: current harness snapshot, tasks, mined failures, logbook memory, previous candidate attempts, and editable/protected surfaces |

## Safety Gates

`harness audit-candidate` rejects candidates when they:

- edit protected surfaces such as `execution_policy`, `checks`, `approvals`, or `sandbox` without override
- widen write, shell, network, allowed-command, approval, or sandbox permissions
- disable checks, remove check steps, or stop failing on check errors
- edit surfaces outside the bounded proposal context
- exceed `optimization.max_candidate_edits`
- miss the required held-out gate
- repeat a previously rejected edit fingerprint

These checks are deterministic and run outside the proposal loop. The proposer can suggest changes; the audit
decides whether the harness may accept them.

## Spec Policy

Put default optimization boundaries in the harness so the policy travels with the project:

```yaml
optimization:
  enabled: true
  require_human_apply: true
  editable_surfaces: [context, workflow, model_policy, agents.tools]
  protected_surfaces: [execution_policy, checks, approvals, sandbox]
  heldout_fraction: 0.3
  max_candidate_edits: 3
```

CLI flags such as `--surfaces`, `--protected-surfaces`, and `--max-candidate-edits` override the spec for one
run. `harness improve --apply` audits the generated best candidate before copying it back; use
`--allow-protected-changes` or `--allow-ungated-apply` only when a human has intentionally accepted that risk.

## Memory Hygiene

The logbook is useful only if it stays current. Use pruning to remove stale, low-signal entries:

```bash
superqode harness logbook prune --min-count 2 --max-patterns 50
```

Rejected candidates are not deleted by pruning because they are negative-result memory. Inspect them with:

```bash
superqode harness candidates list
superqode harness candidates export --output .superqode/self-improve/candidates.md
```
