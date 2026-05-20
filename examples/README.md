# SuperQode Harness Examples

These examples are small HarnessSpec files you can copy, edit, and run.

Start with `coding.yaml` unless you already know which backend you want.

```bash
superqode harness validate examples/harnesses/coding.yaml
superqode harness doctor --spec examples/harnesses/coding.yaml
superqode harness run --spec examples/harnesses/coding.yaml --prompt "summarize this repository"
```

After a run, inspect the stored trace:

```bash
superqode harness events <run-id>
superqode harness graph <run-id>
```

## Choose An Example

| Goal | Example |
| --- | --- |
| General coding with file and shell tools | `harnesses/coding.yaml` |
| Planning and design with no tools | `harnesses/no-tool.yaml` |
| PydanticAI with typed-output-friendly tools, fallbacks, and optional Logfire | `harnesses/pydanticai.yaml` |
| DeepAgents for longer coding tasks with richer subagent and memory events | `harnesses/deepagents.yaml` |
| OpenAI Agents SDK with approvals and sandbox-aware tracing | `harnesses/openai-agents.yaml` |
| Google ADK-backed coding harness | `harnesses/google-adk.yaml` |
| Gemma4 local-model coding profile | `harnesses/gemma4.yaml` |
| DS4 fast local coding profile | `harnesses/ds4.yaml` |

## Optional Backends

Some examples require optional extras:

```bash
pip install "superqode[pydanticai]"
pip install "superqode[deepagents]"
pip install "superqode[openai-agents]"
pip install "superqode[adk]"
```

Use `superqode harness list-backends` to see what is installed in your environment.

