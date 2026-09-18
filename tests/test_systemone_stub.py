"""Schema-strict stub and replay clients. No network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from superqode.systemone.client import (
    ReplaySystemOneClient,
    StubSystemOneClient,
    SystemOneError,
    SystemOneTimeout,
)
from superqode.systemone.pack import load_pack
from superqode.systemone.types import NoulQuestion, SchemaViolation


async def test_stub_is_schema_strict_on_unknown_choice():
    pack = load_pack("tool_gate")
    client = StubSystemOneClient({"disposition": {"choice": "ship_it"}})
    with pytest.raises(SchemaViolation, match="not in the question options"):
        await client.evaluate({"tool": "bash"}, pack.questions)


async def test_stub_fills_missing_answers_with_uncertain_defaults():
    pack = load_pack("tool_gate")
    client = StubSystemOneClient()
    answers = await client.evaluate({"tool": "bash"}, pack.questions)
    assert answers.noul("destructive") == 0.5
    assert answers.choice("disposition").choice == "ask"
    assert answers.choice("disposition").confidence == 0.0
    assert len(client.calls) == 1


async def test_stub_raises_configured_timeout():
    pack = load_pack("tool_gate")
    client = StubSystemOneClient(error=SystemOneTimeout("stub timeout"))
    with pytest.raises(SystemOneTimeout):
        await client.evaluate({}, pack.questions)
    assert client.calls  # the attempt is recorded


async def test_replay_plays_recorded_answers(tmp_path):
    path = tmp_path / "replay.json"
    path.write_text(
        json.dumps(
            {
                "traces": {
                    "t1": {"answers": {"q": {"noul": 0.91}}},
                }
            }
        ),
        encoding="utf-8",
    )
    client = ReplaySystemOneClient(path, trace_id="t1")
    answers = await client.evaluate({}, {"q": NoulQuestion(instructions="yes?")})
    assert answers.noul("q") == 0.91


async def test_replay_is_schema_strict(tmp_path):
    path = tmp_path / "replay.json"
    path.write_text(
        json.dumps({"answers": {"q": {"noul": 0.2, "choice": "nope"}}}),
        encoding="utf-8",
    )
    client = ReplaySystemOneClient(path)
    with pytest.raises((SchemaViolation, Exception)):
        # extra fields on Noul are ignored; unknown question ids are not.
        await client.evaluate({}, {"other": NoulQuestion(instructions="yes?")})


async def test_replay_loads_fixture_trace_directory():
    traces = Path(__file__).parent / "fixtures" / "systemone" / "traces"
    pack = load_pack("tool_gate")
    client = ReplaySystemOneClient(traces, trace_id="pytest-on-repo")
    answers = await client.evaluate({"tool": "bash"}, pack.questions)
    assert answers.choice("disposition").choice == "allow"
    assert answers.noul("on_task") >= 0.9


async def test_replay_missing_trace_errors(tmp_path):
    path = tmp_path / "replay.json"
    path.write_text(
        json.dumps({"traces": {"a": {"answers": {"q": {"noul": 1.0}}}}}),
        encoding="utf-8",
    )
    client = ReplaySystemOneClient(path, trace_id="missing")
    with pytest.raises(SystemOneError, match="no trace"):
        await client.evaluate({}, {"q": NoulQuestion(instructions="yes?")})
