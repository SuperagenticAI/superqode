# `sq gauge`

Emit and check Agent Quality Records. Format:
[SuperGauge](https://github.com/SuperagenticAI/supergauge).

For the concepts behind these commands see
[Agent Quality Records](../advanced/agent-quality-record.md).

---

## `gauge run`

Evaluate a harness and emit a record.

```bash
sq gauge run --spec harness.yaml --tasks eval-tasks.yaml --out record.yaml
```

| Option | Default | Purpose |
| --- | --- | --- |
| `--spec PATH` | required | The HarnessSpec under evaluation |
| `--tasks PATH` | required | Eval task file |
| `--provider` | `ollama` | Model provider |
| `--model` | spec's policy | Model id |
| `--repeat N` | `1` | Independent attempts per task. Above 1 produces `pass^k` and `pass@k`, which L3 requires |
| `--profile ID` | `sg/coding-agent` | Profile the record claims |
| `--tier {T0,T1,T2}` | `T1` | Risk tier |
| `--sealed / --unsealed` | unsealed | Assert the held-out split was closed to anything that tunes |
| `--canary ID` | none | Contamination probe task ids, repeatable |
| `--evaluator-independent` | off | Assert the grader saw only the artifact and resulting state |
| `--ledger PATH` | `.superqode/harness-protocol` | Event ledger to reference |
| `--candidate ID` | latest | Promotion supplying the actor and rollback target |
| `--no-sources` | off | Skip the promotion, policy and ledger readers |
| `--out PATH` | stdout | Where to write; `.json` selects JSON |
| `--live / --dry-run` | dry run | A dry run skips execution, so it reports no measures |

`--sealed` and `--evaluator-independent` are assertions the operator makes.
Neither can be established from a record alone, which is why L4 exists: a third
party replays the ledger and checks for themselves.

---

## `gauge gate`

Exit non-zero when a record does not reach a given level. This is the command
intended for a pipeline step.

```bash
sq gauge gate record.yaml --level L2 --quiet
```

| Option | Default | Purpose |
| --- | --- | --- |
| `--level {L1..L4}` | `L2` | Minimum level required |
| `--quiet` | off | Suppress the report, leave the exit code |

Without `--quiet` it prints each level with its blockers:

```text
L1  pass
L2  fail
      held-out split is not sealed
      no contamination probes recorded

highest level met: L1
```

---

## `gauge show`

Print a record as a scorecard: subject, authority, task set, measures, gates,
verdict and level.

```bash
sq gauge show record.yaml
```

---

## `gauge verify`

Recompute what can be checked without re-running the agent: the harness digest
against the spec on disk, and the presence of the referenced ledger.

```bash
sq gauge verify record.yaml --spec harness.yaml
```

A digest mismatch means the spec moved after the record was written, so the
record describes a harness you no longer have. Replaying the ledger is the
remaining step, and it belongs to whoever is checking the claim.
