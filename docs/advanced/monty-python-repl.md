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

`python_repl` runs Python snippets in a Monty REPL.

| Behavior | Default |
|----------|---------|
| Session state | Persists per SuperQode session |
| Filesystem access | Blocked |
| Workspace mount | Optional at `/workspace` |
| Mount modes | `read-only`, `overlay`, `read-write` |
| Execution limit | Duration, memory, and recursion caps |
| Output limit | Truncated before returning to the model |

The tool parameters are:

| Parameter | Description |
|-----------|-------------|
| `code` | Python snippet to execute |
| `reset` | Reset the session REPL before running |
| `type_check` | Use a fresh type-checking REPL for the snippet |
| `allow_filesystem` | Mount the workspace at `/workspace` |
| `mount_mode` | Filesystem mount mode when mounting is enabled |
| `max_duration_secs` | Maximum execution time |
| `max_memory` | Maximum Monty heap memory |

---

## Filesystem Access

Filesystem access is blocked by default. If a task needs to inspect workspace
files from Python, the tool can explicitly mount the current workspace at
`/workspace`.

Use `read-only` for inspection, `overlay` for temporary writes, and `read-write`
only when the session policy allows real file modification.

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

If code cannot read files, that is expected unless `allow_filesystem` is enabled
for the tool call.

