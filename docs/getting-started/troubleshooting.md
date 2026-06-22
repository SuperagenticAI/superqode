# Troubleshooting

This guide covers the most common SuperQode setup and runtime issues.

## Start With Doctor Commands

Run the checks that match the feature you are using:

```bash
superqode doctor
superqode providers doctor
superqode runtime list
superqode harness doctor --spec harness.yaml
superqode sandbox doctor
superqode memory doctor
superqode trust doctor
```

Use JSON output when you need to paste diagnostics into an issue:

```bash
superqode doctor --json
superqode providers doctor openai --json
superqode harness doctor --spec harness.yaml --json
```

---

## Installation Issues

### `ModuleNotFoundError: No module named 'superqode'`

Reinstall SuperQode in the environment you are using:

```bash
uv tool upgrade superqode
python -c "import superqode; print(superqode.__version__)"
```

With `uv`:

```bash
uv tool install --force superqode
superqode --version
```

For source installs:

```bash
git clone https://github.com/SuperagenticAI/superqode.git
cd superqode
uv pip install -e .
```

### The `superqode` command is not found

Check that the Python scripts directory is on `PATH`:

```bash
python -m site --user-base
uv tool list
```

If you installed with `uv`, check:

```bash
uv tool list
```

---

## Local Model Issues

### First Local Response Is Slow

Local servers often pay a cold-start cost on the first generation. They may need to load model weights, allocate KV cache, or initialize runtime kernels. SuperQode warms local models automatically when you connect from the TUI, but the first prompt can still be slow if the model is large or the machine is under memory pressure.

Manual warmup:

```bash
superqode local warm ollama --model qwen3:8b
```

Disable automatic TUI warmup:

```bash
SUPERQODE_LOCAL_WARMUP=0 superqode
```

Give large models more warmup time:

```bash
SUPERQODE_LOCAL_WARMUP_TIMEOUT=60 superqode
```

If warmup or first-token latency stays high, use a smaller model, reduce context, reduce concurrency, or check `superqode local guardrails --repo .`.

---

## TUI Connection Problems

### The TUI starts but no model is connected

Open the connection picker:

```text
:connect
```

Or connect directly:

```text
:connect byok openai <openai-model>
:connect local ollama qwen3:8b
:connect acp opencode
```

Then confirm state:

```text
:status
```

### Provider authentication fails

Check the provider-specific environment variable:

```bash
echo "$OPENAI_API_KEY"
echo "$ANTHROPIC_API_KEY"
echo "$GOOGLE_API_KEY"
superqode auth check openai
superqode providers doctor openai
```

Never place API keys directly in documentation, issues, logs, or committed config. In `superqode.yaml`, reference environment variables:

```yaml
providers:
  openai:
    api_key_env: OPENAI_API_KEY
```

### ACP agent is unavailable

List and inspect agents:

```bash
superqode agents list
superqode agents doctor opencode
superqode agents doctor opencode --live
```

For OpenCode:

```bash
npm i -g opencode-ai
opencode --help
superqode connect acp opencode
```

---

## Harness Problems

### Harness YAML does not validate

Run:

```bash
superqode harness validate --spec harness.yaml
superqode harness inspect --spec harness.yaml
```

Common fixes:

- use `flavor: coding` or `flavor: no_tool`
- use a known runtime backend such as `builtin`, `openai-agents`, `adk`, `deepagents`, `pydanticai`, or `codex-sdk`
- keep `execution_policy.allow_write` and `execution_policy.allow_shell` false for no-tool harnesses
- define `agents` as a YAML list

### Optional runtime backend is missing

List backends:

```bash
superqode harness list-backends
superqode runtime doctor pydanticai
```

Install only the backend you need:

```bash
uv tool install "superqode[pydanticai]"
uv tool install "superqode[deepagents]"
uv tool install "superqode[openai-agents]"
uv tool install "superqode[adk]"
uv tool install "superqode[codex-sdk]"
```

### A run did something unexpected

Inspect persisted events:

```bash
superqode harness runs
superqode harness events <run-id>
superqode harness graph <run-id>
superqode harness graph <run-id> --json
```

Run `doctor` with the same runtime and sandbox overrides:

```bash
superqode harness doctor --spec harness.yaml --runtime pydanticai --sandbox local
```

---

## Sandbox And Permission Problems

### Shell commands are blocked

Check the active sandbox and harness policy:

```bash
superqode sandbox doctor
superqode harness inspect --spec harness.yaml
```

In the TUI:

```text
:sandbox
:sandbox workspace-write
:status
```

If shell should be allowed, the harness must allow it:

```yaml
execution_policy:
  sandbox: local
  approval_profile: balanced
  allow_shell: true
  allowed_commands:
    - uv run pytest
```

### A tool call is waiting for approval

In the TUI:

```text
:approve
:approve 1 always
:reject
:reject 1 "use a safer command"
```

Use `always` only when you intentionally trust similar calls for the current session.

---

## MCP Problems

### MCP server is not available

Check config and dependencies:

```bash
superqode config init
node --version
npx --version
```

Example `mcp_servers` config:

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

Use `mcpServers` only when importing external MCP config. New SuperQode config should use `mcp_servers`.

---

## Local Model Problems

### Ollama model does not appear

Check Ollama:

```bash
ollama list
ollama serve
ollama pull qwen3:8b
superqode providers doctor ollama --live
```

Connect:

```text
:connect local ollama qwen3:8b
```

### DS4 is slow on first request

DS4 may warm up the model on connect. To skip warm-up:

```bash
export SUPERQODE_DS4_WARMUP=0
```

Then point SuperQode at the DS4 endpoint if needed:

```bash
export DS4_HOST=http://127.0.0.1:8000/v1
superqode providers guide ds4
```

---

## Session And Export Problems

### You cannot find an old session

```bash
superqode sessions list
superqode sessions tree
superqode sessions show <session-id>
```

### You need to hand off a session

```bash
superqode share create <session-id>
superqode share list
superqode share import <artifact.superqode-share.json> --session-id imported
```

### Export failed

Try a specific format and path:

```bash
superqode sessions export <session-id> --format markdown --output session.md
superqode sessions export <session-id> --format json --output session.json
```

---

## Project Trust And Plugins

If plugins, hooks, or MCP config are blocked, inspect project trust:

```bash
superqode trust status
superqode trust doctor
superqode trust yes
superqode plugins doctor
```

Only trust projects whose local executable config you have reviewed.

---

## Getting Help

When opening an issue, include:

- SuperQode version from `superqode --version`
- Python version from `python --version`
- operating system
- command you ran
- relevant `doctor --json` output with secrets removed
- minimal `superqode.yaml` or `harness.yaml` that reproduces the issue

Links:

- [GitHub Issues](https://github.com/SuperagenticAI/superqode/issues)
- [GitHub Discussions](https://github.com/SuperagenticAI/superqode/discussions)
- [Support](https://github.com/SuperagenticAI/superqode/blob/main/SUPPORT.md)
