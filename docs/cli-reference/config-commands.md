# Configuration Commands

Commands for viewing, validating, and editing `superqode.yaml`.

## Show

```bash
superqode config show
superqode config show --format json
superqode config show --section defaults
```

## Validate

```bash
superqode config validate
superqode config validate --fix
```

## Set

```bash
superqode config set defaults.runtime codex-sdk
superqode config set defaults.harness coding
superqode config set memory.provider local
```

## Get

```bash
superqode config get defaults.runtime
superqode config get harnesses.coding
```

Harness behavior lives in harness specs:

```bash
superqode harness init coding
superqode harness validate --spec .superqode/harnesses/coding.yaml
```
