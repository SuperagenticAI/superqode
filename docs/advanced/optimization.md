# Optimization Story

SuperQode treats optimization as a measured, reviewable workflow. It does not
ask an agent to rewrite itself blindly. Every optimizer has the same contract:

1. Start from a versioned artifact.
2. Measure it with a harness eval task file.
3. Propose a candidate in a staging directory.
4. Gate the candidate against regressions.
5. Let a human review and adopt it.

This keeps optimization useful for daily development without making the live
agent unpredictable.

## What Can Be Optimized

| Layer | Artifact | Best tool | Use when |
|---|---|---|---|
| Model route | Provider, model, runtime, local endpoint | `superqode local optimize` | You want the best local/open model routing for planner, implementer, reviewer, and utility roles. |
| Harness | `harness.yaml`, instructions, checks, routing, policies | `superqode harness optimize` | The harness itself needs better workflow, context, permissions, checks, or model policy. |
| Skill | `.agents/skills/.../SKILL.md` | `superqode skills optimize --engine gepa` | A reusable skill works, but misses recurring cases in eval tasks. |
| Custom workflow | Any text artifact with a measurable score | Native SuperQode eval contract, or a custom optimizer | You have a domain-specific artifact and can define a scorecard. |

The core rule is simple: if you cannot measure it, do not optimize it yet.
Write the eval task file first.

The TUI exposes the same optimization surfaces:

```text
:local optimize ...
:harness optimize --spec harness.yaml --tasks eval-tasks.yaml
:harness optimize-inspect <run_dir>
:harness optimize-ledger <run_dir>
:skills optimize <skill> --harness harness.yaml --tasks eval-tasks.yaml --live
:skillopt export <skill> --tasks eval-tasks.yaml --project <dir>
:skillopt check --baseline <path> --candidate <path>
```

## Measurement First

Optimization starts with SuperQode evals:

```bash
superqode harness eval \
  --spec harness.yaml \
  --tasks eval-tasks.yaml \
  --live \
  --json > eval-baseline.json
```

`harness eval` produces a scorecard across tasks. It also acts as a regression
gate when comparing variants: a candidate that breaks a task the baseline
solved exits non-zero unless explicitly overridden.

## Harness Optimization

Harness optimization improves the operating contract: model policy, context,
tools, approval rules, checks, workflow, and supporting instructions.

```bash
superqode harness optimize \
  --spec harness.yaml \
  --tasks eval-tasks.yaml \
  --eval-result eval-baseline.json \
  --backend codex \
  --apply
```

This bridge exports a project for the optional `metaharness` optimizer. It is
the right choice when the problem is not one skill, but the way the whole
harness is configured.

Use harness optimization for:

- weak model routing or runtime selection;
- missing or excessive tool permissions;
- bad workflow topology;
- missing checks;
- context and instruction assembly problems;
- policy changes that should live in `harness.yaml`.

See [Running, Measuring, and Optimizing a Harness](harness-optimization.md).

## Skill Optimization

Skill optimization improves one markdown skill while leaving the harness
contract stable. SuperQode uses GEPA for this path.

```bash
pip install "superqode[optimization]"

superqode skills optimize review \
  --engine gepa \
  --harness harness.yaml \
  --tasks eval-tasks.yaml \
  --live \
  --max-metric-calls 20
```

The command stages a candidate under:

```text
.superqode/skill-optimizations/<skill>-<timestamp>/
  baseline/SKILL.md
  staged/best_skill.md
  report.json
  report.md
```

The live skill is not overwritten. Review the staged skill, run held-out evals,
then adopt it deliberately.

Use skill optimization for:

- recurring mistakes that a reusable instruction can fix;
- repository-specific navigation or debugging patterns;
- review or implementation checklists;
- workflow guidance that should transfer across models and runtimes.

See [Skill Optimization](skill-optimization.md).

## SkillOpt Pattern

SuperQode’s skill optimization workflow follows the useful operational pattern
from SkillOpt:

- treat a compact skill document as trainable text state;
- use scored rollouts as evidence;
- make bounded edits instead of broad rewrites;
- keep a validation gate between proposals and adoption;
- deploy only the final skill artifact.

SuperQode does not require Microsoft SkillOpt as a runtime dependency. The
native workflow keeps the same safety shape while using SuperQode harness evals
and GEPA for the optimizer loop.

## GEPA Role

GEPA is the skill optimizer engine. SuperQode gives GEPA:

- the complete `SKILL.md` text as the candidate;
- eval tasks as the train/validation set;
- task score and failure detail as feedback;
- a staging directory for the best candidate.

The CLI exposes the main GEPA controls for budget and search behavior:

```bash
superqode skills optimize review \
  --harness harness.yaml \
  --tasks eval-tasks.yaml \
  --live \
  --candidate-selection pareto \
  --frontier-type hybrid \
  --acceptance strict_improvement \
  --use-merge \
  --cache-evaluation \
  --max-metric-calls 50
```

Start small. Increase budget only after the eval task file is stable.

## Custom And Native Optimizers

SuperQode’s native contract is intentionally simple:

```text
artifact + eval tasks -> scored candidate + staged proposal
```

A custom optimizer should follow the same boundary:

- read the baseline artifact;
- generate candidates in an isolated workspace;
- score candidates with `harness eval`;
- preserve scorecards and candidate diffs;
- stage the best candidate;
- never auto-apply without an explicit adoption step.

This makes custom optimizers interchangeable with the built-in GEPA and
metaharness paths.

## Choosing The Right Optimizer

| Symptom | Use |
|---|---|
| The model is slow, weak, or routed badly | `superqode local optimize` |
| The whole harness behaves poorly | `superqode harness optimize` |
| One reusable instruction is missing or weak | `superqode skills optimize --engine gepa` |
| You need an offline research loop over sessions | SkillOpt-style staging, then SuperQode eval gates |
| You have a domain-specific text artifact | Custom optimizer using the SuperQode eval contract |

## Recommended Workflow

```text
author harness -> write eval tasks -> measure baseline
       -> choose layer to optimize
       -> stage candidate
       -> run held-out eval
       -> review diff
       -> adopt
```

Optimization is a power tool. Keep the eval task file small and reliable at
first, then grow it as the workflow matures.
