---
title: Dependency Compatibility
description: Review optional dependency conflicts and environment isolation requirements.
---

# Dependency compatibility

## Python and uv

The package supports Python 3.12 and 3.13 and retains
`requires-python = ">=3.12,<3.14"`. The October 11, 2026 audit used Python
3.13.6, 3.14.8, 3.15.0, and uv 0.13.0 on macOS arm64. Python 3.14 and 3.15
are dependency probes, not supported installation targets.

## Python 3.14 blockers

The existing core and development pins installed on Python 3.14, their core
imports worked, and focused runtime tests passed. However, `uv pip check`
reported that both LiteLLM 1.91.5 and Prime Agent Python Client 0.2.0 require
Python below 3.14. Successful resolution and imports do not establish a
compatible environment. Prime Agent Python Client has no newer published
release in the supported range.

Newer LiteLLM releases again provide macOS wheels and allow Python 3.14, but
upgrading LiteLLM alone would leave the Prime Agent client incompatible. The
existing dependency bounds and lockfile remain unchanged pending a coordinated
upgrade. The MLX dependencies are also explicitly limited to Python below
3.14; their markers skip installation on newer interpreters.

## Python 3.15 blockers

- FastUUID 0.14.0, required by LiteLLM, has no CPython 3.15 wheels. Its source
  build uses PyO3 0.26.0, which rejects Python 3.15. The failure was reproduced
  with both locked and current allowed dependency releases.
- The existing locked Tiktoken 0.12.0 also rejects Python 3.15 in its PyO3 build.
  Newer allowed Tiktoken releases resolve for 3.15, but FastUUID still prevents
  a complete core installation.
- PyYAML 6.0.3 has no Python 3.15 wheel on this Mac. Its source build passed,
  so a wheel-only install failure is not the same as an unsupported runtime.
- All 37 optional extras resolved individually with current allowed releases
  for Python 3.15. This is metadata resolution only; their native builds and
  runtime behavior are unverified. MLX's version markers omit its packages,
  and the shared core dependency still fails.

Current LiteLLM releases also explicitly require Python below 3.15, and the
Prime Agent client's Python bound applies here too. Do not widen the project's
Python range until dependencies install, `uv pip check` passes, and runtime
checks pass. Avoid bypassing PyO3's version check as evidence of support.

## uv and developer tools

uv 0.13.0 selects Python 3.15 as the default stable interpreter for unconstrained
new environments. Request Python 3.13 explicitly to avoid an unsupported
interpreter or resolver backtracking to an older SuperQode release:

```bash
uv tool install --python 3.13 superqode
uv sync --locked --python 3.13 --extra dev
```

The hosted installer requests Python 3.13. The compatibility workflow checks
uv 0.13.0 on Python 3.12 and 3.13, including Linux, macOS, and Windows coverage,
and retains a uv 0.8.0 regression job. Manual advisory probes check Python
3.14 and 3.15 separately and upload dependency reports. The existing lockfile
and package pins are preserved.

Use `scripts/check_python_compatibility.py` to perform real dependency
installation and consistency checks without altering `.venv`. It supports
`--locked`, `--extra <name>`, `--wheels-only`, and JSON reports. Runtime tests
remain a separate check.

The locked dependency contracts passed 151 tests on both Python 3.12.8 and
3.13.6. A temporary tool installation with current allowed dependency releases
also passed its dependency consistency check. Click 8.5 changes optional-command
and case-insensitive-choice help formatting; the CLI contract recognizes both
verified renders while still checking all 321 commands. Lazy help now uses
Click's public command API instead of its deprecated utility helper.

Python's `-X dev` mode exposed unclosed TOML files in agent discovery and the
registry; those handles now close after parsing. Thinking-session timing uses
a monotonic clock without requiring an implicitly created asyncio event loop.
These changes prepare the code for newer interpreters while keeping the
current dependency guard.

`devtools` 0.13.0 passed a Python 3.15 formatting smoke check and remains an
optional debugging tool. The preview `uv check` command runs ty but reports a
large existing diagnostics backlog, so it is not a required CI gate. See
[contributing](https://github.com/SuperagenticAI/superqode/blob/main/CONTRIBUTING.md)
for commands. Official references:
[Python 3.15 release](https://www.python.org/downloads/release/python-3150/),
[uv 0.13 release](https://github.com/astral-sh/uv/releases/tag/0.13.0), and
[FastUUID package files](https://pypi.org/project/fastuuid/0.14.0/#files).

## Optional integration conflicts

Install integrations according to repository requirements. The package
resolver blocks the following combinations because their current dependency
requirements cannot share one environment safely:

- `antigravity-sdk` or `vendor-sdks` with `mem0` or `memory-providers`
- `antigravity-sdk` or `vendor-sdks` with `a2a`
- `antigravity-sdk` or `vendor-sdks` with `adk`
- `antigravity-sdk` or `vendor-sdks` with `observability`
- `antigravity-sdk` or `vendor-sdks` with `sandbox-modal` or `sandbox-cloud`
- `antigravity-sdk` or `vendor-sdks` with `pydanticai` or `pydanticai-logfire`

These conflicts currently come from incompatible protobuf requirements. Use
separate `uv` tool environments when both integrations are required:

```bash
uv tool install "superqode[antigravity-sdk]"
uvx --from "superqode[mem0]" superqode memory status
```

Cognee also remains a separate installation because its current dependency
tree requires an older Rich release than SuperQode.
