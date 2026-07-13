# Harness Protocol v1

Harness Protocol v1 is SuperQode's internal control-plane contract for running
different coding-agent harnesses through one session and evidence model. It is
not a replacement for ACP: ACP is one transport adapter, alongside SuperQode
Core and direct Python harnesses.

The protocol deliberately stays below routing and orchestration. It standardizes
how a harness is described, created, sent a message, resumed, steered, cancelled,
checkpointed, and exported. An adapter declares which optional operations it can
actually perform; unsupported operations raise `HarnessCapabilityError`.

## Canonical lifecycle

Every controller-owned run has one ordered event stream:

```text
run.started
message.created          # user
model.requested
message.delta            # zero or more
tool.requested           # zero or more
tool.completed           # zero or more
model.completed
message.created          # final assistant response
run.completed | run.failed | run.cancelled
```

Approval, artifact, checkpoint, thinking, and validation events use the same
envelope. Every stored event includes protocol version, event ID, sequence,
session ID, run ID, harness ID, timestamp, parent event ID, and payload. Memory,
file, and SQLite stores persist the same fields. Older underscore-style kernel
event names remain supported and are normalized only at the protocol boundary.

## Reference adapters

| Adapter | Purpose | Important limits |
| --- | --- | --- |
| `CoreHarnessProtocolAdapter` | Run a native `HarnessSpec` and `HarnessKernel` | Current run path is non-streaming at the adapter boundary; resume restores protocol identity but does not promise provider-private context; steering, cancellation, and native checkpoints are not claimed |
| `DirectPythonHarnessAdapter` | Package a Python callable as a harness | Resume and checkpoints are portable adapter state; durable application state remains the package author's responsibility |
| `ACPHarnessProtocolAdapter` | Run an ACP coding-agent process | Resume works only when the connected ACP agent advertises `loadSession`; ACP does not imply steering or checkpoints |

The controller always provides a portable session export from its ledger. That
does not mean an adapter can export private or provider-native state.

## Build a Python harness package

The normal developer path is one async function:

```python
async def run(message, session):
    return f"handled by {session.harness_id}: {message.content}"
```

Expose that function from `pyproject.toml`:

```toml
[project.entry-points."superqode.harnesses"]
team-reviewer = "my_package:run"
```

After installing the package, SuperQode handles registration, sessions, event
storage, export, and conformance:

```bash
pip install -e .
superqode harness list
superqode harness show team-reviewer
superqode harness run team-reviewer "Review the current diff"
superqode harness protocol conformance team-reviewer
```

See the
[`hello-harness` example](https://github.com/SuperagenticAI/superqode/tree/main/examples/harness-packages/hello-harness)
for a complete minimal package.

## Advanced adapter API

Use the controller directly only when embedding SuperQode or implementing
custom lifecycle behavior:

```python
from superqode.harness import (
    DirectPythonHarnessAdapter,
    FileHarnessStore,
    HarnessCreateRequest,
    HarnessProtocolController,
)


async def answer(message, session):
    return f"handled by {session.harness_id}: {message.content}"


adapter = DirectPythonHarnessAdapter(
    "team-reviewer",
    answer,
    name="Team reviewer",
)
controller = HarnessProtocolController(
    [adapter],
    store=FileHarnessStore(".superqode/harness-protocol"),
)

session = await controller.create(
    HarnessCreateRequest(
        harness_id="team-reviewer",
        provider="anthropic",
        model="claude-sonnet",
    )
)
async for event in controller.send(session, "Review the current diff"):
    print(event.type, event.data)

bundle = controller.export(session)
```

A handler may return a string, `PythonHarnessResult`, an awaitable of either, or
an async iterator of strings and `HarnessEvent` objects. Packages needing custom
resume, steering, cancellation, checkpoints, or ACP behavior can expose a full
`HarnessAdapter` object from the same entry-point group.

## Inspect and test the protocol

```bash
superqode harness protocol describe
superqode harness protocol describe core --json
superqode harness protocol conformance
superqode harness protocol conformance team-reviewer
```

The conformance command is deterministic and offline. It validates the direct
Python reference adapter, canonical envelope, ordering, terminal event,
message preservation, durable ledger, restart-safe export, resume, and
checkpoint behavior. Library authors can call `run_harness_conformance(adapter)`
against their own adapter. Live Core/model and ACP/process validation still
requires the selected provider or agent to be installed and authenticated.

## What v1 does not do

Harness Protocol v1 does not select models, route tasks between harnesses,
schedule teams, move live provider context between incompatible agents, or
promise semantic continuation from an exported transcript. Those features can
build on this contract after adapter evidence is reliable. Session transfer in
v1 means portable history and identifiers; lossless migration of private model
or agent state is not claimed.
