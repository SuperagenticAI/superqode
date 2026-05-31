"""Tests for the harness-native run/session store."""

import pytest

from superqode.harness import (
    ContextSpec,
    FileHarnessStore,
    HarnessEvent,
    HarnessEventGraph,
    SQLiteHarnessStore,
    get_harness_template,
)
from superqode.harness.spec import HarnessSpec


def test_file_harness_store_persists_sessions_runs_and_events(tmp_path):
    store = FileHarnessStore(tmp_path / "harness")
    spec = get_harness_template("coding")

    session = store.open_session("s:1", spec, metadata={"owner": "test"})
    assert session.session_id == "s:1"
    assert session.harness == "superqode-coding"

    run = store.start_run(
        session_id="s:1",
        spec=spec,
        provider="test",
        model="model",
        runtime="builtin",
        prompt="hello\nworld",
    )
    assert run.run_id.startswith("run_")
    assert run.prompt_preview == "hello world"

    event = HarnessEvent(type="run_start", data={"ok": True}, session_id="s:1", run_id=run.run_id)
    store.append_event(run.run_id, event)
    store.end_run(run.run_id, status="succeeded", metadata={"iterations": 1})

    loaded_session = store.get_session("s:1")
    loaded_run = store.get_run(run.run_id)

    assert loaded_session is not None
    assert loaded_session.metadata["owner"] == "test"
    assert loaded_run is not None
    assert loaded_run.status == "succeeded"
    assert loaded_run.metadata["iterations"] == 1
    assert loaded_run.events[0].type == "run_start"
    assert loaded_run.events[0].data == {"ok": True}
    assert store.get_events(run.run_id)[0].type == "run_start"
    assert store.list_sessions()[0].session_id == "s:1"
    assert store.list_runs(session_id="s:1")[0].run_id == run.run_id


def test_file_harness_store_sanitizes_file_names(tmp_path):
    store = FileHarnessStore(tmp_path / "harness")
    spec = get_harness_template("no-tool")

    store.open_session("bad/session:id", spec)

    assert store.get_session("bad/session:id") is not None
    assert (tmp_path / "harness" / "sessions" / "bad_session:id.json").exists()


@pytest.mark.parametrize("store_factory", [FileHarnessStore, SQLiteHarnessStore])
def test_harness_store_contract_persists_runs_and_events(tmp_path, store_factory):
    path = tmp_path / "store.sqlite3" if store_factory is SQLiteHarnessStore else tmp_path / "files"
    store = store_factory(path)
    spec = get_harness_template("coding")

    store.open_session("session-1", spec, metadata={"team": "runtime"})
    run = store.start_run(
        session_id="session-1",
        spec=spec,
        provider="openai",
        model="gpt-5",
        runtime="builtin",
        prompt="hello world",
        metadata={"typed_output": True},
    )
    store.append_event(
        run.run_id,
        HarnessEvent(type="delta", data={"text": "ok"}, session_id="session-1", run_id=run.run_id),
    )
    store.end_run(run.run_id, status="succeeded", metadata={"iterations": 1})

    loaded = store.get_run(run.run_id)
    assert loaded is not None
    assert loaded.status == "succeeded"
    assert loaded.metadata["typed_output"] is True
    assert loaded.metadata["iterations"] == 1
    assert loaded.events[0].data == {"text": "ok"}
    assert store.list_sessions()[0].metadata["team"] == "runtime"
    assert store.list_runs(session_id="session-1")[0].run_id == run.run_id


