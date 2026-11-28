# ACP protocol controls in macOS

New macOS ACP connections default to **Auto · Prefer v2**. The choice is saved
separately for each agent and project. The CLI/TUI retain their existing v1
default and explicit v2 opt-in. `superqode serve acp` continues to negotiate
either version on its existing stdio entry point.

## Select and check a protocol

The composer shows a protocol menu beside the agent's model controls. The same
choice appears in agent setup and connection options:

| Choice | Behavior |
| --- | --- |
| Auto · Prefer v2 | Request v2; reconnect once with v1 if the agent selects v1 or explicitly rejects v2 as unsupported during initialization |
| ACP v1 · Compatibility | Request v1 for this agent in this project |
| ACP v2 · Preview (required) | Require v2; unsupported agents fail the check without falling back |

Changing the policy invalidates the previous connection check. Use **Check
protocol** or **Check connection** to test the selected policy. The check sends
no coding prompt and denies host tool execution. Check results are bound to the
project, launch configuration and protocol policy; a result for another policy
or project cannot mark the current choice ready.

The status badge shows the negotiated version, never an assumed version based
on the menu selection. Click it to see the requested version, negotiated
version, agent/adapter release and fallback reason. An orange **ACP v1 ·
Fallback** notice explains a downgrade. Strict v2 reports the compatibility
failure instead. A historical session's badge remains its recorded version even
when the menu chooses a different policy for the next session.

## Switch versions in a conversation

Finish or close the active agent session before changing its policy. A changed
policy starts a fresh agent session on the next turn while preserving the same
visible SuperQode conversation. Recent visible conversation context is handed
over; private reasoning and remembered permissions are not transferred as
conversation context. A v2 session is never resumed through v1, or vice versa.

An unchanged Auto policy resumes an existing session with its original negotiated
version. This preserves a v1 session that was created through fallback instead
of trying to upgrade its session ID during reconnect. A changed launch route or
an unavailable resume remains an explicit error or a deliberate new-session
handoff, following the existing conversation rules.

Fallback is restricted to initialization before user work. Authentication,
permission, network, session-setup and runtime failures do not cause an automatic
v1 resend. Once a prompt has been sent, a lost response may mean work was already
inserted or executed. Recovery preserves that uncertainty and the original
submission key; a protocol switch never replays that task automatically.

## Foreground and background controls

The activity panel shows **Response running**, **Waiting for your approval**, or
**Response finished · N background tasks running**. Unknown activity stays
unconfirmed. Expand child-agent transcripts, tools and display terminals to see
their current state and output.

- **Stop response** cancels foreground work and preserves independent background
  tasks.
- **Stop this tool**, **Stop terminal** and **Stop subagent** appear only when
  the agent advertises the corresponding cancellation capability.
- **Close agent session** stops the session and its owned work.

The desktop keeps the connection while background work remains. Its existing
single-writer project rule still applies: finish the remaining work or close the
session before starting another turn in that project. The composer keeps the
next draft while waiting, and does not show a foreground spinner after the
response is idle.

## Checks on your Mac

Implementation and deterministic local checks are included. Native macOS
compilation and live editor/provider checks are reserved for your machine.
Run the native tests using the existing app build setup:

```bash
swift test --build-system native --package-path apps/macos -c release
```

Then verify these user flows in the app:

1. Select Auto, check an agent, and compare the badge's requested and negotiated
   versions. Confirm there was no coding prompt during the check.
2. Select v1 and recheck. Select required v2 and confirm that a v1-only agent
   produces an actionable failure.
3. Change agent and project, then restart the app. Confirm protocol choices stay
   scoped to the saved agent/project pair.
4. Complete a harmless task, switch versions, and send a new follow-up. Confirm
   the visible conversation remains while the agent session is recreated.
5. With an agent supporting background work, confirm response completion leaves
   the session open. Exercise advertised item controls and session close.

See [validation results](acp-v2-validation.md) for executed test coverage and the
[ACP command reference](../cli-reference/acp-commands.md) for CLI controls.
