# CLI Reference

SuperQode provides a CLI for your portable coding agent harness: coding sessions, runtime management, provider setup, agents, and configuration. This reference documents the available commands, options, and usage patterns.

---

## Command Structure

```bash
superqode [OPTIONS] COMMAND [ARGS]...
```

### Global Options

| Option | CLI | Description |
|--------|-----|-------------|
| `--version` | superqode | Show version and exit |
| `--help` | superqode | Show help message and exit |
| `--tui` | superqode | Force the Textual TUI (default) |
| `-p`, `--print` | superqode | Run one headless coding task and print the response |
| `--mode json` | superqode | Run one headless task and emit structured JSON |
| `--profile` | superqode | Select harness profile: `build`, `plan`, or `review` |
| `--provider` | superqode | Override provider for headless mode |
| `--model` | superqode | Override model for headless mode |
| `--changes` | superqode | Control post-run change output: `summary`, `files`, `diff`, or `none` |

### Headless SuperQode

Use `superqode` directly for one-shot coding harness tasks:

```bash
superqode doctor
superqode -p "summarize this repository"
superqode -p --changes files "make the small docs fix"
superqode -p --changes none "answer without a change footer"
superqode --mode json --profile plan "plan the auth refactor"
superqode -p --resume abc123 "continue from the last turn"
superqode -p --fork abc123 "try a safer implementation"
```

Profiles:

| Profile | Purpose |
|---------|---------|
| `build` | Full-access implementation work |
| `plan` | Read-only planning; shell requires approval and is denied in headless mode |
| `review` | Read-only code review |

Inspect the tools and permissions for a profile:

```bash
superqode profiles list
superqode tools list --profile build
superqode tools list --profile plan --json
```

`repo_search` is available in coding profiles for broad codebase exploration. It combines ranked file matches, literal content matches, and symbol matches into one compact tool result.

Headless runs keep output clean by default. SuperQode prints the model response and then a compact change footer like `Changes: 2 files (+18 -3)` when the agent modified the workspace. Use `--changes files` to show the file list, `--changes diff` to show the patch, or `--changes none` to hide the footer.

Session commands:

```bash
superqode sessions list
superqode sessions tree
superqode sessions show abc123
superqode sessions export abc123 --format markdown --output session.md
```

Portable session handoff:

```bash
superqode share create abc123
superqode share export abc123 --format markdown --output session.md
superqode share import .superqode/shares/share-abc123.superqode-share.json --session-id imported
superqode share list --json
superqode share revoke share-abc123.superqode-share.json
```

Project trust:

```bash
superqode trust status
superqode trust status --json
superqode trust doctor
superqode trust yes
superqode trust no
```

Plugin manifests and local plugin packages:

```bash
superqode plugins list
superqode plugins list --all --json
superqode plugins show my-plugin
superqode plugins validate .superqode/plugins/my-plugin/plugin.json
superqode plugins doctor
superqode trust yes
superqode plugins add ./my-plugin
superqode plugins disable my-plugin
superqode plugins enable my-plugin
```

Agent memory:

```bash
superqode memory status
superqode memory providers
superqode memory doctor
superqode memory remember "Use pnpm in this repo; do not use npm" --kind preference --tag tooling
superqode memory search "package manager"
superqode memory search "auth requirements" --provider specmem
superqode memory search "release checklist" --provider mem0
superqode memory search "release checklist" --provider cognee
superqode memory search "release checklist" --provider supermemory
superqode memory forget <id>
superqode memory export --provider local --output memory.json
```

`local` is the default provider. `specmem`, `mem0`, `cognee`, and
`supermemory` are opt-in providers configured under `memory.providers` in
`superqode.yaml`.

Provider and model guidance:

```bash
superqode providers doctor openai --json
superqode providers guide openai
superqode providers guide ds4
superqode providers recommend coding
superqode providers recommend local
superqode providers recommend large-context --json
superqode -p --provider ds4 --model deepseek-v4-flash "summarize this repo"
```

For DS4, start `ds4-server` separately and point SuperQode at its OpenAI-compatible endpoint with `DS4_HOST` if it is not running on `http://127.0.0.1:8000/v1`.

In the TUI, use `Ctrl+K` for the command palette or type `:status`, `:harness`, `:providers`, `:recommend coding`, `:sandbox`, `:tree`, `:share`, `:trust`, `:plugins`, and `:benchmark`. Use `Ctrl+1` to open the persistent Harness sidebar tab.

Benchmark harness:

```bash
superqode benchmark run tasks.json --target superqode --target opencode --target pi --target deepagents
```

Harness event graph:

```bash
superqode harness doctor --spec harness.yaml
superqode harness events <run-id>
superqode harness graph <run-id>
superqode harness graph <run-id> --json
```

Sandbox capability profiles:

