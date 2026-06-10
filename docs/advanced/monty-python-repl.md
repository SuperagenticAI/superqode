# Monty Python REPL

SuperQode can expose an optional `python_repl` tool backed by
[pydantic-monty](https://github.com/pydantic/monty). Monty is a small Python
interpreter written in Rust for running agent-written snippets with tighter
controls than direct host Python execution.

This is not a model provider. It is a tool the coding agent can use for quick
calculations, parsing, small transformations, and controlled interpreter-style
work during a session.

---

## Install

Monty support is optional:

```bash
uv sync --extra monty
```

For installed packages:

```bash
pip install 'superqode[monty]'
```

Verify the dependency:

```bash
superqode providers monty check
```

Run a smoke test:

```bash
superqode providers monty smoke
```

---

## Tool Availability

When `pydantic-monty` is installed, SuperQode registers `python_repl` in the
standard and full tool profiles.

If Monty is not installed, SuperQode does not expose the tool to the model. This
keeps the default install small and avoids failing sessions on missing optional
dependencies.

---

## Behavior

`python_repl` runs a Python snippet in a fresh Monty sandbox and returns the
captured `print()` output plus the value of the final expression.

| Behavior | Default |
|----------|---------|
| Isolation | Each call runs in a fresh sandbox - no state carries between calls |
| Host filesystem | No access (`open` is not defined in the sandbox) |
| Network | No access |
| Environment / stdlib | No third-party imports; only a minimal built-in subset |
| Execution limit | Duration and memory caps |
| Output limit | Truncated before returning to the model |

The tool parameters are:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `code` | - | Python snippet to execute. Use `print()` to emit output. |
| `type_check` | `false` | Type-check the snippet before running it |
| `max_duration_secs` | `2.0` | Maximum execution time in seconds |
| `max_memory` | `32 MiB` | Maximum Monty heap memory in bytes |

---

## Sandbox Isolation

Monty has **no access to the host**. The filesystem, environment variables, and
network are all unavailable inside the sandbox - for example `open(...)` raises
`NameError` and `import socket` raises `ModuleNotFoundError`. This is what makes
it safe to run model-written snippets in-process without a container.

If a task needs to read or write real project files, use the `read_file`,
`write_file`, or `edit_file` tools (which run under the permission system), or
`bash` for shell access.

> **Note:** Monty is experimental and implements a subset of Python. Snippets
> that need third-party packages (NumPy, requests, ...), the full standard
> library, or the project's own modules should use `bash` with the project's
> Python interpreter instead.

---

## When To Use

Good uses:

- Small calculations
- Parsing structured text
- Trying a tiny algorithm
- Transforming JSON or tabular data
- Testing a small pure-Python expression

Use `bash` or project test commands instead when the task needs:

- Third-party Python packages from the project environment
- Full CPython compatibility
- Running the project's real test suite
- Shell commands, package managers, or external programs

---

## Troubleshooting

If `python_repl` is missing:

```bash
superqode providers monty check
```

If the check reports that `pydantic-monty` is not installed, install the optional
extra and restart the SuperQode session:

```bash
uv sync --extra monty
```

If code cannot read files, call the network, or import third-party packages,
that is expected - Monty is fully isolated from the host by design. Use
`read_file`/`bash` for those tasks instead.

