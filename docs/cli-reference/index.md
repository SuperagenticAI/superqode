# CLI Reference

SuperQode provides a harness-first CLI for coding sessions, runtime management, provider setup, validation workflows, agents, and configuration. This reference documents the available commands, options, and usage patterns.

---

## Command Structure

```bash
superqode qe [OPTIONS] COMMAND [ARGS]...
superqode [OPTIONS] COMMAND [ARGS]...
```

### Global Options

| Option | CLI | Description |
|--------|-----|-------------|
| `--version` | superqode qe, superqode | Show version and exit |
| `--help` | superqode qe, superqode | Show help message and exit |
| `--tui` | superqode | Force the Textual TUI (default) |
| `-p`, `--print` | superqode | Run one headless coding task and print the response |
| `--mode json` | superqode | Run one headless task and emit structured JSON |
| `--profile` | superqode | Select harness profile: `build`, `plan`, `review`, or `qe` |
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
cat failing.log | superqode -p --profile qe "find the likely regression"
superqode -p --resume abc123 "continue from the last turn"
superqode -p --fork abc123 "try a safer implementation"
```

Profiles:

| Profile | Purpose |
|---------|---------|
| `build` | Full-access implementation work |
| `plan` | Read-only planning; shell requires approval and is denied in headless mode |
| `review` | Read-only code review |
| `qe` | Quality-engineering/adversarial validation; shell and network require approval |

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

Plugin manifests:

```bash
superqode plugins list
superqode plugins show my-plugin
superqode plugins validate .superqode/plugins/my-plugin/plugin.json
```

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

In the TUI, use `Ctrl+K` for the command palette or type `:status`, `:harness`, `:providers`, `:recommend coding`, `:sandbox`, `:plugins`, and `:benchmark`. Use `Ctrl+1` to open the persistent Harness sidebar tab.

Benchmark harness:

```bash
superqode benchmark run tasks.json --target superqode --target opencode --target pi --target deepagents
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

-   **Validation Commands (superqode qe)**

    ---

    Quality engineering commands for running validation sessions, viewing reports, and managing artifacts.

    [:octicons-arrow-right-24: Validation Commands](qe-commands.md)

-   **Config Commands (superqode config)**

    ---

    Configuration management commands for viewing, validating, and modifying settings.

    [:octicons-arrow-right-24: Config Commands](config-commands.md)

-   **Provider Commands (superqode providers)**

    ---

    Commands for managing BYOK providers, testing connections, and listing available models.

    [:octicons-arrow-right-24: Provider Commands](provider-commands.md)

-   **Suggestion Commands (superqode suggestions)**

    ---

    Commands for reviewing and applying verified fix suggestions from validation sessions.

    [:octicons-arrow-right-24: Suggestion Commands](suggestion-commands.md)

-   **Agents Commands (superqode agents)**

    ---

    Commands for listing, showing, and managing ACP coding agents.

    [:octicons-arrow-right-24: Agents Commands](agents-commands.md)

-   **Auth Commands (superqode auth)**

    ---

    Show authentication and security information for providers and agents.

    [:octicons-arrow-right-24: Auth Commands](auth-commands.md)

-   **Roles Commands**

    ---

    Commands for viewing and inspecting team roles and their configuration.

    [:octicons-arrow-right-24: Roles Commands](roles-commands.md)

-   **Serve Commands**

    ---

    Start LSP and web servers for IDE and browser integration.

    [:octicons-arrow-right-24: Serve Commands](serve-commands.md)

-   **Init Commands**

    ---

    Initialize SuperQode configuration for a project.

    [:octicons-arrow-right-24: Init Commands](init-commands.md)

</div>

---

## Quick Command Reference

### Validation Commands

| Command | Description |
|---------|-------------|
| `superqode qe run .` | Run validation session on current directory |
| `superqode qe run . --mode quick` | Quick 60-second scan |
| `superqode qe run . --mode deep` | Deep 30-minute analysis |
| `superqode qe run . -r security_tester` | Run specific role |
| `superqode qe roles` | List available validation roles |
| `superqode qe status` | Show workspace status |
| `superqode qe artifacts` | List validation artifacts |
| `superqode qe report` | View latest report |
| `superqode qe logs` | View agent work logs |
| `superqode qe dashboard` | Open report in web browser |
| `superqode qe feedback` | Provide feedback on findings |
| `superqode qe suppressions` | Manage finding suppressions |

### Validation Commands

| Command | Description |
|---------|-------------|
| `superqode qe run . --mode quick` | Fast validation pass |
| `superqode qe run . --mode deep` | Broader release-readiness pass |
| `superqode qe run . -r security_tester` | Focused security validation |
| `superqode qe roles` | List validation roles |
| `superqode qe artifacts` | List validation artifacts |

### Config Commands

| Command | Description |
|---------|-------------|
| `superqode config init` | Create `superqode.yaml` in the current directory (recommended) |
| `superqode config init --force` | Initialize config (overwrite if present) |
| `superqode config list-modes` | List configured modes and roles |
| `superqode config set-model MODE.ROLE MODEL` | Set model for a mode/role |
| `superqode config set-agent MODE.ROLE AGENT` | Set ACP agent for a mode/role |
| `superqode config enable-role MODE.ROLE` | Enable a role |
| `superqode config disable-role MODE.ROLE` | Disable a role |

### Provider Commands

| Command | Description |
|---------|-------------|
| `superqode providers list` | List available providers |
| `superqode providers show PROVIDER` | Show provider details |
| `superqode providers test PROVIDER` | Test provider connection |
| `superqode providers mlx ACTION` | Manage MLX models |

### Suggestion Commands

| Command | Description |
|---------|-------------|
| `superqode suggestions list` | List verified fix suggestions |
| `superqode suggestions show ID` | Show suggestion details |
| `superqode suggestions apply ID` | Apply a suggestion |
| `superqode suggestions reject ID` | Reject a suggestion |

---

## TUI Commands

When running the interactive TUI (`superqode`), prefix commands with `:`:

| TUI Command | Description |
|-------------|-------------|
| `:connect` or `:c` | Interactive connection picker (recommended) |
| `:connect acp opencode` | Connect directly to ACP agent |
| `:connect byok <provider> <model>` | Connect directly to BYOK provider |
| `:connect local <provider> <model>` | Connect directly to local model |
| `:qe <role>` | Switch to validation role mode (e.g., `:qe security_tester`) |
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
| `SUPERQODE_CONFIG` | Path to configuration file |
| `SUPERQODE_OUTPUT_DIR` | Default output directory |
| `SUPERQODE_LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `GOOGLE_API_KEY` | Google AI API key |
| `DEEPSEEK_API_KEY` | Deepseek API key |
| `GROQ_API_KEY` | Groq API key |
| `OPENROUTER_API_KEY` | OpenRouter API key |

---

## Detailed Command Reference

For detailed documentation of each command group:

- [Validation Commands](qe-commands.md) - Quality engineering operations
- [Validation Commands](advanced-validation-commands.md) - Validation workflows and release evidence
- [Config Commands](config-commands.md) - Configuration management
- [Provider Commands](provider-commands.md) - Provider management
- [Suggestion Commands](suggestion-commands.md) - Fix suggestion handling
- [Agents Commands](agents-commands.md) - ACP agent management
- [Auth Commands](auth-commands.md) - Authentication and security
- [Roles Commands](roles-commands.md) - Team roles management
- [Serve Commands](serve-commands.md) - Server commands for IDE/web
- [Init Commands](init-commands.md) - Project initialization
