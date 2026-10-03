"""Pydantic input models and live progress through the offline PiPy SDK."""

import asyncio

from pydantic import BaseModel, ConfigDict, Field

from superqode.pipy import (
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


class Lookup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1)
    limit: int = Field(default=3, ge=1, le=10)


async def lookup(args: Lookup, context: ToolContext) -> AgentToolResult:
    context.check_cancelled()
    context.emit(AgentToolResult(content="Looking up records"))
    return AgentToolResult(content=f"Found {args.key}", details=args.model_dump())


async def main():
    tool = create_typed_tool("lookup", "Read example records", Lookup, lookup, replay_safe=True)
    harness = AgentHarness(
        session=await create_session(MemorySessionStorage()),
        model=Model(id="offline", provider="fixture"),
        tools=[tool],
        stream_fn=FakeStream(
            [
                tool_response(ToolCall(id="lookup-1", name="lookup", arguments={"key": "example"})),
                text_response("Typed tool completed."),
            ]
        ),
    )
    print((await harness.prompt("Find the example")).text)


if __name__ == "__main__":
    asyncio.run(main())
