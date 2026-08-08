from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

from prime_agent_client import PrimeEvent

from superqode.harness import RuntimeSpec, get_harness_template
from superqode.harness.backends import (
    HarnessBackendRequest,
    PrimeAgentHarnessBackend,
    PrimeAgentSettings,
    create_harness_backend,
    known_harness_backend_names,
)
from superqode.harness.backends.prime_agent import from_prime_event


FAKE_RPC = Path(__file__).parent / "fixtures" / "fake_prime_rpc.py"


def _request(tmp_path: Path) -> HarnessBackendRequest:
    spec = replace(
        get_harness_template("coding"),
        runtime=RuntimeSpec(
            backend="prime-agent",
            config={
                "prime_agent": {
                    "command": [sys.executable, str(FAKE_RPC)],
                    "session_dir": ".sessions",
                }
            },
        ),
    )
    return HarnessBackendRequest(
        spec=spec,
        prompt="implement it",
        provider="prime",
        model="fake-model",
        working_directory=tmp_path,
        session_id="prime-test",
    )


def test_prime_backend_is_registered() -> None:
    assert "prime-agent" in known_harness_backend_names()
    assert isinstance(create_harness_backend("prime-agent"), PrimeAgentHarnessBackend)


def test_builtin_prime_python_harness_selects_rpc_backend() -> None:
    spec = get_harness_template("prime-agent-python")

    assert spec.runtime.backend == "prime-agent"
    assert spec.metadata["python_client"] == "prime-agent-python-client"
    assert spec.metadata["rich_stream_events"] is True


def test_settings_keep_launch_as_argv_and_resolve_session_directory(tmp_path: Path) -> None:
    settings = PrimeAgentSettings.from_request(_request(tmp_path))

    assert settings.command == (sys.executable, str(FAKE_RPC))
    assert settings.session_dir == (tmp_path / ".sessions").resolve()


async def test_prime_backend_runs_through_native_rpc_client(tmp_path: Path) -> None:
    result = await PrimeAgentHarnessBackend().run(_request(tmp_path))

    assert result.backend == "prime-agent"
    assert result.runtime == "prime_rpc"
    assert result.response.content == "done"
    assert result.response.stopped_reason == "complete"
    assert result.response.input_tokens == 30
    assert result.response.output_tokens == 12
    assert result.response.total_tokens == 42
    assert result.response.cost_usd == 0.01
    assert result.metadata["prime_state"]["sessionId"] == "fake-session"
    assert any(event.type == "prime_event" for event in result.metadata["events"])


def test_event_mapping_preserves_raw_payload() -> None:
    event = from_prime_event(
        PrimeEvent.from_dict(
            {
                "type": "tool_execution_start",
                "toolCallId": "call-1",
                "toolName": "bash",
                "args": {"command": "pwd"},
                "futureField": {"kept": True},
            }
        )
    )

    assert event.type == "tool_call"
    assert event.data["name"] == "bash"
    assert event.data["prime_event"]["futureField"] == {"kept": True}
