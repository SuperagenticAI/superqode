# Configuration Commands

Commands for initializing `superqode.yaml`.

## Init

```bash
superqode config init
superqode config init --force
```

### Options

| Option | Description |
|--------|-------------|
| `--force` | Overwrite existing configuration |

Creates `./superqode.yaml` and `.superqode/` runtime directory if they don't exist. The generated config is local first: `default.mode` is `local`, the default provider is `ollama`, and the starter model is `qwen3:8b`.

`superqode.yaml` is project configuration. It stores provider hints, endpoint configuration, MCP servers, memory providers, aliases, and default connection settings.

`config init` also creates starter harness specs under `.superqode/harnesses/`. Those files are examples of runnable HarnessSpec policy. They are not the same as `superqode.yaml`, and they are not active until you load one with `--harness` or `:harness`.

For the TUI demo path, generate and select the local harness:

```bash
superqode local init --repo .
superqode local smoke --harness superqode.local.yaml
```

Inside the TUI, use `:local init`, `:connect local`, and `:harness superqode.local.yaml`. `superqode.local.yaml` is a HarnessSpec generated for the current machine and local model setup.
