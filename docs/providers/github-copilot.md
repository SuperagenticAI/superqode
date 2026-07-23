# GitHub Copilot

SuperQode supports GitHub Copilot through two official integration paths. Both
use the models and quota available to the signed-in Copilot account. They do
not turn a Copilot licence into an OpenAI API credential.

| Path | SuperQode command | Integration | Use when |
| --- | --- | --- | --- |
| Copilot SDK | `:connect copilot` | Official `github-copilot-sdk` Python package | You want Copilot inside the SuperQode runtime with normalized events, model selection, permission checks, evaluation, and resumable sessions |
| Copilot ACP | `:connect copilot-acp` | Official `copilot --acp --stdio` server | You want the standard Copilot CLI agent exposed through ACP |

GitHub Copilot owns the inner agent loop in both paths. SuperQode owns the
terminal experience and the surrounding HarnessSpec, policy, evidence,
evaluation, WorkOrder, and session-switching surfaces.

## SDK Path

Install the optional SDK runtime:

```bash
uv tool install "superqode[copilot-sdk]"
```

The optional extra installs GitHub's current 1.x Python SDK. Its wheel pins a
compatible Copilot runtime. The SDK downloads that runtime on first use when it
is not already cached. Preload it for offline or controlled environments with:

```bash
uv run --with "github-copilot-sdk>=1.0.8,<2" python -m copilot download-runtime
```

Authenticate by signing in with the Copilot CLI or by providing a supported
GitHub token:

```bash
npm install -g @github/copilot
copilot login

# Alternative for service or managed environments
export COPILOT_GITHUB_TOKEN=...
```

Connect and select a model from the account's live catalog:

```text
:connect copilot
:copilot status
:copilot models
:copilot model gpt-5.6-sol
```

The exact model list depends on the Copilot plan, organization policy, and
GitHub rollout status. `:copilot models` is authoritative for the active
account. SuperQode does not hardcode account entitlements.

The SDK adapter maps the following data into SuperQode's runtime events:

- streamed assistant text and reasoning updates
- tool start, progress, and completion events
- permission requests
- usage and model-change events
- plan and todo updates
- cancellation and turn completion

Session state remains in the Copilot runtime store. SuperQode exposes it with:

```text
:copilot sessions
:copilot resume <session-id>
```

For headless use:

```bash
superqode --connect copilot --print "review this repository"
superqode --runtime copilot-sdk --model gpt-5.6-sol --print "run the tests and report failures"
```

## ACP Path

Install and authenticate the official Copilot CLI:

```bash
npm install -g @github/copilot
copilot login
```

Connect from the TUI:

```text
:connect copilot-acp
```

The equivalent command is also available through the general ACP catalog:

```text
:connect acp copilot
:copilot acp
```

SuperQode starts `copilot --acp --stdio`, creates an ACP session for the
current repository, and renders the events in the standard SuperQode terminal
surface. Copilot CLI commands advertised over ACP remain available to the
session. GitHub currently identifies Copilot CLI ACP support as public preview,
so the ACP command contract may change independently of SuperQode.

## Choosing a Path

Use the SDK path as the default for SuperQode workflows. It provides direct
model discovery, runtime event normalization, permission integration, and
session controls. Use ACP when compatibility with the standard Copilot CLI
agent is more important than the deeper SuperQode runtime integration.

The two paths maintain separate active sessions. Switching paths does not
translate a live SDK session into ACP or an ACP session into the SDK. Persisted
SDK sessions can be resumed through `:copilot resume`.

## Optional Dependency Policy

GitHub Copilot is not installed with the default SuperQode package. The
`copilot-sdk` extra can be installed independently or through the optional
vendor bundle:

```bash
uv tool install "superqode[vendor-sdks]"
```

The ACP path still requires the separately installed `copilot` CLI on `PATH`.

## References

- [GitHub Copilot SDK](https://github.com/github/copilot-sdk)
- [GitHub Copilot CLI ACP server](https://docs.github.com/en/copilot/reference/copilot-cli-reference/acp-server)
- [GitHub Copilot supported models](https://docs.github.com/en/copilot/reference/ai-models/supported-models)
