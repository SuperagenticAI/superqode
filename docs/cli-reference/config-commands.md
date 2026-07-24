# Configuration Commands

Initialize, inspect, and validate `superqode.yaml`.

## Init

```bash
superqode config init
superqode config init --force
```

### Options

| Option | Description |
|--------|-------------|
| `--force` | Overwrite existing configuration |

Creates `./superqode.yaml` and the `.superqode/` runtime directory if they do not exist. The generated configuration is local-first: `default.mode` is `local`, the default provider is `ollama`, and the starter model is `qwen3:8b`.

`superqode.yaml` is project configuration. It stores provider hints, endpoint configuration, MCP servers, memory providers, aliases, and default connection settings.

`config init` also creates starter harness specs under `.superqode/harnesses/`. Those files are examples of runnable HarnessSpec policy. They are not the same as `superqode.yaml`, and they are not active until you load one with `--harness` or `:harness`.

For the TUI demo path, generate and select the local harness:

```bash
superqode local init --repo .
superqode local smoke --harness superqode.local.yaml
```

Inside the TUI, use `:local init`, `:connect local`, and `:harness superqode.local.yaml`. `superqode.local.yaml` is a HarnessSpec generated for the current machine and local model setup.

## Show

Show the resolved project configuration.

```bash
superqode config show [PATH] [OPTIONS]
```

| Option | Description |
| --- | --- |
| `-f, --format yaml|json|tree` | Select the output format. |
| `-s, --section PATH` | Show one dotted section, such as `team.modes.dev`. |

Examples:

```bash
superqode config show
superqode config show --format json
superqode config show --section team.modes.dev
superqode config show ./superqode.yaml
```

## Validate

Validate YAML syntax, required fields, supported values, provider configuration,
and harness tool availability.

```bash
superqode config validate [PATH] [--fix]
```

`--fix` attempts supported repairs for common configuration errors. Review the
resulting file before committing it.

Examples:

```bash
superqode config validate
superqode config validate ./superqode.yaml
superqode config validate --fix
```
