---
title: Herdr
description: Run SuperQode in Herdr with lifecycle status and approval notifications.
---

# Herdr

[Herdr](https://herdr.dev/docs/agents/) is a terminal application for running
and monitoring coding agents in separate panes. SuperQode reports its own
status when its interactive TUI runs inside a Herdr pane.

## Start SuperQode

Install Herdr using its [installation guide](https://herdr.dev/docs/install/).
In a Herdr pane, change to your project directory and run:

```bash
superqode
```

SuperQode detects Herdr automatically. There is no extra Python dependency,
hook installation, or SuperQode configuration. Outside Herdr, the reporter
stays inactive. Headless commands do not claim a pane.

## Status and decisions

| SuperQode activity | Herdr status |
| --- | --- |
| Ready for a prompt | `idle` |
| Running a turn or another TUI operation | `working` |
| Waiting for tool approval | `blocked`, with `Approval needed` |
| Waiting for an agent question | `blocked`, with `Answer needed` |
| Finished, failed, or cancelled and ready for another prompt | `idle` |

Herdr displays the agent as `superqode`. Its normal completion and attention
notifications follow these lifecycle transitions. Resolve approvals and
questions in SuperQode as usual. A reported idle state means the TUI is ready
for input; it does not certify that a task succeeded.

SuperQode also publishes `summary`, `harness`, `model`, `session`, and `restore`
display tokens.
These are optional sidebar details, configured through
[Herdr's status metadata](https://herdr.dev/docs/agents/#custom-status-labels).
Reports contain display labels, not prompts, responses, or tool arguments.

## Inspect the integration

From the pane hosting SuperQode, or another shell targeting that Herdr server:

```bash
herdr agent list
herdr pane get <pane-id>
herdr agent wait <pane-id> --until idle --until blocked --timeout 120000
```

Use the pane ID returned by `herdr agent list`. A state wait observes the
current state and can return immediately if it already matches. For automation
that submits a new task, Herdr 0.9.3 requires a built-in agent registry entry
for `agent prompt` and `agent send-keys`. Use pane input until SuperQode is
registered upstream:

```bash
herdr pane send-text <pane-id> "summarize this repository"
herdr pane send-keys <pane-id> enter
```

These input commands do not track turn completion. See
[Herdr's agent automation](https://herdr.dev/docs/agent-automation/) for wait
semantics.

## Reporting and exit

Reporting runs in a background writer with a short timeout per CLI call.
Queued updates keep only the latest state. A missing or unavailable Herdr
server does not interrupt SuperQode. Quitting the TUI releases its pane
authority after any in-flight report.

Nested coding agents and shell processes do not receive the parent's Herdr
pane authority. Start an independent agent in its own Herdr pane to monitor
it separately.

## Restore conversations

Herdr 0.9.2 or later can restore SuperQode after a server restart. For a
connected session stored by SuperQode, it automatically registers an
interactive resume command containing the session ID, harness, provider,
model, runtime, approval policy, and plan/build mode. Switching or forking
sessions updates that command. Restoring reopens the conversation without
submitting another prompt.

You can also reopen a conversation directly:

```bash
superqode --resume <session-id>
superqode --fork <session-id>
superqode --resume <session-id> --approval-mode deny --interaction-mode plan
```

Session files, harness configuration, credentials, and the selected runtime
must remain available. If restoration fails, the TUI stays open and Herdr
reports `blocked` with `Session restore failed`. Resume a valid session in
SuperQode to recover.

The `restore` display token shows `conversation` for a resumable conversation
and `fresh` for a fresh TUI launch. Disconnected sessions and backends without
durable SuperQode session storage register a fresh launch. Arguments that
Herdr cannot represent also fall back to a fresh launch. SuperQode replaces
the previous command so an old conversation is not reopened by mistake.

Installed releases use `superqode` on `PATH`. A source checkout with a local
virtual environment and `uv` uses `uv run --project <checkout> --no-sync
superqode` so restoration keeps the same checkout. Keep that checkout available.

See [Herdr's integration contract](https://herdr.dev/docs/add-herdr-support/)
for its resume command requirements.

## Current scope

Launch SuperQode normally in a pane. Herdr's documented `agent start --kind`
list does not yet include SuperQode. Its guarded `agent prompt` and
`agent send-keys` commands also require an upstream registry entry.

This integration does not create or manage other Herdr panes on behalf of
SuperQode.
