# Contributing to SuperQode

Thanks for your interest in improving SuperQode. This guide keeps contributions fast, safe, and consistent.

## Development Setup

1. Use Python 3.12 or 3.13. Python 3.14 and 3.15 are currently blocked by dependencies.
2. Install uv using the [official uv documentation](https://docs.astral.sh/uv/).
3. Clone the repo and install dependencies with uv.

```bash
git clone https://github.com/SuperagenticAI/superqode.git
cd superqode
uv sync --locked --python 3.13 --extra dev --extra docs
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

## Python and uv Compatibility

Use uv 0.13.0 for the current toolchain. It defaults to Python 3.15 for new
unconstrained environments, so specify a supported interpreter. The hosted
installer selects Python 3.13, which also supports the MLX extra.

Run the same focused runtime contracts used by the compatibility workflow in
Python's development mode. Keep candidate environments outside the checkout:

```bash
UV_PROJECT_ENVIRONMENT=/tmp/superqode-py313 uv sync --locked --python 3.13 --extra dev
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 UV_PROJECT_ENVIRONMENT=/tmp/superqode-py313 \
  uv run --locked python -X dev -m pytest \
  -p pytest_asyncio.plugin tests/test_thinking_session_timing.py tests/test_cli_contract.py \
  tests/test_headless.py tests/test_runtime_builtin.py tests/test_mcp.py \
  tests/test_config_loader.py tests/test_tools.py tests/test_core_tool_history.py \
  tests/test_tool_call_repair.py tests/test_streaming_tool_calls.py \
  tests/test_release_metadata.py tests/test_version.py -q
```

To check an interpreter beyond the package's declared range, use the dependency
probe. It creates and removes a temporary environment, performs real installs
and source builds, then checks dependency consistency. Exit status 1 means the
probe failed. It does not establish runtime support or change the project environment:

```bash
# Check the existing lockfile on a supported interpreter.
python3 scripts/check_python_compatibility.py --python 3.13 --locked --extra dev \
  --output /tmp/superqode-py313-dependencies.json

# Check current allowed dependency releases on Python 3.15.
python3 scripts/check_python_compatibility.py --python 3.15 --extra dev \
  --output /tmp/superqode-py315-dependencies.json
```

Add `--wheels-only` to identify packages requiring a local compiler. Check
optional integrations individually with `--extra <name>` because several
extras have declared conflicts. The manual Python compatibility workflow
uploads Python 3.14 and 3.15 dependency reports as advisory checks.

Optional developer tools:

```bash
# uv's preview type checker; evaluated separately from the existing mypy check.
uv check --locked --extra dev

# Temporary debugging dependency, without adding it to pyproject.toml or uv.lock.
uv run --locked --with devtools python your_debug_script.py

# Python 3.15's built-in profiler can be explored in a standalone environment.
uv run --no-project --python 3.15 python -m profiling.sampling --help
```

`uv check` currently reports a substantial existing type-checking backlog and
is not a required CI gate. `devtools` 0.13.0 passed a Python 3.15 formatting smoke
check; it remains optional. See [dependency compatibility](docs/integrations/dependency-compatibility.md)
for the interpreter limitations and upstream blockers.

## Coding Standards

- Python 3.12-compatible syntax, 4-space indentation, line length 100
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
