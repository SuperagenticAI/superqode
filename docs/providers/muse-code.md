# Meta Muse Code

[Muse Code](https://dev.meta.ai) is Meta's coding agent, running on Muse Spark
models. SuperQode connects it as a subscription vendor alongside Codex, Cursor
and Copilot.

Muse Code 0.1.0 exposes no ACP server, so this is an external CLI connection
rather than a driven one. SuperQode reports what is installed and signed in and
then hands off to `muse`. It does not claim to drive Muse Code's tool loop.

## Connection route

| Route | Primary command | Authentication | Harness owner |
| --- | --- | --- | --- |
| Muse Code subscription | `:connect muse` | `muse login` | Muse Code |
| Meta BYOK | `:connect byok meta muse-spark-1.1` | `META_MODEL_API_KEY` | SuperQode |

These two routes use different credentials and different harnesses. Muse Code
owns its own loop and model selection. The BYOK route runs SuperQode's harness
against Meta's first-party API and is documented under
[BYOK Providers](byok.md#meta-muse-spark).

## Install

Muse Code ships for macOS and Linux. On Windows the profile reports as
unavailable rather than offering an installer that cannot run.

```bash
curl -fsSL https://dev.meta.ai/install.sh | bash
muse login
```

## Authentication

Meta owns this login end to end. SuperQode never implements Meta's OAuth and
never copies a Muse token; the vendor CLI owns its credential store throughout.

```text
:muse login
```

That runs Meta's own `muse login`. SuperQode checks for an existing session
first, so a valid login is never disturbed, and the browser opens only after an
explicit confirmation.

`muse login` presents an interactive menu with arrow-key selection and prints no
URL, so it needs a real terminal. There is no piped device-code flow to
substitute for it.

### A payment method is required

Meta requires a payment method on the account before a Muse session survives.
Without one, Muse removes the credential it just stored and signs the user back
out on the next run, which looks like a login that silently did nothing.

Add a payment method at [dev.meta.ai](https://dev.meta.ai), then log in again.
SuperQode states this on the connect screen rather than leaving it to be
discovered.

### META_API_KEY moves you onto per-token billing

Muse Code reads `META_API_KEY` ahead of any stored account session. A key left
in the environment therefore moves an account session onto per-token billing
without any visible change, so SuperQode registers it with the subscription
billing policy and says so.

`META_MODEL_API_KEY` is deliberately excluded from that policy. It belongs to
the `meta` BYOK provider, which Muse Code never reads.

### Credential location

SuperQode resolves Muse's credential store the way Muse resolves it:

1. `MUSE_AUTH_PATH`
2. `$XDG_CONFIG_HOME/muse/auth.json`
3. `~/.config/muse/auth.json`

Reading only the last of these reports a signed-in user as unauthenticated.

The file is authoritative in both directions, because Muse writes the credential
on login and removes it on logout, including the automatic logout it performs
when an account has no payment method. SuperQode reads the provider map inside
it rather than the file size, which stays non-zero because of the
`{"providers": {}}` skeleton.

## TUI commands

| Command | Behavior |
| --- | --- |
| `:muse` | Show readiness, the same screen as `:muse status` |
| `:muse connect` | Show readiness and connection guidance |
| `:muse login` | Run Meta's `muse login` |
| `:muse status` | Readiness detail |
| `:muse help` | Usage |

`:muse-code` is accepted as an alias. `:connect muse` reaches the same screen
from the Subscriptions menu.

## Readiness states

Readiness distinguishes owning Muse Code from being able to run it.

| State | Meaning |
| --- | --- |
| not installed | The `muse` binary is not on PATH |
| installed, no credential detected | One step away. The binary exists but no session or `META_API_KEY` was found |
| installed, credential found | A stored `muse login` session or `META_API_KEY` is present |

The middle state reports what was observed rather than asserting the user is
signed out, because a credential can live somewhere SuperQode was not told
about.

## What SuperQode does and does not do

SuperQode reports installation and sign-in state, runs Meta's login flow, warns
about billing precedence, and hands off to `muse`.

Muse Code owns the agent loop, tool execution, model selection and context. It
is closed source, and there is no ACP server to drive, so SuperQode does not
stream its tool calls or apply its own approval and sandbox policy to that
session. For a Meta model under SuperQode's own harness and policy stack, use
the BYOK route instead.
