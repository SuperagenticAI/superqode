# Init Commands

Initialize SuperQode configuration in a repository (creates `superqode.yaml`).

---

## init

```bash
superqode config init [--force]
```

### What It Does

- Creates/overwrites `./superqode.yaml`
- Creates `.superqode/` runtime directory (artifacts, history, temp)
- Uses local-first defaults: Ollama provider, `local` mode, and `qwen3:8b`
- Creates starter harness specs under `.superqode/harnesses/`

`superqode.yaml` is the project configuration file. It describes the environment: providers, endpoints, MCP servers, memory providers, aliases, and default connection hints.

Harness files describe run behavior. The starter specs under `.superqode/harnesses/`, a hand-authored `harness.yaml`, and a generated `superqode.local.yaml` are all HarnessSpec files. Load a harness explicitly with `superqode --harness <file>` or `:harness <file>`.

### Examples

```bash
# Initialize current directory
superqode config init

# Overwrite existing config
superqode config init --force

# Generate a local model harness for the TUI
superqode local init --repo .
```
