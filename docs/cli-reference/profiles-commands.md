# Profiles Commands

List harness profiles and their tool sets.

---

## profiles list

List available harness profiles.

```bash
superqode profiles list
```

### Output

```text
Profile    Description
build      Full-access implementation work
plan       Read-only planning; shell requires approval
review     Read-only code review
```

---

## tools list

List tools available in a profile.

```bash
superqode tools list [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--profile` | Profile to inspect (default: build) |
| `--json` | Emit JSON output |

### Examples

```bash
superqode tools list
superqode tools list --profile build
superqode tools list --profile plan --json
```

---

## Profiles

| Profile | Purpose | Tool Access | Shell Access |
|---------|---------|-------------|--------------|
| `build` | Full-access implementation work | All tools | Yes |
| `plan` | Read-only planning | Read-only tools | Requires approval (denied in headless mode) |
| `review` | Read-only code review | Read-only tools | No |

Use `--profile` with any headless or TUI session to apply the profile's tool permissions:

```bash
superqode -p --profile plan "design the auth refactor"
superqode -p --profile review "review the latest diff"
```
