# ACP Protocol Commands

`superqode acp` provides ACP protocol diagnostics. Agent installation and catalog commands remain under `superqode agents`.

## Check a connection

```bash
superqode acp doctor claude --live --protocol-version 2 --json
superqode agents doctor codex --live --protocol-version 1
```

`superqode acp doctor` accepts an optional agent name, `--live`, `--timeout`, `--protocol-version 1|2`, and `--json`. Without `--live`, it checks installation and configuration. A live check initializes the agent and opens a session without sending a coding prompt. Output distinguishes the requested and negotiated versions; successful fallback to v1 does not verify v2 compatibility.

## Use ACP v2 Preview

CLI/TUI clients default to v1. Opt into v2 for the TUI or interactive client:

```bash
SUPERQODE_ACP_PROTOCOL_VERSION=2 superqode
SUPERQODE_ACP_PROTOCOL_VERSION=2 superqode connect acp claude
```

V1-only agents remain supported through a bounded reconnect using a v1 handshake.
Set `SUPERQODE_ACP_PROTOCOL_VERSION=1` to force v1. New macOS ACP connections
default to **Auto · Prefer v2**, with a saved per-agent/project choice of Auto,
v1 or required v2. See [macOS protocol controls](../advanced/acp-macos-protocols.md).

The Python client also accepts `protocol_policy="auto"`, `"v1"` or `"v2"`.
The last option is strict and disables v1 fallback. The existing
`protocol_version=2` API retains its v2-with-fallback behavior.

The TUI supports `:agents doctor claude --live --protocol-version 2` and `:agents cancel <session> tool|terminal <item>`. Use `:agents cancel <child-session> session` only when that child advertises cancellation. The UI also shows child sessions and background item IDs. Commands reject controls the agent has not advertised.

## Serve SuperQode to an editor

```bash
superqode serve acp
superqode serve acp --protocol-version 1
superqode serve acp --protocol-version 2 --spec harness.yaml
```

The default `auto` mode selects the highest supported version at or below the editor's request. Each connection keeps its negotiated protocol. Restricting the server to v1 provides a rollback for future connections.

V2 session history and retained submission keys live in `~/.superqode/acp-v2/sessions.sqlite3`, or under `SUPERQODE_HOME`. A successful prompt response acknowledges insertion; foreground completion arrives separately. Closing a session stops its foreground and owned background work. Cancelling foreground work leaves independent background work running.

The initial TUI retains pending submissions in memory and never automatically resends uncertain work. The client API provides an optional private, disk-backed outbox and explicit retry using the original key and session. Desktop workers use that outbox; a disconnected task is not automatically replayed as a fresh submission.

See [ACP agents](../providers/acp.md), [the agent server](../advanced/acp-agent-server.md), and [the adoption research and contracts](../advanced/acp-v2-adoption.md).
