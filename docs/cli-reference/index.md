# CLI Reference

SuperQE provides the automation CLI for quality engineering tasks. SuperQode focuses on the developer TUI and includes helper commands for agents, providers, and configuration. This reference documents the available commands, options, and usage patterns.

---

## Command Structure

```bash
superqe [OPTIONS] COMMAND [ARGS]...
superqe advanced [OPTIONS] COMMAND [ARGS]...
superqode [OPTIONS] COMMAND [ARGS]...
```

### Global Options

| Option | CLI | Description |
|--------|-----|-------------|
| `--version` | superqe, superqode | Show version and exit |
| `--help` | superqe, superqode | Show help message and exit |
| `--tui` | superqode | Force the Textual TUI (default) |

---

## Command Groups

<div class="grid cards" markdown>

-   **QE Commands (superqe)**

    ---

    Quality engineering commands for running QE sessions, viewing reports, and managing artifacts.

    [:octicons-arrow-right-24: QE Commands](qe-commands.md)

-   **SuperQE Advanced (superqe advanced)**

    ---

    Advanced quality engineering with CodeOptiX integration - AI-powered evaluation capabilities.

    [:octicons-arrow-right-24: SuperQE Commands](superqe-commands.md)

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

    Commands for reviewing and applying verified fix suggestions from QE sessions.

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

### QE Commands

| Command | Description |
|---------|-------------|
| `superqe run .` | Run QE session on current directory |
| `superqe run . --mode quick` | Quick 60-second scan |
| `superqe run . --mode deep` | Deep 30-minute analysis |
| `superqe run . -r security_tester` | Run specific role |
| `superqe roles` | List available QE roles |
| `superqe status` | Show workspace status |
| `superqe artifacts` | List QE artifacts |
| `superqe report` | View latest QR |
| `superqe logs` | View agent work logs |
| `superqe dashboard` | Open QR in web browser |
| `superqe feedback` | Provide feedback on findings |
| `superqe suppressions` | Manage finding suppressions |

### SuperQE Advanced Commands

| Command | Description |
|---------|-------------|
| `superqe advanced run .` | Enhanced evaluation with CodeOptiX |
| `superqe advanced run . --behaviors security-vulnerabilities` | Security-focused SuperQE |
| `superqe advanced behaviors` | List SuperQE enhanced behaviors |
| `superqe advanced agent-eval . --agents claude-code,codex` | Compare AI agents |
| `superqe advanced scenarios generate . --behavior security` | Generate Bloom scenarios |

### Config Commands

| Command | Description |
|---------|-------------|
| `superqe init` | Create `superqode.yaml` in the current directory (recommended) |
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

### Connect Commands

| Command | Description |
|---------|-------------|
| `superqode connect byok PROVIDER MODEL` | Connect to BYOK provider |
| `superqode connect acp AGENT` | Connect to ACP agent |
| `superqode connect local PROVIDER MODEL` | Connect to local provider |

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
| `:qe <role>` | Switch to QE role mode (e.g., `:qe security_tester`) |
| `:superqe run . --behaviors security` | Run SuperQE enhanced evaluation |
| `:superqe behaviors` | List SuperQE enhanced behaviors |
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

- [QE Commands](qe-commands.md) - Quality engineering operations
- [SuperQE Commands](superqe-commands.md) - Advanced quality engineering with CodeOptiX
- [Config Commands](config-commands.md) - Configuration management
- [Provider Commands](provider-commands.md) - Provider management
- [Suggestion Commands](suggestion-commands.md) - Fix suggestion handling
- [Agents Commands](agents-commands.md) - ACP agent management
- [Auth Commands](auth-commands.md) - Authentication and security
- [Roles Commands](roles-commands.md) - Team roles management
- [Serve Commands](serve-commands.md) - Server commands for IDE/web
- [Init Commands](init-commands.md) - Project initialization
