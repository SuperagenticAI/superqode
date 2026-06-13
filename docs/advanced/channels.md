# Chat Channels: Remote Control

Long Local Agentic Coding runs should not chain you to a terminal. The
SuperQode daemon connects your agent to Telegram, Slack, and Discord so a
run that takes an hour on your workstation can be supervised from your
phone: progress, tool approvals, mid-run steering, and session control.

```bash
pip install superqode[channels]   # Telegram alone needs no extra
superqode daemon
```

## What a channel can do

| You send | The agent does |
|---|---|
| plain text | runs it as a prompt; while a run is active, plain text steers the run instead |
| `/approve` or `/approve always` | approves the pending tool call and resumes |
| `/deny [reason]` | rejects the pending tool call, optionally with feedback |
| `/status` | session, model, run state, pending approvals |
| `/stop` | cancels the active run |
| `/new` | starts a fresh session |
| `/model provider/model` | switches model |
| `/cd path` | switches working directory |

When a run hits a tool that needs approval, the chat receives the tool name
and arguments with **Approve / Always / Deny buttons** on all three
platforms (Slack Block Kit, Discord components, Telegram inline keyboards).
Completion messages carry **Status / New / Stop** buttons. Typing the
commands always works as a fallback. The approval semantics are identical to
the TUI: the run pauses, your decision resumes it.

On Slack, replies are **threaded** under the message that started the task,
so each task reads as one conversation. Buttons on Slack need
**Interactivity** enabled on the app (Socket Mode delivers the button
presses; no Request URL is needed).

While the agent works, the "Working on it" message is **edited in place**
with live tool progress (`🤖 Working (3 tool calls) / 🛠️ bash: pytest -q`),
throttled to avoid rate limits, on all three platforms. The final message
ends with a compact runtime footer (`🧠 ollama/qwen3-coder · 📁 ~/repo`) so
you always know which model and directory produced the answer.

## Security model

Allowlist-first, no exceptions:

1. Every channel has an allowlist of chat or channel ids in the config.
2. A message from any other chat gets pairing instructions (showing the chat
   id to add) and nothing else. The agent never runs for unknown chats.
3. Tokens come from environment variables, never from the config file by
   default.
4. The daemon is outbound-only: Telegram long-polls, Slack uses Socket Mode,
   Discord uses the Gateway. No inbound HTTP port is opened.

Treat any allowed chat as having the same power as your keyboard: it can run
prompts that edit files and execute commands on the daemon's machine, inside
the same permission, exec-policy, and sandbox rules every SuperQode run gets.

## Setup

### 1. Configure tokens and allowlists

Create `~/.superqode/channels.yaml`:

```yaml
defaults:
  provider: ollama
  model: qwen3-coder:30b-a3b
  working_directory: ~/projects/myrepo
  # harness: ~/projects/myrepo/harness.yaml   # optional tuned harness

telegram:
  allowed_chat_ids: ["123456789"]

slack:
  allowed_channel_ids: ["C0123ABCD"]

discord:
  allowed_channel_ids: ["987654321098765432"]
```

Export the tokens for the channels you use:

```bash
export SUPERQODE_TELEGRAM_BOT_TOKEN="123:abc"     # from @BotFather
export SUPERQODE_SLACK_APP_TOKEN="xapp-..."       # Socket Mode app token
export SUPERQODE_SLACK_BOT_TOKEN="xoxb-..."       # bot token
export SUPERQODE_DISCORD_BOT_TOKEN="..."          # Discord bot token
```

Platform prerequisites:

- **Telegram**: create a bot with @BotFather. Nothing else; the transport is
  stdlib-only.
- **Slack**: create an app, enable Socket Mode (app-level token with
  `connections:write`), add a bot token with `chat:write`, subscribe to
  `message.im` and `app_mention` events, and install it to your workspace.
- **Discord**: create an application and bot, enable the Message Content
  intent, and invite the bot to your server with read/send permissions.

### 2. Find your chat id

Start the daemon and message the bot from the chat you want to pair. Chats
not yet on the allowlist receive pairing instructions containing the exact
id to add. Add it to `channels.yaml` and restart.

### 3. Validate and run

```bash
superqode daemon --check     # tokens, dependencies, connectivity
superqode daemon             # all configured channels
superqode daemon --telegram --no-discord   # explicit selection
```

A lock file (`~/.superqode/daemon.lock`) prevents two daemons from running
against the same state.

## A full remote session

```text
you:    refactor the auth module and run the tests
agent:  Working on it. Plain text now steers the run.
agent:  Tool approval needed
        tool: bash
        args: {'command': 'pytest tests/ -q'}
        [Approve] [Always] [Deny]
you:    (taps Approve)
agent:  Approved.
you:    skip the slow integration tests
agent:  Steering the active run with your message.
agent:  Refactor complete: 3 files changed, 42 tests passing. ...
```

## Pairing with the rest of SuperQode

- Point `defaults.harness` at a spec from `superqode local doctor --generate`
  and every chat session runs your tuned local stack.
- Approvals respect [exec policies and permission rules](policies.md): hard
  denies cannot be approved from chat either.
- Sessions are regular SuperQode sessions: inspect them later with
  `superqode sessions` or export a transcript.

## Related pages

- [Local Agentic Coding](../local-agentic-coding.md)
- [Policies & Safety](policies.md)
- [Headless & CI](headless-ci.md)
