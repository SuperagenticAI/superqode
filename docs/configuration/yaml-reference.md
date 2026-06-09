# YAML Reference

This page documents the `superqode.yaml` project configuration file loaded by SuperQode.

Use HarnessSpec files for run behavior such as runtime backend, model policy, tools, sandbox, approvals, checks, hooks, workflow, observability, and output schema. See [Harness System](../advanced/harness-system.md).

---

## File Discovery

SuperQode loads the first config file it finds:

1. `./superqode.yaml`
2. `~/.superqode.yaml`
3. `/etc/superqode/superqode.yaml`

---

## Top-Level Structure

```yaml
superqode:
  version: "1.0"
  team_name: My Project
  description: Project-specific SuperQode configuration
  runtime: builtin
  gateway:
    type: litellm
  cost_tracking:
    enabled: true
    show_after_task: true
  errors:
    surface_rate_limits: true
    surface_auth_errors: true

default:
  mode: byok
  provider: openai
  model: gpt-4o-mini

providers: {}
agents: {}
custom_models: {}
model_aliases: {}
mcp_servers: {}
```

---

## Top-Level Fields

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `superqode` | object | No | built-in defaults | Global SuperQode metadata and runtime/gateway settings |
| `default` | object | No | `null` | Default connection settings |
| `providers` | object | No | `{}` | Provider metadata and API key environment names |
| `agents` | object | No | `{}` | ACP agent metadata |
| `code_agents` | array | No | `[]` | Compatibility list of known code agents |
| `custom_models` | object | No | `{}` | Named model definitions mapped to provider/model pairs |
| `model_aliases` | object | No | `{}` | Short aliases for model references |
| `mcp_servers` | object | No | `{}` | MCP server definitions |
| `mcpServers` | object | No | `{}` | Compatibility spelling for MCP server definitions |
| `legacy` | object | No | `{}` | Compatibility bucket for old config data |

---

## `superqode`

```yaml
superqode:
  version: "1.0"
  team_name: My Project
  description: Project-specific SuperQode configuration
  runtime: builtin
```

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `version` | string | `"1.0"` | Project config format marker |
| `team_name` | string | `"My Development Team"` | Display name for the project or team |
| `name` | string | none | Compatibility alias for `team_name` |
| `description` | string | `"Multi-agent software development team"` | Human-readable description |
| `runtime` | string | `null` | Optional default runtime name |

### Gateway

```yaml
superqode:
  gateway:
    type: litellm
```

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `type` | string | `litellm` | Gateway type. Supported values are `litellm` and `openresponses` |

OpenResponses has additional defaults in code for `base_url`, reasoning effort, truncation, timeout, and built-in tool toggles. Configure OpenResponses behavior through provider setup and runtime-specific docs where possible.

### Cost Tracking

```yaml
superqode:
  cost_tracking:
    enabled: true
    show_after_task: true
```

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `enabled` | boolean | `true` | Enable cost tracking where provider metadata is available |
| `show_after_task` | boolean | `true` | Show a cost summary after tasks |

### Errors

```yaml
superqode:
  errors:
    surface_rate_limits: true
    surface_auth_errors: true
```

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `surface_rate_limits` | boolean | `true` | Show clearer rate-limit errors |
| `surface_auth_errors` | boolean | `true` | Show clearer authentication errors |

---

## `default`

The `default` section selects the default connection path for headless runs and initial project behavior.

### BYOK

```yaml
default:
  mode: byok
  provider: openai
  model: gpt-4o-mini
```

### Local

```yaml
default:
  mode: local
  provider: ollama
  model: qwen3:8b
```

### ACP

```yaml
default:
  mode: acp
  agent: opencode
```

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `mode` | string | inferred | `byok`, `acp`, or `local` |
| `provider` | string | `null` | Provider ID for BYOK or local mode |
| `model` | string | `null` | Model ID for BYOK or local mode |
| `agent` | string | `null` | ACP agent ID |
| `agent_config.provider` | string | `null` | Optional provider used inside an ACP agent |
| `agent_config.model` | string | `null` | Optional model used inside an ACP agent |
| `mcp_servers` | array | `[]` | MCP server IDs to make available |
| `expert_prompt_enabled` | boolean | `false` | Enables a custom expert prompt in compatible paths |
| `expert_prompt` | string | `null` | Custom expert prompt text |

`coding_agent`, `persona`, and `mcp` are accepted for compatibility with older config files. New config should use `agent`, `job_description`, and `mcp_servers`.

---

## `providers`

