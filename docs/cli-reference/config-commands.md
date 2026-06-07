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

Creates `./superqode.yaml` and `.superqode/` runtime directory if they don't exist.

Harness behavior is configured through harness specs:

```bash
superqode harness init coding
superqode harness validate --spec .superqode/harnesses/coding.yaml
```
