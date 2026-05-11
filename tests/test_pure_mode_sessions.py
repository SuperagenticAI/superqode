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
