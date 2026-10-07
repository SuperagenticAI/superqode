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

The fingerprint covers the normalized manifest plus task, HarnessSpec and live workspace fixture digests. `artifacts.json` covers every published file. `bench-verify` fails when a raw run, manifest, scorecard, or report was changed after the package was produced.

## Workspace isolation

Live benchmarks freeze `working_dir` once before execution. Every repetition
receives a fresh copy; `harness eval` also creates a fresh workspace and harness
session for every task and variant. Disposable RLM cells use an in-process
session and close it after execution, so resident workers do not outlive their
fixtures; this execution mode is recorded in task evidence. Ordinary RLM
sessions retain their resident behavior. A candidate cannot inherit files written by
the baseline or a previous task. Temporary fixtures are removed after execution,
including failed runs. Benchmark output stays in the requested output directory.

For a Git repository root, fixtures include tracked and non-ignored untracked
files, retaining local edits and deletions. Each copy has independent Git
metadata pinned to the recorded base commit, without a remote pointing back to
the source. The Git index starts at that base commit; source staging state is
not reproduced. Live evaluations refuse inherited Git repository overrides,
including `GIT_DIR`, `GIT_WORK_TREE` and `GIT_INDEX_FILE`; clear those variables
before running so Git commands cannot redirect into the source repository.
Git-ignored files, dependency directories, caches and session ledgers
are omitted. Project `.superqode/policy.yaml` is retained even when ignored. Plain
directories are also supported. External or looping symlinks are rejected;
internal absolute symlinks are rewritten to stay within the fixture. Git
submodule fixtures require separate preparation. Fixtures are limited to
50,000 entries and 256 MiB of file content, excluding Git history.

Prepare fixture inputs explicitly rather than depending on an ignored virtual
environment or generated files. Tools keep their existing host and sandbox
permissions; disposable copies do not introduce an OS security boundary.
Absolute paths and external services are outside this file-isolation contract.

Raw task results record `workspace_fixture` with a content digest and Git base,
plus requested backend/provider/model and sandbox configuration. Provider-side
model identity remains unverified. Setup time is recorded separately per task;
variant wall time includes fixture creation and cleanup. Recovery identities include the fixture
digest, so committed results are reused only for matching input snapshots.

For observed local runtime boundaries, run `sq harness certify builtin --json`.
See [the certification command](../cli-reference/harness-commands.md#harness-certify)
for its scope and incomplete-result gate.

## Publishing rules

For a public scorecard:

1. use a committed task suite and HarnessSpecs
2. include at least one held-out manifest
3. run multiple repetitions when the model is stochastic
4. publish the entire directory, including raw failures
5. state the provider, model, runtime, sandbox, date, and SuperQode version
6. run `bench-verify` in CI before publishing

HarnessBench is evidence, not a universal leaderboard. Its claim is deliberately narrower and reproducible: the observed harness effect for one fixed workload and model configuration.

For a start-to-finish path that includes a headless smoke test and Terminal-Bench 4.0, see [Benchmarking SuperQode](benchmarking.md).
