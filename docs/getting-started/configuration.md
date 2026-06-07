# Configuration

SuperQode configuration is now harness-first. `superqode.yaml` selects defaults and points to reusable harness specs; it no longer uses built-in `dev`, `qe`, or `devops` role modes.

## Create Config

```bash
superqode config init
superqode harness init coding --output .superqode/harnesses/coding.yaml
```

## Minimal `superqode.yaml`

```yaml
version: 2

project:
  name: My SuperQode Project
  root: .

defaults:
  harness: coding
  runtime: builtin
  provider: ollama
  model: gemma4:12b-mlx

harnesses:
  coding: .superqode/harnesses/coding.yaml

memory:
  enabled: true
  provider: local

mcp_servers: {}
providers: {}
```

## Common Tasks

```bash
superqode config show
superqode config validate
superqode config set defaults.runtime codex-sdk
superqode config get defaults.runtime
```

Use harness specs for behavior, tools, prompts, checks, and workflows:

```bash
superqode harness templates
superqode harness validate --spec .superqode/harnesses/coding.yaml
```
