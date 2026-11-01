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
        # Omitting caching lets upstream auto-detect provider support. Passing
        # "auto" explicitly raises for Ollama and some Bedrock models.
        **({"caching": settings["caching"]} if settings.get("caching", "auto") != "auto" else {}),
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


def error_diagnostic(exc):
    """Classify errors without returning provider response bodies or credentials."""
    kind = type(exc).__name__
    status = (
        getattr(exc, "status_code", None)
        or getattr(exc, "status", None)
        or getattr(exc, "code", None)
    )
    response = getattr(exc, "response", None)
    code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
    if kind in {"PackageNotFoundError", "ImportError", "ModuleNotFoundError"}:
        return (
            "runtime_setup",
            "Strands dependencies are missing. Run `superqode harness strands setup`.",
        )
    if isinstance(exc, ValueError) and str(exc).startswith("Unsupported Strands runtime"):
        return (
            "runtime_setup",
            "Strands runtime versions/API do not match this adapter. Run `superqode harness strands setup`.",
        )
    if (
        status == 401
        or kind
        in {
            "AuthenticationError",
            "NoCredentialsError",
            "PartialCredentialsError",
            "CredentialRetrievalError",
            "SSOTokenLoadError",
            "UnauthorizedSSOTokenError",
        }
        or code in {"UnrecognizedClientException", "ExpiredTokenException", "InvalidClientTokenId"}
    ):
        return (
            "authentication",
            "Strands authentication failed. Check the selected provider's saved API key or renew the AWS profile session.",
        )
    if (
        status == 403
        or kind == "PermissionDeniedError"
        or code in {"AccessDeniedException", "UnauthorizedOperation"}
    ):
        return (
            "permission",
            "Strands provider access was denied. Check model access, AWS permissions and region.",
        )
    if status == 404 or kind == "NotFoundError" or code == "ResourceNotFoundException":
        return (
            "model_not_found",
            "Strands model or endpoint was not found. Check the model identifier, provider endpoint and AWS region.",
        )
    if status == 429 or kind == "RateLimitError" or code == "ThrottlingException":
        return "rate_limit", "Strands provider rate limit reached. Check quota or retry later."
    if isinstance(exc, TimeoutError) or kind in {
        "APITimeoutError",
        "ReadTimeout",
        "ConnectTimeout",
    }:
        return (
            "timeout",
            "Strands provider request timed out. Check connectivity or retry with a longer timeout.",
        )
    if kind in {"APIConnectionError", "ConnectError", "ConnectionError"}:
        return (
            "connection",
            "Strands could not connect to the provider. Check the endpoint, local model server, proxy and TLS configuration.",
        )
    if status == 400 or isinstance(exc, ValueError) or code == "ValidationException":
        return (
            "configuration",
            "Strands rejected the model configuration. Check the model identifier, reasoning effort and provider settings.",
        )
    return (
        "execution",
        f"Strands execution failed ({kind}). Check the runtime and selected provider configuration.",
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
            category, message = error_diagnostic(exc)
            send({"type": "error", "category": category, "message": message})
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
