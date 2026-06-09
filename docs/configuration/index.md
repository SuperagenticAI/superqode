# Configuration Reference

!!! tip "No config file needed"
    Everything works without a `superqode.yaml`. Connect a model and start asking.
    Configuration is optional — add it later with `superqode init` when you want
    to pin defaults, add providers, or configure harness checks.

SuperQode configuration is intentionally split:

- `superqode.yaml` stores project defaults, provider definitions, ACP agent definitions, MCP servers, model aliases, gateway settings, and compatibility settings.
- HarnessSpec YAML files store runtime, model policy, tool policy, sandbox behavior, approvals, hooks, checks, observability, workflow, and output behavior.

For a first project, use the getting-started guide. Use this reference when you need exact YAML fields.

---

## Quick Navigation

<div class="grid cards" markdown>

-   **YAML Reference**

    ---

    Complete reference for `superqode.yaml`.

    [:octicons-arrow-right-24: YAML Reference](yaml-reference.md)

-   **MCP Configuration**

    ---

    Configure Model Context Protocol servers for tool integration.

    [:octicons-arrow-right-24: MCP Configuration](mcp-config.md)

-   **Provider Configuration**

    ---

    Configure BYOK providers, ACP agents, local models, and OpenResponses.

    [:octicons-arrow-right-24: Provider Configuration](../providers/index.md)

-   **Harness System**

    ---

    Configure runtime, tools, sandbox, checks, hooks, workflows, output, and events in reusable harness specs.

    [:octicons-arrow-right-24: Harness System](../advanced/harness-system.md)

</div>

---

## Configuration File Locations

SuperQode loads configuration from multiple locations in order of precedence:

| Priority | Location | Scope |
| --- | --- | --- |
| 1 | `./superqode.yaml` | Project-specific |
| 2 | `~/.superqode.yaml` | User-specific |
| 3 | `/etc/superqode/superqode.yaml` | System-wide |

Values in higher-priority files override lower-priority files.

---

## Create Configuration

```bash
superqode config init
```

Create a harness spec separately when you want repeatable run behavior:

```bash
superqode harness init my-coder --template coding --output harness.yaml
superqode harness doctor --spec harness.yaml
```

---

## Minimal Project Config

```yaml
superqode:
  version: "1.0"
  team_name: "My Project"
  description: "SuperQode project configuration"

default:
  mode: byok
  provider: openai
  model: gpt-4o-mini

providers:
  openai:
    api_key_env: OPENAI_API_KEY
    recommended_models:
      - gpt-4o-mini
```

For ACP:

```yaml
superqode:
  version: "1.0"
  team_name: "My Project"

default:
  mode: acp
  agent: opencode

agents:
  opencode:
    description: OpenCode coding agent
    protocol: acp
    command: opencode
```

For local models:

```yaml
superqode:
  version: "1.0"
  team_name: "My Project"

default:
  mode: local
  provider: ollama
  model: qwen3:8b

providers:
  ollama:
    base_url: http://localhost:11434
```

---

## Important Sections

| Section | Purpose |
| --- | --- |
| `superqode` | Global metadata, runtime default, gateway, cost tracking, and error settings |
| `default` | Default connection mode and provider/model or ACP agent |
| `providers` | BYOK and local provider metadata |
| `agents` | ACP agent metadata |
| `custom_models` | Model aliases with explicit provider and model mapping |
| `model_aliases` | Short names for provider/model strings |
| `mcp_servers` | MCP server process and HTTP definitions |

Runtime and tool policy belong in HarnessSpec files, not in `superqode.yaml`.

---

## Verify Configuration

```bash
superqode providers doctor
superqode harness validate --spec harness.yaml
superqode harness doctor --spec harness.yaml
```

---

## Environment Variables

| Variable | Description |
| --- | --- |
| `SUPERQODE_PROVIDER` | Default provider for headless mode |
| `SUPERQODE_MODEL` | Default model for headless mode |
| `SUPERQODE_SANDBOX` | Local command sandbox mode |
| `SUPERQODE_SEARCH_ROOTS` | Extra read-only repo roots that search and read tools may access |
| `SUPERQODE_DS4_WARMUP` | Set `0` or `false` to skip DS4 warm-up |
| `OPENAI_API_KEY` | OpenAI API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `GOOGLE_API_KEY` | Google API key |
| `DEEPSEEK_API_KEY` | DeepSeek API key |

See [Local Code Search](../providers/local.md#local-code-search-no-web-access) for `SUPERQODE_SEARCH_ROOTS`.

---

## Next Steps

- [YAML Reference](yaml-reference.md)
- [MCP Configuration](mcp-config.md)
- [Provider Configuration](../providers/index.md)
- [Harness System](../advanced/harness-system.md)
