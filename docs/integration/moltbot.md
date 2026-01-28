# Moltbot Integration (Enterprise)

Moltbot is the first supported Enterprise integration for SuperQode/SuperQE. It enables
self-hosted, lab-style automation with Moltbot clients while keeping SuperQE in control of audits
and deep evaluation testing. More bot integrations will be added over time.

## What This Enables

- Self-hosted Moltbot Gateway + clients in a controlled lab environment
- SuperQode TUI access via ACP for interactive exploration
- SuperQE CLI automation for audits (current agent: OpenCode)
- Enterprise reporting outputs and deep evaluation testing against the Moltbot codebase

## Integration Model

Moltbot exposes an ACP bridge (`moltbot acp`) that connects to its Gateway. SuperQode/SuperQE can
treat this as an ACP agent for interactive sessions and automated runs.

## Scope (Enterprise)

- Setup remains self-hosted and isolated
- External channels are optional (default to isolated lab)
- No product changes or code patches are applied automatically

For access and enablement, contact the Superagentic AI team.
