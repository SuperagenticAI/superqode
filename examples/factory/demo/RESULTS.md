# Live Factory reference trial — 21 November 2026

The final reference suite passed using the real local route
`ollama/qwen3.5:9b`. No cloud model, API key, synthetic response or prewritten
candidate fix was used. SuperQode's workers made the application edits.

| Task | Baseline Factory | Candidate Factory | Protected probes per run |
| --- | --- | --- | --- |
| Accumulate category totals | Passed | Passed | 4/4 |
| Require explicit boolean active status | Passed | Passed | 4/4 |
| Stable Unicode case-insensitive ordering | Passed | Passed | 4/4 |

The original application failed two of the four probes for each task. Both
Factory revisions produced passing candidates from identical application seed
files. An audit confirmed that only the selected investigation goal differed
between paired Factory definitions; harnesses, models, evaluators, permissions
and the demo authority were identical.

**There was no demonstrated quality improvement:** both revisions solved 3/3
tasks, with no regressions. The candidate is not automatically promoted.

The completed suite exercised:

- Six end-to-end workflows and eighteen successful model-driven stages.
- Twenty-four passing protected probes using the native Seatbelt OS sandbox.
- Six persisted gate holds and controller reopenings; completed stages each
  retained one attempt, with no duplicate completed work.
- Six verified P-256 demo signatures and local applications, with repeat
  application through the core API leaving each result unchanged.
- Unchanged visible regression scripts and unchanged unrelated application
  functions, checked against their original syntax trees.
- Native SuperQode inspection of a completed run, with no new jobs and no
  changes to its Factory definition. The native build also passed 26 Swift tests.

| Recorded usage | Baseline, three workflows | Candidate, three workflows |
| --- | --- | --- |
| Elapsed seconds | 126.50 | 133.16 |
| Input + output tokens | 89,777 | 101,728 |
| Model tool calls | 29 | 32 |
| API-reported cost USD | 0.00 | 0.00 |

These are descriptive measurements from one small replay. Local hardware,
electricity and human operating costs were not measured. The slower candidate
and its higher token usage do not support a speed or cost improvement claim.

An earlier attempt reached passing protected verification on all three tasks,
but the demo runner incorrectly expected the full report in the desktop job's
summary response. That runner error was corrected by reading the persisted
verification artifact. The unsuccessful attempt remains recorded separately:
77,062 additional tokens and 107.47 elapsed seconds. Those workflows were not
reported as fully completed or applied.

## Evidence and local projects

These artifacts belong to this local execution and are not required source
files for a fresh checkout. Use the [demo instructions](README.md) to reproduce.

- [Final machine-readable report](../../../.superqode/validation/factory-demo-qwen9b-comparison/report.json)
- [Post-run snapshot, signature and scope audit](../../../.superqode/validation/factory-demo-qwen9b-comparison/audit.json)
- [Native app inspection](../../../.superqode/validation/factory-live-demo-native-inspection.json)
- [Earlier runner failure report](../../../.superqode/validation/factory-demo-qwen9b-attempt1/report.json)
- [Completed project shown in SuperQode](../../../.superqode/validation/factory-demo-qwen9b-comparison/projects/candidate/ordered)

## What this confirms

The demonstrated Factory execution, worktree isolation, persisted gate
continuation, protected verification and exact-candidate local application work
on these reference tasks with this local model.

Gate continuation and signing used an **automated demo operator and ephemeral
software key**. Actual human review, Secure Enclave enrollment and production
delivery were not tested. Evaluation was not sealed or statistically independent.
Hard interruption during a model write, deployment recovery, larger repositories
and broader model quality remain unverified.