```yaml
providers:
  openai:
    api_key_env: OPENAI_API_KEY
    description: OpenAI API
    base_url: https://api.openai.com/v1
    recommended_models:
      - gpt-4o-mini
      - gpt-4o
    custom_models_allowed: true

  ollama:
    base_url: http://localhost:11434
    recommended_models:
      - qwen3:8b
```

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `api_key_env` | string | `""` | Environment variable containing the API key |
| `api_key` | string | `""` | Compatibility alias for `api_key_env` |
| `description` | string | `""` | Provider description |
| `base_url` | string | `null` | Provider endpoint |
| `endpoint` | string | `null` | Compatibility alias for `base_url` |
| `recommended_models` | array | `[]` | Suggested model IDs |
| `models` | array | `[]` | Compatibility alias for `recommended_models` |
| `custom_models_allowed` | boolean | `true` | Whether custom model IDs are allowed |

---

## `agents`

ACP agents can be listed in `agents`. SuperQode also has built-in agent discovery for known agents.

```yaml
agents:
  opencode:
    description: OpenCode coding agent
    protocol: acp
    command: opencode
    args: []
    capabilities:
      - file_editing
      - shell_execution
      - mcp_tools
```

The parser stores agent dictionaries as provided. Specific keys are consumed by ACP discovery and connection code.

---

## `custom_models` And `model_aliases`

Use `custom_models` when a short name should resolve to a provider/model pair:

```yaml
custom_models:
  fast-coder:
    provider: openai
    model: gpt-4o-mini
```

Use `model_aliases` when a short name should expand before provider inference:

```yaml
model_aliases:
  local-fast: qwen3:8b
  sonnet: claude-sonnet-4
```

---

## `mcp_servers`

```yaml
mcp_servers:
  filesystem:
    transport: stdio
    enabled: true
    auto_connect: true
    command: npx
    args:
      - -y
      - "@modelcontextprotocol/server-filesystem"
      - "."
    env: {}
    cwd: .
    timeout: 30.0

  docs:
    transport: http
    enabled: true
    auto_connect: true
    url: http://localhost:8080/mcp
    headers:
      Authorization: "Bearer ${MCP_TOKEN}"
    timeout: 30.0
```

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `transport` | string | `stdio` | `stdio`, `http`, or `sse` |
| `enabled` | boolean | `true` | Whether the server is enabled |
| `disabled` | boolean | `false` | Compatibility inverse of `enabled` |
| `auto_connect` | boolean | `true` | Connect automatically when MCP starts |
| `autoConnect` | boolean | `true` | Compatibility spelling |
| `command` | string | `null` | Stdio command |
| `args` | array | `[]` | Stdio command arguments |
| `env` | object | `{}` | Environment variables |
| `cwd` | string | `null` | Working directory for stdio command |
| `url` | string | `null` | HTTP or SSE endpoint |
| `headers` | object | `{}` | HTTP headers |
| `timeout` | number | `30.0` | Request timeout in seconds |

---

## Complete Example

```yaml
superqode:
  version: "1.0"
  team_name: My Project
  description: SuperQode project configuration
  runtime: builtin
  gateway:
    type: litellm
  cost_tracking:
    enabled: true
    show_after_task: true
  errors:
    surface_rate_limits: true
    surface_auth_errors: true

default:
  mode: byok
  provider: openai
  model: gpt-4o-mini

providers:
  openai:
    api_key_env: OPENAI_API_KEY
    recommended_models:
      - gpt-4o-mini
      - gpt-4o

  ollama:
    base_url: http://localhost:11434
    recommended_models:
      - qwen3:8b

agents:
  opencode:
    description: OpenCode coding agent
    protocol: acp
    command: opencode

model_aliases:
  local-fast: qwen3:8b

mcp_servers:
  filesystem:
    transport: stdio
    enabled: true
    auto_connect: true
    command: npx
    args:
      - -y
      - "@modelcontextprotocol/server-filesystem"
      - "."
```

---

## Related HarnessSpec Fields

These fields are not part of `superqode.yaml`. They belong in a harness file:

- `runtime`
- `model_policy`
- `execution_policy`
- `agents`
- `workflow`
- `context`
- `checks`
- `hooks`
- `observability`
- `metadata`

Create one with:

```bash
superqode harness init my-coder --template coding --output harness.yaml
superqode harness validate --spec harness.yaml
```

## Next Steps

- [MCP Configuration](mcp-config.md)
- [Harness System](../advanced/harness-system.md)
- [Providers](../providers/index.md)
