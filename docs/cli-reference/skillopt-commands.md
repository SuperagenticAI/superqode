# SkillOpt Commands

`superqode skillopt` provides lower-level utilities around bounded skill edits
and SkillOpt-style workspaces. Most users should start with
`superqode skills optimize`.

```bash
superqode skillopt COMMAND [ARGS]...
```

## check

Check a candidate skill against the bounded-edit safety gate.

```bash
superqode skillopt check \
  --baseline .superqode/skill-optimizations/run/baseline/SKILL.md \
  --candidate .superqode/skill-optimizations/run/staged/best_skill.md
```

| Option | Purpose |
| --- | --- |
| `--baseline PATH` | Baseline skill file |
| `--candidate PATH` | Candidate skill file |
| `--max-edits INTEGER` | Maximum allowed edit operations, default `4` |
| `--max-bytes INTEGER` | Maximum candidate size, default `50000` |
| `--json` | Emit JSON |

## export

Export a SkillOpt-style workspace for one SuperQode skill.

```bash
superqode skillopt export review \
  --tasks eval-tasks.yaml \
  --project .superqode/skillopt/review
```

| Option | Purpose |
| --- | --- |
| `--tasks PATH` | Eval tasks to include |
| `--project PATH` | Workspace output path |
| `--root PATH` | Project root, default `.` |
| `--harness PATH` | Harness for generated eval gates |
| `--max-edits INTEGER` | Bounded edit limit, default `4` |
| `--live-eval` | Put `--live` in the generated harness eval gate |
| `--force` | Overwrite an existing project directory |
| `--json` | Emit JSON |

Related page: [Skill Optimization](../advanced/skill-optimization.md).

