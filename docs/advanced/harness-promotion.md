# Harness Promotion, Canary, and Rollback

SuperQode treats an improved HarnessSpec like a release artifact. Generating a candidate does not make it live. The candidate must pass audit, held-out evaluation, canary routing, contextual promotion policy, and explicit human activation.

## Promotion lifecycle

```text
candidate
  → audit and held-out eval
  → staged with rollback snapshot
  → deterministic WorkOrder canary
  → live held-out HarnessBench evidence
  → human activation
  → verified rollback when needed
```

The append-only registry defaults to `.superqode/harnesses/promotions.jsonl`. Pre-promotion snapshots live beside it under `snapshots/` and are addressed by digest.

## Stage

First produce a normal held-out eval result, then stage:

```bash
sq harness eval \
  --spec harness.yaml \
  --variant candidate.yaml \
  --tasks eval-tasks.yaml \
  --split held-out \
  --live --json > heldout-eval.json

sq harness promote stage \
  --base harness.yaml \
  --candidate candidate.yaml \
  --tasks eval-tasks.yaml \
  --eval-result heldout-eval.json \
  --actor shashi \
  --reason "Improve recovery without widening permissions"
```

Staging runs the native candidate audit, records accepted and rejected evidence, checks protected surfaces and regressions, fingerprints both files, and preserves the exact stable spec for rollback.

## Canary WorkOrders

```bash
sq harness promote canary cand_... --percent 10 --actor shashi
sq harness promote select harness.yaml --key work_... --json
```

WorkOrders using that file are routed by a stable hash of the WorkOrder ID. The same WorkOrder always selects the same side of the canary. The candidate does not overwrite the stable spec during this phase.

## Activate

Run a live, held-out HarnessBench manifest whose `specs` are the exact staged base and candidate, then activate:

```bash
sq harness bench --manifest heldout-bench.yaml --output results/canary
sq harness bench-verify results/canary

sq harness promote activate cand_... \
  --evidence results/canary/scorecard.json \
  --actor shashi \
  --reason "Held-out quality improved with no regression runs"
```

Activation refuses dry-run evidence, changed source digests, missing variants, regression runs, or a candidate mean below baseline. The repository's contextual `promotion` policy is evaluated last. Only then is the candidate atomically installed at the stable path.

## Roll back

```bash
sq harness promote rollback cand_... \
  --actor shashi \
  --reason "Cost variance exceeded the canary target"
```

Rolling back a canary stops routing without changing the stable file. Rolling back an active candidate restores the verified snapshot. If a person or another process changed the active HarnessSpec after promotion, rollback stops rather than overwriting that later work.

Inspect the full history at any time:

```bash
sq harness promote status cand_... --json
```

