# Hub Commands

Browse the same versioned Harness Hub inventory used by the terminal interface.

## hub

List the complete catalog. The filters are also accepted by `hub list`.

```bash
superqode hub [OPTIONS]
sq hub --search codex
sq hub --readiness ready
```

| Option | Description |
| --- | --- |
| `--search`, `-s` | Search identity, name, description, category, runtime, source, provider, and model |
| `--readiness` | Filter to `ready`, `setup-required`, `supported`, or `not-supported` |
| `--category` | Filter by an exact Hub category |
| `--json` | Emit the versioned Hub index |
| `--public` | Exclude repository and user-registry harnesses, and report machine-independent readiness, for a publication-safe snapshot |

## hub list

List or filter the catalog explicitly. This is the recommended form for scripts.

```bash
superqode hub list
superqode hub list --search acp
superqode hub list --readiness setup-required
superqode hub list --json
superqode hub list --public --json
```

## hub show

Show one entry's readiness, integration level, runtime, continuity behavior,
description, setup guidance, and warnings.

```bash
superqode hub show codex
superqode hub show codex --json
```

The JSON catalog is presentation-neutral and excludes executable internal
objects. Documentation and website builds can consume it without duplicating
the TUI's catalog definitions.
