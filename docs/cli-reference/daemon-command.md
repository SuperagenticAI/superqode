# Daemon Command

`superqode daemon` runs the channel daemon for Telegram, Slack, and Discord.
Use it when a long local coding run needs remote approvals, progress updates,
mid-run steering, and session commands from chat.

```bash
superqode daemon [OPTIONS]
```

For the full setup flow, see [Chat Channels Remote Control](../advanced/channels.md).

## Examples

```bash
superqode daemon --check
superqode daemon
superqode daemon --telegram --no-discord
superqode daemon --config ~/.superqode/channels.yaml
```

## Options

| Option | Purpose |
| --- | --- |
| `--telegram` / `--no-telegram` | Include or exclude Telegram |
| `--slack` / `--no-slack` | Include or exclude Slack |
| `--discord` / `--no-discord` | Include or exclude Discord |
| `--config PATH` | Channels config file, default `~/.superqode/channels.yaml` |
| `--check` | Validate config and tokens, then exit |

## Security Model

The daemon is allowlist-first. Unknown chats only receive pairing instructions;
SuperQode does not run prompts for chats that are not explicitly allowed in the
channel config. Treat an allowed chat as equivalent to local keyboard access
inside the same harness, policy, approval, and sandbox rules.

