"""A custom read tool through the public SDK; no provider calls."""

import asyncio

from superqode.pipy import (
    AgentHarness,
    AgentTool,
    AgentToolResult,
    MemorySessionStorage,
    Model,
    ToolCall,
    create_session,
)
from superqode.pipy.ai import FakeStream, text_response, tool_response


async def lookup(call_id, args, signal=None, on_update=None):
    if signal:
        signal.throw_if_aborted()
    return AgentToolResult(content=f"Found {args['key']}", details={"key": args["key"]})


async def main():
    tool = AgentTool(
        name="lookup",
        label="Lookup",
        description="Read an example record",
        parameters={
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
            "additionalProperties": False,
        },
        execute_fn=lookup,
        replay_safe=True,
    )
    harness = AgentHarness(
        session=await create_session(MemorySessionStorage()),
        model=Model(id="offline", provider="fixture"),
        tools=[tool],
        stream_fn=FakeStream(
            [
                tool_response(ToolCall(id="lookup-1", name="lookup", arguments={"key": "example"})),
                text_response("Custom tool completed."),
            ]
        ),
    )
    result = await harness.prompt("Find the example")
    print(result.text)


if __name__ == "__main__":
    asyncio.run(main())
