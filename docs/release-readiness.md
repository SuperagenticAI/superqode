# Release Readiness

Use this checklist before publishing a SuperQode release.

## User-Facing Scope

This release should present SuperQode as a coding agent harness first:

- Interactive TUI for coding-agent sessions
- Headless CLI for coding tasks and provider checks
- ACP, BYOK, and Local provider support
- Compact tool activity display
- Dynamic OpenCode free model discovery
- Local DS4 provider support
- Optional Monty-backed `python_repl` tool
- SuperQE workflows for release validation and quality engineering

SuperQE should remain documented as an important workflow, but not as the only purpose of SuperQode.

## Documentation Checklist

- README describes SuperQode as a multi-agent coding harness.
- Documentation home page matches the README positioning.
- TUI reference covers `:connect`, local provider selection, BYOK selection, log verbosity, and compact tool activity.
- Local providers page documents DS4 without exposing local user paths.
- Provider command reference documents provider checks, model listing, dynamic OpenCode model discovery, and Monty checks.
- Tools system page lists the optional `python_repl` tool and links to the Monty setup guide.
- Monty guide explains installation, availability, filesystem behavior, limits, and troubleshooting.
- No user-facing release copy uses em dashes.

## Manual Smoke Tests

Run these checks from a clean working tree or a disposable test repository:

```bash
superqode --help
superqode providers list
superqode providers recommend local
superqode providers models ds4
superqode providers guide ds4
superqode providers monty check
```

If Monty is installed:

```bash
superqode providers monty smoke
```

For the TUI:

1. Start `superqode`.
2. Open `:connect`.
3. Open `:connect local` and confirm DS4 appears when the local server is available.
4. Open the ACP provider flow and confirm OpenCode free models are discovered dynamically when OpenCode is installed.
5. Open `:connect byok` and confirm provider setup hints are readable.
6. Run a small coding prompt and confirm tool calls are compact by default.
7. Run `:log verbose` and confirm successful tool output can be expanded.

## Automated Checks

Recommended focused checks:

```bash
uv run pytest tests/test_tui_tool_display.py tests/test_tools.py tests/test_agent_loop_harness.py tests/test_monty_tool.py tests/test_acp_free_models.py
uv run ruff check src tests
uv run ruff format --check src tests
```

Recommended packaging check:

```bash
uv build
```

## Release Notes Template

```markdown
## SuperQode Release

### Highlights

- Coding-harness-first TUI and CLI experience.
- Improved provider and model selection for ACP, BYOK, and Local workflows.
- Dynamic OpenCode free model discovery.
- Local DS4 provider support.
- Optional Monty-backed `python_repl` tool.
- Compact TUI tool activity display.

### Upgrade Notes

- Monty support is optional. Install with `superqode[monty]` or use `uv sync --extra monty` in a source checkout.
- DS4 requires a running local DS4-compatible server.
- Dynamic OpenCode free model discovery depends on the installed OpenCode CLI or available provider metadata.

### Validation

- List the pytest, ruff, packaging, and manual TUI checks performed for the release.
```
