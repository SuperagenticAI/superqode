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

### Examples

```bash
# Initialize current directory
superqode config init

# Overwrite existing config
superqode config init --force
```
