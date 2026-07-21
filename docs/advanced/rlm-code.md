# RLM Code Integration

SuperQode can run [RLM Code](https://github.com/SuperagenticAI/rlm-code) v0.1.11 or newer as a first-class harness backend.

The integration keeps the responsibility boundary explicit:

- **RLM Code** owns recursive REPL execution, symbolic context, programmatic subcalls, root-observation policy, structural history, sandbox execution, and native JSONL trajectories.
- **SuperQode** owns the repository `HarnessSpec`, model and execution policy, portable sessions, canonical events, evidence, comparison, evaluation, and guarded optimization.

SuperQode does not copy RLM Code's implementation. It controls and measures it through a native adapter.

## Install

Install RLM Code into the same environment as SuperQode:

```bash
uv tool install "superqode[rlm-code]"
```

For a development checkout:

```bash
uv sync --extra rlm-code
```

The integration requires `rlm-code>=0.1.11,<0.2.0` because v0.1.11 added caller-owned context, the `lid` profile, root/submodel attribution, and the trajectory evidence consumed by this adapter.

Check discovery and backend availability:

```bash
superqode harness list-backends
superqode harness protocol list
superqode harness protocol describe rlm-code
```

## Run the LID example

The maintained example is [`examples/harnesses/rlm-code-lid.yaml`](https://github.com/SuperagenticAI/superqode/blob/main/examples/harnesses/rlm-code-lid.yaml).

Start Ollama with a suitable local model, then run:

```bash
superqode harness doctor --spec examples/harnesses/rlm-code-lid.yaml
superqode harness run \
  --spec examples/harnesses/rlm-code-lid.yaml \
  --provider ollama \
  --model qwen3:8b \
  --prompt "Map this repository's architecture and cite the evidence used"
```

After the run, inspect the normalized evidence:

```bash
superqode harness events <run-id>
superqode harness graph <run-id>
superqode harness evidence <run-id>
```

The native RLM JSONL trajectory is stored under `.superqode/rlm-code/runs/` by default and is also recorded as an `artifact.created` event.

## Architecture

```text
HarnessSpec / Harness Protocol session
              │
              ▼
     RLMCodeHarnessBackend
              │
              ▼
        RLMRunner v0.1.11+
              │
      PureRLMEnvironment
              │
     Docker / Monty sandbox
              │
              ▼
  native JSONL trajectory + result
              │
              ▼
SuperQode events, graph, evidence and evals
```

There are two public integration surfaces:

| Surface | Use it when |
| --- | --- |
| `runtime.backend: rlm-code` | A repository owns a repeatable RLM configuration in its `HarnessSpec`. |
| `RLMCodeHarnessProtocolAdapter` | A controller or installed harness client needs the portable Harness Protocol lifecycle directly. |

Both surfaces use the same backend and evidence normalization.

## HarnessSpec configuration

Configure the backend under `runtime.config.rlm_code`:

```yaml
runtime:
  backend: rlm-code
  config:
    rlm_code:
      profile: lid
      context_profile: evidence
      max_steps: 12
      exec_timeout: 90
      sandbox_backend: docker
      root_observation_mode: opaque
      history_policy: offload
      decomposition_hint: true
      max_root_history_chars: 40000
      history_preserve_last: 2
      max_iteration_output_chars: 12000
      output_mode: summarize
      max_depth: 0
      parallelism: 2
```

### Execution and context options

| Field | Default | Meaning |
| --- | --- | --- |
| `profile` | `lid` | `reference`, `repo_evidence`, or `lid`. |
| `context_profile` | `evidence` | `auto`, `mini`, `evidence`, `full`, or `explicit`. |
| `context_paths` | empty | Explicit repository paths to place in the RLM context variable. |
| `context_include` / `context_exclude` | empty | File-selection patterns passed to RLM Code. |
| `root_observation_mode` | profile default | `configured`, `raw`, `metadata`, or `opaque`. |
| `history_policy` | profile default | `full`, `structural`, or `offload`. |
| `decomposition_hint` | profile default | Encourage focused subcalls rather than one monolithic delegation. |
| `max_root_history_chars` | `40000` | Offload structural history after this root-history budget. |
| `history_preserve_last` | `2` | Recent root turns retained when older history is offloaded. |
| `max_iteration_output_chars` | `12000` | Bound one REPL iteration's root-visible output. |
| `output_mode` | `summarize` | `truncate`, `summarize`, or metadata-only output shaping. |
| `max_steps` | agent/model policy | Maximum RLM root iterations. |
| `exec_timeout` | `60` | Timeout for one REPL action. |
| `time_budget_seconds` | recursion budget | Overall run budget. |
| `branch_width` | `1` | Root action candidates considered per step. |
| `parallelism` | workflow policy | Maximum RLM parallel work. |
| `sub_provider` / `sub_model` | root route | Optional separate route for programmatic subcalls. |
| `run_dir` | `.superqode/rlm-code/runs` | Native RLM trajectory directory. |

`context` may also be supplied programmatically as message metadata named `rlm_context`. Caller-owned context is passed through without being replaced by repository discovery.

### Sandbox policy

RLM Code supports `docker`, `monty`, and an explicitly unsafe `exec` backend. SuperQode defaults this integration to Docker even when a generic run request says `local`.

```yaml
execution_policy:
  sandbox: docker
  allow_read: true
  allow_write: false
  allow_shell: false
  allow_network: false
```

Network access is denied unless both the HarnessSpec and RLM configuration allow it. The in-process `exec` backend additionally requires `runtime.config.rlm_code.allow_unsafe_exec: true`; do not use it for untrusted model-generated code.

When `execution_policy.sandbox` is explicitly `docker` or `monty`, the nested RLM setting cannot replace it with a different backend. This prevents a runtime-specific option from weakening the repository-owned policy.

## Evidence mapping

SuperQode preserves the native trajectory and adds normalized events:

| RLM evidence | SuperQode event |
| --- | --- |
| root run request and selected profiles | `model_request` (`model.requested` at the protocol boundary) |
| each RLM action | `tool_call` (`tool.requested`) with `tool_name: rlm_repl` |
| observation, reward, step usage, and role usage | `tool_result` (`tool.completed`) |
| context source, selected files, exposure policy, structural actions | `validation.completed` |
| native JSONL trajectory | `artifact.created` |
| aggregate root/submodel usage and harness metrics | `model_result` (`model.completed`) |

The final response becomes the ordinary assistant `message.created` event. Protocol controllers then persist and export all of this through the same ledger used by Core, Python, and ACP harnesses.

Important measurements include:

- root calls versus submodel calls;
- root and submodel token attribution;
- root-exposed and root-hidden characters;
- repository context profile and source;
- structural actions and history offload count;
- reward, steps, completion state, and original RLM run ID.

## Direct Harness Protocol use

Python callers can register the adapter directly:

```python
from pathlib import Path

from superqode.harness import (
    HarnessCreateRequest,
    HarnessProtocolController,
    RLMCodeHarnessProtocolAdapter,
)

adapter = RLMCodeHarnessProtocolAdapter(
    config={"profile": "lid", "context_profile": "evidence"}
)
controller = HarnessProtocolController([adapter])
session = await controller.create(
    HarnessCreateRequest(
        harness_id="rlm-code",
        provider="ollama",
        model="qwen3:8b",
        working_directory=Path.cwd(),
    )
)

async for event in controller.send(session, "Inspect the repository architecture"):
    print(event.type, event.data)
```

The adapter declares portable resume, cooperative cancellation, usage evidence, and RLM tool activity. It does not claim steering, approvals, native checkpoints, or token streaming.

Run protocol conformance against a connected model:

```bash
superqode harness protocol conformance rlm-code \
  --provider ollama \
  --model qwen3:8b
```

## Evaluation and optimization

Use normal SuperQode evals to compare RLM configurations with Core or another harness under the same model and task budget:

```bash
superqode harness eval \
  --spec examples/harnesses/rlm-code-lid.yaml \
  --variant examples/harnesses/local-recursive-dynamic.yaml \
  --tasks tasks.yaml \
  --provider ollama \
  --model qwen3:8b \
  --live
```

Good candidate surfaces are profile, context profile, step limit, decomposition guidance, root/submodel route, and history threshold. Keep these protected unless a human explicitly changes them:

- opaque root observation for `lid` evaluations;
- network and sandbox policy;
- held-out split boundaries;
- raw private context;
- human promotion requirements.

Trajectory similarity is evidence about structural generalization, not proof that a model learned a universally transferable policy. Keep correctness, cost, latency, leakage, and held-out performance in the same scorecard.

## RLM Code demonstrations

RLM Code v0.1.11 ships two demonstrations that complement the SuperQode adapter:

- `examples/july_harness_generalization/demo.py` is an API-key-free proof covering cross-domain correctness, 8× length extrapolation, context isolation, decomposed subcalls, structural similarity, and history offloading.
- `examples/aie_world_fair_2026/rlm_probe.py` is the maintained live probe from the AI Engineer World's Fair 2026 talk, with repository evidence and Docker-first execution.

Run those demonstrations in an RLM Code checkout, then use SuperQode for cross-harness comparison, durable evidence, policy, and optimization gates.

## Current limits

- RLM Code runs complete asynchronously but does not currently expose root-token streaming through this adapter.
- SuperQode stores the RLM trajectory but does not attempt to reconstruct private interpreter state during resume.
- Approval pauses are not exposed by the RLM runner.
- RLM Code's trajectory-similarity helpers remain owned by RLM Code; SuperQode records their outputs when they are part of benchmark evidence rather than maintaining a competing implementation.
- The backend is optimized for analysis and evidence-producing work. File mutation should remain disabled until a WorkOrder supplies explicit isolation, checks, and merge gates.
