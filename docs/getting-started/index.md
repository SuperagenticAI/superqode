# Getting Started

SuperQode is a harness engineering framework for coding agents, optimized for local and open models. It gives developers a TUI and CLI for building, measuring, and running a coding harness they own, with explicit model choice, tool access, sandbox policy, approvals, sessions, events, and repeatable HarnessSpec files.

This guide gets you from install to a useful first run.

---

## Quick Navigation

<div class="grid cards" markdown>

-   **Installation**

    ---

    Install SuperQode and verify the command works.

    [:octicons-arrow-right-24: Install now](installation.md)

-   **Quick Start**

    ---

    Run the TUI, create a harness, run a headless task, and inspect events.

    [:octicons-arrow-right-24: Quick start](quickstart.md)

-   **First Session**

    ---

    Walk through a normal interactive coding session.

    [:octicons-arrow-right-24: First session](first-session.md)

-   **Configuration**

    ---

    Configure project defaults, providers, ACP agents, local models, and MCP servers.

    [:octicons-arrow-right-24: Configure](configuration.md)

-   **Harness Examples**

    ---

    Start from ready-to-run HarnessSpec examples.

    [:octicons-arrow-right-24: Examples](../examples.md)

-   **Troubleshooting**

    ---

    Diagnose install, provider, runtime, harness, sandbox, MCP, and session issues.

    [:octicons-arrow-right-24: Troubleshooting](troubleshooting.md)

</div>

---

## Prerequisites

| Requirement | Version | Notes |
| --- | --- | --- |
| Python | 3.12+ | Required for the Python package |
| pip or uv | latest recommended | `uv tool install superqode` gives an isolated install |
| Git | 2.25+ | Recommended for repository work and reviewing changes |

Optional tools depend on your workflow:

| Tool | Use |
| --- | --- |
| Node.js and npm | ACP agents, MCP servers, JavaScript tooling |
| Ollama, LM Studio, MLX, vLLM, SGLang, or DS4 | Local model workflows |
| Docker or optional sandbox SDKs | Container or remote sandbox profiles |

---

## 1. Install

=== "uv"

    ```bash
    uv tool install superqode
    superqode --version
    ```

=== "pip"

    ```bash
    python -m pip install superqode
    superqode --version
    ```

=== "source"

    ```bash
    git clone https://github.com/SuperagenticAI/superqode.git
    cd superqode
    python -m pip install -e .
    superqode --version
    ```

---

## 2. Start The TUI

```bash
cd /path/to/your/project
superqode
```

Connect a model or agent:

```text
:connect
```

Direct examples:

```text
:connect byok openai <openai-model>
:connect local ollama qwen3:8b
:connect acp opencode
```

Check state:

```text
:status
```

Then ask a small first task:

```text
Summarize this repository and suggest the smallest safe improvement.
```

---

## 3. Choose A Connection Path

| Path | Use when | Setup |
| --- | --- | --- |
| ACP | You want an external coding agent with its own tool loop | `superqode agents list` and `superqode agents doctor <agent>` |
| BYOK | You want hosted providers with your own API keys | Set `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, or another provider key |
| Local | You want private or offline inference | Start Ollama, LM Studio, MLX, vLLM, SGLang, DS4, or another local server |
| SDK | You want to use your ChatGPT or Claude subscription, or vendor-native agent behavior | `:connect codex`, `:connect claude`, or `:connect antigravity` in the TUI |

See [Connection Modes](../concepts/modes.md) for how the four paths differ.

Provider diagnostics:

```bash
superqode providers doctor
superqode providers guide openai
superqode providers recommend coding
```

---

## 4. Create A Harness

A HarnessSpec makes a run repeatable. It controls runtime, model policy, tools, sandbox, approvals, checks, hooks, events, workflow, and output.

```bash
superqode harness init my-coder --template coding --output harness.yaml
superqode harness doctor --spec harness.yaml
superqode harness run --spec harness.yaml --prompt "summarize this repository"
```

Load it in the TUI:

```text
:harness harness.yaml
:harness status
```

Built-in templates:

```bash
superqode harness list-templates
```

Common templates:

| Template | Purpose |
| --- | --- |
| `coding` | Repository coding with file, search, edit, shell, todo, checks, and approvals |
| `no-tool` | Model-only reasoning without repository or shell tools |
| `gemma4-coding` | Gemma4 local coding starting point |
| `gemma4-no-tool` | Gemma4 model-only reasoning |
| `ds4-coding` | DS4 local coding starting point |
| `ds4-fast-local` | Lower-latency DS4 local iteration |

---

## 5. Run Headless

Use headless mode for scripts and one-off terminal tasks:

```bash
superqode --print "summarize this repository"
superqode --mode json --print "summarize this repository"
superqode --profile plan --print "plan the safest fix for the failing test"
```

Use a harness for repeatable headless behavior:

```bash
superqode harness run --spec harness.yaml --prompt "make the smallest safe fix and run the narrowest useful test"
```

---

## 6. Inspect Sessions And Runs

Sessions:

```bash
superqode sessions list
superqode sessions tree
superqode sessions show <session-id>
superqode sessions export <session-id> --format markdown --output session.md
```

Harness runs:

```bash
superqode harness runs
superqode harness events <run-id>
superqode harness graph <run-id>
superqode harness evidence <run-id>
```

Portable share artifacts:

```bash
superqode share create <session-id>
superqode share import <artifact.superqode-share.json> --session-id imported
```

---

## 7. Common CLI Commands

| Command | Purpose |
| --- | --- |
| `superqode` | Launch the TUI |
| `superqode --print "..."` | Run one headless task |
| `superqode doctor` | Check core environment health |
| `superqode config init` | Create `superqode.yaml` |
| `superqode providers doctor` | Check provider setup |
| `superqode agents list` | List known ACP agents |
| `superqode runtime list` | List runtime backends |
| `superqode harness init ...` | Create a HarnessSpec |
| `superqode harness doctor --spec harness.yaml` | Preflight a harness |
| `superqode harness run --spec harness.yaml --prompt "..."` | Run a harness task |
| `superqode memory status` | Check memory providers |
| `superqode sandbox doctor` | Check sandbox providers |
| `superqode trust doctor` | Audit local project trust inputs |

---

## Which Workflow Should I Use?

Use the TUI when:

- exploring a repository
- making interactive changes
- reviewing tool calls and approvals
- switching providers or runtimes during a session
- exporting or sharing a conversation

Use headless CLI when:

- scripting a single task
- running in automation
- collecting JSON output
- running repeatable HarnessSpec tasks
- inspecting persisted run events

---

## Next Steps

1. [Quick Start](quickstart.md)
2. [Your First Session](first-session.md)
3. [Configuration](configuration.md)
4. [Inside the Agent Loop](../advanced/agent-loop.md), to understand what the engine is doing for you
5. [Harness System](../advanced/harness-system.md)
6. [Connection Modes](../concepts/modes.md)
7. [CLI Reference](../cli-reference/index.md)
