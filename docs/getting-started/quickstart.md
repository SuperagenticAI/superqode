---
title: Quick Start
description: Install SuperQode, connect an agent or model, and create a first harness.
---

# Quick Start

This guide covers the shortest path from installation to a working coding
session. A custom harness is optional for the first session.

## 1. Install SuperQode

Run the installer:

```bash
curl -fsSL https://superqode.dev/install.sh | sh
```

The installer creates an isolated `uv` tool environment and does not require
`sudo`.

If `uv` is already installed:

```bash
uv tool install superqode
```

Verify the command:

```bash
superqode --version
```

See [Installation](installation.md) for operating-system requirements,
alternative installation methods, upgrades, and optional dependencies.

## 2. Open a repository

Start SuperQode from the repository that the agent may inspect:

```bash
cd /path/to/your/project
superqode
```

The terminal user interface starts by default.

## 3. Connect an agent or model

Open the connection picker:

```text
:connect
```

Choose one connection path. Only one is required.

### Local model

Start a local server and download a model. This example uses Ollama:

```bash
ollama serve
ollama pull qwen3:8b
```

Connect from the TUI:

```text
:connect local ollama qwen3:8b
```

Run `superqode local doctor` if the model or server is not detected. See
[Local Providers](../providers/local.md) for Ollama, LM Studio, vLLM, SGLang,
TGI, MLX, and other local routes.

### ACP coding agent

Open the installed and featured ACP agent list:

```text
:connect acp
```

Select an installed agent, or inspect the complete catalog:

```text
:connect acp all
```

For a named installed agent:

```text
:connect acp opencode
```

See [ACP Coding Agents](../providers/acp.md) for discovery, installation, and
diagnostics.

### BYOK provider

Set the provider's API key before starting SuperQode. For example:

```bash
export OPENAI_API_KEY="your-key"
```

Connect through the picker:

```text
:connect byok
```

Or select a provider and model directly:

```text
:connect byok openai <model>
```

Check provider readiness with:

```bash
superqode providers doctor openai
```

See [BYOK Providers](../providers/byok.md) for supported providers and
credential names.

### OpenAI Codex

Install the Codex runtime and complete the local login:

```bash
uv tool install "superqode[codex-sdk]"
codex login
```

Connect from the TUI:

```text
:connect codex
```

See [OpenAI Codex](../providers/codex.md) for SDK, ACP, and BYOK routes.

### Google Antigravity

Install the `agy` CLI:

```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

Run `agy` once to complete Google sign-in, then connect from the TUI:

```text
:connect antigravity
```

The signed-in CLI owns the Antigravity agent loop. See
[Google Antigravity](../providers/antigravity.md) for CLI, SDK, managed, and
BYOK routes.

### xAI Grok

Install the Grok CLI and authenticate:

```bash
curl -fsSL https://x.ai/cli/install.sh | bash
grok login
```

Connect Grok Build:

```text
:connect grok
```

See [xAI Grok](../providers/grok.md) for Grok Build, subscription-model, and
BYOK routes.

## 4. Run the first coding task

Check the active connection:

```text
:status
```

Submit a small repository task:

```text
Summarize this repository and identify the smallest safe improvement.
```

Review approval requests before allowing file edits or shell commands.

## 5. List and switch harnesses

List repository and installed harnesses from the shell:

```bash
superqode harness list
```

Open the Harness Switcher:

```text
:harness
```

The list includes built-in harnesses, project HarnessSpecs, connected coding
agents, ACP agents, model presets, installed harnesses, and optional
integrations.

Inspect or switch the active harness:

```text
:harness current
:harness switch workbench
```

Create an independent session branch during a switch:

```text
:harness switch kimi-code --fork
```

See [Your First Session](first-session.md) for session controls, approvals, and
change inspection.

## 6. Build the first project harness

Create a repository-owned coding harness:

```bash
superqode harness init my-coder --template coding --output harness.yaml
```

Validate the generated specification:

```bash
superqode harness validate --spec harness.yaml
superqode harness doctor --spec harness.yaml
```

Load it in the current TUI session:

```text
:harness harness.yaml
```

Or run it directly:

```bash
superqode harness run \
  --spec harness.yaml \
  --prompt "Summarize the repository architecture"
```

The generated `harness.yaml` records the runtime, model policy, tools,
permissions, sandbox, workflow, and output behavior. Commit it when the
configuration is ready to become part of the repository contract.

See [Bring Your Own Harness](bring-your-own-harness.md) for the guided builder,
templates, editing, testing, and policy reference.

## Next steps

| Goal | Guide |
| --- | --- |
| Compare every connection method | [Connect Agents, Models, and Harnesses](../concepts/modes.md) |
| Browse external systems and optional dependencies | [Integrations](../integrations/index.md) |
| Use local and open models | [Local Agentic Coding](../local-agentic-coding.md) |
| Evaluate and optimize a harness | [Harness Optimization](../advanced/harness-optimization.md) |
| Follow the complete command workflow | [Complete Getting Started Guide](complete-guide.md) |
