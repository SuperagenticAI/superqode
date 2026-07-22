# HarnessBench

HarnessBench answers the product's central proof question: with the same tasks and the same model, what changes when only the coding-agent harness changes?

Unlike a one-off benchmark command, a HarnessBench run is a publishable package containing the exact manifest, source digests, every raw repetition, an aggregate scorecard, a Markdown report, and checksums.

## Create a manifest

```yaml
schema_version: 1
id: coding-heldout-july
tasks: eval-tasks.yaml
specs:
  - harness.yaml
  - candidate.yaml
provider: openai
model: gpt-5
runtime: builtin
working_dir: .
sandbox: docker
split: held-out
repetitions: 3
live: true
```

At least two HarnessSpecs are required. The provider and model are fixed for every cell; use another manifest for another model family.

## Run and verify

```bash
sq harness bench --manifest harnessbench.yaml
sq harness bench --manifest harnessbench.yaml --output results/july
sq harness bench-verify results/july
```

Use `--dry-run` to validate packaging without model calls. A dry run is not accepted as promotion evidence.

The output directory contains:

```text
results/july/
├── manifest.json
├── scorecard.json
├── scorecard.md
├── artifacts.json
└── raw/
    ├── run-001.json
    ├── run-002.json
    └── run-003.json
```

`scorecard.json` reports mean, population standard deviation, minimum, maximum, and reporting coverage for success, cost, tokens, and latency. It also preserves per-task outcomes, regression counts, quality/cost/latency ranking, and Pareto membership. Unknown provider cost or token usage stays `null`; it is never estimated as zero.

The fingerprint covers the normalized manifest plus task and HarnessSpec digests. `artifacts.json` covers every published file. `bench-verify` fails when a raw run, manifest, scorecard, or report was changed after the package was produced.

## Publishing rules

For a public scorecard:

1. use a committed task suite and HarnessSpecs
2. include at least one held-out manifest
3. run multiple repetitions when the model is stochastic
4. publish the entire directory, including raw failures
5. state the provider, model, runtime, sandbox, date, and SuperQode version
6. run `bench-verify` in CI before publishing

HarnessBench is evidence, not a universal leaderboard. Its claim is deliberately narrower and reproducible: the observed harness effect for one fixed workload and model configuration.

