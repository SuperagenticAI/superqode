# Meta Muse Code

[Muse Code](https://dev.meta.ai/docs/muse-code) is Meta's coding agent. SuperQode connects its native Muse Session Protocol host to the TUI prompt while Muse keeps ownership of its model, tools, sandbox and login.

## Connect

Install the current Muse Code CLI on macOS or Linux and sign in through Meta's own flow:

```bash
curl -fsSL https://dev.meta.ai/install.sh | bash
muse login
```

In SuperQode:

```text
:connect muse
```

Then enter your prompt normally. Responses stream into the conversation, tool requests use SuperQode's approval dialog, and cancellation is sent to Muse. Successive prompts reuse the same Muse session and process. The host starts on the first prompt rather than at TUI startup; SuperQode suppresses the launcher's periodic updater for this child process.

This requires a Muse build supporting `muse serve` (the adapter was checked against 1.4.0). Older builds must be updated. Windows installation is not offered by this profile.

## Authentication

Meta owns authentication and credential storage. SuperQode detects local credentials without copying tokens. Credential presence is a setup hint, not proof that the host can authenticate or that billing is enabled. Muse validates its login when calling the model.

If Muse reports that it is not logged in, open `muse` in a terminal, run `/login`, then reconnect in SuperQode. This also lets you refresh a stale credential that SuperQode still detects.

The account route removes `META_API_KEY` from the Muse child environment and reports that it was ignored, preserving the account route you selected. Running `muse` directly can prefer an API key over browser sign-in; see [Meta's authentication documentation](https://dev.meta.ai/docs/muse-code/auth).

Local credential detection resolves `MUSE_AUTH_PATH`, then `$XDG_CONFIG_HOME/muse/auth.json`, then `~/.config/muse/auth.json`. It checks the provider map rather than assuming that a nonempty file means signed in.

## Commands

| Command | Behavior |
| --- | --- |
| `:connect muse` | Connect Muse Code to the prompt |
| `:muse` / `:muse connect` | Connect Muse Code |
| `:muse login` | Start Meta's login flow if no credential is detected |
| `:muse status` | Show installation and credential presence |
| `:muse help` | Show usage |

`:muse-code` is also accepted as an alias.

## Other Meta routes

| Route | Command | Harness owner |
| --- | --- | --- |
| Muse Code account | `:connect muse` | Muse Code |
| Meta BYOK | `:connect byok meta muse-spark-1.1` | SuperQode |
| Muse Code API key | Run `muse` directly with its API key | Muse Code |

Meta BYOK uses `META_MODEL_API_KEY` and is described in [BYOK Providers](byok.md#meta-muse-spark). Muse Code's separate API-key Hub row still provides external CLI guidance.

The native adapter forwards approval requests and tool results; Muse executes the tools under its own policy. Custom agent question dialogs are not enabled. SuperQode does not replace Muse's harness with Core or claim that SuperQode's sandbox runs Muse's tools.
