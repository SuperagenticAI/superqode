# Init Commands

Initialize SuperQode validation configuration in a repository (creates `superqode.yaml`).

---

## init

Create `superqode.yaml` in the current directory from the comprehensive role catalog template.

```bash
superqode config init [--force] [--guided]
```

### What It Does

- Creates/overwrites `./superqode.yaml`
- Uses the comprehensive role catalog template (disable or remove roles you don’t need)
- Creates `.superqode/` runtime directory (artifacts, history, temp)

### Examples

```bash
# Initialize current directory
superqode config init

# Guided, interactive setup
superqode config init --guided

# Overwrite existing config
superqode config init --force
```

---

## Next Steps

```bash
# Inspect configuration
cat superqode.yaml

# List configured modes/roles (SuperQode CLI)
superqode config list-modes

# Run a quick scan
superqode qe run . --mode quick

# View the latest report
superqode qe report
```
