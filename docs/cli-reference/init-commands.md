# Init Commands

Initialize SuperQode validation configuration in a repository (creates `superqode.yaml`).

---

## init


```bash
superqode config init [--force] [--guided]
```

### What It Does

- Creates/overwrites `./superqode.yaml`
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


# Run a quick scan

# View the latest report
```
