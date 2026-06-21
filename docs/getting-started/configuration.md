# Configuration

SuperQode uses two complementary configuration files:

- `superqode.yaml` stores project defaults, provider hints, ACP agent definitions, MCP servers, aliases, and gateway settings.
- HarnessSpec files such as `harness.yaml` store run behavior: runtime, model policy, tools, sandbox, approvals, checks, hooks, events, and output.

Most developers can start with `superqode config init`, connect from the TUI with `:connect`, and create a harness only when they want repeatable policy.

---

## Create Project Config

```bash
cd /path/to/project
superqode config init
```

SuperQode looks for config in this order:

| Priority | Path | Scope |
| --- | --- | --- |
| 1 | `./superqode.yaml` | Project |
| 2 | `~/.superqode.yaml` | User |
| 3 | `/etc/superqode/superqode.yaml` | System |

---

## Minimal Config

For a hosted provider:

```yaml
superqode:
  version: "1.0"
  team_name: "My Project"

default:
  mode: byok
  provider: openai
  model: <openai-model>

providers:
  openai:
    api_key_env: OPENAI_API_KEY
    recommended_models:
      - <openai-model>
      - <openai-fast-model>
```

For a local model:

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
    recommended_models:
      - qwen3:8b
```

For an ACP agent:

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

`coding_agent` is still accepted for compatibility, but new config should use `agent` for ACP defaults.

---

## Add A Harness

Create a reusable harness when you want the same runtime, tool, sandbox, and approval policy across runs:

```bash
superqode harness init my-coder --template coding --output harness.yaml
superqode harness doctor --spec harness.yaml
superqode harness run --spec harness.yaml --prompt "summarize this repository"
```

Load the same harness in the TUI:

```bash
superqode --harness harness.yaml
```

Or from inside the TUI:

```text
:harness harness.yaml
:harness status
```

---

## Common Config Commands

```bash
superqode config init
superqode config init --force
```

Harness commands:

```bash
superqode harness list-templates
superqode harness validate --spec harness.yaml
superqode harness inspect --spec harness.yaml
superqode harness compile --spec harness.yaml --json
```

---

## Provider Settings

Providers are configured by ID. API keys should be stored in environment variables, not in YAML.

```yaml
providers:
  anthropic:
    api_key_env: ANTHROPIC_API_KEY
    recommended_models:
      - <anthropic-model>

  google:
    api_key_env: GOOGLE_API_KEY
    recommended_models:
      - gemini-flash-latest

  ollama:
    base_url: http://localhost:11434
    recommended_models:
      - qwen3:8b
```

Check setup:

```bash
superqode providers doctor
superqode providers doctor openai --json
superqode providers guide ollama
superqode providers recommend coding
```

---

## MCP Servers

Use `mcp_servers` for Model Context Protocol servers:

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
```

SuperQode also accepts `mcpServers` for compatibility with common MCP config formats.

---

## Environment Variables

| Variable | Purpose |
| --- | --- |
| `SUPERQODE_PROVIDER` | Default provider for headless runs |
| `SUPERQODE_MODEL` | Default model for headless runs |
| `SUPERQODE_SANDBOX` | Local command sandbox mode |
| `SUPERQODE_SEARCH_ROOTS` | Extra read-only search roots outside the workspace |
| `SUPERQODE_DS4_WARMUP` | Set `0` or `false` to skip DS4 warm-up |
| `OPENAI_API_KEY` | OpenAI API key |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `GOOGLE_API_KEY` | Google API key |
| `DEEPSEEK_API_KEY` | DeepSeek API key |

---

## What Belongs Where

| Setting | Put it in |
| --- | --- |
| Default provider or local model | `superqode.yaml` |
| API key environment variable names | `superqode.yaml` |
| MCP server process definitions | `superqode.yaml` |
| Runtime backend for a repeatable run | HarnessSpec |
| Allowed tools and shell access | HarnessSpec |
| Approval rules and sandbox policy | HarnessSpec |
| Project checks | HarnessSpec |
| Event storage and output schema | HarnessSpec |

## Next Steps

- [YAML Reference](../configuration/yaml-reference.md)
- [MCP Configuration](../configuration/mcp-config.md)
- [Harness System](../advanced/harness-system.md)
- [Provider Guide](../providers/index.md)
