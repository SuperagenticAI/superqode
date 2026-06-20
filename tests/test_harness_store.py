"""Tests for the harness-native run/session store."""

import pytest

from superqode.harness import (
    ContextSpec,
    FileHarnessStore,
    HarnessEvent,
    HarnessEventGraph,
    MemoryHarnessStore,
    SQLiteHarnessStore,
    build_harness_replay_plan,
    build_harness_evidence,
    render_harness_replay_plan,
    render_harness_evidence,
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


@pytest.mark.parametrize(
    "store_factory", [MemoryHarnessStore, FileHarnessStore, SQLiteHarnessStore]
)
def test_harness_store_persists_run_lineage(tmp_path, store_factory):
    if store_factory is MemoryHarnessStore:
        store = store_factory()
    else:
        path = (
            tmp_path / "store.sqlite3"
            if store_factory is SQLiteHarnessStore
            else tmp_path / "files"
        )
        store = store_factory(path)
    spec = get_harness_template("coding")

    root = store.start_run(
        session_id="session-lineage",
        spec=spec,
        provider="openai",
        model="gpt-5",
        runtime="builtin",
        prompt="root",
    )
    child = store.start_run(
        session_id="session-lineage",
        spec=spec,
        provider="openai",
        model="gpt-5",
        runtime="builtin",
        prompt="child",
        metadata={"parent_run_id": root.run_id, "root_run_id": root.run_id},
    )

    loaded = store.get_run(child.run_id)

    assert loaded is not None
    assert loaded.parent_run_id == root.run_id
    assert loaded.root_run_id == root.run_id


def test_harness_replay_plan_renders_recursive_children(tmp_path):
    store = FileHarnessStore(tmp_path / "harness")
    spec = get_harness_template("coding")
    root = store.start_run(
        session_id="session-lineage",
        spec=spec,
        provider="openai",
        model="gpt-5",
        runtime="builtin",
        prompt="root task",
    )
    child = store.start_run(
        session_id="session-lineage",
        spec=spec,
        provider="openai",
        model="gpt-5-mini",
        runtime="builtin",
        prompt="child task",
        metadata={"parent_run_id": root.run_id, "root_run_id": root.run_id},
    )

    plan = build_harness_replay_plan(store, root.run_id)
    rendered = render_harness_replay_plan(plan)

    assert plan["lineage"]["children"][0]["run_id"] == child.run_id
    assert "Child runs:" in rendered
    assert child.run_id in rendered


def test_harness_replay_plan_renders_dynamic_workflow_tree(tmp_path):
    store = FileHarnessStore(tmp_path / "harness")
    spec = get_harness_template("coding")
    root = store.start_run(
        session_id="session-dynamic",
        spec=spec,
        provider="openai",
        model="gpt-5",
        runtime="builtin",
        prompt="root task",
    )
    child = store.start_run(
        session_id="session-dynamic",
        spec=spec,
        provider="openai",
        model="gpt-5-mini",
        runtime="builtin",
        prompt="child task",
        metadata={"parent_run_id": root.run_id, "root_run_id": root.run_id},
    )
    store.append_event(
        root.run_id,
        HarnessEvent(
            type="tool_result",
            run_id=root.run_id,
            data={
                "tool_name": "dynamic_workflow_script",
                "success": True,
                "metadata": {
                    "script_compiled": True,
                    "plan": {
                        "objective": "diagnose ci",
                        "steps": [
                            {
                                "id": "logs",
                                "task": "scan logs",
                                "context_handle": "file:ci.log",
                                "fanout": True,
                            }
                        ],
                    },
                    "child_run_ids": [child.run_id],
                    "results": [
                        {
                            "id": "logs",
                            "success": True,
                            "metadata": {"child_run_ids": [child.run_id]},
                        }
                    ],
                },
            },
        ),
    )

    plan = build_harness_replay_plan(store, root.run_id)
    rendered = render_harness_replay_plan(plan)

    assert plan["dynamic_workflows"][0]["objective"] == "diagnose ci"
    assert plan["dynamic_workflows"][0]["steps"][0]["child_run_ids"] == [child.run_id]
    assert "Dynamic workflows:" in rendered
    assert "dynamic_workflow_script compiled-script: diagnose ci" in rendered
    assert child.run_id in rendered


def test_harness_evidence_renders_dynamic_workflow_tree(tmp_path):
    store = FileHarnessStore(tmp_path / "harness")
    spec = get_harness_template("coding")
    root = store.start_run(
        session_id="session-dynamic-evidence",
        spec=spec,
        provider="openai",
        model="gpt-5",
        runtime="builtin",
        prompt="root task",
    )
    child = store.start_run(
        session_id="session-dynamic-evidence",
        spec=spec,
        provider="openai",
        model="gpt-5-mini",
        runtime="builtin",
        prompt="child task",
        metadata={"parent_run_id": root.run_id, "root_run_id": root.run_id},
    )
    store.append_event(
        root.run_id,
        HarnessEvent(
            type="tool_result",
            run_id=root.run_id,
            data={
                "tool_name": "dynamic_workflow",
                "success": True,
                "metadata": {
                    "objective": "audit auth",
                    "child_run_ids": [child.run_id],
                    "results": [
                        {
                            "id": "routes",
                            "success": True,
                            "metadata": {"child_run_id": child.run_id},
                        }
                    ],
                },
            },
        ),
    )

    evidence = build_harness_evidence(store, root.run_id)
    rendered = render_harness_evidence(evidence)

    assert evidence["dynamic_workflows"][0]["objective"] == "audit auth"
    assert evidence["dynamic_workflows"][0]["steps"][0]["child_run_ids"] == [child.run_id]
    assert "Dynamic workflows:" in rendered
    assert "dynamic_workflow: audit auth" in rendered
    assert child.run_id in rendered


def test_file_harness_store_sanitizes_file_names(tmp_path):
    store = FileHarnessStore(tmp_path / "harness")
    spec = get_harness_template("no-tool")

    store.open_session("bad/session:id", spec)

    assert store.get_session("bad/session:id") is not None
    assert (tmp_path / "harness" / "sessions" / "bad_session:id.json").exists()


@pytest.mark.parametrize(
    "store_factory", [MemoryHarnessStore, FileHarnessStore, SQLiteHarnessStore]
)
def test_harness_store_inbox_contract(tmp_path, store_factory):
    if store_factory is MemoryHarnessStore:
        store = store_factory()
    else:
        path = (
            tmp_path / "store.sqlite3"
            if store_factory is SQLiteHarnessStore
            else tmp_path / "files"
        )
        store = store_factory(path)

    first = store.admit_input(
        session_id="session-1",
        input_id="input-a",
        prompt="first",
        delivery="queue",
        metadata={"source": "test"},
    )
    second = store.admit_input(session_id="session-1", input_id="input-b", prompt="second")
    other = store.admit_input(session_id="session-2", input_id="input-c", prompt="other")

    assert first.status == "pending"
    assert first.metadata["source"] == "test"
    assert [item.input_id for item in store.list_inputs(session_id="session-1")] == [
        "input-a",
        "input-b",
    ]
    assert [item.input_id for item in store.list_inputs(status="pending")] == [
        "input-a",
        "input-b",
        "input-c",
    ]

    duplicate = store.admit_input(session_id="session-1", input_id="input-a", prompt="first")
    assert duplicate.input_id == first.input_id
    with pytest.raises(ValueError):
        store.admit_input(session_id="session-1", input_id="input-a", prompt="changed")

    claimed = store.claim_next_input(session_id="session-1", owner_id="worker-1")
    assert claimed is not None
    assert claimed.input_id == first.input_id
    assert claimed.status == "running"
    assert claimed.owner_id == "worker-1"
    assert claimed.lease_expires_at is not None
    renewed = store.renew_input_lease(
        claimed.input_id,
        owner_id="worker-1",
        lease_seconds=600,
    )
    assert renewed.lease_expires_at is not None
    assert renewed.lease_expires_at >= claimed.lease_expires_at
    with pytest.raises(PermissionError):
        store.renew_input_lease(claimed.input_id, owner_id="worker-2")
    with pytest.raises(PermissionError):
        store.mark_input_done(claimed.input_id, run_id="run-bad", owner_id="worker-2")
    done = store.mark_input_done(claimed.input_id, run_id="run-1", owner_id="worker-1")
    assert done.status == "done"
    assert done.run_id == "run-1"
    assert done.owner_id == ""
    assert done.lease_expires_at is None

    failed_claim = store.claim_next_input(session_id="session-1")
    assert failed_claim is not None
    assert failed_claim.input_id == second.input_id
    failed = store.mark_input_failed(failed_claim.input_id, error="boom")
    assert failed.status == "failed"
    assert failed.error == "boom"

    assert store.claim_next_input(session_id="session-1") is None
    assert store.claim_next_input(session_id="session-2").input_id == other.input_id


@pytest.mark.parametrize(
    "store_factory", [MemoryHarnessStore, FileHarnessStore, SQLiteHarnessStore]
)
def test_harness_store_recovers_stale_running_inputs(tmp_path, store_factory):
    if store_factory is MemoryHarnessStore:
        store = store_factory()
    else:
        path = (
            tmp_path / "store.sqlite3"
            if store_factory is SQLiteHarnessStore
            else tmp_path / "files"
        )
        store = store_factory(path)

    admitted = store.admit_input(
        session_id="session-1",
        input_id="input-recover",
        prompt="retry me",
    )
    claimed = store.claim_next_input(
        session_id=admitted.session_id,
        owner_id="worker-1",
        lease_seconds=0,
    )

    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.owner_id == "worker-1"

    recovered = store.recover_stale_inputs(session_id="session-1", stale_after_seconds=300)

    assert [item.input_id for item in recovered] == ["input-recover"]
    assert recovered[0].status == "pending"
    assert recovered[0].owner_id == ""
    assert recovered[0].lease_expires_at is None
    assert recovered[0].metadata["recovered_from_owner"] == "worker-1"
    reclaimed = store.claim_next_input(session_id="session-1", owner_id="worker-2")
    assert reclaimed is not None
    assert reclaimed.input_id == "input-recover"
    assert reclaimed.owner_id == "worker-2"


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
