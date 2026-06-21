import json

from superqode.agent.session_manager import SessionManager, SessionMessage
from superqode.session.factory import SoftwareFactory
from superqode.session.share_artifacts import create_share_artifact, import_share_artifact
from superqode.session.switchboard import SessionSwitchboard


def test_switchboard_tracks_sessions_forks_and_active(tmp_path):
    storage_dir = tmp_path / "sessions"
    manager = SessionManager(storage_dir=str(storage_dir))
    manager.store.create_session("root", provider="test", model="model", title="Root")
    manager.store.append_message("root", SessionMessage(role="user", content="build this"))
    manager.store.fork_session("root", "root-review")

    switchboard = SessionSwitchboard(storage_dir=storage_dir)
    active = switchboard.switch("root")
    assert active["session_id"] == "root"
    assert switchboard.active() == "root"

    children = switchboard.children("root")
    assert [child["session_id"] for child in children] == ["root-review"]
    assert children[0]["kind"] == "fork"


def test_switchboard_fork_to_agent_appends_handoff(tmp_path):
    storage_dir = tmp_path / "sessions"
    manager = SessionManager(storage_dir=str(storage_dir))
    manager.store.create_session("root", title="Root")
    manager.store.append_message("root", SessionMessage(role="user", content="please implement"))
    manager.store.append_message("root", SessionMessage(role="assistant", content="working on it"))

    payload = SessionSwitchboard(storage_dir=storage_dir).fork_to_agent(
        "root",
        agent="reviewer",
        new_session_id="root-reviewer",
        title="Review Pass",
        goal="review the patch",
    )

    assert payload["session"]["session_id"] == "root-reviewer"
    assert payload["session"]["agent_id"] == "reviewer"
    messages = manager.store.get_messages("root-reviewer")
    assert "SuperQode handoff packet" in messages[-1].content
    assert "review the patch" in messages[-1].content


def test_share_tree_round_trips_graph(tmp_path):
    source_storage = tmp_path / "source" / "sessions"
    target_storage = tmp_path / "target" / "sessions"
    manager = SessionManager(storage_dir=str(source_storage))
    manager.store.create_session("root", title="Root")
    manager.store.append_message("root", SessionMessage(role="user", content="root message"))
    SessionSwitchboard(storage_dir=source_storage).fork_to_agent(
        "root",
        agent="coder",
        new_session_id="root-coder",
        title="Coder Fork",
        goal="finish it",
    )
    SessionSwitchboard(storage_dir=source_storage).fork_to_agent(
        "root-coder",
        agent="reviewer",
        new_session_id="root-coder-reviewer",
        title="Reviewer Fork",
        goal="check it",
    )

    artifact = create_share_artifact(
        "root",
        output=tmp_path / "tree.superqode-share.json",
        storage_dir=str(source_storage),
        include_tree=True,
    )
    payload = json.loads(artifact.read_text())
    assert payload["format"] == "superqode-share-v2"
    assert sorted(payload["sessions"]) == ["root", "root-coder", "root-coder-reviewer"]

    imported_root = import_share_artifact(
        artifact,
        new_session_id="imported-root",
        storage_dir=str(target_storage),
    )
    assert imported_root == "imported-root"
    imported = SessionSwitchboard(storage_dir=target_storage)
    children = imported.children("imported-root")
    assert len(children) == 1
    assert children[0]["agent_id"] == "coder"
    grandchildren = imported.children(children[0]["session_id"])
    assert len(grandchildren) == 1
    assert grandchildren[0]["agent_id"] == "reviewer"


def test_factory_records_model_harness_mode_lineage(tmp_path):
    storage_dir = tmp_path / "sessions"
    manager = SessionManager(storage_dir=str(storage_dir))
    manager.store.create_session("root", provider="local", model="old", title="Root")

    factory = SoftwareFactory(storage_dir=storage_dir)
    factory.set_mode("no-subscription", session_id="root", reason="stay portable")
    factory.switch_model("ollama/qwen3-coder", session_id="root", reason="local coding")
    factory.switch_harness("review", session_id="root", reason="review pass")

    status = factory.status("root")
    assert status["factory"]["mode"] == "no-subscription"
    assert status["factory"]["model_ref"] == "ollama/qwen3-coder"
    assert status["factory"]["harness"] == "review"
    assert [event["kind"] for event in status["lineage"]] == ["mode", "model", "harness"]


def test_factory_policy_file_and_privacy_warning(tmp_path, monkeypatch):
    storage_dir = tmp_path / "sessions"
    workspace = tmp_path / "repo"
    workspace.mkdir()
    (workspace / ".env").write_text("SECRET=value\n")
    (workspace / ".git").mkdir()
    monkeypatch.chdir(workspace)

    manager = SessionManager(storage_dir=str(storage_dir))
    manager.store.create_session("root", provider="ollama", model="qwen", title="Root")

    factory = SoftwareFactory(storage_dir=storage_dir)
    policy_path = factory.init_policy()
    assert policy_path.exists()
    assert factory.policy()["default_route"] == "no-subscription"

    factory.set_mode("no-subscription", session_id="root")
    payload = factory.switch_model("openai/gpt-5", session_id="root")
    warnings = payload["privacy_warnings"]
    assert any("cloud" in warning.lower() for warning in warnings)
    assert any(".env" in warning for warning in warnings)
    assert payload["factory"]["next_turn"]["model_ref"] == "openai/gpt-5"


def test_factory_fork_model_preserves_graph_and_model_metadata(tmp_path):
    storage_dir = tmp_path / "sessions"
    manager = SessionManager(storage_dir=str(storage_dir))
    manager.store.create_session("root", title="Root")
    manager.store.append_message("root", SessionMessage(role="user", content="implement it"))

    payload = SoftwareFactory(storage_dir=storage_dir).fork_model(
        "root",
        model_ref="local/deepseek-coder",
        role="coder",
        new_session_id="root-local-coder",
        goal="try local implementation",
    )

    session = payload["fork"]["session"]
    assert session["session_id"] == "root-local-coder"
    assert session["parent_session_id"] == "root"
    status = SoftwareFactory(storage_dir=storage_dir).status("root-local-coder")
    assert status["factory"]["model_ref"] == "local/deepseek-coder"
    assert status["lineage"][-1]["kind"] == "model"
