# Skill Optimization

SuperQode can optimize markdown skills with GEPA and stage the result for
review. Use this when a skill is useful but still misses recurring cases in
your eval tasks.

For the broader optimization model across harnesses, skills, local routing, and
custom optimizers, see [Optimization Story](optimization.md).

## Install

GEPA is optional:

```bash
pip install "superqode[optimization]"
```

The base SuperQode install does not include optimization dependencies.

## Run

```bash
superqode skills optimize review \
  --engine gepa \
  --harness harness.yaml \
  --tasks eval-tasks.yaml \
  --live \
  --max-metric-calls 20
```

From the TUI, use the same arguments after `:skills optimize`:

```text
:skills optimize review --harness harness.yaml --tasks eval-tasks.yaml --live --max-metric-calls 20
```

`--live` is required because optimization needs real eval scores. The command
does not overwrite the live skill. It writes staged artifacts under:

```text
.superqode/skill-optimizations/<skill>-<timestamp>/
  baseline/SKILL.md
  staged/best_skill.md
  report.json
  report.md
  gepa-run/
  evals/
```

Review `staged/best_skill.md` and run held-out evals before copying it over the
live `.agents/skills/.../SKILL.md`.

## Review

The optimizer output is a proposal. Review the staged skill and compare it
against the baseline:

```bash
diff -u \
  .superqode/skill-optimizations/<run>/baseline/SKILL.md \
  .superqode/skill-optimizations/<run>/staged/best_skill.md
```

Run the bounded-edit check before adoption:

```bash
superqode skillopt check \
  --baseline .superqode/skill-optimizations/<run>/baseline/SKILL.md \
  --candidate .superqode/skill-optimizations/<run>/staged/best_skill.md
```

Then run a held-out eval pack or a task file that was not used for the
optimization run.

## Tuning

Most runs only need `--max-metric-calls`, `--reflection-lm`, and `--max-edits`.
Use the advanced controls when you want to tune search cost or exploration:

| Option | Use |
|---|---|
| `--max-metric-calls` | Total evaluation budget |
| `--max-candidate-proposals` | Candidate proposal budget |
| `--max-reflection-cost` | Reflection LM cost cap |
| `--minibatch-size` | Reflection minibatch size |
| `--max-workers` | Parallel candidate evaluation workers |
| `--candidate-selection` | `pareto`, `current_best`, `epsilon_greedy`, or `top_k_pareto` |
| `--frontier-type` | `instance`, `objective`, `hybrid`, or `cartesian` |
| `--acceptance` | `strict_improvement` or `improvement_or_equal` |
| `--cache-evaluation` | GEPA candidate/example evaluation cache |
| `--use-merge` | GEPA merge proposals across frontier candidates |
| `--max-merge-invocations` | Merge proposal limit |
| `--reflection-lm` | Model used by GEPA for reflection |

Start with a small budget first. Increase `--max-metric-calls` only after the
eval task file is stable and has a clear pass/fail signal.
