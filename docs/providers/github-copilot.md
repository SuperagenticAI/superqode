# GitHub Copilot

SuperQode presents one **GitHub Copilot** choice on the Subscriptions screen.
It selects the best installed official route: the SDK when available, otherwise
the Copilot CLI over ACP. Both use the models and usage allowance available to
the signed-in Copilot account. Neither turns a Copilot plan into an OpenAI API
credential.

| Path | Selection | Integration |
| --- | --- | --- |
| Copilot SDK | Preferred by `:connect copilot`; force with `:copilot sdk` | Official `github-copilot-sdk` Python package with normalized events, model selection, permission checks, evaluation, and resumable sessions |
| Copilot CLI | Automatic fallback when the SDK is absent; force with `:copilot cli` | Official `copilot` CLI over ACP. The CLI owns authentication and its own agent loop |

GitHub Copilot owns the inner agent loop in both paths. SuperQode owns the
terminal experience and the surrounding HarnessSpec, policy, evidence,
evaluation, WorkOrder, and session-switching surfaces.

## SDK Path

Install the optional SDK runtime:

```bash
uv tool install "superqode[copilot-sdk]"
```

The optional extra installs GitHub's current stable 1.x Python SDK. Its wheel
pins a compatible Copilot runtime. When an installed `copilot` command is on
`PATH`, SuperQode explicitly reuses it, avoiding the SDK's first-use download
and sharing the same `copilot login` state. Otherwise, the SDK downloads its
pinned runtime on first use. Preload it for offline or controlled environments
with:

```bash
uv run --with "github-copilot-sdk>=1.0.8,<2" python -m copilot download-runtime
```

Authenticate by signing in with the Copilot CLI or by providing a Copilot
token:

```bash
npm install -g @github/copilot
copilot login

# Alternative for service or managed environments
export COPILOT_GITHUB_TOKEN=...
```

`COPILOT_GITHUB_TOKEN` is the only token variable SuperQode explicitly forwards
to the SDK. This prevents unrelated `GH_TOKEN` or `GITHUB_TOKEN` values from
silently overriding a working local OAuth login. Account launches also remove the known `COPILOT_PROVIDER_*`,
`COPILOT_PROVIDERS_CONFIG` and offline-provider overrides, so a GitHub login
cannot silently redirect this route to a configured BYOK provider. Supplying
`COPILOT_GITHUB_TOKEN` does not bypass that guard. GitHub identity alone does
not prove included quota or how an organization bills usage; status remains
unverified when the agent does not expose that information. Use `COPILOT_GITHUB_TOKEN` for
non-interactive SuperQode SDK runs.

Inside the TUI, `:copilot login` runs the official OAuth device flow after an
explicit confirmation and streams the sign-in URL/code in place. SuperQode
does not open a browser automatically or copy the resulting credential.

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

On the CLI route, some plans advertise no selectable models at all. Verified
against Copilot CLI 1.0.75 on a Copilot Free account, `session/models` returns
an empty list and no `model` session option is offered, so Copilot chooses the
model for every turn. The CLI still answers `session/set_model` with success
for an arbitrary id in that state, so SuperQode refuses the change rather than
reporting a selection that never took effect. `:copilot models` explains this
instead of showing an empty picker.

Session modes work on every plan, including Free:

```text
:copilot mode
:copilot mode plan
```

`:copilot mode` opens a picker over the modes the CLI advertises (Agent, Plan,
and the experimental Autopilot). Short names, full ACP mode URIs, and the
displayed names are all accepted. Modes are a CLI/ACP feature, so the command
reports that clearly when the SDK route is active.

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

Both are SDK features. On a CLI-only installation they report that the SDK
extra is required and print the install command, rather than failing with a
runtime error.

For headless use:

```bash
superqode --connect copilot --print "review this repository"
superqode --runtime copilot-sdk --model gpt-5.6-sol --print "run the tests and report failures"
```

A headless `--connect copilot` resolves to the SDK route, because ACP sessions
are interactive. Without the extra installed it exits non-zero naming the
missing extra. The CLI/ACP route is a TUI feature: `--connect copilot-cli` with
`--print` exits with a usage error rather than silently answering from the
default provider.

## CLI Path

Install and authenticate the official Copilot CLI:

