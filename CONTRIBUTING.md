# Contributing to SuperQode

Thanks for your interest in improving SuperQode. This guide keeps contributions fast, safe, and consistent.

## Development Setup

1. Ensure Python 3.12+ is installed.
2. Install uv using the [official uv documentation](https://docs.astral.sh/uv/).
3. Clone the repo and install dependencies with uv.

```bash
git clone https://github.com/SuperagenticAI/superqode.git
cd superqode
uv sync --extra dev --extra docs
```

## Common Commands

```bash
# Run tests
uv run pytest

# Lint and format
uv run ruff check .
uv run ruff format .

# Type checks
uv run mypy src/superqode

# Build docs locally
uv run mkdocs serve
```

## Coding Standards

- Python 3.12+, 4-space indentation, line length 100
- Double quotes, Google-style docstrings
- Prefer small, focused changes with tests
- Keep public behavior changes documented

## Pull Requests

- Explain the problem and the solution clearly.
- Link related issues when applicable.
- Include tests or rationale if tests are not added.
- Update docs when behavior or CLI output changes.

## Reporting Issues

Use GitHub Issues for bugs and feature requests. Include:
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Python version, provider)
