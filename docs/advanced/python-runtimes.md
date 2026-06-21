# Python Runtimes API

## Overview

SuperQode provides a Python API to embed the agent runtime directly in your applications. The runtime system supports multiple backends through a common AgentRuntime protocol.

## Available Runtimes

| Name | Backend | Install |
|------|---------|---------|
| builtin | SuperQode native loop | always available |
| openai-agents | OpenAI Agents SDK | pip install superqode[openai-agents] |
| adk | Google Agent Development Kit | pip install superqode[adk] |
| pydanticai | PydanticAI agent framework | pip install superqode[pydanticai] |
| codex-sdk | OpenAI Codex Python SDK | pip install superqode[codex-sdk] |
| claude-agent-sdk | Anthropic Claude Agent SDK | pip install superqode[claude-agent-sdk] |

## create_runtime()

```python
from superqode.runtime import create_runtime

runtime = create_runtime("builtin", config=config, tools=tools)
response = await runtime.run("Write hello.txt")
```

Parameters: `name` (str or None, None = builtin), `**kwargs` forwarded to runtime constructor.

## resolve_runtime_name()

Resolves active runtime with precedence: CLI > YAML > env var > default (builtin).

```python
from superqode.runtime import resolve_runtime_name
name = resolve_runtime_name(cli="codex-sdk", env_var="SUPERQODE_RUNTIME")
```

## list_runtimes() / known_runtime_names()

```python
for info in list_runtimes():
    print(f"{info.name}: installed={info.installed}")
```

Each `RuntimeInfo` has `name`, `description`, `installed`, and `install_hint`.

## Codex SDK Python API

```python
from superqode.codex import run_codex, stream_codex, codex_session

# One-shot
response = run_codex("Summarize this repo", cwd="myproject")

# Streaming
async for event in stream_codex("Write tests", cwd="myproject"):
    print(event.type, event.data)

# Multi-turn session
with codex_session(cwd="myproject") as cx:
    models = cx.models()
    resp1 = asyncio.run(cx.run("Do first task"))
    resp2 = asyncio.run(cx.run("Do second task"))
```

Parameters: `prompt`, `model`, `cwd`, `provider`, `tools`, `system_prompt`, `require_confirmation`, `sandbox_backend`, `approval_callback`, `permission_manager`, `session_id`.

## Claude Agent SDK Python API

```python
from superqode.runtime import create_runtime
from superqode.agent.loop import AgentConfig

config = AgentConfig(model="<anthropic-balanced-model>", working_directory="myproject")
runtime = create_runtime("claude-agent-sdk", config=config)
response = await runtime.run("Explain this codebase")
runtime.close()
```

The `claude-agent-sdk` runtime supports model switching (`set_model`), reasoning effort (`set_reasoning_effort` with `low`/`medium`/`high`/`xhigh`/`max`), thread management (`list_threads`, `resume_thread`, `fork_thread`, `rename_thread`, `tag_thread`), and streaming (`run_streaming`, `run_harness_events`).
