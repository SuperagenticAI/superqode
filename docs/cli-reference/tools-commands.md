# Tools Commands

`superqode tools` inspects the builtin tools available to a harness profile.
Use it before tuning a harness, debugging tool access, or comparing policy
profiles.

```bash
superqode tools COMMAND [ARGS]...
```

## list

List tools available to a harness profile.

```bash
superqode tools list
superqode tools list --profile build
superqode tools list --profile plan --json
```

| Option | Purpose |
| --- | --- |
| `--profile TEXT` | Harness profile to inspect |
| `--json` | Emit JSON |

See [Tools Catalog](../advanced/tools-catalog.md) for the full tool behavior,
permissions, and guarantees.

