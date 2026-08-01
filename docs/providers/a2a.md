# A2A Protocol

SuperQode can expose a versioned HarnessSpec as an [A2A 1.0](https://github.com/a2aproject/A2A/blob/main/docs/specification.md) agent and can call other A2A HTTP+JSON agents. The official [`a2a-sdk`](https://github.com/a2aproject/a2a-python) implements discovery, version negotiation, task lifecycle, streaming, subscription, and cancellation; SuperQode maps those tasks to its Harness Protocol and durable run ledger.

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

The bridge uses two durable stores with separate schemas. The SuperQode harness store persists sessions, runs, canonical events, and evidence. The official SDK's SQLite task store persists A2A task lookup, listing, and terminal task state across server restarts. The legacy `--store` spelling remains an alias for `--harness-store`. A process crash does not resume an A2A request that was actively executing; production operators should reconcile tasks left in `TASK_STATE_WORKING` against the durable SuperQode run ledger.

## Publish the runtime Agent Card

Generate the static discovery document from the same model used by the server:

```bash
superqode serve a2a \
  --spec harness.yaml \
  --public-url https://super-agentic.ai/superqode/a2a \
  --token preview-only-value \
  --export-agent-card agent-card.json
```

The token value is not written to the document; supplying one declares Bearer authentication. Publish the generated file at `/.well-known/agent-card.json`. The checked-in [publication example](../../examples/a2a/agent-card.json) is generated this way and protected against runtime drift by tests.

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

Advanced applications can pass a configured `HarnessProtocolController` instead of a spec. This is the clean embedding boundary for custom adapters and durable stores.

## Call another A2A agent

```python
from superqode.a2a import A2AClient

async with A2AClient("https://agent.example.com", bearer_token="...") as client:
    card = await client.get_agent_card()
    task = await client.send_message("Review the current change")
```

The TUI also provides `:a2a connect`, `:a2a discover`, `:a2a call`, and workflow commands. Client discovery uses the well-known Agent Card and routes every operation to the selected A2A 1.0 HTTP+JSON URL in `supportedInterfaces`, including path-prefixed deployments.

## QM collaboration pattern

[YC's QM](https://github.com/yc-software/qm) and SuperQode overlap at the product level but have different technical centers: QM provides an organization-shared, durable TypeScript agent computer; SuperQode provides a Python HarnessSpec, execution kernel, evaluation, optimization, and evidence ledger. That makes A2A a useful collaboration boundary rather than a reason to merge internals.

There are two complementary modes:

1. **Inside the computer:** install the [QM deployment-layer example](https://github.com/SuperagenticAI/superqode/tree/main/examples/qm-deployment-layer). QM invokes `superqode harness run` in the same durable workspace under both QM command policy and the SuperQode execution policy.
2. **Across services:** run `superqode serve a2a`; when QM exposes an A2A Agent Card, exchange A2A tasks and artifacts. Keep the direct Harness API as a private fallback for capabilities A2A does not yet represent.

A practical interop demo should test Agent Card discovery, Python-to-TypeScript and TypeScript-to-Python task exchange, context continuity, artifact transfer, cancellation, approval-required states, authentication, and restart behavior. Publish those results as a compatibility matrix instead of claiming the systems are identical.

## Protocol boundaries

- A2A is for agent discovery and task exchange across a network boundary.
- MCP is for exposing harness operations as tools to an existing agent.
- ACP is for editor/terminal clients that drive SuperQode as the coding agent.
- Harness Protocol is SuperQode's internal, runtime-neutral session and event contract.

See also [ACP Agents](acp.md), [MCP Tools](../configuration/mcp-config.md), and [Harness Protocol](../advanced/harness-protocol.md).
