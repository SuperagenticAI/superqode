# Running, Measuring, and Optimizing a Harness

These are three different jobs. SuperQode does the first two. A separate, optional tool, `metaharness`, does the third. Keeping them clear avoids a common confusion: "is `harness eval` the same as harness optimization?" No. They answer different questions.

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

Optimizing is a different, heavier job: an outer loop that **rewrites the harness for you** (the `HarnessSpec` plus instruction files like `AGENTS.md`, setup scripts, validation scripts, test scripts, routing) and keeps the best version, with stored evidence for every attempt.

SuperQode does not do this itself. The optimizer is a separate, **optional** tool, [`metaharness`](https://github.com/SuperagenticAI/metaharness) (an open-source implementation of the Meta Harness paper). You only install it when you want optimization:

```bash
uv tool install superagentic-metaharness
```

SuperQode bridges to it with one command, `harness optimize`, so you stay in the SuperQode workflow. It exports your spec and tasks into a metaharness project, runs the optimization, and can apply the winning spec back:

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

If `metaharness` is not installed, `harness optimize` tells you how to install it rather than failing silently. So optimization is genuinely optional: you never need it to run or measure, but it is the recommended path when you want the harness itself improved automatically, on your own models, with inspectable evidence.

## Which one do I use?

- Just getting a model working and answering tasks? **Run** it with SuperQode.
- Want to know if your harness is good, or compare two harnesses? **Measure** with `harness test` / `eval`.
- Measured it, it is not good enough, and you want the harness and its scripts improved for you? **Optimize** with `superqode harness optimize` (which uses the optional `metaharness`). This is the recommended path for serious harness improvement, and it is optional: you never need it to run or measure.

A natural end-to-end flow:

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
