---
title: Benchmarking SuperQode
description: How to run HarnessBench and Terminal-Bench 4.0.
---

# Benchmarking SuperQode

[HarnessBench](harnessbench.md) compares SuperQode harnesses on a fixed task set and model. It runs on the host and does not use ACP. Terminal-Bench 4.0 scores SuperQode as an agent on Harbor's 66-task suite. Harbor talks to SuperQode over ACP. Keep the two reports separate; they measure different things.

| Harness | Role | Headless |
| --- | --- | --- |
| `core` | Native loop: `read`, `write`, `edit`, `bash` | Start here. Default approvals are `balanced`; set `yolo` for unattended runs |
| `benchmark-coding` | Coding loop that applies a change and verifies it (`yolo`) | Use on Terminal-Bench 4.0 |
| `pipy` | Event-first loop, parallel tools, host permissions | `SUPERQODE_PURE_PERMISSIONS_HEADLESS=1` |
| `rlm` | One persistent `python` tool and child agents | Same env var. Lower `max_depth` and `max_children` on the first live run |

MCP is opt-in on a builtin spec (`runtime.config.mcp_servers`). These four templates leave it off.

## Headless smoke

```bash
curl -fsSL https://superqode.dev/install.sh | sh
export SUPERQODE_PROVIDER=deepseek
export SUPERQODE_MODEL=deepseek-v3
export DEEPSEEK_API_KEY=...

superqode -p --harness core --provider "$SUPERQODE_PROVIDER" --model "$SUPERQODE_MODEL" \
  "summarize this repository in 5 bullets"
```

Exit `0` means the run finished. `--mode json` emits `content`, `stopped_reason`, `success`, and `changes`. Swap provider, model, and key if you are measuring a different account.

```bash
SUPERQODE_PURE_PERMISSIONS_HEADLESS=1 \
superqode -p --harness pipy --provider "$SUPERQODE_PROVIDER" --model "$SUPERQODE_MODEL" \
  "summarize this repository in 5 bullets"

SUPERQODE_PURE_PERMISSIONS_HEADLESS=1 \
superqode -p --harness rlm --provider "$SUPERQODE_PROVIDER" --model "$SUPERQODE_MODEL" \
  "Inspect README.md with python and summarize the project"
```

## How to run HarnessBench

HarnessBench fingerprints **spec files on disk**. Names such as `core` are templates, so copy them to YAML first. `superqode harness init` writes that copy. The first argument is the spec `name`; `-o` is the file the manifest will hash.

```bash
superqode harness init core --template core -o core.yaml
superqode harness init benchmark-coding --template benchmark-coding -o benchmark-coding.yaml
superqode harness init pipy --template pipy -o pipy.yaml
superqode harness init rlm --template rlm -o rlm.yaml
```

In `core.yaml` set `execution_policy.approval_profile: yolo`. `benchmark-coding.yaml` already uses `yolo`. Leave PiPy and RLM as generated.

You also need a task file, one provider and model for every cell, an API key, and a disposable clone as `working_dir`. HarnessBench does not reset that directory between harnesses; prefer read-only tasks. A larger suite is `examples/bench/dspy-comprehension.yaml`.

```yaml
# tasks.yaml
tasks:
  - id: smoke-hello
    split: held-in
    prompt: "Reply with exactly: superqode harness ok"
    expect_contains: ["superqode harness ok"]
  - id: repo-readme
    split: held-out
    prompt: |
      Read README.md. Quote the first heading exactly.
    expect_contains: ["#"]
```

Scoring uses `expect_contains` on the response text.

```yaml
# harnessbench.yaml
schema_version: 1
id: core-vs-benchmark-coding
tasks: tasks.yaml
specs:
  - core.yaml
  - benchmark-coding.yaml
provider: deepseek
model: deepseek-v3
runtime: builtin
working_dir: /tmp/superqode-bench-clone
sandbox: local
split: all
repetitions: 3
live: true
```

The manifest must list at least two spec paths. A first run can be `core.yaml` and `benchmark-coding.yaml`. Add `pipy.yaml` and `rlm.yaml` on a later manifest. For those cells export `SUPERQODE_PURE_PERMISSIONS_HEADLESS=1`, and on `rlm.yaml` set `runtime.config.max_depth` to `1` and `max_children` to `2` until cost is known.

```bash
git clone --depth 1 https://github.com/example/repo.git /tmp/superqode-bench-clone

sq harness bench --manifest harnessbench.yaml --output results/core-vs-coding --dry-run
sq harness bench --manifest harnessbench.yaml --output results/core-vs-coding
sq harness bench-verify results/core-vs-coding
```

`--dry-run` checks packaging and skips model calls. `--live` / `--dry-run` override the manifest `live` field. Omit `--output` to write under `.superqode/harnessbench/` with the bench id and a UTC timestamp. `--json` prints the run payload.

A passing live run prints status, winner, fingerprint, and the scorecard path. The directory contains:

```text
results/core-vs-coding/
├── manifest.json
├── scorecard.json
├── scorecard.md
├── artifacts.json
└── raw/
```

`bench-verify` checks that those files still match the recorded checksums. Unknown cost or token fields stay `null`.

A published package includes committed specs and tasks, a held-out split, the full output directory (failures included), and a passing `bench-verify`. Record provider, model, runtime, sandbox, date, and SuperQode version.

Ready-made example in this repository:

