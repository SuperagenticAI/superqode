# A2A Protocol

SuperQode can **serve** a versioned HarnessSpec as an [A2A 1.0](https://github.com/a2aproject/A2A/blob/main/docs/specification.md) agent and **call** other A2A HTTP+JSON agents. The official [`a2a-sdk`](https://github.com/a2aproject/a2a-python) implements discovery, version negotiation, task lifecycle, streaming, subscription, and cancellation. SuperQode maps those tasks onto its Harness Protocol and durable run ledger.

A2A is the primary cross-service integration surface for SuperQode: other agents, orchestrators, and multiplayer computers discover a SuperQode agent card and submit tasks without sharing SuperQode internals.

## Public preview status

| Surface | URL | Status |
| --- | --- | --- |
| Agent Card (discovery) | `https://super-agentic.ai/.well-known/agent-card.json` | **Published** (static preview) |
| A2A operations | `https://super-agentic.ai/superqode/a2a/*` | **Maintenance** until the Python A2A server is reverse-proxied |

Treat the public card as discovery and intent, not a guarantee that remote clients can run tasks yet. Local `superqode serve a2a` is fully usable today.

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

Generate the static discovery document from the same model used by the server:

```bash
superqode serve a2a \
  --public-url https://super-agentic.ai/superqode/a2a \
  --token preview-only-value \
  --export-agent-card examples/a2a/agent-card.json
```

Notes:

- The token value is **not** written into the card; supplying one only declares Bearer authentication.
- Publish the file at `/.well-known/agent-card.json`.
- The checked-in [publication artifact](../../examples/a2a/agent-card.json) matches the runtime export and the public preview card.
- Skill text on the card is product-facing (`SuperQode Harness`); the bound `--spec` still decides what the server actually runs.
- Regenerate and republish when SuperQode version, public URL, capabilities, or auth policy change.

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

An independent Node TypeScript client lives at [examples/qm-deployment-layer/interop/a2a-client.mts](../../examples/qm-deployment-layer/interop/a2a-client.mts) and is exercised by the test suite against a local server.

## Protocol boundaries

| Protocol | Role |
| --- | --- |
| **A2A** | Agent discovery and task exchange across a network boundary |
| **MCP** | Expose harness operations as tools to an existing agent |
| **ACP** | Editor/terminal clients that drive SuperQode as the coding agent |
| **Harness Protocol** | SuperQode's internal, runtime-neutral session and event contract |

## Experimental: multiplayer computers (QM)

**Status: experimental.** Not a production SuperQode feature surface.

[YC's QM](https://github.com/yc-software/qm) is an open-source multiplayer agent harness (Slack + web, org scopes, durable computers). SuperQode's center is different: versioned HarnessSpec, execution kernel, evaluation, optimization, and evidence ledger. The systems are complementary rather than competitive.

We keep a thin experimental deployment example while watching the QM ecosystem:

1. **A2A (preferred long-term boundary):** run `superqode serve a2a`; when a multiplayer computer exposes an A2A Agent Card, exchange tasks and artifacts without sharing Python or TypeScript internals.
2. **In-computer CLI (experimental packaging):** the [QM deployment-layer example](https://github.com/SuperagenticAI/superqode/tree/main/examples/qm-deployment-layer) shows how a QM sandbox tool/skill can invoke `superqode harness run` under both QM command policy and SuperQode execution policy.

Do not treat the QM example as a supported product integration. Prefer A2A for cross-service collaboration. A practical interop matrix should cover discovery, path-prefixed interface URLs, context continuity, artifacts, cancellation, approvals, authentication, and restart recovery.

See also [ACP Agents](acp.md), [MCP Tools](../configuration/mcp-config.md), and [Harness Protocol](../advanced/harness-protocol.md).
