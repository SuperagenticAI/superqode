# A2A Keys Commands

Issue, inspect, and revoke API keys for a hosted SuperQode A2A agent.

---

## Overview

The `superqode a2a-keys` command group manages the credentials a hosted A2A
agent accepts. A key is signed rather than stored, so verifying one is a
signature check and a clock comparison with no lookup. That matters on a host
whose filesystem does not survive a deploy.

See the [A2A guide](../providers/a2a.md) for how the server uses these keys.

---

## One secret, many keys

Two values do different jobs, and mixing them up is the usual cause of a key
that looks correct but is rejected.

| Value | Where it lives | How many |
| --- | --- | --- |
| `SUPERQODE_A2A_KEY_SECRET` | On the server, never shared | One, permanent |
| `sqk_live_...` key | Given to a customer | One per customer |

The secret signs every key the deployment issues. Changing it invalidates all
of them, and a key minted with a different secret fails signature verification.

---

## Commands

### `superqode a2a-keys secret`

Print a new signing secret to set as `SUPERQODE_A2A_KEY_SECRET`.

```bash
superqode a2a-keys secret
```

Run this once. Set the value on the server that verifies keys and keep it
there.

### `superqode a2a-keys issue`

Mint a key for a customer.

```bash
superqode a2a-keys issue "Acme Corp" --tier one-off --days 30
```

| Option | Default | Description |
| --- | --- | --- |
| `--tier` | `trial` | Tier recorded in the key |
| `--days` | `30` | How long the key stays valid |
| `--test-key` | off | Mint a `sqk_test_` key instead of `sqk_live_` |
| `--secret` | `$SUPERQODE_A2A_KEY_SECRET` | Signing secret |

The key is shown once and cannot be displayed again. The command also prints
the key id, which is what you need to revoke it later.

The tier is recorded on the key and surfaced to the executor, but the server
does not currently branch on its value. Treat it as an attribution label.

### `superqode a2a-keys verify`

Check whether a key would be accepted right now.

```bash
superqode a2a-keys verify sqk_live_...
```

Reports the customer, tier, key id, and remaining validity, or the reason the
key was rejected.

### `superqode a2a-keys status`

Show whether this environment can issue and verify keys.

```bash
superqode a2a-keys status
```

Reports whether a signing secret is configured and how many key ids are
revoked.

---

## Revoking a key

Add its key id to `SUPERQODE_A2A_REVOKED_KEYS` on the server, comma separated.
No code change or redeploy of the application is required.

```bash
SUPERQODE_A2A_REVOKED_KEYS=4f649b6aa4a0,7c0c437264e1
```

---

## From the terminal interface

The same group is available as `:a2a-keys` inside the TUI, defaulting to
`status`.

---

## Related

- [A2A Agents](../providers/a2a.md)
- [Serve Commands](serve-commands.md)
- [Environment Variables](../configuration/environment-variables.md)
