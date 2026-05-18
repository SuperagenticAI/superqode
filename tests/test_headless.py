"""Tests for headless harness profiles."""

from superqode.headless import create_tool_registry, get_harness_profiles, response_to_json
from superqode.agent.loop import AgentConfig, AgentLoop
from superqode.agent.session_manager import SessionManager
from superqode.providers.gateway.base import GatewayResponse
from superqode.tools.permissions import Permission
from superqode.agent.loop import AgentResponse
from test_agent_loop_harness import ScriptedGateway


def test_plan_profile_is_read_only_and_shell_requires_approval():
    profile = get_harness_profiles()["plan"]
    registry = create_tool_registry(profile)
    tool_names = {tool.name for tool in registry.list()}

    assert "read_file" in tool_names
    assert "grep" in tool_names
    assert "bash" in tool_names
    assert "write_file" not in tool_names
    assert "edit_file" not in tool_names
    assert profile.permissions.get_permission("bash") == Permission.ASK


def test_build_profile_exposes_full_registry():
    profile = get_harness_profiles()["build"]
    tool_names = {tool.name for tool in create_tool_registry(profile).list()}

    assert "read_file" in tool_names
    assert "write_file" in tool_names
    assert "agent" in tool_names


def test_no_tool_profile_exposes_no_tools_and_denies_permissions():
    profile = get_harness_profiles()["no-tool"]
    registry = create_tool_registry(profile)

    assert registry.list() == []
    assert profile.system_level.value == "no_tool"
    assert profile.permissions.get_permission("read_file") == Permission.DENY
    assert profile.permissions.get_permission("bash") == Permission.DENY


def test_response_to_json_is_stable():
    response = AgentResponse(
        content="done",
        messages=[],
        tool_calls_made=2,
        iterations=3,
        stopped_reason="complete",
    )

    payload = response_to_json(response, provider="openai", model="gpt-5.4", profile="build")

    assert '"type": "superqode.result"' in payload
    assert '"content": "done"' in payload
    assert '"success": true' in payload


def test_export_session_markdown_and_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = SessionManager(".superqode/sessions")
    manager.start_session("session-1", provider="test", model="m")
    manager.add_user_message("hello")
    manager.add_assistant_message("world")

    from superqode.headless import export_session

    markdown = export_session("session-1")
    assert "# SuperQode Session session-1" in markdown
    assert "hello" in markdown
    assert "world" in markdown

    exported_json = export_session("session-1", fmt="json")
    assert '"session_id": "session-1"' in exported_json
    assert '"content": "hello"' in exported_json


def test_session_tree_tracks_forks(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = SessionManager(".superqode/sessions")
    manager.start_session("root", provider="test", model="m")
    manager.add_user_message("hello")
    manager.fork_current_session("child")

    from superqode.headless import session_tree

    tree = session_tree()

    assert tree[0]["session_id"] == "root"
    assert tree[0]["children"][0]["session_id"] == "child"
    assert tree[0]["children"][0]["parent_session_id"] == "root"


def test_agent_loop_resumes_stored_messages(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = SessionManager(".superqode/sessions")
    manager.start_session("resume-1", provider="test", model="m")
    manager.add_user_message("previous question")
    manager.add_assistant_message("previous answer")

    gateway = ScriptedGateway([GatewayResponse(content="next answer")])
    loop = AgentLoop(
        gateway=gateway,
        tools=create_tool_registry(get_harness_profiles()["review"]),
        config=AgentConfig(
            provider="test",
            model="m",
            enable_session_storage=True,
            session_storage_dir=".superqode/sessions",
            session_id="resume-1",
        ),
    )

    import asyncio

    response = asyncio.run(loop.run("next question"))

    assert response.content == "next answer"
    sent_contents = [message.content for message in gateway.calls[0]]
    assert "previous question" in sent_contents
    assert "previous answer" in sent_contents
    assert "next question" in sent_contents
