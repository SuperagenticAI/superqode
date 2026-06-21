# Your First Session

This guide walks through a normal SuperQode TUI session: connect a model or agent, load a harness, ask for a repository task, approve tool calls when needed, and inspect what happened.

SuperQode is your portable coding agent harness. The TUI is the best place to explore a project because it keeps prompts, tool activity, approvals, file changes, and session state visible in one terminal.

---

## Before You Start

You need:

- SuperQode installed: `superqode --version`
- A project directory
- One configured provider, ACP agent, or local model

Start in a Git repository when possible:

```bash
cd /path/to/your/project
git status
```

If this is your first run in a valuable repository, use a throwaway branch.

---

## 1. Launch The TUI

```bash
superqode
```

The TUI opens with a prompt at the top and the conversation area below it. Type natural-language requests in the prompt and press `Enter` to submit.

Useful keys:

| Key | Action |
| --- | --- |
| `Ctrl+K` | Open the command palette |
| `:` | Enter command mode |
| `Ctrl+T` | Toggle thinking/session logs |
| `Ctrl+Q` | Quit |
| `Escape` | Close a modal or picker |

---

## 2. Connect A Model Or Agent

Open the connection picker:

```text
:connect
```

You can also connect directly:

```text
:connect acp opencode
:connect byok openai <openai-model>
:connect local ollama qwen3:8b
```

Check the current state:

```text
:status
```

Use ACP when you want an external coding agent, BYOK when you want a hosted model with your API key, and local when you want Ollama, LM Studio, DS4, MLX, vLLM, or another local server.

---

## 3. Load Or Create A Harness

A harness defines the run contract: runtime, model policy, tools, sandbox policy, approvals, events, and output handling.

For the default coding setup:

```bash
superqode harness init my-coder --template coding --output harness.yaml
superqode harness doctor --spec harness.yaml
```

Then load it in the TUI:

```text
:harness harness.yaml
```

Other harness commands:

| Command | Purpose |
| --- | --- |
| `:harness status` | Show the active harness |
| `:harness templates` | List available templates |
| `:harness off` | Return to the non-harness runtime path |

For local models, start with a repo-local harness:

```bash
superqode local init --repo .
superqode --harness superqode.local.yaml
```

`local init` detects hardware and available engines, writes `superqode.local.yaml`,
and runs a non-destructive smoke check when possible. Use `:local build` when
you want the guided builder for a specific model, endpoint, or pack. Treat the
pack as a model-family starter, then edit the harness for your repo's memory,
tools, approval policy, and eval results.

You can also start the TUI with a harness:

```bash
superqode --harness harness.yaml
```

---

## 4. Ask A Small First Task

Start with a low-risk prompt:

```text
Summarize this repository and identify the smallest safe improvement.
```

Then try a focused coding task:

```text
Find one low-risk bug or cleanup, make the smallest fix, and run the narrowest useful test.
```

The TUI keeps successful tool activity compact by default:

```text
read_file(pyproject.toml)
grep("TODO", src)
bash("uv run pytest tests/test_config.py")
```

Use verbose logs only when you need detail:

```text
:log verbose
```

---

## 5. Handle Approvals

When policy requires approval, the TUI shows the pending tool call before it runs. Review the command or file operation, then approve or reject it:

```text
:approve
:approve 1 always
:reject
:reject 1 "use a safer command"
```

Use `always` only when you want to allow the same kind of request for the rest of the session.

---

## 6. Inspect Changes

Ask SuperQode what changed:

```text
Summarize the files changed and the tests you ran.
```

You can also use normal Git commands in another terminal:

```bash
git status --short
git diff
```

If you ran through a harness, JSON runs include a `run_id`. Use it to inspect events and the graph:

```bash
superqode harness events <run-id>
superqode harness graph <run-id>
superqode harness graph <run-id> --json
```

---

## 7. Switch Runtime Or Provider

List available runtimes:

```text
:runtime list
```

Switch runtime when available:

```text
:runtime builtin
:runtime pydanticai
:runtime openai-agents
```

Use `:connect` again if you want to switch provider or model.

---

## 8. Run Checks When Needed

If your harness defines checks, ask the agent to run the narrowest useful one after making changes. You can also put the command directly in `checks.custom_steps` so the policy travels with the harness.

```yaml
checks:
  enabled: true
  custom_steps:
    - name: unit-tests
      command: uv run pytest tests/test_config_loader.py
      enabled: true
      timeout: 300
```

For normal implementation work, stay in the TUI and use focused prompts plus harness policy:

```text
Make the smallest safe fix and run the configured unit test.
```

---

## Complete First Session

```bash
cd ~/projects/my-app
superqode harness init my-coder --template coding --output harness.yaml
superqode harness doctor --spec harness.yaml
superqode --harness harness.yaml
```

Inside the TUI:

```text
:connect
:status
Summarize this repository and suggest the smallest safe improvement.
Find one low-risk cleanup, make the smallest fix, and run the narrowest useful test.
:approve
Summarize what changed.
```

---

## Troubleshooting

??? question "The TUI starts but no model is connected"

    Run `:connect` and choose ACP, BYOK, or local. Then check `:status`.

??? question "A tool call is waiting for approval"

    Review the pending operation. Use `:approve` to allow it once, `:approve 1 always` to allow similar requests for the session, or `:reject` to block it.

??? question "The output is too noisy"

    Use `:log minimal` or keep the default normal mode. Use `Ctrl+T` to hide thinking/session logs.

??? question "I want to see every tool result"

    Use `:log verbose` before running the task.

??? question "I want a no-tool planning session"

    Create and load a no-tool harness:

    ```bash
    superqode harness init planner --template no-tool --output planner.yaml
    superqode --harness planner.yaml
    ```

---

## Next Steps

1. [Quick Start](quickstart.md)
2. [Harness System](../advanced/harness-system.md)
3. [Terminal User Interface](../advanced/tui.md)
4. [Runtime Backends](../runtimes.md)
5. [Configuration Guide](configuration.md)
