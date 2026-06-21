# Skills Commands

`superqode skills` manages and optimizes project skills. A skill is a markdown
artifact that teaches the harness a repeatable workflow, review style, tool
sequence, or project convention.

```bash
superqode skills COMMAND [ARGS]...
```

## optimize

Optimize a markdown skill with a staged GEPA run. The live skill is not
overwritten. SuperQode writes staged artifacts for review.

```bash
superqode skills optimize review \
  --engine gepa \
  --harness harness.yaml \
  --tasks eval-tasks.yaml \
  --live
```

Important options:

| Option | Purpose |
| --- | --- |
| `--harness PATH` | Harness used to evaluate candidates |
| `--tasks PATH` | Eval task file |
| `--output PATH` | Directory for staged artifacts |
| `--provider TEXT` | Provider for eval runs |
| `--model TEXT` | Model for eval runs |
| `--runtime TEXT` | Runtime or backend override |
| `--sandbox TEXT` | Sandbox profile, default `local` |
| `--reflection-lm TEXT` | Model used by GEPA for reflection |
| `--max-metric-calls INTEGER` | Evaluation budget |
| `--max-edits INTEGER` | Bounded edit limit |
| `--live` | Execute eval tasks against the configured model |
| `--json` | Emit JSON |

For workflow guidance, see [Skill Optimization](../advanced/skill-optimization.md).

