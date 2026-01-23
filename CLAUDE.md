# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**SuperQode** is a quality-oriented harness and orchestration layer for AI coding agents. It consists of two entrypoints:
- **`superqode`**: Interactive TUI for developers
- **`superqe`**: Automation CLI for QE/CI pipelines

**Core Philosophy:** *Let agents break the code. Prove the fix. Ship with confidence.*

SuperQE is the quality paradigm: multiple QE agents attack and validate code in sandboxes before it ships. This is adversarial validation with evidence, not test generation.

## Build & Development Commands

```bash
# Setup (editable install with dev dependencies)
uv pip install -e ".[dev]"

# Run the TUI
superqode

# Run QE automation
superqe run . --mode quick
superqe run . --mode deep --verbose

# Testing
pytest                              # Run all tests
pytest tests/test_specific.py       # Run specific test file
pytest tests/test_specific.py -k "test_name"  # Run specific test

# Linting & Formatting
ruff check .                        # Check for issues
ruff format .                       # Format code
ruff check . --fix                  # Auto-fix issues

# Type checking
mypy src/superqode

# Documentation
mkdocs serve                        # Local docs at localhost:8000
```

## Architecture Overview

### Key Modules

```
src/superqode/
├── main.py              # TUI CLI entrypoint (superqode command)
├── superqe_cli.py       # SuperQE CLI entrypoint (superqe command)
├── app_main.py          # Textual TUI application (large monolithic file)
│
├── superqe/             # Core QE orchestration
│   ├── orchestrator.py  # Multi-role coordination
│   ├── session.py       # QE session state management
│   ├── roles.py         # QE role definitions (security_tester, api_tester, etc.)
│   ├── verifier.py      # Fix verification logic
│   └── noise.py         # False positive filtering
│
├── workspace/           # Ephemeral workspace isolation
│   ├── manager.py       # Workspace lifecycle
│   ├── snapshot.py      # File-based isolation
│   ├── git_snapshot.py  # Git stash isolation
│   └── worktree.py      # Git worktree isolation
│
├── providers/           # AI model provider abstraction
│   ├── manager.py       # Provider lifecycle
│   ├── registry.py      # Provider registration
│   └── gateway/         # LiteLLM, OpenResponses gateways
│
├── agent/               # Agent runtime
│   ├── loop.py          # Main agent execution loop
│   └── system_prompts.py
│
├── tools/               # Agent tools (file, shell, search, edit, etc.)
├── commands/            # CLI commands (Click-based)
├── config/              # Configuration loading and schema validation
└── qr/                  # Quality Report generation
```

### Ephemeral Workspace Model

This is the core safety feature:
1. **SNAPSHOT** - Original code preserved
2. **QE SANDBOX** - Agents modify, test, break freely
3. **REPORT** - Document findings and fixes
4. **REVERT** - All changes removed automatically
5. **ARTIFACTS** - QRs and patches preserved in `.superqode/qe-artifacts/`

Isolation modes: `snapshot` (file-based), `git_snapshot` (stash), `worktree` (git worktree)

### Execution Pipeline

```
Request Parse → Resolve → Workspace Setup → Runner → Verification → Noise Filter → QR Generation → Cleanup
```

### Multi-Agent QE Architecture

- Multiple agents with different models cross-validate findings
- Roles defined in `superqe/roles.py` (security_tester, api_tester, fullstack, unit_tester, etc.)
- Session coordination with locking in `workspace/coordinator.py`

### Provider Abstraction

- **BYOK**: LiteLLM gateway for Anthropic, OpenAI, Google, etc.
- **ACP**: Agent Client Protocol for SuperAgentic platform
- **Local**: Ollama with local models
- **OpenResponses**: Community models

## Configuration

Config hierarchy (highest to lowest priority):
1. CLI Arguments
2. Environment Variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.)
3. User config (`~/.superqode.yaml`)
4. Project config (`./superqode.yaml`)

Key config files:
- `superqode.yaml` - Project configuration
- `superqode-template.yaml` - Full template with all options
- `superqode-all.yaml` - All roles enabled

## Coding Standards

- Python 3.12+, 4-space indentation, line length 100
- Double quotes, Google-style docstrings
- Ruff for linting/formatting
- pytest for testing (`test_*.py`, `Test*` classes, `test_*` functions)

## Key Patterns

- **Safety-First**: All changes isolated in sandbox, suggestions only by default
- **Human-in-the-Loop**: Agents report findings; humans approve/reject
- **Quality Reports (QRs)**: Forensic artifacts documenting what failed, how, why, and whether fixes work
- **Constitution System**: Guardrails for agent behavior in `superqe/constitution/`

## Runtime Artifacts

- `.superqode/` - Runtime data (not committed)
- `.superqode/qe-artifacts/` - QRs and patches

## Important Notes

- `app_main.py` is very large (~700KB) - consider this when making TUI changes
- Workspace isolation is critical - never bypass the revert-on-cleanup guarantee
- AGPL-3.0 license applies to all contributions
