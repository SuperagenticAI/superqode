import asyncio

from superqode.agent.session_manager import SessionManager
from superqode.harness.events import HarnessEvent
from superqode.pure_mode import PureMode


def test_rewind_truncates_history_to_chosen_user_message(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = SessionManager(".superqode/sessions")
    manager.start_session("rewindtest01", provider="ollama", model="qwen")

    manager.add_user_message("first question")
    manager.add_assistant_message("first answer")
    manager.add_user_message("second question")
    manager.add_assistant_message("second answer")
    manager.add_user_message("third question")
    manager.add_assistant_message("third answer")

    # Rewind to the 2nd user message: it and everything after must be removed.
    removed = manager.rewind_to_user_message(2)
    assert removed == 4  # second q/a + third q/a

    remaining = [(m.role, m.content) for m in manager.get_messages()]
    assert remaining == [("user", "first question"), ("assistant", "first answer")]

    # Metadata count stays consistent with the truncated file.
    info = manager.get_session_info("rewindtest01")
    assert info.message_count == 2


def test_rewind_out_of_range_is_noop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = SessionManager(".superqode/sessions")
    manager.start_session("rewindtest02", provider="ollama", model="qwen")
    manager.add_user_message("only question")
    manager.add_assistant_message("only answer")

    assert manager.rewind_to_user_message(5) == 0
    assert manager.rewind_to_user_message(0) == 0
    assert len(manager.get_messages()) == 2


def test_rewind_to_first_message_clears_everything(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = SessionManager(".superqode/sessions")
    manager.start_session("rewindtest03", provider="ollama", model="qwen")
    manager.add_user_message("q1")
    manager.add_assistant_message("a1")
    manager.add_user_message("q2")

    assert manager.rewind_to_user_message(1) == 3
    assert manager.get_messages() == []


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


def test_pure_mode_uses_core_harness_by_default(monkeypatch):
    monkeypatch.delenv("SUPERQODE_TOOL_PROFILE", raising=False)
    monkeypatch.delenv("SUPERQODE_HARNESS", raising=False)

    pure = PureMode()
    status = pure.get_status()

    assert status["tool_profile"] == "core"
    assert status["tools"] == ["read", "write", "edit", "bash"]
    assert status["harness"]["id"] == "core"


def test_pure_mode_switches_to_ds4_profile_on_connect(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPERQODE_TOOL_PROFILE", raising=False)
    monkeypatch.setenv("SUPERQODE_HARNESS", "workbench")
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
    monkeypatch.setenv("SUPERQODE_HARNESS", "workbench")
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


def test_core_harness_does_not_expand_for_ds4_or_mcp(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_HARNESS", "core")
    monkeypatch.setenv("SUPERQODE_MCP_SEARCH", "1")
    monkeypatch.delenv("SUPERQODE_TOOL_PROFILE", raising=False)
    monkeypatch.chdir(tmp_path)

    pure = PureMode()
    pure.connect("ds4", "deepseek-v4-flash")

    assert pure.get_status()["tools"] == ["read", "write", "edit", "bash"]
    assert pure._agent is not None
    assert pure._agent.config.system_prompt_level.value == "core"
    assert pure._agent.config.loop_policy.mcp is False


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


def test_resume_harness_spec_carries_session_id_into_kernel(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = SessionManager(".superqode/sessions")
    manager.start_session(
        "kimi-session-1234",
        provider="moonshot",
        model="kimi-k3",
        harness_id="kimi-coding",
        harness_source="built-in-template",
    )
    manager.add_user_message("inspect the repository")

    pure = PureMode()
    pure._session_manager = SessionManager(".superqode/sessions")
    messages = pure.resume_session("kimi-session")

    assert messages
    assert pure.session.harness_name == "kimi-coding"
    assert pure.get_current_session_id() == "kimi-session-1234"
    assert pure._harness_session_id == "kimi-session-1234"


def test_legacy_session_resumes_with_workbench_harness(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SUPERQODE_HARNESS", raising=False)
    manager = SessionManager(".superqode/sessions")
    manager.start_session("legacy-session", provider="ollama", model="qwen2.5-coder")

    pure = PureMode()
    pure._session_manager = SessionManager(".superqode/sessions")
    assert pure.resume_session("legacy-session") == []

    status = pure.get_status()
    assert status["harness"]["id"] == "workbench"
    assert status["tool_profile"] == "coding"


def test_new_session_records_core_harness_contract(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPERQODE_HARNESS", "core")

    pure = PureMode()
    pure.connect("ollama", "qwen2.5-coder", session_id="core-session")

    metadata = SessionManager(".superqode/sessions").get_session_info("core-session")
    assert metadata is not None
    assert metadata.harness_id == "core"
    assert metadata.harness_source == "built-in"
    assert metadata.harness_digest.startswith("sha256:")
    assert metadata.tool_contract_version == "core-tools-v1"
    assert metadata.harness_transitions[-1]["to_harness"] == "core"


def test_reconnecting_session_records_harness_transition(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPERQODE_HARNESS", "core")

    pure = PureMode()
    pure.connect("ollama", "qwen2.5-coder", session_id="durable-session")
    pure.select_harness("workbench")
    pure.connect("ollama", "qwen2.5-coder", session_id="durable-session")

    metadata = SessionManager(".superqode/sessions").get_session_info("durable-session")
    assert metadata is not None
    assert metadata.harness_id == "workbench"
    assert [
        (item["from_harness"], item["to_harness"]) for item in metadata.harness_transitions
    ] == [
        ("", "core"),
        ("core", "workbench"),
    ]


def test_disconnect_closes_self_contained_runtime():
    class Runtime:
        closed = False
        cancelled = False

        def cancel(self):
            self.cancelled = True

        def close(self):
            self.closed = True

    pure = PureMode()
    runtime = Runtime()
    pure._runtime = runtime

    pure.disconnect()

    assert runtime.cancelled is True
    assert runtime.closed is True
    assert pure._runtime is None


def test_aclose_awaits_async_runtime_cleanup():
    class Runtime:
        closed = False

        def cancel(self):
            return None

        async def aclose(self):
            await asyncio.sleep(0)
            self.closed = True

    async def exercise():
        pure = PureMode()
        runtime = Runtime()
        pure._runtime = runtime
        await pure.aclose()
        return runtime

    assert asyncio.run(exercise()).closed is True


def test_structured_runtime_events_are_capability_based():
    class Runtime:
        def cancel(self):
            return None

        async def run_harness_events(self, _prompt):
            yield HarnessEvent(type="thinking", data={"text": "checking"})
            yield HarnessEvent(
                type="tool_call",
                data={"tool_name": "read", "tool_call_id": "1", "args": {"path": "README.md"}},
            )
            yield HarnessEvent(
                type="tool_result",
                data={
                    "tool_name": "read",
                    "tool_call_id": "1",
                    "success": True,
                    "output": "contents",
                },
            )
            yield HarnessEvent(type="model_delta", data={"text": "done"})

    async def exercise():
        pure = PureMode(runtime="antigravity-sdk")
        pure._runtime = Runtime()
        pure._agent = None
        thinking = []
        calls = []
        results = []

        async def on_thinking(text):
            thinking.append(text)

        pure.on_thinking = on_thinking
        pure.on_tool_call = lambda name, args: calls.append((name, args))
        pure.on_tool_result = lambda name, result: results.append((name, result.output))
        chunks = [chunk async for chunk in pure.run_streaming("inspect")]
        await asyncio.sleep(0)
        return chunks, thinking, calls, results

    chunks, thinking, calls, results = asyncio.run(exercise())
    assert chunks == ["done"]
    assert thinking == ["checking"]
    assert calls == [("read", {"path": "README.md"})]
    assert results == [("read", "contents")]
