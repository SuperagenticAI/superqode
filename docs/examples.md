# Harness Examples

SuperQode is your portable coding agent harness. It ships ready-to-run HarnessSpec examples in `examples/harnesses/`.

Use them when you want a complete starting point instead of generating a minimal template.

```bash
superqode harness validate --spec examples/harnesses/coding.yaml
superqode harness doctor --spec examples/harnesses/coding.yaml
superqode harness run --spec examples/harnesses/coding.yaml --prompt "summarize this repository"
```

## Which Example To Use

| Example | Use it when | Backend |
| --- | --- | --- |
| `coding.yaml` | You want the default repository coding harness with file, search, patch, shell, validation, approvals, and event storage. | `builtin` |
| `no-tool.yaml` | You want planning, architecture review, or summarization without filesystem, shell, network, or hidden repository context. | `builtin` |
| `pydanticai.yaml` | You want PydanticAI with SuperQode tools, fallback models, typed-output-friendly runs, and optional Logfire traces. | `pydanticai` |
| `deepagents.yaml` | You want a longer-running coding harness with subagent, memory, and rich graph events. | `deepagents` |
| `openai-agents.yaml` | You want OpenAI Agents SDK behavior with approval pauses and sandbox-aware event traces. | `openai-agents` |
| `google-adk.yaml` | You want to run through the Google ADK backend with SuperQode tool and permission policy. | `adk` |
| `gemma4.yaml` | You want a local Gemma-style coding profile with strict JSON tool calls and compact context. | `builtin` |
| `ds4.yaml` | You want fast local DS4 iteration with compact JSON tools and short session history. | `builtin` |

## Validate All Examples

From the repository root:

```bash
for spec in examples/harnesses/*.yaml; do
  superqode harness validate --spec "$spec"
done
```

## Check Optional Backends

Some examples require optional packages.

```bash
superqode harness list-backends
```

Install the backend you need:

```bash
pip install "superqode[pydanticai]"
pip install "superqode[deepagents]"
pip install "superqode[openai-agents]"
pip install "superqode[adk]"
```

Run `doctor` after installing:

```bash
superqode harness doctor --spec examples/harnesses/pydanticai.yaml
```

## Inspect A Run

Use `--json` on a run to get the `run_id`:

```bash
superqode harness run --spec examples/harnesses/coding.yaml --prompt "summarize this repository" --json
```

Then inspect the normalized timeline and graph:

```bash
superqode harness events <run-id>
superqode harness graph <run-id>
superqode harness graph <run-id> --json
```

## Customize Safely

The safest changes are:

- change `name` and `description`
- change `model_policy.primary`
- add or remove `model_policy.fallbacks`
- adjust `execution_policy.allowed_commands`
- change `approval_profile` between `deny`, `balanced`, and stricter team policies
- add project-specific `validation.custom_steps`

Run this before committing a customized spec:

```bash
superqode harness validate --spec my-harness.yaml
superqode harness doctor --spec my-harness.yaml
```
