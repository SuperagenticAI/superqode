# Running, Measuring, and Optimizing a Harness

Running, measuring, and optimizing a harness are separate operations.
SuperQode performs execution and measurement. It offers two staged outer-loop
optimizers: the existing optional `metaharness` integration and guarded GEPA
Omni optimization.

For the broader picture across local model routing, harness specs, markdown
skills, and custom optimizers, see [Optimization Story](optimization.md).

| Job | Question it answers | Tool |
| --- | --- | --- |
| **Run** | "Do the work with this harness." | SuperQode (`superqode --harness ...`) |
| **Measure** | "Is this harness good right now?" | SuperQode (`harness test` / `eval` / `auto-bench`) |
| **Refine one task** | "Try instruction changes while completing this task." | `harness refine` with Harness2 and CodeGem |
| **Optimize** | "Make this harness better over many tries." | `harness optimize` with `metaharness`, or `harness optimize-omni` with GEPA |

## Run and measure: SuperQode

For task-local refinement through CodeGem, see
[Harness2 task refinement](harness2.md). It supports local Gemma and Gemini,
separate attempt workspaces, a CLI/TUI workflow, and explicit patch application.

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

## Optimize with GEPA Omni

`harness optimize-omni` treats the complete YAML HarnessSpec as the candidate
artifact. Omni explores with GEPA, AutoResearch, and GEPA meta-harness in
parallel and continues from the strongest result:

```bash
superqode harness optimize-omni \
  --spec superqode.local.yaml \
  --tasks tasks.yaml \
  --max-evals 20 \
  --max-token-cost 4 \
  --live
```

This path is intentionally staging-only. Before any rollout, SuperQode parses
and audits each candidate against the baseline's `optimization` policy.
After optimization it runs a separate held-out baseline-versus-candidate
seesaw gate. The live specification is never overwritten.

Use this path when you want several optimization strategies to compete on the
same eval contract. Keep `harness optimize` when you want the existing
standalone metaharness project, file-surface export, and explicit apply flow.

### Tiny subscription experiment

For the guided path, run the checked-in script. It performs local preflight
checks, prints the exact bounded command, and asks before making any model call:

```bash
# One-evaluation subscription smoke test (recommended first)
scripts/run_tiny_omni_experiment.sh \
  --spec examples/harnesses/omni-tiny-local.yaml

# Release-quality bounded Omni run
scripts/run_tiny_omni_experiment.sh \
  --spec examples/harnesses/omni-tiny-local.yaml \
  --mode omni
```

The script uses `uv run --with` to load the pinned, tested GEPA Omni commit for
the command, so it does not require a permanent GEPA installation. It requires
`ANTHROPIC_API_KEY` for the optimizer and stops with instructions when that key
is absent, Ollama is unavailable, or the chosen model is not installed. It does
not reuse Claude Code subscription credentials. Pass `--help` to see path and output options. The
prepared example uses `qwen3.5:9b` for both local rollouts and GEPA reflection.
Smoke mode uses one held-in and one held-out plumbing task. Omni mode uses three
held-in decision cases and two distinct sealed held-out cases.

Start with a single AutoResearch evaluation. This verifies Anthropic API
authentication and the end-to-end staging path before spending the minimum
four-evaluation Omni budget. It is a plumbing check, not optimization evidence:

```bash
superqode harness optimize-omni \
    --spec path/to/your-harness.yaml \
    --tasks examples/evals/omni-tiny.yaml \
    --engine autoresearch \
    --provider ollama \
    --model qwen3.5:9b \
    --optimizer-model haiku \
    --max-evals 1 \
    --max-token-cost 0.10 \
    --output .superqode/harness-optimizations/subscription-smoke \
    --live
```

For a release experiment, give each of the four Omni phases enough budget for
one baseline and one candidate pass over the three optimizer-visible cases:

```bash
superqode harness optimize-omni \
    --spec path/to/your-harness.yaml \
    --tasks examples/evals/omni-release.yaml \
    --engine omni \
    --continuation-engine gepa \
    --provider ollama \
    --model qwen3.5:9b \
    --reflection-lm ollama/qwen3.5:9b \
    --optimizer-model haiku \
    --max-evals 24 \
    --explore-max-evals 6 \
    --max-token-cost 2 \
    --max-workers 1 \
    --output .superqode/harness-optimizations/omni-tiny \
    --live
```

The 24-evaluation budget gives six evaluation units to GEPA, AutoResearch, and
GEPA meta-harness, followed by six for GEPA continuation. The final
baseline-versus-candidate gate adds four short local-model rollouts across two
sealed cases. The three explorers still start in parallel; `--max-workers 1`
bounds candidate evaluation concurrency inside each engine.

The optimizer-model cap is an API-price-equivalent guard passed to Claude
Code's print mode. It does not require an API key, but it still consumes your
subscription allowance and can use extra usage if you enabled that separately
in your Claude account. `haiku` minimizes Claude usage, while the rollout model
and GEPA reflection model remain local. Before running, sign in through
`claude`, check `/status`, and start Ollama. Override `--model` if you want a
different installed model.

The supplied release task file remains a controlled demonstration rather than
a statistical benchmark. Replace it with representative project tasks before
making production claims. The command never modifies the source HarnessSpec.

## Operation selection

- Use **Run** to execute tasks with a configured harness.
- Use **Measure** to assess one harness or compare multiple harnesses with `harness test` and `harness eval`.
- Use **Optimize** to generate and evaluate changes to the harness and its associated scripts with the optional `metaharness` package.
- Use **Optimize with Omni** for a staged, policy-audited complete-spec search
  with parallel GEPA engines and a sealed held-out gate.

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
- [GEPA Omni Integration Experiment](gepa-omni-experiment.md): reproducible
  subscription-plus-local release evidence.
- [Harness Commands](../cli-reference/harness-commands.md): `test`, `eval`, `auto-bench`, and the rest.
- [Bring Your Own Harness](../getting-started/bring-your-own-harness.md): author and edit a harness.
- [metaharness](https://github.com/SuperagenticAI/metaharness): the optional optimization tool.
