# Moltbot Integration (Enterprise)

Moltbot is the first supported Enterprise integration for SuperQode/SuperQE. It is **experimental**
and intended for **self-hosted** deployments only. It enables lab-style automation with Moltbot
clients while keeping SuperQE in control of audits and deep evaluation testing. More bot
integrations will be added over time.

## What This Enables

- Self-hosted Moltbot Gateway + clients in a controlled lab environment
- SuperQode TUI access via ACP for interactive exploration
- SuperQE CLI automation for audits (current agent: OpenCode)
- Enterprise reporting outputs and deep evaluation testing against the Moltbot codebase
- Secure and private **local models** for lab isolation

## Install

```bash
npm install -g moltbot@latest
```

## Integration Model

Moltbot exposes an ACP bridge (`moltbot acp`) that connects to its Gateway. SuperQode/SuperQE can
treat this as an ACP agent for interactive sessions and automated runs.

## Quick Start (Enterprise)

```bash
# Start the gateway (in a separate terminal)
moltbot gateway --port 18789 --verbose

# Connect via SuperQode
superqode connect acp moltbot
```

If your gateway requires auth, pass `--token` or `--password` to the ACP bridge.

## Scope (Enterprise)

- Setup remains self-hosted and isolated
- External channels are optional (default to isolated lab)
- No product changes or code patches are applied automatically
 - Use secure, private **local models** for enterprise lab environments

For access and enablement, contact the Superagentic AI team.
