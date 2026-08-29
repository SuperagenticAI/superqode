# A2A Protocol

SuperQode can **serve** a versioned HarnessSpec as an [A2A 1.0](https://github.com/a2aproject/A2A/blob/main/docs/specification.md) agent and **call** other A2A agents over JSON-RPC 1.0, JSON-RPC 0.3, or HTTP+JSON 1.0. The official [`a2a-sdk`](https://github.com/a2aproject/a2a-python) implements discovery, version negotiation, task lifecycle, streaming, subscription, and cancellation. SuperQode maps those tasks onto its Harness Protocol and durable run ledger.

A2A is the primary cross-service integration surface for SuperQode: other agents, orchestrators, and multiplayer computers discover a SuperQode agent card and submit tasks without sharing SuperQode internals.

A2A also appears on the Protocols screen, reachable directly as
`:connect protocol-a2a`.

From the TUI, `:connect` → **Protocols** → **A2A** (or `:connect a2a` /
`:connect protocol-a2a`) opens a short screen: origin, optional credential,
and purple chips for **OAuth on**, **Headers**, **mTLS**, and **Inspect**.
A bare `:connect a2a <url>` or `:a2a connect <url>` opens that screen with
the origin filled in. Empty credential is an open card. Click Headers or mTLS to open those fields
on the same screen. After Connect, **Send** is the conversation with that
remote agent and keeps the same `contextId` thread. Cards that advertise
streaming stream their replies. Skill examples fill the message box. **Use**
saves the connection and stays on the screen; **Back** returns. **y** copies
the last reply, **r** resends, **Esc** stops a wait. The main prompt stays
your ACP or local agent. Logout clears a stored OAuth token.
Those checks are client-fit, not an A2A TCK result (TCK is planned for a
later release). A saved connection lives at `~/.superqode/a2a.json`. Later:
`:a2a call <name>`.
From the shell, `superqode connect a2a --inspect` prints the trace and
`superqode connect a2a --conformance` runs the checks. `--no-send` skips the
task so a card-only check does not wait on a cold host. Repeatable
`--header NAME:VALUE` flags are sent on every call. If the card declares an
API key scheme, inspect names the header or query parameter. A header key is
sent as that header; a query key is appended to every request URL. When the
card does not also ask for HTTP Bearer, the token field is that key. HTTP
Basic takes `--token` as `user:password`. If the card requires OAuth or OIDC
and no token is present, SuperQode uses a stored access token, refreshes it,
or tries client credentials when `SUPERQODE_A2A_OAUTH_CLIENT_ID` and
`SUPERQODE_A2A_OAUTH_CLIENT_SECRET` are set. Otherwise it opens a browser
using PKCE. The redirect URI is always
`http://localhost:19876/a2a/oauth/callback` — register that exact value with
the identity provider; SuperQode will not pick another port. Dynamic client
registration, when advertised, posts to the authorization server's
`registration_endpoint`, not the agent origin. Over SSH, or when the
authorization server advertises `device_authorization_endpoint` and there is
no local display, SuperQode uses the device-code grant instead of a
localhost redirect. Tokens sit in the OS keyring when one is available,
otherwise under `~/.superqode/a2a-oauth/`. `connect a2a --logout` deletes
that record and revokes the tokens when the authorization server advertised
`revocation_endpoint`. Mutual TLS uses `--tls-cert` and `--tls-key`.
Discovery tries `/.well-known/agent-card.json`, then `/.well-known/agent.json`.

The client speaks SendMessage, GetTask, and CancelTask (and the 0.3 method
names). It does not implement ListTasks, GetExtendedAgentCard, or claim an
A2A TCK result. The checks answer whether SuperQode can talk to the card.

## Public Agent Card and pilot status

### Public Agent Card (discovery)

SuperQode publishes a static A2A Agent Card at:

**[https://super-agentic.ai/.well-known/agent-card.json](https://super-agentic.ai/.well-known/agent-card.json)**

Use that URL for discovery. The card carries product identity, skills, capabilities, the advertised security schemes, and `supportedInterfaces`. Send operational requests to the interface `url` in the card, which may differ from the discovery origin.

The card is deliberately dual-shaped. It carries the A2A 1.0 `supportedInterfaces`
array **and** the 0.3 discovery fields (`url`, `preferredTransport`,
`protocolVersion`), because several host platforms still read only the 0.3
fields. One published document therefore satisfies both.

Inspect the advertised interfaces:

```bash
curl -sS https://super-agentic.ai/.well-known/agent-card.json \
  | python3 -c "import sys,json; [print(i['protocolBinding'], i['protocolVersion'], i['url']) for i in json.load(sys.stdin)['supportedInterfaces']]"
```

A checked-in publication artifact lives at `examples/a2a/agent-card.json`. Regenerate it with `--export-agent-card` when version, public interface URL, capabilities, or auth policy change (see below).

### Operational pilot

| Surface | Status |
| --- | --- |
| Public Agent Card | **Published** at `https://super-agentic.ai/.well-known/agent-card.json` |
| A2A operations | Follow the first entry in `supportedInterfaces` (public pilot, shortlist skill only, anonymous access permitted) |
| Path `https://super-agentic.ai/superqode/a2a/*` | **Not an A2A endpoint.** The discovery origin is a static host; operations belong at the interface `url` in the card |
| Local `superqode serve a2a` | Fully usable for development |

Treat the public pilot as experimental. The host may cold-start, and this is not a multi-tenant production deployment. Tokens and provider keys never belong in the Agent Card.

## Skills

The Agent Card advertises the skills a deployment actually serves. A loopback
bind serves both. A remote bind serves `harness-shortlist` only, unless the
operator opts in as described under Remote binds below.

| Skill | Behaviour | Cost |
| --- | --- | --- |
| `superqode-harness` | Runs the bound HarnessSpec against the server working directory | Model tokens and sandbox time |
| `harness-shortlist` | Searches the curated Harness Hub and returns ranked third-party candidates | Free for anonymous callers; one short model call for keyed callers |

### harness-shortlist

A caller on a chat surface has no checkout on the server, so this skill answers
from the published Hub. It returns catalogue entries with licence and setup
details.

SuperQode entries are held back from the ranking. Published readiness is
derived from integration level, so every entry the Hub marks `ready` is one
SuperQode supplies, while every third-party entry reads as `setup-required`.
Ranking on readiness would promote SuperQode entries on every request. They
appear separately at the end of the answer with an explicit disclosure, and
they join the ranking only when the request asks for them or when the Hub
holds no third-party entry.

Capability fitness is reported where the Hub records it and omitted where it
does not. Native harnesses and presets declare labelled policies such as
`Sandbox: local`. Managed and protocol entries carry prose descriptions,
because the vendor owns that tool loop and SuperQode has no structured record
of it. A request mentioning sandboxing returns a note saying the Hub cannot
answer that, in place of a guess inferred from a description.

The output is a catalogue shortlist. Ranking candidates against a specific
codebase requires measurement, which is what HarnessBench does.

### Routing

A2A carries no field for selecting a skill, so the server decides per turn:

1. An explicit skill id in metadata takes precedence. Set `superqode_skill` on
   either the request metadata or the message metadata.
2. When the harness skill is not served, every request goes to the shortlist.
   Nothing else is available, and phrase matching would reject callers who
   describe their situation in their own words.
3. Otherwise a narrow phrase match identifies shortlist questions, such as
   "which harness" or "recommend a harness". Everything else runs the harness.

```bash
curl -sS https://your-agent.example.com/message:send \
  -H 'A2A-Version: 1.0' -H 'Content-Type: application/json' \
  -d '{"message": {"messageId": "1", "role": "ROLE_USER",
       "parts": [{"text": "open source harness with a sandbox and approvals"}],
       "metadata": {"superqode_skill": "harness-shortlist"}}}'
```

Set `shortlist_enabled=False` in `A2AServerConfig` to serve the harness skill
alone.

## Install

```bash
uv tool install "superqode[a2a]"
```

The extra includes the official HTTP server and SQLite task-store integration. It cannot currently be combined with `antigravity-sdk` or `vendor-sdks`: A2A SDK 1.x requires Protobuf below 7 while the Antigravity SDK requires Protobuf 7.35 or newer. Run those optional runtimes in separate environments.

## Expose a harness

```bash
superqode serve a2a \
  --spec harness.yaml \
  --provider openai \
  --model gpt-5.4 \
  --harness-store .superqode/a2a/harness.sqlite3 \
  --task-store .superqode/a2a/tasks.sqlite3
```

The default listener is local at `127.0.0.1:8000`. Discovery is available at:

```text
GET /.well-known/agent-card.json
```

Three interfaces are served from one process, advertised in preference order:

| Binding | Version | Where |
| --- | --- | --- |
| `JSONRPC` | 1.0 | `POST /` |
| `JSONRPC` | 0.3 | `POST /` (same endpoint, version-negotiated) |
| `HTTP+JSON` | 1.0 | `POST /message:send` and the other REST paths |

JSONRPC leads because it is the default binding for A2A clients and the one
host platforms document. Serving 0.3 alongside 1.0 is what keeps the agent
registrable where only 0.3 is accepted; pass `legacy_v0_3=False` in
`A2AServerConfig` to serve and advertise 1.0 only.

**A2A 1.0 requests must send the `A2A-Version: 1.0` header.** When the header
is absent the SDK negotiates down to 0.3, so a 1.0 method name without the
header is rejected. A 0.3 client needs no header.

Each A2A `contextId` maps to one SuperQode Harness Protocol session, so later tasks in the same context reuse harness history while each A2A task keeps its own lifecycle and artifacts.

!!! note "0.3 compatibility covers JSON-RPC, not the legacy REST paths"

    `a2a-sdk` 1.1.2 mounts `/v1/*` REST routes when compatibility is enabled,
    but they reject 0.3 request bodies. The Agent Card therefore advertises 0.3
    under the `JSONRPC` binding only, which is the combination that works.

Remote binding is intentionally guarded:

```bash
export SUPERQODE_A2A_TOKEN='<secret>'
superqode serve a2a \
  --spec harness.yaml \
  --host 0.0.0.0 \
  --allow-remote \
  --public-url https://superqode.example.com \
  --token "$SUPERQODE_A2A_TOKEN"
```

`--allow-remote` is required outside loopback. Terminate TLS at a trusted proxy.

### Access tiers

The credential a caller presents determines what the server will do for them.

| Caller | Credential | Receives |
| --- | --- | --- |
| Anonymous | none | The shortlist skill, answered from the Hub without a model call |
| Keyed | `sqk_live_...` key | The tier recorded in the key |
| Operator | the `--token` value | Everything the deployment serves |

Discovery and health are never gated. Host platforms fetch the Agent Card
before they hold any credential, so a protected card path prevents
registration.

Anonymous access is enabled by default. The shortlist reads a public catalogue
and makes no model call for these callers, so serving them costs nothing. Set
`allow_anonymous=False` in `A2AServerConfig` to require a credential on every
operation.

A caller who presents no key is served the anonymous tier. A caller who
presents a key that fails verification receives `401` with the reason. The
distinction matters because an expired or revoked key would otherwise look
like a working one that had quietly lost its privileges.

### Reading a request with a model

Requests from keyed callers are read by a model before ranking. Anonymous
callers use the keyword parser, which is what keeps the open tier free to
serve.

The model interprets the request and returns constraints. It is never sent the
catalogue and never asked to name a harness, so it cannot introduce a claim
about a product that the Hub does not record. Any capability it returns that
the Hub has no field for is discarded.

Both sides of the call are bounded: 800 characters of request, 512 output
tokens, temperature zero, and `reasoning_effort` set to none. The output
budget covers more than the JSON reply because current Gemini Flash models
draw thinking tokens from the same allowance, and too small a budget returns
empty content.

A model call that errors, times out, or returns something other than JSON
falls back to the keyword parser. The reply metadata carries
`superqode_understood`, so a caller can tell which path produced the answer.
Watch that field in production: a missing provider key produces a silent
downgrade, not an error.

Set `understand_requests=False` in `A2AServerConfig` to keep every tier on the
keyword parser.

### Request limits

Counters are held in memory and reset when the process restarts or an idle
instance spins down. The alternative is a database on the request path, which
the spend behind a single query does not warrant. These limits bound a burst
and a bad day. They do not meter usage.

| Setting | Default | Applies to |
| --- | --- | --- |
| `anonymous_per_minute` | 10 | Callers with no credential |
| `keyed_per_minute` | 60 | Callers presenting a valid key |
| `global_per_day` | 5000 | Every caller, including exempt tiers |

A caller over its window receives `429` with `Retry-After`. Discovery and
health are exempt, so a host platform polling the Agent Card cannot be
throttled into a failed registration.

The operator token skips its per-caller window but still counts toward the
daily total. The global ceiling exists to bound the total when per-caller
accounting is wrong, so no tier is exempt from it.

Callers are identified by key id where one is presented, and otherwise by
address, reading `X-Forwarded-For` ahead of the socket address because the
hosted agent sits behind a proxy. That header is supplied by the client and
can be forged. It shapes traffic and grants no access, and the global ceiling
covers the forged case.

`GET /health` reports the current counters.

### API keys

Keys are signed, never stored. Verifying one is a signature check and a
clock comparison, with no lookup, which matters on a host whose filesystem
does not survive a deploy.

```bash
superqode a2a-keys secret                  # once, then set SUPERQODE_A2A_KEY_SECRET
superqode a2a-keys issue "Platform Team" --tier standard --days 30
superqode a2a-keys verify sqk_live_...
superqode a2a-keys status
```

`SUPERQODE_A2A_KEY_SECRET` is one value held by the server. It signs every key
that server issues, and changing it invalidates all of them. Keys minted
with a different secret fail signature verification, which is the usual cause
of a key that looks correct but is rejected.

A key carries a label, tier and expiry, and cannot be displayed again
after issue. To revoke one before it expires, add its key id to
`SUPERQODE_A2A_REVOKED_KEYS` on the server.

The tier is recorded on the key and surfaced to the executor through
`caller_tier()`, but the server does not currently branch on its value. Any
key that verifies receives the keyed rate limit and the model-backed
shortlist, whatever its tier says. Treat
the field as an attribution label that a deployment can build on, and do not
rely on it to gate behaviour until something reads it. Only two values change
what the server does: `anonymous`, applied when no credential is presented,
and `operator`, applied to the `--token` value and exempt from per-caller
limits.

With no signing secret configured, the server rejects every key. A
misconfigured server refuses work instead of opening.

### Remote binds do not serve the harness skill by default

A bearer token is shared by everyone who holds it, so it identifies a
deployment, not a person. Serving the harness skill remotely would give
every holder the same working directory under whatever the bound spec permits.
The default coding template permits shell access and writes with `sandbox:
local`, which provides no isolation from the host.

A remote bind therefore serves the shortlist skill only. The harness skill is
omitted from the Agent Card, and a request that names it is refused with an
explanation.

To serve harnesses remotely, opt in and name the spec:

```bash
superqode serve a2a \
  --spec read-only.yaml \
  --host 0.0.0.0 --allow-remote \
  --public-url https://superqode.example.com \
  --token "$SUPERQODE_A2A_TOKEN" \
  --expose-harness
```

`--expose-harness` requires both `--spec` and a token. The spec decides what an
accepted request may do, so exposing the default template remotely has to be a
deliberate choice, not a side effect of one flag.

Loopback binds are unaffected. There the caller and the repository belong to
the same person, and both skills are served.

### Durability

The bridge uses two durable stores with separate schemas:

| Store | Flag | Contents |
| --- | --- | --- |
| Harness store | `--harness-store` (alias: `--store`) | SuperQode sessions, runs, canonical events, evidence |
| A2A task store | `--task-store` | Official SDK SQLite task lookup, listing, and terminal state |

Completed A2A task records survive process restart. An actively executing request is **not** auto-resumed after a crash; operators should reconcile tasks left in `TASK_STATE_WORKING` against the SuperQode run ledger.

## Publish the runtime Agent Card

Generate the static discovery document from the same model used by the server. Set `--public-url` to the **operational** interface clients should call (the value written into `supportedInterfaces`):

```bash
superqode serve a2a \
  --host 0.0.0.0 --allow-remote \
  --public-url https://your-a2a-interface.example.com \
  --export-agent-card examples/a2a/agent-card.json
```

Notes:

- The token value is **not** written into the card. On an open deployment, supplying `--token` advertises the Bearer scheme without making it mandatory. `securityRequirements` is set only when `allow_anonymous=False`.
- Publish the generated file at `https://super-agentic.ai/.well-known/agent-card.json` (or your discovery host).
- Skill text on the card is product-facing; a remote bind serves `harness-shortlist` unless `--expose-harness` is set.
- Avoid leading or trailing whitespace in interface URLs; clients may reject a spaced URL as invalid.
- Regenerate and republish when the public interface URL, capabilities, auth policy, or skills change.
- The public pilot may take about a minute to answer the first call after idle. Open calls use keyword matching. A signed key reads the sentence. Email hello@super-agentic.ai for a key.

### The card version is not the package version

`AGENT_CARD_VERSION` in `superqode.a2a.server` holds a stable agent version and
is bumped by hand. It is not `superqode.__version__`.

A2A defines this field as the version of the agent, and callers read it to
notice that an interface has changed. Deriving it from the package version tied
republication to the release cadence, so the card required a manual upload
after every PyPI release even when nothing a caller depends on had changed.
Bump it when the interface URL, capabilities, auth policy or skills change.

The running build is reported at `GET /health` as `superqode_version`.

### Checking the published card

The discovery origin is a static host deployed separately from the A2A server,
so the two can disagree without anything failing. CI runs:

```bash
uv run python scripts/check_published_agent_card.py
```

The check fetches the discovery URL, compares it field by field against
`examples/a2a/agent-card.json`, and prints each difference. It also confirms
that `iconUrl` resolves to an image, since a dead icon renders as a broken
image in a host platform gallery, not as an absent one.

An unreachable or cold-starting host is reported without failing the build.
Pass `--url` to check a different origin, or `--warn-only` to report without
failing.

Generate the artifact the way the deployment runs, or the published card will
promise skills the server does not serve:

```bash
superqode serve a2a \
  --host 0.0.0.0 --allow-remote \
  --public-url https://superqode.example.com \
  --export-agent-card examples/a2a/agent-card.json
```

## Host platforms

### Microsoft Foundry

Foundry's A2A tool lets a Foundry agent call a remote agent as one of its tools.
It supports A2A protocol versions 1.0 and 0.3, fetches the Agent Card
anonymously by default, and is text only with no streaming. The public
SuperQode agent satisfies all of that as shipped, so no configuration change is
needed on the SuperQode side.

Foundry requires an Azure subscription with an active Foundry project, a model
deployment in that project, the **Foundry Project Manager** role to create the
connection, and **Foundry User** to create and test the agent.

Create the connection in the Foundry portal:

1. Sign in to [Microsoft Foundry](https://ai.azure.com) with the **New Foundry** toggle on.
2. Select **Tools**, then **Connect tool**.
3. Open the **Custom** tab, select **Agent2Agent (A2A)**, then **Create**.
4. Enter a name and the A2A agent endpoint.
5. Under **Authentication**, choose a method.

| Field | Value |
| --- | --- |
| Name | `superqode` |
| A2A Agent Endpoint | `https://superqode.onrender.com` |
| Agent card path | Leave unset. Foundry resolves `/.well-known/agent-card.json` under the target |
| Authentication | **None** for the open tier, or key based with credential name `Authorization` and value `Bearer <key>` |

The same connection can be created with the Azure Developer CLI:

```bash
azd ai connection create superqode-a2a \
  --kind remote-a2a \
  --target https://superqode.onrender.com \
  --auth-type none
```

Four points decide whether this works on the first attempt.

The connection target is the operational URL carried in the card, not the
discovery origin. Registering `https://super-agentic.ai` fails, because that
host serves the card and nothing else. The SuperQode agent serves an identical
card at both hosts, so Foundry can resolve the default card path under the
operational URL.

Anonymous callers are limited to ten requests per minute. That is enough to
evaluate the connection and too little for regular use, so request a key before
wiring the connection into anything that runs on a schedule.

The operational pilot runs on a suspending free tier. A first request after an
idle period can take about a minute to return, which is long enough for a
connection test to look like a failure. Send a request to `/health` and wait for
it to answer before creating the connection.

Registration is scoped to the project that creates it. Foundry has no public
catalogue of third-party agents, so registering SuperQode makes it available
inside that project and does not list it for other Foundry customers.

## Python server API

```python
from superqode.a2a import create_a2a_server

server = await create_a2a_server(
    spec="harness.yaml",
    server_url="https://superqode.example.com",
    provider="openai",
    model="gpt-5.4",
    bearer_token="...",
)
server.run(host="0.0.0.0", port=8000)
```

Advanced applications can pass a configured `HarnessProtocolController` instead of a spec. That is the clean embedding boundary for custom adapters and durable stores.

## Call another A2A agent

```python
from superqode.a2a import A2AClient

async with A2AClient("https://agent.example.com", bearer_token="...") as client:
    card = await client.get_agent_card()
    task = await client.send_message("Review the current change")
```

The TUI also provides `:a2a connect`, `:a2a discover`, `:a2a call`, and workflow commands. `:a2a connect` with no URL opens the same screen as `:connect a2a`. Client discovery uses the well-known Agent Card and speaks the first advertised interface it can: JSON-RPC 1.0, JSON-RPC 0.3, or HTTP+JSON 1.0. Operations implemented today are send, get, and cancel. ListTasks and GetExtendedAgentCard are not implemented.

### Interop clients in this repository

For harness-to-harness and cross-language checks against a live or local A2A server:

- **Python smoke client:** `examples/a2a/smoke_client.py`. Discover from a base URL (for example the public Agent Card host), follow the interface URL, send a message, print task state.
- **TypeScript client:** `examples/qm-deployment-layer/interop/a2a-client.mts`. Dependency-free Node client used for independent wire tests (Node 22+).

Example (from the SuperQode repo root):

```bash
uv run --extra a2a python examples/a2a/smoke_client.py https://super-agentic.ai
```

A token is optional. Set `SUPERQODE_A2A_TOKEN` only when the agent requires Bearer.

## Protocol boundaries

| Protocol | Role |
| --- | --- |
| **A2A** | Agent discovery and task exchange across a network boundary |
| **MCP** | Expose harness operations as tools to an existing agent |
| **ACP** | Editor/terminal clients that drive SuperQode as the coding agent |
| **Harness Protocol** | SuperQode's internal, runtime-neutral session and event contract |

## Multiplayer computers and QM (experimental)

**Status: experimental.** Not a production SuperQode product integration or support contract.

[YC's QM](https://github.com/yc-software/qm) is an open-source multiplayer agent harness (Slack + web, org scopes, durable computers). SuperQode’s center is different: versioned HarnessSpec, execution kernel, evaluation, optimization, and evidence ledger. The systems are complementary: multiplayer computers host people and shared work; SuperQode exposes a constrained coding harness other agents can call.

Preferred boundary for collaboration is **A2A**:

1. **Across services (recommended):** run `superqode serve a2a` and publish an Agent Card. Clients (including TypeScript or future multiplayer-computer agents) discover SuperQode and exchange tasks and artifacts without sharing Python or TypeScript internals.
2. **Inside a QM-style sandbox (optional packaging):** the [QM deployment-layer example](https://github.com/SuperagenticAI/superqode/tree/main/examples/qm-deployment-layer) shows how a tool/skill bootstrap can invoke `superqode harness run` under both outer command policy and SuperQode execution policy.

Do not treat the QM example as official QM support. Prefer protocol-level interop fixtures: discovery, path-aware interface URLs, authentication, context continuity, artifacts, cancellation, approvals, and restart recovery. See also [Protocols and tools](../integrations/protocols-tools.md#a2a-and-multiplayer-computers).

See also [ACP Agents](acp.md), [MCP Tools](../configuration/mcp-config.md), and [Harness Protocol](../advanced/harness-protocol.md).