```bash
# clone the target repo named in the manifest first
sq harness bench --manifest examples/bench/dspy-comprehension.manifest.yaml \
  --output results/dspy-comprehension
sq harness bench-verify results/dspy-comprehension
```

## How to run Terminal-Bench 4.0

Dataset: `terminal-bench/terminal-bench@4.0.0` ([release notes](https://www.tbench.ai/news/terminal-bench-4-0)). Sixty-six tasks, an eight-hour agent timeout, five trials on the public board. Earlier Terminal-Bench versions use a different task set.

Harbor has no built-in SuperQode agent (`-a superqode` is not a Harbor name). The path SuperQode ships is ACP: Harbor installs SuperQode from `install/acp-registry/superqode/agent.json` and runs `superqode serve acp` in the task container. Other Harbor `-a` values (`claude-code`, `codex`, `terminus-2`, `pi`) are those products.

[HarnessBench](harnessbench.md) does not use ACP. `sq harness bench` drives SuperQode harnesses on the host. Use that runner for Core, PiPy, and RLM comparisons that stay off ACP.

A Harbor job that skips ACP would need a custom Harbor installed agent wrapping `superqode -p`. SuperQode does not ship that adapter.

Harbor starts SuperQode inside each task container. Docker must be running on the host. Use `template:benchmark-coding` for the first job.

```bash
uv tool install harbor

export DEEPSEEK_API_KEY=...
export SUPERQODE_PROVIDER=deepseek
export SUPERQODE_MODEL=deepseek-v3
```

One trial (`-k 1`) from a SuperQode checkout:

```bash
harbor run -d terminal-bench/terminal-bench@4.0.0 \
  -a acp \
  --ak registry_entry_path=install/acp-registry/superqode/agent.json \
  --ak auth_policy=disabled \
  -m deepseek/deepseek-v3 \
  --ae SUPERQODE_ACP_SPEC=template:benchmark-coding \
  --ae SUPERQODE_PROVIDER=deepseek \
  --ae SUPERQODE_MODEL=deepseek-v3 \
  --ae DEEPSEEK_API_KEY \
  -k 1 \
  -n 1 \
  -o jobs/tb4-k1
```

| Flag | Meaning |
| --- | --- |
| `-d` | Dataset. Use `terminal-bench/terminal-bench@4.0.0` |
| `-a acp` | SuperQode via the registry manifest |
| `--ak registry_entry_path=...` | Local `install/acp-registry/superqode/agent.json` |
| `-m` | Model id Harbor forwards as `HARBOR_ACP_REQUESTED_MODEL` |
| `--ae` | Environment variable copied into the task container. Repeat per secret |
| `-k` | Trials per task. Start at `1`; the public board uses `5` |
| `-n` | Concurrent trials. Start at `1` |
| `-o` | Job directory |

After SuperQode is listed in the agent registry, `-a acp:superqode` replaces the `registry_entry_path` and `auth_policy` flags.

Inspect `jobs/tb4-k1` for failed tasks and timeouts. When that job finishes cleanly:

```bash
harbor run -d terminal-bench/terminal-bench@4.0.0 \
  -a acp \
  --ak registry_entry_path=install/acp-registry/superqode/agent.json \
  --ak auth_policy=disabled \
  -m deepseek/deepseek-v3 \
  --ae SUPERQODE_ACP_SPEC=template:benchmark-coding \
  --ae SUPERQODE_PROVIDER=deepseek \
  --ae SUPERQODE_MODEL=deepseek-v3 \
  --ae DEEPSEEK_API_KEY \
  -k 5 \
  -n 4 \
  -o jobs/tb4-k5
```

Same model, different SuperQode harness (keep `-m` fixed):

```bash
for t in core benchmark-coding pipy rlm; do
  harbor run -d terminal-bench/terminal-bench@4.0.0 \
    -a acp \
    --ak registry_entry_path=install/acp-registry/superqode/agent.json \
    --ak auth_policy=disabled \
    -m deepseek/deepseek-v3 \
    --ae SUPERQODE_ACP_SPEC=template:$t \
    --ae SUPERQODE_PURE_PERMISSIONS_HEADLESS=1 \
    --ae DEEPSEEK_API_KEY \
    -k 1 \
    -o jobs/tb4-$t
done
```

`core` pauses on approvals unless the spec uses `yolo`. Prefer `benchmark-coding` for the first full job. PiPy and RLM need `SUPERQODE_PURE_PERMISSIONS_HEADLESS=1` in the container.

Task containers cannot reach host loopback. For Ollama pass `--ae OLLAMA_HOST=http://host.docker.internal:11434`.

Record SuperQode version, template, provider, model, dataset id, trial count, and date.

## Order

1. Headless `core`, then optional `pipy` and `rlm` smokes.
2. Copy templates to YAML. HarnessBench `--dry-run`, then live `core.yaml` vs `benchmark-coding.yaml` with `repetitions: 3`.
3. `sq harness bench-verify`.
4. Optional second manifest that adds `pipy.yaml` and a capped `rlm.yaml`.
5. Harbor Terminal-Bench 4.0 with `-k 1` and `template:benchmark-coding`.
6. `-k 5` after that job finishes cleanly.

## See also

- [HarnessBench](harnessbench.md)
- [Headless and CI](headless-ci.md)
- [ACP agent server](acp-agent-server.md)
- [PiPy](pipy.md)
- [Native RLM](rlm.md)
- [Harbor Hub](https://hub.harborframework.com/datasets/terminal-bench/terminal-bench/4)