@pytest.mark.parametrize("store_factory", [FileHarnessStore, SQLiteHarnessStore])
def test_harness_store_builds_event_graph(tmp_path, store_factory):
    path = tmp_path / "store.sqlite3" if store_factory is SQLiteHarnessStore else tmp_path / "files"
    store = store_factory(path)
    spec = get_harness_template("coding")
    store.open_session("session-graph", spec)
    run = store.start_run(
        session_id="session-graph",
        spec=spec,
        provider="openai",
        model="gpt-5",
        runtime="builtin",
        prompt="build graph",
    )

    store.append_event(
        run.run_id,
        HarnessEvent(type="model_delta", data={"text": "thinking"}, run_id=run.run_id),
    )
    store.append_event(
        run.run_id,
        HarnessEvent(type="tool_call", data={"tool": "read_file"}, run_id=run.run_id),
    )
    store.append_event(
        run.run_id,
        HarnessEvent(type="approval_required", data={"pending": 1}, run_id=run.run_id),
    )

    graph = store.get_event_graph(run.run_id)

    assert isinstance(graph, HarnessEventGraph)
    assert [node.type for node in graph.nodes] == ["model", "tool", "approval"]
    assert [node.label for node in graph.nodes] == [
        "model_delta",
        "tool_call",
        "approval_required",
    ]
    assert [edge.type for edge in graph.edges] == ["calls", "pause"]
    assert graph.to_dict()["nodes"][1]["data"]["type"] == "tool_call"


@pytest.mark.parametrize("store_factory", [FileHarnessStore, SQLiteHarnessStore])
def test_harness_store_forks_run_event_prefix(tmp_path, store_factory):
    path = tmp_path / "store.sqlite3" if store_factory is SQLiteHarnessStore else tmp_path / "files"
    store = store_factory(path)
    spec = get_harness_template("coding")
    store.open_session("session-fork", spec)
    run = store.start_run(
        session_id="session-fork",
        spec=spec,
        provider="openai",
        model="gpt-5",
        runtime="builtin",
        prompt="fork me",
        metadata={"workflow": True},
    )
    store.append_event(run.run_id, HarnessEvent(type="run_start", data={"n": 1}, run_id=run.run_id))
    store.append_event(run.run_id, HarnessEvent(type="tool_call", data={"n": 2}, run_id=run.run_id))
    store.append_event(run.run_id, HarnessEvent(type="run_end", data={"n": 3}, run_id=run.run_id))

    fork = store.fork_run(run.run_id, after=1, session_id="forked-session")

    assert fork.run_id != run.run_id
    assert fork.status == "forked"
    assert fork.session_id == "forked-session"
    assert fork.metadata["fork_of"] == run.run_id
    assert fork.metadata["fork_after"] == 1
    assert [event.type for event in fork.events] == ["run_start", "tool_call"]
    assert all(event.run_id == fork.run_id for event in fork.events)


@pytest.mark.parametrize("store_factory", [FileHarnessStore, SQLiteHarnessStore])
def test_harness_store_prompt_persistence_policy(tmp_path, store_factory):
    path = tmp_path / "store.sqlite3" if store_factory is SQLiteHarnessStore else tmp_path / "files"
    store = store_factory(path)
    full = HarnessSpec(
        name="full",
        context=ContextSpec(session_storage=str(tmp_path), prompt_persistence="full"),
    )
    off = HarnessSpec(
        name="off",
        context=ContextSpec(session_storage=str(tmp_path), prompt_persistence="off"),
    )

    full_run = store.start_run(
        session_id="s",
        spec=full,
        provider="p",
        model="m",
        runtime="builtin",
        prompt="exact prompt\nwith newline",
    )
    off_run = store.start_run(
        session_id="s",
        spec=off,
        provider="p",
        model="m",
        runtime="builtin",
        prompt="do not store me",
    )

    loaded_full = store.get_run(full_run.run_id)
    loaded_off = store.get_run(off_run.run_id)
    assert loaded_full is not None
    assert loaded_full.prompt_preview == "exact prompt with newline"
    assert loaded_full.metadata["prompt"] == "exact prompt\nwith newline"
    assert loaded_full.metadata["prompt_persistence"] == "full"
    assert loaded_off is not None
    assert loaded_off.prompt_preview == ""
    assert "prompt" not in loaded_off.metadata
    assert loaded_off.metadata["prompt_persistence"] == "off"