```bash
superqode -p --sandbox read-only "review this repository"
superqode -p --sandbox no-shell "make a small docs edit"
superqode -p --sandbox git-worktree "try an isolated implementation"
superqode -p --sandbox docker "run tests in a container-isolated profile"
superqode -p --sandbox e2b "validate this patch in a remote sandbox profile"
superqode -p --sandbox daytona "prototype this change remotely"
superqode -p --sandbox modal "run a cloud sandbox validation"
superqode -p --sandbox vercel "run in a Vercel Sandbox profile"
superqode -p --sandbox runloop "validate in a Runloop devbox profile"
superqode -p --sandbox agentcore "validate in an AgentCore Code Interpreter profile"
superqode -p --sandbox langsmith "validate in a LangSmith sandbox profile"
```

Sandbox execution providers:

```bash
superqode sandbox doctor
superqode sandbox doctor e2b --json
superqode sandbox run docker --image python:3.12 -- pytest -q
superqode sandbox run e2b -- "pytest -q"
```

`docker` uses the local Docker CLI. `e2b`, `daytona`, `modal`, `runloop`, `agentcore`, and `langsmith` use optional Python SDKs when installed and authenticated. `vercel` uses the Vercel Sandbox CLI and token/OIDC authentication.

---

## Command Groups

<div class="grid cards" markdown>

-   **Config Commands (superqode config)**

    ---

    Configuration management commands for viewing, validating, and modifying settings.

    [:octicons-arrow-right-24: Config Commands](config-commands.md)

-   **Provider Commands (superqode providers)**

    ---

    Commands for managing BYOK providers, testing connections, and listing available models.

    [:octicons-arrow-right-24: Provider Commands](provider-commands.md)

-   **Agents Commands (superqode agents)**

    ---

    Commands for listing, showing, and managing ACP coding agents.

    [:octicons-arrow-right-24: Agents Commands](agents-commands.md)

-   **Auth Commands (superqode auth)**

    ---

    Show authentication and security information for providers and agents.

    [:octicons-arrow-right-24: Auth Commands](auth-commands.md)


-   **Init Commands**

    ---

    Initialize SuperQode configuration for a project.

    [:octicons-arrow-right-24: Init Commands](init-commands.md)

</div>

---

## Quick Command Reference

### Session And Memory Commands

| Command | Description |
|---------|-------------|
| `superqode sessions list` | List saved sessions |
| `superqode sessions tree` | Show session branches and forks |
| `superqode share create <session-id>` | Create a portable local session artifact |
| `superqode memory status` | Show memory provider status |
| `superqode memory remember "..."` | Store an explicit project fact or preference |

### Config Commands

| Command | Description |
|---------|-------------|
| `superqode config init` | Create `superqode.yaml` in the current directory (recommended) |
| `superqode config init --force` | Initialize config (overwrite if present) |
| `superqode harness init coding` | Create a reusable coding harness spec |
| `superqode harness validate --spec <file>` | Validate a harness spec |

### Provider Commands

| Command | Description |
|---------|-------------|
| `superqode providers list` | List available providers |
| `superqode providers show PROVIDER` | Show provider details |
| `superqode providers test PROVIDER` | Test provider connection |
| `superqode providers mlx ACTION` | Manage MLX models |

### Harness Commands

| Command | Description |
|---------|-------------|
| `superqode harness list-templates` | List built-in harness templates |
| `superqode harness list-backends` | List harness runtime backends |
| `superqode harness inspect --spec <file>` | Show resolved harness policy |
| `superqode harness compile --spec <file>` | Compile effective harness settings |
| `superqode harness diff old.yaml new.yaml` | Compare two harness specs |
| `superqode harness runs` | List persisted harness runs |
| `superqode harness events <run-id>` | Show normalized run events |
| `superqode harness graph <run-id>` | Show event graph |
| `superqode harness evidence <run-id>` | Show run evidence receipt |
| `superqode harness replay <run-id>` | Replay or inspect a prior run |
| `superqode harness fork <run-id>` | Fork persisted run context |

---

## TUI Commands

When running the interactive TUI (`superqode`), prefix commands with `:`:

| TUI Command | Description |
|-------------|-------------|
| `:connect` or `:c` | Interactive connection picker (recommended) |
| `:connect acp opencode` | Connect directly to ACP agent |
| `:connect byok <provider> <model>` | Connect directly to BYOK provider |
| `:connect local <provider> <model>` | Connect directly to local model |
| `:plan <task>` | Ask for a plan only without native tool execution |
| `:plan approve` | Execute the last planned request with tools enabled |
| `:plan edit [task]` | Edit the pending planned request before execution |
| `:plan reject` | Clear the pending planned request |
| `:disconnect` | Disconnect current session |
| `:status` | Show session status |
| `:help` | Show help |
| `:quit` | Exit SuperQode |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Error or findings detected |
| `130` | Interrupted (Ctrl+C) |

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `GOOGLE_API_KEY` | Google AI API key |
| `DEEPSEEK_API_KEY` | Deepseek API key |
| `GROQ_API_KEY` | Groq API key |
| `OPENROUTER_API_KEY` | OpenRouter API key |

---

## Detailed Command Reference

For detailed documentation of each command group:

- [Config Commands](config-commands.md) - Configuration management
- [Provider Commands](provider-commands.md) - Provider management
- [Agents Commands](agents-commands.md) - ACP agent management
- [Auth Commands](auth-commands.md) - Authentication and security
- [Init Commands](init-commands.md) - Project initialization
