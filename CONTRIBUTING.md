# Contributing to SuperQode

Thanks for your interest in improving SuperQode. This guide keeps contributions fast, safe, and consistent.

## Development Setup

1. Ensure Python 3.12+ is installed.
2. Clone the repo and create a virtual environment.

```bash
git clone https://github.com/SuperagenticAI/superqode.git
cd superqode
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Common Commands

```bash
# Run tests
pytest

# Lint and format
ruff check .
ruff format .

# Type checks
mypy src/superqode

# Build docs locally
mkdocs serve
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
