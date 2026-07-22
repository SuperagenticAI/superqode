# Running, Measuring, and Optimizing a Harness

Running, measuring, and optimizing a harness are separate operations. SuperQode performs execution and measurement. The optional `metaharness` integration performs iterative optimization.

For the broader picture across local model routing, harness specs, markdown
skills, and custom optimizers, see [Optimization Story](optimization.md).

| Job | Question it answers | Tool |
| --- | --- | --- |
| **Run** | "Do the work with this harness." | SuperQode (`superqode --harness ...`) |
| **Measure** | "Is this harness good right now?" | SuperQode (`harness test` / `eval` / `auto-bench`) |
| **Optimize** | "Make this harness better over many tries." | `superqode harness optimize` + `metaharness` (optional, recommended) |

## Run and measure: SuperQode

SuperQode is where you author, run, and measure a harness.

Run a task through a harness:

```bash
superqode --harness superqode.local.yaml
```

Measure whether the harness is ready and where it is weak:

```bash
superqode harness test --spec superqode.local.yaml      # fast readiness + failure digest
superqode harness eval --spec superqode.local.yaml      # scorecard across tasks and variants
superqode harness auto-bench --spec superqode.local.yaml # first-run setup recommendations
```

Measuring is a single pass: it tells you the current score and what failed. It does not change your harness. You read the result and edit the harness yourself (or with `harness wizard`).

`harness eval` also enforces a **seesaw gate**: if a candidate spec (passed with `--variant`) regresses any task the baseline solved, the command exits non-zero. Use it to verify an optimized harness before you trust it:

```bash
superqode harness eval --spec base.yaml --variant optimized.yaml --tasks tasks.yaml
```

The failure digest from `harness test` also tags each failure with one of nine harness dimensions (model selection, context assembly, memory, tools, execution, evaluation, control/safety, observability, training bridge), so it points at the spec field to change.

## Optimize: `harness optimize` + metaharness (optional)

Optimization uses an outer loop to modify the `HarnessSpec` and related instruction, setup, validation, test, and routing files. It retains the highest-scoring candidate and stores evidence for every attempt.

The optimizer is the separate, optional [`metaharness`](https://github.com/SuperagenticAI/metaharness) package, an open-source implementation of the Meta Harness paper. Install it only on systems that require optimization:

```bash
uv tool install superagentic-metaharness
```

The `harness optimize` command exports the specification and tasks to a metaharness project, runs the optimization, and can apply the selected specification:

```bash
# Export a metaharness project from your harness + tasks, run it on a local model,
# and write the best result back to the spec.
superqode harness optimize \
  --spec superqode.local.yaml \
  --tasks tasks.json \
  --backend codex --oss --local-provider ollama --model qwen3-coder:30b-a3b \
  --apply
```

Useful options:

| Option | What it does |
| --- | --- |
| `--tasks PATH` | The tasks the optimizer scores candidates against (required) |
| `--export-only` | Create the metaharness project but do not run it |
| `--apply` / `--output PATH` | Write the best candidate spec back (to `--spec` or `--output`) |
| `--test-result FILE` / `--eval-result FILE` | Feed prior `harness test --json` / `harness eval --json` output in as evidence |
| `--backend` | `codex` (validated), plus experimental `gemini` / `omnigent`; `fake` for a dry run |
| `--oss --local-provider {ollama,lmstudio} --model` | Optimize using your local models, not a hosted API |

If `metaharness` is unavailable, `harness optimize` reports the required installation command. Optimization is not required for harness execution or measurement.

## Operation selection

- Use **Run** to execute tasks with a configured harness.
- Use **Measure** to assess one harness or compare multiple harnesses with `harness test` and `harness eval`.
- Use **Optimize** to generate and evaluate changes to the harness and its associated scripts with the optional `metaharness` package.

Example end-to-end flow:

```text
superqode local init                          # author a local harness
superqode harness eval --spec ... --json      # measure it (save the scorecard)
superqode harness optimize --spec ... \        # optimize it (optional; uses metaharness)
  --tasks tasks.json --eval-result eval.json --apply
superqode --harness ...                        # run the improved harness
```

## Related

- [Harness System](harness-system.md): the full HarnessSpec reference.
- [Harness Commands](../cli-reference/harness-commands.md): `test`, `eval`, `auto-bench`, and the rest.
- [Bring Your Own Harness](../getting-started/bring-your-own-harness.md): author and edit a harness.
- [metaharness](https://github.com/SuperagenticAI/metaharness): the optional optimization tool.