```bash
npm install -g @github/copilot
copilot login
```

The normal `:connect copilot` command reaches this path automatically when the
SDK extra is absent and the CLI is installed. You can also select it explicitly:

```text
:connect copilot-cli
:copilot cli
:connect acp copilot
```

`:connect copilot-acp` and `:copilot acp` remain accepted as older aliases for
the same route.

SuperQode starts `copilot --acp --stdio`, creates an ACP session for the
current repository, and renders the events in the standard SuperQode terminal
surface. Copilot CLI commands advertised over ACP remain available to the
session. GitHub currently identifies Copilot CLI ACP support as public preview,
so the ACP command contract may change independently of SuperQode.

## Route Selection

Use `:connect copilot` for the polished default. SuperQode prefers the SDK when
it is installed because that path supports direct model discovery, runtime
event normalization, permission integration, and resumable sessions.

When only the CLI is installed, the same command falls back to ACP. Use
`:copilot cli` to force that route when the vendor CLI should own
authentication and the agent loop.

The two paths maintain separate active sessions. Switching paths does not
translate a live SDK session into ACP or an ACP session into the SDK. Persisted
SDK sessions can be resumed through `:copilot resume`.

## Troubleshooting

Run `:copilot status` first. It reports SDK and CLI availability, which
authentication source is in effect, and which token variables are being
ignored.

| Symptom | Cause | Action |
| --- | --- | --- |
| The first prompt takes a long time before any output | The SDK downloads its pinned Copilot runtime on first use | Wait for the one-time download, or preload it with `python -m copilot download-runtime` |
| SDK startup exceeds 60 seconds | Runtime download, authentication, or the session handshake is blocked | Install the `copilot` CLI so the SDK can reuse it, use `:copilot cli`, or change `SUPERQODE_COPILOT_STARTUP_TIMEOUT` |
| The SDK cannot authenticate although `copilot login` works | `GH_TOKEN` or `GITHUB_TOKEN` was previously picked up | Nothing to do. SuperQode now forwards only `COPILOT_GITHUB_TOKEN` |
| A turn ends reporting a timeout | The turn exceeded the idle wait | Raise `SUPERQODE_COPILOT_TIMEOUT` (seconds, default `600`) |
| `:copilot models` reports no selectable models | The signed-in plan advertises no catalog, which is normal on Copilot Free | Let Copilot choose the model, or upgrade the plan. Use `:copilot mode` for the session controls that do apply |
| `:copilot model <id>` is refused | The account advertises no catalog, so the change could not be honoured | Nothing to do. SuperQode refuses rather than reporting a selection the CLI silently ignores |
| `:copilot sessions` says the SDK is required | Only the CLI route is installed | Install `superqode[copilot-sdk]`, or continue without persisted session listing |

Approval prompts are answered on a worker thread, so the terminal stays
responsive while a Copilot tool call waits for a decision. SDK startup and
prompt turns also have hard deadlines, so a failed network or runtime process
ends with an actionable error instead of hanging the terminal.

## Plan and Enterprise Availability

GitHub documents Copilot CLI as available with every Copilot plan. Copilot
Free and Student accounts have more limited model selection: a Copilot Free
account tested on CLI 1.0.75 advertised no selectable models over ACP at all.
Paid individual and organization plans expose the allowance and models
assigned to the account.
For Business and Enterprise seats, an organization administrator must enable
the separate Copilot CLI policy. GitHub Enterprise Server is not supported;
GitHub Enterprise Cloud and its data-residency login host are supported by the
official CLI.

## Optional Dependency Policy

GitHub Copilot is not installed with the default SuperQode package. The
`copilot-sdk` extra can be installed independently or through the optional
vendor bundle:

```bash
uv tool install "superqode[vendor-sdks]"
```

The CLI path still requires the separately installed `copilot` CLI on `PATH`.

## References

- [GitHub Copilot SDK](https://github.com/github/copilot-sdk)
- [GitHub Copilot plans](https://docs.github.com/en/copilot/get-started/plans)
- [Authenticate GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/authenticate-copilot-cli)
- [GitHub Copilot CLI ACP server](https://docs.github.com/en/copilot/reference/copilot-cli-reference/acp-server)
- [GitHub Copilot supported models](https://docs.github.com/en/copilot/reference/ai-models/supported-models)
