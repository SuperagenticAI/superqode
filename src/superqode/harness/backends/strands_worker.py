"""Standalone worker executed by the separate, pinned Strands interpreter."""

from __future__ import annotations

import asyncio
import contextlib
from importlib.metadata import version
import json
import sys

MAX_PACKET = 1_000_000
EXPECTED = {"strands-harness": "0.3.3", "strands-agents": "1.63.0", "pydantic-monty": "0.0.23"}
WIRE = sys.stdout


def send(packet):
    line = json.dumps(packet, allow_nan=False) + "\n"
    if len(line.encode()) > MAX_PACKET:
        raise ValueError("Worker packet exceeds size limit")
    WIRE.write(line)
    WIRE.flush()


def receive():
    line = sys.stdin.buffer.readline(MAX_PACKET + 1)
    if not line or len(line) > MAX_PACKET:
        raise ValueError("Missing or oversized host packet")
    packet = json.loads(line)
    if not isinstance(packet, dict):
        raise ValueError("Invalid host packet")
    return packet


def check():
    versions = {name: version(name) for name in EXPECTED}
    if versions != EXPECTED:
        raise ValueError(f"Unsupported Strands runtime versions: {versions}; expected {EXPECTED}")
    from strands_harness import create_harness
    from strands import Agent
    if not callable(create_harness) or not hasattr(Agent, "stream_async"):
        raise ValueError("Unsupported Strands runtime API")
    return versions


async def run(request):
    from strands.types.tools import AgentTool
    from strands.types._events import ToolResultEvent
    from strands_harness import create_harness

    lock = asyncio.Lock()
    calls = 0

    class BridgedTool(AgentTool):
        def __init__(self, spec):
            super().__init__()
            self.spec = spec

        @property
        def tool_name(self):
            return self.spec["name"]

        @property
        def tool_spec(self):
            return self.spec

        @property
        def tool_type(self):
            return "function"

        async def stream(self, tool_use, invocation_state, **kwargs):
            nonlocal calls
            async with lock:
                calls += 1
                identity = str(calls)
                send(
                    {
                        "type": "tool_request",
                        "id": identity,
                        "name": self.tool_name,
                        "arguments": tool_use["input"],
                    }
                )
                result = await asyncio.to_thread(receive)
                if result.get("id") != identity:
                    raise ValueError("Host tool response id mismatch")
                text = result.get("output") or ""
                if not result.get("success"):
                    text = result.get("error") or "Host denied or failed tool execution"
                yield ToolResultEvent(
                    {
                        "toolUseId": tool_use["toolUseId"],
                        "status": "success" if result.get("success") else "error",
                        "content": [{"text": text}],
                    }
                )

    settings = request["settings"]
    agent = create_harness(
        model=request["model"],
        effort=settings.get("effort", "auto"),
        instructions=request.get("instructions") or None,
        tools=[BridgedTool(spec) for spec in request["tools"]],
        builtin_tools=[],
        builtin_plugins=[],
        skills=False,
        memory=False,
        background_tasks=False,
        session=request["session"],
        context_manager=settings.get("context_manager", "auto"),
        caching=settings.get("caching", "auto"),
        callback_handler=None,
    )
    result = None
    turns = 0
    try:
        async for event in agent.stream_async(
            request["prompt"],
            limits={
                "turns": settings["max_turns"],
                "total_tokens": settings["total_tokens"],
                "output_tokens": settings["output_tokens"],
            },
        ):
            if "data" in event and isinstance(event["data"], str):
                send({"type": "delta", "text": event["data"]})
            if "message" in event and event["message"].get("role") == "assistant":
                turns += 1
            if "result" in event:
                result = event["result"]
    finally:
        # Only publish a terminal result after session/memory cleanup completes.
        await agent.shutdown_async()
    if result is None:
        raise ValueError("Agent produced no terminal result")
    stops = {
        "end_turn": "complete",
        "stop_sequence": "complete",
        "limit_turns": "max_iterations",
        "limit_total_tokens": "max_tokens",
        "limit_output_tokens": "max_tokens",
        "max_tokens": "max_tokens",
        "cancelled": "cancelled",
    }
    if result.stop_reason not in stops:
        raise ValueError(f"Agent did not complete: {result.stop_reason}")
    usage = result.metrics.accumulated_usage
    send(
        {
            "type": "result",
            "content": str(result),
            "stopped_reason": stops[result.stop_reason],
            "iterations": turns,
            "tool_calls_made": calls,
            "input_tokens": usage.get("inputTokens"),
            "output_tokens": usage.get("outputTokens"),
            "total_tokens": usage.get("totalTokens"),
        }
    )


def main():
    # Provider/SDK printers must never corrupt the private protocol stream.
    with contextlib.redirect_stdout(sys.stderr):
        try:
            versions = check()
            send({"type": "ready", "versions": versions})
            if "--check" not in sys.argv:
                asyncio.run(run(receive()))
        except Exception as exc:
            if isinstance(exc, ValueError) and str(exc).startswith(
                "Unsupported Strands runtime versions"
            ):
                message = str(exc)
            else:
                message = f"Strands worker failed ({type(exc).__name__}). Check the runtime setup, provider credentials and model."
            send({"type": "error", "message": message})
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
