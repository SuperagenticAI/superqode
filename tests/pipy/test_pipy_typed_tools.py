"""Python-native tools retain loop validation, streaming and recovery semantics."""

import pytest
from pydantic import BaseModel, ConfigDict, Field, model_validator

from superqode.pipy import (
    AbortController,
    AbortError,
    AgentHarness,
    AgentToolResult,
    MemorySessionStorage,
    Model,
    ToolCall,
    ToolContext,
    create_session,
    create_typed_tool,
)
from superqode.pipy.ai import FakeStream, text_response, tool_response
from superqode.pipy.validation import ToolArgumentError


class Lookup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1)
    limit: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def permitted_key(self):
        if self.key == "private":
            raise ValueError("private records are excluded")
        return self


@pytest.mark.asyncio
async def test_typed_tool_builds_schema_defaults_and_streams_in_real_loop():
    calls = []

    async def lookup(args: Lookup, context: ToolContext):
        calls.append((args, context.tool_call_id))
        context.emit(AgentToolResult(content="searching"))
        return AgentToolResult(content=f"{args.key}:{args.limit}", details=args.model_dump())

    tool = create_typed_tool("lookup", "Read records", Lookup, lookup, replay_safe=True)
    assert tool.parameters == Lookup.model_json_schema()
    assert tool.replay_safe and tool.prompt_snippet == "Read records"
    harness = AgentHarness(
        session=await create_session(MemorySessionStorage()),
        model=Model(id="fake", provider="fake"),
        tools=[tool],
        stream_fn=FakeStream(
            [
                tool_response(ToolCall(id="call-1", name="lookup", arguments={"key": "public"})),
                text_response("done"),
            ]
        ),
    )
    events = []
    harness.subscribe(events.append)
    assert (await harness.prompt("lookup")).text == "done"
    assert calls[0][0] == Lookup(key="public") and calls[0][1] == "call-1"
    assert any(getattr(event, "type", "") == "tool_execution_update" for event in events)


@pytest.mark.asyncio
async def test_direct_calls_validate_schema_and_model_before_user_code():
    executed = []

    async def execute(args, context):
        executed.append(args)
        return AgentToolResult(content="ok")

    tool = create_typed_tool("lookup", "Read", Lookup, execute)
    with pytest.raises(ToolArgumentError):
        await tool.execute("bad", {"key": "x", "limit": 11})
    with pytest.raises(ToolArgumentError):
        await tool.execute("extra", {"key": "x", "unknown": True})
    with pytest.raises(ValueError, match="private records"):
        await tool.execute("private", {"key": "private"})
    assert not executed


@pytest.mark.asyncio
async def test_nested_models_and_cancellation_preserve_typed_call_context():
    class Batch(BaseModel):
        rows: list[Lookup]

    controller = AbortController()
    captured = []

    async def execute(args, context):
        assert isinstance(args.rows[0], Lookup)
        assert context.signal is controller.signal
        captured.append(context)
        return AgentToolResult(content="ok")

    tool = create_typed_tool("batch", "Read batch", Batch, execute)
    await tool.execute("batch-1", {"rows": [{"key": "x"}]}, controller.signal)
    assert not tool.replay_safe
    controller.abort("cancelled")
    with pytest.raises(AbortError, match="cancelled"):
        await tool.execute("batch-2", {"rows": [{"key": "x"}]}, controller.signal)
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_typed_tools_reuse_committed_outcomes_without_reexecuting(tmp_path):
    from superqode.execution_recovery import RecoveryScope, recovery_scope
    from superqode.workorders import WorkOrder, WorkOrderStore, WorkOrderTask

    store = WorkOrderStore(tmp_path / "work.sqlite3")
    store.create(
        WorkOrder(
            work_order_id="work",
            goal="lookup",
            repository=str(tmp_path),
            tasks=(WorkOrderTask(task_id="task", title="Lookup", goal="lookup"),),
        ),
        queue=True,
    )
    _, task = store.claim_next_task(reference="work", worker_id="worker")
    calls = []

    async def execute(args, context):
        calls.append(args)
        return AgentToolResult(content="found", details={"key": args.key})

    tool = create_typed_tool("lookup", "Read", Lookup, execute)
    with recovery_scope(RecoveryScope(store, "work", "task", "worker", task.attempts)):
        first = await tool.execute("same-call", {"key": "x"})
        second = await tool.execute("same-call", {"key": "x"})
    assert second == first and len(calls) == 1
