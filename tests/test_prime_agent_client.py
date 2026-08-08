from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from prime_agent_client import (
    PrimeProcessExited,
    PrimeRequestTimeout,
    PrimeRpcError,
    PrimeRpcTransport,
    PrimeSession,
    compatibility_for,
    parse_version,
)


FAKE_RPC = Path(__file__).parent / "fixtures" / "fake_prime_rpc.py"
FAKE_COMMAND = (sys.executable, str(FAKE_RPC))


def test_version_parser_and_compatibility_are_explicit() -> None:
    version = parse_version("prime-agent 0.7.1\n")

    assert version.normalized == "0.7.1"
    assert compatibility_for(version).tested is True
    assert parse_version("development build").normalized is None


async def test_transport_correlates_concurrent_requests() -> None:
    transport = PrimeRpcTransport(command=FAKE_COMMAND)
    await transport.start()
    try:
        first, second = await asyncio.gather(
            transport.request("echo", value={"number": 1}),
            transport.request("echo", value={"number": 2}),
        )
    finally:
        await transport.close()

    assert first.data == {"number": 1}
    assert second.data == {"number": 2}
    assert transport.argv[-2:] == ("--mode", "rpc")


async def test_session_uses_readiness_probe_and_preserves_unknown_events() -> None:
    async with PrimeSession(command=FAKE_COMMAND) as session:
        events = await session.prompt_and_wait("hello")
        state = await session.state()

    assert session.version is not None
    assert session.version.normalized == "0.7.1"
    assert session.compatibility is not None
    assert session.compatibility.tested is True
    assert state["sessionId"] == "fake-session"
    future = next(event for event in events if event.type == "future_prime_event")
    assert future.get("text") == "left\u2028right\u2029done"
    assert future.get("extra") == {"preserved": True}


async def test_rpc_failure_has_command_context() -> None:
    transport = PrimeRpcTransport(command=FAKE_COMMAND)
    await transport.start()
    try:
        with pytest.raises(PrimeRpcError, match="deliberate failure") as raised:
            await transport.request("fail")
    finally:
        await transport.close()

    assert raised.value.command == "fail"


async def test_request_timeout_cleans_up_pending_request() -> None:
    transport = PrimeRpcTransport(command=FAKE_COMMAND, request_timeout=0.05)
    await transport.start()
    try:
        with pytest.raises(PrimeRequestTimeout):
            await transport.request("hang")
        response = await transport.request("echo", value="still-alive")
    finally:
        await transport.close()

    assert response.data == "still-alive"


async def test_process_death_rejects_pending_request_and_captures_stderr() -> None:
    transport = PrimeRpcTransport(command=FAKE_COMMAND)
    await transport.start()
    try:
        with pytest.raises(PrimeProcessExited) as raised:
            await transport.request("exit", timeout=2)
    finally:
        await transport.close()

    assert raised.value.returncode == 7
    assert "intentional fake crash" in raised.value.stderr


async def test_malformed_output_becomes_observable_protocol_event() -> None:
    transport = PrimeRpcTransport(command=FAKE_COMMAND)
    await transport.start()
    stream = transport.events()
    try:
        await transport.request("malformed")
        protocol_error = await asyncio.wait_for(stream.__anext__(), timeout=1)
        following = await asyncio.wait_for(stream.__anext__(), timeout=1)
    finally:
        await stream.aclose()
        await transport.close()

    assert protocol_error.type == "protocol_error"
    assert protocol_error.get("raw") == "{not-json}"
    assert following.type == "after_malformed"


async def test_ui_requests_are_answered_without_typescript_host() -> None:
    async def confirm(_event):
        return True

    async with PrimeSession(command=FAKE_COMMAND, ui_handler=confirm) as session:
        events = await session.prompt_and_wait("ui")

    ui_result = next(event for event in events if event.type == "ui_result")
    assert ui_result.get("rawResponse") == {
        "type": "extension_ui_response",
        "id": "ui-1",
        "confirmed": True,
    }


async def test_prompt_stream_timeout_aborts_the_active_run() -> None:
    async with PrimeSession(command=FAKE_COMMAND, prompt_timeout=0.05) as session:
        with pytest.raises(PrimeRequestTimeout) as raised:
            await session.prompt_and_wait("stall")

    assert raised.value.command == "prompt_events"
