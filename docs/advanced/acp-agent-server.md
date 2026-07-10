# ACP Agent Server

`superqode serve acp` runs SuperQode as an **Agent Client Protocol (ACP) agent** on stdio. Any ACP client (Zed, JetBrains IDEs, Neovim, Devin Desktop, or the Harbor benchmark framework) can drive SuperQode as its coding agent.

This is the inverse of [ACP Agents](../providers/acp.md), where SuperQode is the *client* connecting to other agents. Here SuperQode is the agent, and the loop it runs is your [HarnessSpec](harness-system.md) rather than a fixed pipeline.

```bash
superqode serve acp                       # stdio, auto-discovered harness
superqode serve acp --spec harness.yaml   # pin one HarnessSpec for all sessions
```

---

## Quick start in Zed

```json
// settings.json
"agent_servers": {
  "SuperQode": {
    "command": "uvx",
    "args": ["superqode", "serve", "acp"]
  }
}
```

Open the Agent Panel, start a SuperQode thread, and prompt. Harness tool calls stream into the panel as tool entries; harness approvals appear as native permission dialogs (Allow once / Always allow / Reject).

SuperQode is also submitted to the [ACP agent registry](https://github.com/agentclientprotocol/registry), which makes it installable from the agent picker in Zed and JetBrains IDEs without manual configuration.

---

## How a session picks its harness

Each ACP session resolves a HarnessSpec, in order:

1. `--spec <path>` or `SUPERQODE_ACP_SPEC` (see template selection below)
2. `superqode.local.yaml` in the session's working directory
3. `harness.yaml` in the session's working directory
4. The first spec under a conventional harness directory (`.superqode/harness/`, `harness/`, ...)
5. The built-in `coding` template as a fallback

The editor runs the harness file versioned with the open project.

### Template selection without a spec file

`SUPERQODE_ACP_SPEC` also accepts `template:<name>` to pin any built-in template:

```bash
SUPERQODE_ACP_SPEC=template:qwen-coding superqode serve acp
```

Run `superqode harness list-templates` for the available names. This matters most in benchmark containers, where no spec file exists and you want to control or compare harness variants per run.

---

## Model resolution

The session's provider and model resolve in order:

1. `--provider` / `--model` flags
2. `SUPERQODE_ACP_PROVIDER` / `SUPERQODE_ACP_MODEL` environment variables
3. `HARBOR_ACP_REQUESTED_MODEL` (set by Harbor with the benchmark's `--model` value)
4. The spec's `model_policy.primary` (for example `ollama/qwen3-coder`)

Clients may also switch models mid-session through ACP `session/set_model`; SuperQode accepts `provider/model` references or bare model ids.

---

## Authentication

SuperQode needs no login for local or BYOK use. The initialize response advertises one **terminal auth** method, `superqode-setup`, which runs:

```bash
superqode local init --repo .
```

This interactive setup detects your hardware, recommends a local model, and generates a starter harness for the project. Run it once per project from the editor's auth prompt, or skip it entirely if the project already has a harness or you use environment variables.

---

## What the client sees

Harness events map onto ACP session updates:

| Harness event | ACP update |
|---------------|------------|
| `model_delta` / `delta` | Agent message chunk |
| `thinking` | Agent thought chunk |
| `tool_call` | Tool call start (with read/edit/search/execute kind) |
| `tool_result` | Tool call completion or failure, with clipped output |
| `approval_required` | Permission request (allow once / always / reject) |
| `session/cancel` from the client | Stops the running turn (`stopReason: cancelled`) |

Full tool output and the complete event graph stay in the harness run store (`.superqode/sessions/`), inspectable with `superqode harness events <run-id>`.

---

## Running on Terminal-Bench with Harbor

[Harbor](https://www.harborframework.com/), the official harness for Terminal-Bench 2.x, has first-class ACP support, so SuperQode runs on the benchmark without adapter code. Harbor installs SuperQode inside each task container from the ACP registry manifest, speaks ACP to it, and records the full trajectory.

Once SuperQode is in the ACP registry:

```bash
harbor run -d terminal-bench@2.0 -a acp:superqode -m <provider/model>
```

Or point at a local registry manifest (before the registry listing, or to test manifest changes):

```bash
harbor run -d terminal-bench@2.0 \
  -a acp \
  --ak registry_entry_path=install/acp-registry/superqode/agent.json \
  --ak auth_policy=disabled \
  -m ollama/qwen3-coder \
  -k 5 -o jobs
```

The benchmark's `-m` flag reaches SuperQode automatically via `HARBOR_ACP_REQUESTED_MODEL`.

### The `benchmark-coding` template

Interactive harnesses ask clarifying questions; benchmarks have no user to answer them. The built-in `benchmark-coding` template is the coding harness with an autonomous stance (never ask the user, investigate recoverable state such as reflog, stashes, and backups, always apply a concrete attempt, and verify before finishing) plus `yolo` approvals, since the task container is the sandbox:

```bash
harbor run -d terminal-bench@2.0 -a acp:superqode -m <provider/model> \
  --ae SUPERQODE_ACP_SPEC=template:benchmark-coding
```

### Measuring the harness effect

Because the harness is selectable per run, you can benchmark the same model across harness variants and measure the effect of each configuration:

```bash
for t in coding benchmark-coding no-tool; do
  harbor run -d terminal-bench@2.0 -a acp:superqode -m <provider/model> \
    --ae SUPERQODE_ACP_SPEC=template:$t -o jobs/$t
done
```

The score deltas between those runs are pure harness effect: same model, same tasks, one variable changed.

### Local models from task containers

Task containers cannot see `localhost` on your host. Point SuperQode's Ollama provider at the host gateway:

```bash
--ae OLLAMA_HOST=http://host.docker.internal:11434
```

---

## Options

| Option | Description |
|--------|-------------|
| `--spec PATH` | Pin one HarnessSpec for all sessions |
| `--dir PATH` | Directory of specs for discovery |
| `--provider` | Provider override (env: `SUPERQODE_ACP_PROVIDER`) |
| `--model` | Model override (env: `SUPERQODE_ACP_MODEL`) |

stdout carries JSON-RPC; human-facing output goes to stderr.
