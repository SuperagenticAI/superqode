# A2A Protocol

SuperQode can **serve** a versioned HarnessSpec as an [A2A 1.0](https://github.com/a2aproject/A2A/blob/main/docs/specification.md) agent and **call** other A2A HTTP+JSON agents. The official [`a2a-sdk`](https://github.com/a2aproject/a2a-python) implements discovery, version negotiation, task lifecycle, streaming, subscription, and cancellation. SuperQode maps those tasks onto its Harness Protocol and durable run ledger.

A2A is the primary cross-service integration surface for SuperQode: other agents, orchestrators, and multiplayer computers discover a SuperQode agent card and submit tasks without sharing SuperQode internals.

## Public Agent Card and pilot status

### Public Agent Card (discovery)

SuperQode publishes a static A2A Agent Card at:

**[https://super-agentic.ai/.well-known/agent-card.json](https://super-agentic.ai/.well-known/agent-card.json)**

Use that URL for discovery. The card includes product identity, skills, capabilities, bearer authentication advertisement, and `supportedInterfaces` (A2A 1.0 HTTP+JSON). Clients **must** send operational requests to the interface `url` in the card, which may differ from the discovery origin.

Inspect the live interface URL:

```bash
curl -sS https://super-agentic.ai/.well-known/agent-card.json \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['supportedInterfaces'][0]['url'])"
```

A checked-in publication artifact lives at [examples/a2a/agent-card.json](../../examples/a2a/agent-card.json). Regenerate it with `--export-agent-card` when version, public interface URL, capabilities, or auth policy change (see below).

### Operational pilot

| Surface | Status |
| --- | --- |
| Public Agent Card | **Published** at `https://super-agentic.ai/.well-known/agent-card.json` |
| A2A operations | Follow the card’s `supportedInterfaces[0].url` (temporary public pilot; bearer required) |
| Path `https://super-agentic.ai/superqode/a2a/*` | May remain **maintenance** until reverse-proxied to a SuperQode process |
| Local `superqode serve a2a` | Fully usable for development |

Treat the public pilot as experimental: authentication is required for operations, the host may cold-start, and this is not a multi-tenant production SLA. Tokens and provider keys never belong in the Agent Card.

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

A2A operations require the `A2A-Version: 1.0` header. The advertised interface uses the `HTTP+JSON` binding. Each A2A `contextId` maps to one SuperQode Harness Protocol session, so later tasks in the same context reuse harness history while each A2A task keeps its own lifecycle and artifacts.

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

`--allow-remote` is required outside loopback, and remote serving also requires a bearer token. Terminate TLS at a trusted proxy and keep the HarnessSpec execution policy restrictive: A2A authentication controls who may submit work, while the HarnessSpec controls what accepted work may do.

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
  --public-url https://your-a2a-interface.example.com \
  --token preview-only-value \
  --export-agent-card examples/a2a/agent-card.json
```

Notes:

- The token value is **not** written into the card; supplying one only declares Bearer authentication.
- Publish the generated file at `https://super-agentic.ai/.well-known/agent-card.json` (or your discovery host).
- Skill text on the card is product-facing (`SuperQode Harness`); the bound `--spec` still decides what the server actually runs.
- Avoid leading or trailing whitespace in interface URLs; clients may reject a spaced URL as invalid.
- Regenerate and republish when SuperQode version, public interface URL, capabilities, or auth policy change.

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

The TUI also provides `:a2a connect`, `:a2a discover`, `:a2a call`, and workflow commands. Client discovery uses the well-known Agent Card and routes every operation to the selected A2A 1.0 HTTP+JSON URL in `supportedInterfaces`, including path-prefixed deployments such as `/superqode/a2a`.

### Interop clients in this repository

For harness-to-harness and cross-language checks against a live or local A2A server:

- **Python smoke client:** [examples/a2a/smoke_client.py](../../examples/a2a/smoke_client.py). Discover from a base URL (for example the public Agent Card host), follow the interface URL, send a message, print task state.
- **TypeScript client:** [examples/qm-deployment-layer/interop/a2a-client.mts](../../examples/qm-deployment-layer/interop/a2a-client.mts). Dependency-free Node client used for independent wire tests (Node 22+).

Example (from the SuperQode repo root):

```bash
export SUPERQODE_A2A_TOKEN='<secret>'
uv run --extra a2a python examples/a2a/smoke_client.py https://super-agentic.ai
```

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
