# Harness2 task refinement

Harness2 refines the instructions used to complete one coding task. SuperQode
runs the task with CodeGem, proposes instruction changes, tries those changes
in separate workspaces, and produces a final patch for you to inspect and apply.
The integration is based on
[Google Research Harness2](https://github.com/google-research/harness2).

Available in SuperQode **2.24.0 and later**, this is an experimental, opt-in
feature. It runs above the CodeGem executor and supports Gemini through the
Google API or local Gemma. It can use more time and tokens than an ordinary
CodeGem run, and refinement does not guarantee a better result.

## Start in the TUI

Launch `superqode` in your project, then enter:

```text
:harness refine
```

You can also open `:hub` and choose **Harness² refine**. In the refinement panel:

1. Select a provider and enter its model ID.
2. Set the source directory and a new output directory.
3. Describe the coding task. Add a check command and any files that must remain
   unchanged, such as an existing regression test.
4. Choose **Plan** to review the model, execution count, limits, and paths.
5. Choose **Start** to run the job and follow its progress.
6. Choose **Inspect** to review the final patch, generated instructions, and
   check results. **Apply** becomes available when the selected result passes
   your explicit checks.

Protected file names are relative to the source directory. Separate multiple
names with spaces and quote names containing spaces. **Cancel** or Escape stops
the job and leaves the panel open for inspection; press Escape again to return.

## Run with Gemini

Configure a Google provider key through SuperQode or set `GEMINI_API_KEY` or
`GOOGLE_API_KEY` in your environment. See
[CodeGem's Gemini setup](codegem.md#use-gemini-through-the-google-api).
Use a Gemini model available to your account:

```bash
superqode harness refine \
  --provider google --model gemini-3.1-flash-lite \
  --source /path/to/project \
  --prompt "Fix the failing regression test with a focused source change." \
  --output /path/to/refinement-job \
  --check 'python -m pytest -q' \
  --protect tests/test_regression.py \
  --max-sessions 10 --max-turns 16 --max-seconds 600 \
  --dry-run
```

Replace the source, output, check command, and protected file with paths that
exist in your project. Remove `--dry-run` to execute. The preview makes no model
calls and creates no job files. Use `--task-file /path/to/task.md` instead of
`--prompt` when the task is saved in a file.

## Run with local Gemma

Start your local model server. For Ollama, use a Gemma model installed on your
machine and save the following as `harness2.yaml`:

```yaml
name: harness2-local
inherits: codegem
runtime:
  backend: codegem
  config:
    tool_mode: json
    context_window: 32768
model_policy:
  primary: ollama/gemma4:12b
optimization:
  enabled: true
  config:
    method: harness2
    mode: sequential
    k: 1
    max_parallel: 1
    max_sessions: 10
    max_turns: 16
    max_output_tokens: 4096
    max_wall_seconds: 600
```

Then run:

```bash
superqode harness refine \
  --spec /path/to/harness2.yaml \
  --source /path/to/project \
  --task-file /path/to/task.md \
  --output /path/to/refinement-job \
  --check 'python -m pytest -q' \
  --protect tests/test_regression.py \
  --dry-run
```

The model route comes from `model_policy.primary`; `--provider` and `--model`
can select an explicit route. This example uses JSON tool mode for local Gemma.
No Google API key is needed for local execution. The repository also includes
[`examples/harnesses/harness2-codegem.yaml`](https://github.com/SuperagenticAI/superqode/blob/main/examples/harnesses/harness2-codegem.yaml).

## Workspaces and checks

Every coding attempt starts from the same source snapshot in a separate working
directory. The original project changes only when you explicitly apply the
selected patch. CodeGem tools run with host permissions: workspace copies do
not provide an OS sandbox, and commands can affect files outside those copies.
Use a trusted project and review commands you supply as checks.

Snapshots exclude Git metadata, dependency directories, caches, `.superqode`,
`.env*`, `*.pem`, and `*.key`. At a Git root they also respect Git ignores.
File symlinks are rejected and directory symlinks are omitted. The snapshot
limit is 2 MiB per file and 32 MiB total; choose a smaller source directory for
larger projects. A job output directory inside the source must be under
`.superqode/`.

`--check` is repeatable. Commands run without an implicit shell, with a
120-second limit per check inside the job's overall time limit. Dependency
directories are excluded from copies, so use an interpreter from your existing
environment when needed, such as `/path/to/venv/bin/python -m pytest -q`.
Checks that modify candidate source files fail validation.

`--protect` is also repeatable. It rejects an attempt that changes a named file;
it does not prevent the model from reading that file. Check commands and their
output are available to the refinement process. Keep private evaluation checks
outside the source directory and the public check list.

Without an explicit check, the result is marked `unchecked` and application is
disabled. Passing checks establishes only the properties those commands test.

## Inspect, cancel, resume, and apply

```bash
superqode harness refine inspect /path/to/refinement-job --json
superqode harness refine cancel /path/to/refinement-job
superqode harness refine resume /path/to/refinement-job --json
superqode harness refine apply /path/to/refinement-job
```

The output directory contains the result and check output, `selected.patch`,
and `selected-harness.json` with the generated instructions. Native run records
are retained for troubleshooting. Use `--json` for machine-readable execution
or inspection results.

In the TUI, enter an existing output directory and choose **Open**, or use:

```text
:harness refine inspect /path/to/refinement-job
```

Choose **Resume** to continue a saved job. Completed work is reused only when
the saved inputs and files still match. Changes to the source, task, model, or
harness settings require a new output directory. Keep the same model version
loaded when resuming a local model alias.

An interrupted stage may have uncertain tool effects. Inspect those effects
before using `resume --retry-interrupted` or selecting the TUI's interrupted
retry checkbox. Retrying preserves the earlier attempt's evidence.

Application requires passing explicit checks and an unchanged original source
snapshot. If your project changed since the job started, reconcile the patch
or start a new job. Applying updates the task's source files; it does not install
the generated instructions as your default harness. A process crash during
application can require manual reconciliation.

## Modes and resource limits

The default `k=1` job schedules four coding attempts and three instruction
editing/composition sessions. Each session can make multiple model requests.
Invalid editor replies can be retried once, so allow up to ten sessions for
the initial job. A rejected edit retains the existing instructions.

| Option | Default | Purpose |
| --- | --- | --- |
| `--mode` | `sequential` | Carry changes forward, or propose independent changes with `parallel` |
| `--k` | `1` | Refinement rounds/candidates, from 1 to 4 |
| `--max-parallel` | `1` | Maximum simultaneous sessions, from 1 to 4 |
| `--max-sessions` | `64` | Maximum admitted sessions, including editor retries, in this invocation |
| `--max-seconds` | `900` | Overall time limit for this invocation |
| `--max-turns` | `12` | Maximum turns in each coding session |
| `--max-output-tokens` | `4096` | Output token limit per model turn |

Explicit CLI options override `optimization.config` in the harness file.
Resume uses a new invocation's limits and reports earlier usage separately.
Unknown cost or token measurements remain unknown. These controls bound work;
the general `harness refine` command does not enforce a dollar spending cap.

Higher `k` values increase the number of attempts and editing sessions. The
parallel mode controls how proposals are made; `--max-parallel` controls how
many sessions actually execute at once. Begin with `k=1` and one active session.

## Supported scope

Harness2 currently uses CodeGem and one provider/model route for all stages.
It changes instruction, memory-note, and tool-guidance text, with at most
12,000 characters combined. Tool schemas, model selection, permissions, and
check commands remain outside the editable instruction set. Ambient skills
and prompt templates are disabled during refinement.

Other executors, generated executable helpers, skill mutation, cross-task
libraries, and automatic persistent harness promotion are not supported in
this integration. Ordinary `harness run` keeps its usual behavior; refinement
starts only through `harness refine` or the TUI action.
