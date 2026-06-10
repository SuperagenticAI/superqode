# A2A Protocol

The Agent-to-Agent (A2A) protocol enables SuperQode to communicate and coordinate with external A2A-compliant agents. This integration extends SuperQode into a multi-agent orchestration platform for coding-agent harness workflows.

---

## Overview

A2A is an open protocol backed by Google, IBM, and other major AI providers. It allows different AI agents to:

- Discover each other's capabilities through AgentCards
- Exchange messages and artifacts
- Coordinate on long-running tasks
- Work together without exposing private implementation details

SuperQode implements both A2A client and server capabilities, allowing you to call external agents or expose SuperQode as an A2A agent.

---

## Quick Start

### Install A2A Dependencies

```bash
pip install superqode[a2a]
```

### Connect to an A2A Agent

In the TUI, use the A2A command:

```bash
:a2a connect http://localhost:8000
```

### Discover Agent Capabilities

```bash
:a2a discover http://agent:8080
```

### Call an Agent

```bash
:a2a call myagent "Write a unit test for the auth module"
```

---

## Using A2A Tools

SuperQode includes two A2A tools that you can use within agent sessions:

### a2a_call

Call an external A2A-compliant agent directly from SuperQode:

```yaml
Tool: a2a_call
Arguments:
  - agent_url: URL of the A2A agent server
  - message: Task to send to the agent
  - agent_name: Optional name to cache the connection
```

Example usage in a prompt:

```text
Use a2a_call to call http://security-agent:8000 with message "Run a security scan on the codebase"
```

### a2a_discover

Discover and list A2A agents from a registry or direct URL:

```yaml
Tool: a2a_discover
Arguments:
  - registry_url: URL of agent registry or single agent
  - scan_known: Also scan known public A2A agents
```

---

## A2A Workflows

SuperQode supports multiple multi-agent orchestration patterns:

### Parallel Execution

Run multiple agents simultaneously and collect results:

```python
from superqode.a2a import A2AWorkflowEngine

engine = A2AWorkflowEngine()
result = await engine.parallel([
    {"url": "http://test-agent:8000", "prompt": "Run unit tests"},
    {"url": "http://security-agent:8000", "prompt": "Run security scan"},
    {"url": "http://lint-agent:8000", "prompt": "Run linter"},
])
```

### Sequential Execution

Run agents in sequence, passing results to the next agent:

```python
result = await engine.sequential([
    {"url": "http://dev-agent:8000", "prompt": "Write code"},
    {"url": "http://test-agent:8000", "prompt": "Test the code: {previous_result}"},
    {"url": "http://deploy-agent:8000", "prompt": "Deploy the tested code"},
])
```

### Fan-out/Fan-in

Dispatch to multiple workers and aggregate results:

```python
result = await engine.fan_out_fan_in(
    dispatcher_url="http://dispatcher:8000",
    worker_urls=["http://worker1:8000", "http://worker2:8000"],
    task="Process these 100 files"
)
```

---

## Workflow Presets

SuperQode includes pre-built workflow presets for common scenarios:

| Preset | Description | Pattern |
|--------|-------------|---------|
| `pre_commit` | Quick checks before commit: format, lint, unit tests | Parallel |
| `ci_pipeline` | Full CI pipeline: build, test, security, deps | Sequential |
| `review_cycle` | Automated code review: style, security, quality, smells | Parallel |
| `deploy` | Deploy application: build, test, push, deploy | Sequential |

### Using Presets

```python
from superqode.a2a import get_presets

presets = get_presets()

# List available presets
print(presets.list_presets("quality"))

# Get preset description
print(presets.describe_preset("pre_commit"))

# Run a preset
result = await presets.run("pre_commit", [
    {"url": "http://test:8000", "prompt": "Run tests"},
    {"url": "http://lint:8000", "prompt": "Run linter"},
])
```

---

## Skill Mapping

A2A skills from external agents can be mapped to SuperQode capabilities:

```python
from superqode.a2a import get_skill_mapper

mapper = get_skill_mapper()

# Map all skills from an agent card
mappings = mapper.map_skills(agent_card.skills)
# Returns list of SkillMapping with confidence scores
```

---

## Multi-Agent Analysis with A2A

Orchestrate external A2A agents from your workflow:

```python

# Run analysis with external A2A agents
result = await orch.run_a2a([
    "http://test-agent:8000",
    "http://security-agent:8000",
], task="Run full analysis")
```

---

## A2A Registry

Manage multiple A2A agent connections:

```python
from superqode.a2a import A2ARegistry

registry = A2ARegistry()

# Add and verify an agent
await registry.add("gemini", "http://localhost:8000")

# Find agents by skill
testers = registry.get_by_skill("testing")

# Save registry to file
registry.save()

# Load from file
registry.load()
```

---

## Exposing SuperQode as an A2A Agent

Run SuperQode as an A2A server so other A2A clients can call it:

```python
from superqode.a2a import create_a2a_server
from superqode.agent import AgentConfig

config = AgentConfig(
    provider="openai",
    model="gpt-4o",
)

server = await create_a2a_server(config, server_url="http://localhost:8000")
await server.start()
```

### Available Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /agentCard` | Returns agent metadata and skills |
| `POST /message:send` | Send a message and get response |
| `POST /message:stream` | Send with streaming response |
| `GET /tasks/{id}` | Get task state |
| `POST /tasks/{id}:cancel` | Cancel a running task |
| `GET /tasks/{id}:subscribe` | Subscribe to task updates |

---

## TUI Commands

All A2A operations are available through the TUI command:

| Command | Description |
|---------|-------------|
| `:a2a connect <url>` | Connect to an A2A agent |
| `:a2a list` | List connected agents |
| `:a2a discover <url>` | Discover agent at URL |
| `:a2a call <name> <msg>` | Call an agent |
| `:a2a workflow <type>` | Run workflow (parallel/sequential) |
| `:a2a remove <name>` | Remove an agent |
| `:a2a help` | Show help |

---

## Requirements

A2A functionality requires these dependencies:

```toml
# pyproject.toml
[project.optional-dependencies]
a2a = [
    "fastapi>=0.115.0",
    "uvicorn>=0.32.0",
]
```

Install with:

```bash
pip install superqode[a2a]
```

---

## See Also

- [ACP Agents](acp.md) - Alternative protocol for external agents
- [MCP Tools](../configuration/mcp-config.md) - Tool integration via Model Context Protocol
- [Session Management](../advanced/session-management.md) - Persistent conversation storage
