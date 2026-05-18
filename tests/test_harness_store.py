"""Tests for the harness-native run/session store."""

from superqode.harness import FileHarnessStore, HarnessEvent, get_harness_template


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
