# SuperQode Harness Examples

These examples are small HarnessSpec files you can copy, edit, and run.

Start with `coding.yaml` unless you already know which backend you want.

```bash
superqode harness validate --spec examples/harnesses/coding.yaml
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
| Omnigent-style orchestrator with researcher, coder, reviewer, and persistent child sessions | `harnesses/omnigent-multi-agent.yaml` |
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

## Omnigent-Style Import Smoke

`examples/omnigent-multi-agent.agent.yaml` shows the concise Omnigent-style
authoring shape. To verify import, MCP preservation, delegated child agents, and
`agent_session` resume behavior without external credentials:

```bash
uv run python scripts/smoke_omnigent_agent_sessions.py
```
