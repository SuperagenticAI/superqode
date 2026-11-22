# Live local-model Factory demo

This reference project contains three intentional defects in a standard-library
Python JSON CLI. Each trial creates its own clean Git project under
`.superqode/validation`, then uses SuperQode's actual desktop jobs and WorkOrder
engine to investigate, implement, pause, resume, verify and apply a change.
No synthetic model, mocked executor or prewritten fix is used.

| Case | Requested behavior |
| --- | --- |
| `totals` | Accumulate repeated categories, including negative and zero amounts. |
| `active` | Include only items explicitly marked with JSON boolean `true`. |
| `ordered` | Stable Unicode case-insensitive sorting using `casefold`. |

The seed `app.py` is deliberately faulty. Do not treat its initial self-check
failures as repository regressions. The visible `self_check.py` provides a small
regression test; each case also has four protected CLI acceptance probes.

From the SuperQode checkout, with an installed local model server available:

```bash
.venv/bin/python scripts/run-factory-demo.py --live --compare \
  --model ollama/qwen3.5:9b
```

`--compare` replays all cases against two Factory revisions. The candidate changes
only the investigation stage's goal to request more explicit evidence and edge
cases. It preserves the model, harness, permissions, checks and demo signing
authority. A tie is reported as a tie, not an improvement. This descriptive
comparison does not issue an optimizer adoption receipt or activate a Factory.

Use `--cases totals` for a shorter trial, or `--output` to choose a new directory
inside `.superqode/validation`. Existing output directories are never overwritten.
Only `ollama/` and `lmstudio/` routes at fixed loopback endpoints are supported.
The runner does not install, download or switch to a cloud model.

Each case checks:

1. The original application fails at least one protected probe under real OS isolation.
2. Repeated admission returns the same WorkOrder.
3. Real model-driven investigation and implementation use isolated worktrees.
4. Only `app.py` changes; the visible regression script remains intact.
5. The verification gate persists across closing and reopening the desktop controller.
6. Holding the gate executes no work; resumption does not repeat completed stages.
7. The verification stage and protected acceptance probes complete.
8. A pinned P-256 demo signature authorizes the exact candidate for local application.
9. Repeating that application through the core API leaves the result unchanged.

Model file tools are limited to project reads and permitted writes. Model shell
and network tools are disabled. The controller runs self-check commands, while
the protected verifier requires an OS sandbox and holds missing evidence.
Each workflow has a 20-minute, 60,000-token and 70-tool-call ceiling. These are
per-workflow bounds; `--compare` runs six workflows sequentially.

The JSON report records actual usage, case outcomes, application seed identities,
Factory digests, job IDs, probe receipts and evidence paths. Each generated
project also retains the candidate patch and complete WorkOrder record.

## Scope of the evidence

The operator gate and release signature are exercised by an **automated demo
controller using an ephemeral software key**. They do not establish real human
review, Secure Enclave enrollment or production release authorization. No
personal signing key, commit to the SuperQode checkout, push or deployment is used.
Application changes are applied only within the generated demo projects.

Acceptance probes are separate from candidate execution, but this demo does not
claim sealed evaluator secrecy or statistical independence. Cases are tiny,
requirements are known, and the model can inspect visible regression tests.
API-reported local model cost does not measure electricity, hardware or human
operating cost. Closing and reopening a controller at a gate tests persisted
continuation; killing a model invocation mid-write is a different recovery test.

Passing this demo supports the demonstrated Factory protocol on these tasks.
It does not establish general model quality, production readiness, deployment
recovery or the value of the candidate Factory revision.
