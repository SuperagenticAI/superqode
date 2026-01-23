# Repository Guidelines for AI Agents

This document provides guidance for AI agents (Claude Code, Codex, Gemini CLI, etc.) working with the SuperQode codebase.

## Project Structure

```
src/superqode/           # Core Python package
├── main.py              # TUI CLI entrypoint (superqode command)
├── superqe_cli.py       # SuperQE CLI entrypoint (superqe command)
├── app_main.py          # Textual TUI application
├── superqe/             # Core QE orchestration
├── workspace/           # Ephemeral workspace isolation
├── providers/           # AI model provider abstraction
├── agent/               # Agent runtime
├── tools/               # Agent tools (file, shell, search, edit)
├── commands/            # CLI commands (Click-based)
├── config/              # Configuration loading and schema
└── qr/                  # Quality Report generation

tests/                   # pytest test suites
docs/                    # MkDocs documentation source
examples/                # Sample configs and usage
scripts/                 # Helper tooling
```

## Supported Agents

SuperQode supports multiple AI coding agents via the Agent Client Protocol (ACP):

| Agent | Identity | Protocol | Install Command |
|-------|----------|----------|-----------------|
| Claude Code | `claude.com` | ACP | `npm install -g @zed-industries/claude-code-acp` |
| Gemini CLI | `geminicli.com` | ACP | `npm install -g @google/gemini-cli` |
| OpenCode | `opencode.ai` | ACP | `npm i -g opencode-ai` |
| Codex | `codex.openai.com` | ACP | Via OpenAI platform |
| OpenHands | `openhands.dev` | ACP | Via pip |
| Goose | `goose.ai` | ACP | `pipx install goose-ai` |

Agent definitions are stored in `src/superqode/agents/data/*.toml`.

## Agent Capabilities

### What Agents Can Do in SuperQode
- Execute code analysis and testing in sandboxed environments
- Propose fixes for identified issues
- Generate Quality Reports (QRs) documenting findings
- Cross-validate findings with other agents (multi-agent mode)
- Run destructive testing without affecting production code

### What Agents Cannot Do
- Modify production code directly (all changes are suggestions)
- Bypass the human-in-the-loop approval process
- Access data outside the sandboxed workspace
- Execute commands outside the defined tool permissions

## Build, Test, and Development Commands

```bash
# Setup (editable install)
uv pip install -e ".[dev]"

# Run the TUI
superqode

# Run QE automation
superqe run . --mode quick
superqe run . --mode deep --verbose

# Testing
pytest                              # Run all tests
pytest tests/test_specific.py       # Run specific test file
pytest -k "test_name"               # Run specific test

# Linting & Formatting
ruff check .                        # Check for issues
ruff format .                       # Format code
ruff check . --fix                  # Auto-fix issues

# Type checking
mypy src/superqode

# Documentation
mkdocs serve                        # Local docs at localhost:8000
```

## Coding Standards

- **Python**: 3.12+, 4-space indentation, line length 100, double quotes
- **Formatter/Linter**: Ruff
- **Docstrings**: Google style
- **Naming**: `snake_case` for modules, `CapWords` for classes, `UPPER_SNAKE` for constants
- **Tests**: pytest conventions (`test_*.py`, `Test*` classes, `test_*` functions)

## Adding a New Agent

1. Create a TOML file in `src/superqode/agents/data/` with the agent definition:
   ```toml
   identity = "example.com"
   name = "Example Agent"
   short_name = "example"
   url = "https://example.com/"
   protocol = "acp"
   type = "coding"
   description = "Description of the agent"
   tags = ["tag1", "tag2"]
   run_command."*" = "example-agent --acp"
   ```

2. Add install actions:
   ```toml
   [actions."*".install]
   command = "npm install -g example-agent"
   description = "Install Example Agent"
   ```

3. The agent will be automatically discovered by the registry.

## Configuration

- **Project config**: `superqode.yaml` in project root
- **User config**: `~/.superqode.yaml`
- **Template**: `superqode-template.yaml` for all options
- **Environment**: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, etc.

## Key Patterns

- **Safety-First**: All changes isolated in sandbox; suggestions only by default
- **Human-in-the-Loop**: Agents report findings; humans approve/reject
- **Ephemeral Workspaces**: Snapshot, modify, report, revert automatically
- **Quality Reports**: Forensic artifacts documenting what failed and why

## Runtime Artifacts

- `.superqode/` - Runtime data (not committed to git)
- `.superqode/qe-artifacts/` - QRs and patches

## Important Notes

- `app_main.py` is very large (~700KB) - consider this when making TUI changes
- Workspace isolation is critical - never bypass the revert-on-cleanup guarantee
- AGPL-3.0 license applies to all contributions
