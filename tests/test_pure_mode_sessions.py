from superqode.agent.session_manager import SessionManager
from superqode.pure_mode import PureMode


def test_session_listing_preserves_full_id_and_prefix_resolution(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = SessionManager(".superqode/sessions")
    manager.start_session("abcdefgh1234", provider="ollama", model="qwen2.5-coder")
    manager.add_user_message("hello")

    pure = PureMode()
    pure._session_manager = SessionManager(".superqode/sessions")

    sessions = pure.list_sessions()

    assert sessions[0]["session_id"] == "abcdefgh1234"
    assert sessions[0]["display_id"] == "abcdefgh"
    assert pure.resolve_session_id("abcdefgh") == "abcdefgh1234"
    assert pure.resolve_session_id("abcdefgh1234") == "abcdefgh1234"


def test_pure_mode_uses_coding_tool_profile_by_default(monkeypatch):
    monkeypatch.delenv("SUPERQODE_TOOL_PROFILE", raising=False)

    pure = PureMode()
    status = pure.get_status()

    assert status["tool_profile"] == "coding"
    assert "patch" in status["tools"]
    assert "web_fetch" in status["tools"]


def test_pure_mode_switches_to_ds4_profile_on_connect(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPERQODE_TOOL_PROFILE", raising=False)
    monkeypatch.chdir(tmp_path)

    pure = PureMode()
    pure.connect("ds4", "deepseek-v4-flash")
    status = pure.get_status()

    assert status["tool_profile"] == "ds4"
    assert "patch" in status["tools"]
    assert "batch" not in status["tools"]
    assert pure._agent is not None
    assert pure._agent.config.max_iterations == 0
    assert pure._agent.config.session_history_limit == 8
    assert pure._agent.parallel_tools is False


def test_pure_mode_enables_mcp_tools_for_byok_and_local_when_requested(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_MCP_SEARCH", "1")
    monkeypatch.chdir(tmp_path)

    byok = PureMode()
    byok.connect("anthropic", "claude-sonnet-4")
    assert byok._agent is not None
    byok_tool_names = {tool.name for tool in byok._agent.tools.list()}
    byok_defs = {definition.name for definition in byok._agent._get_tool_definitions()}
    assert {"mcp_search", "mcp_execute"}.issubset(byok_tool_names | byok_defs)

    local = PureMode()
    local.connect("ds4", "deepseek-v4-flash")
    assert local._agent is not None
    local_tool_names = {tool.name for tool in local._agent.tools.list()}
    local_defs = {definition.name for definition in local._agent._get_tool_definitions()}
    assert {"mcp_search", "mcp_execute"}.issubset(local_tool_names | local_defs)


def test_explicit_tool_profile_overrides_ds4_default(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_TOOL_PROFILE", "coding")
    monkeypatch.chdir(tmp_path)

    pure = PureMode()
    pure.connect("ds4", "deepseek-v4-flash")
    status = pure.get_status()

    assert status["tool_profile"] == "coding"
    assert "batch" in status["tools"]


def test_session_manager_can_load_recent_messages_only(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = SessionManager(".superqode/sessions")
    manager.start_session("history-window", provider="ds4", model="deepseek-v4-flash")

    for i in range(30):
        manager.add_user_message(f"message {i}")

    recent = manager.get_messages(limit=5)

    assert [message.content for message in recent] == [
        "message 25",
        "message 26",
        "message 27",
        "message 28",
        "message 29",
    ]


def test_resume_reuses_resolved_session_id_and_fork_branches_active_session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = SessionManager(".superqode/sessions")
    manager.start_session("resume-session-1234", provider="ollama", model="qwen2.5-coder")
    manager.add_user_message("fix the bug")

    pure = PureMode()
    pure._session_manager = SessionManager(".superqode/sessions")

    messages = pure.resume_session("resume-session")

    assert messages
    assert pure.get_current_session_id() == "resume-session-1234"

    fork_id = pure.fork_current_session("resume-session-branch")

    assert fork_id == "resume-session-branch"
    assert pure.get_current_session_id() == "resume-session-branch"
    assert pure._session_manager.current_session_id == "resume-session-branch"
