# Agent Quality Records

`superqode harness eval` tells you how a harness scored. It does not tell anyone
later what was checked before a change reached production, which conditions had
to hold, who accepted the result, or what to revert to.

`sq gauge` writes that down. It emits an **Agent Quality Record** in the format
published at [SuperGauge](https://github.com/SuperagenticAI/supergauge), an open
specification any tool may implement.

```bash
sq gauge run --spec harness.yaml --tasks eval-tasks.yaml --out record.yaml
sq gauge gate record.yaml --level L2      # exits non-zero below L2
sq gauge show record.yaml                 # the scorecard a human reads
sq gauge verify record.yaml --spec harness.yaml
```

## What it computes

The record introduces no new measurement. It projects state SuperQode already
holds:

| Record field | Comes from |
| --- | --- |
| `task.completion`, split counts | `harness eval` task results |
| `efficiency.*_per_success` | the usage aggregate `harness eval` already reports |
| `subject.harness_digest` | sha256 of the spec file |
| `subject.authority` | `execution_policy.sandbox`, network policy, agent tool lists |
| `policy.hard_rules` gate | governance decisions, from the ledger or the policy in force |
| `decision.actor`, `rolls_back_to` | the promotion registry |
| `assurance.evidence` | the harness protocol ledger and its event count |

Measures appear only where the run produced them. An evaluation without
`--repeat` carries no reliability measure and stops at L2. That is the accurate
result, and inflating it would defeat the point of keeping a record.

## Conformance levels

Levels are cumulative and self-asserted. `sq gauge gate` reproduces the claim.

| Level | Reached when |
| --- | --- |
| **L1** | Schema-valid, with genuine digests and an `authority` block |
| **L2** | Deterministic gates enforced, held-out split sealed and fingerprinted, contamination probes recorded |
| **L3** | `reliability.pass_hat_k` reported, evaluator independence asserted, judge pinned where anything is model-graded |
| **L4** | Signed, with a rollback target and a replayable ledger |

Reaching L3 needs `--repeat`:

```bash
sq gauge run --spec harness.yaml --tasks eval-tasks.yaml \
  --repeat 5 --live --sealed --canary tsk_c1 --canary tsk_c2 \
  --evaluator-independent --out record.yaml
```

Attempts must be independent. SuperQode resets working state between them; where
that cannot be guaranteed, the measure is unsound and should be left out.

## The evidence readers

By default `gauge run` reads three of SuperQode's own stores. Each degrades to
nothing when its store is absent, which lowers the level and never fails the run.

**Promotion.** `--candidate <id>` selects a staged promotion, otherwise the most
recent one covering this spec is used. The rollback target is the *base* digest,
the version in force before the candidate, since that is what a reader needs
when the candidate turns out to be wrong.

**Policy.** Recorded `policy.*` events are read from the ledger when present.
Otherwise the policy in force is evaluated per phase and reported as the default
disposition, which asserts what the configuration allows and stops short of
replaying what happened.

**Ledger.** `--ledger PATH` overrides the default `.superqode/harness-protocol`.
L4 asks for an event count so a third party knows the size of what they are
being invited to replay.

`--no-sources` turns all three off.

## In CI

```yaml
- run: |
    sq gauge run --spec harness.yaml --tasks eval-tasks.yaml \
      --live --sealed --out record.yaml
    sq gauge gate record.yaml --level L2 --quiet
```

Pick the level your profile requires. Records are small and worth committing:
the point of a release record is that somebody can read it months later.

## Gates and judges

A gate is deterministic. A model-graded measure is reported against the release
and cannot satisfy one, so `add_gate` raises on `answer.grounded` and
`robustness.multi_turn` instead of accepting them quietly.

The reasoning is in the specification: a judge varies between runs and can be
influenced by the system it grades. Agents that quietly disable tests and then
report a passing review have been observed in roughly two percent of production
coding-agent sessions.

## Relationship to `harness promote`

The two commands answer different questions and are designed to compose.

`harness promote` decides whether a candidate spec becomes active and maintains
the digest-pinned lifecycle around that decision. `sq gauge` records what was
true at that moment, in a format readable outside SuperQode. Running promotion
alone leaves the decision undocumented for anyone without access to the
registry. Running the record alone omits the rollback target, which holds it
below L4.

## See also

- [Running, Measuring, and Optimizing a Harness](harness-optimization.md)
- [Harness Promotion](harness-promotion.md)
- [Policies & Safety](policies.md)
- [SuperGauge specification](https://github.com/SuperagenticAI/supergauge)
