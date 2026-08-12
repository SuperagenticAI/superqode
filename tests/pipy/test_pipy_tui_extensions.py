"""Picker presentation and the extension bridge (checklist X1 to X8)."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import MODEL

from superqode.agent.hooks import (
    AFTER_TOOL_CALL,
    AFTER_TURN_COMPLETE,
    BEFORE_TOOL_CALL,
    SESSION_START,
    STOP,
    USER_PROMPT_SUBMIT,
    HookDecision,
    HookRegistry,
)
from superqode.app.harness_picker import harness_picker_items
from superqode.harness.pipy_extensions import (
    BRIDGED_HOOK_POINTS,
    attach_extension_hooks,
    fire_session_start,
)
from superqode.pipy import ToolCall, ToolResultMessage
from superqode.pipy.ai import FakeStream, text_response, tool_response
from superqode.pipy.coding_session import CodingSessionOptions, PiPyCodingSession


async def open_session(tmp_path, script) -> PiPyCodingSession:
    return await PiPyCodingSession.create(
        CodingSessionOptions(
            cwd=tmp_path,
            model=MODEL,
            stream_fn=FakeStream(list(script)),
            session_root=tmp_path / ".sessions",
        )
    )


def write_call(name: str = "b.txt") -> ToolCall:
    return ToolCall(id="c1", name="write", arguments={"path": name, "content": "x"})


# -- picker ------------------------------------------------------------------ #


def test_pipy_carries_a_permissions_warning():
    items = {item.id: item for item in harness_picker_items(include_all=True)}

    assert "Pure host permissions" in items["pipy"].warning
    assert "no sandbox" in items["pipy"].warning


def test_harnesses_with_execution_caveats_carry_warnings():
    """Every harness whose execution model is not the default warns before selection.

    Two kinds qualify, and the warning text distinguishes them: harnesses that
    delegate tool execution to the host, and RLM kernels that confine it. A new
    harness in either group must state which it is, so this asserts the exact
    set rather than a minimum.
    """
    items = harness_picker_items(include_all=True)

    warned = {item.id for item in items if item.warning}

    assert warned == {"pipy", "prime-agent-python", "rlm", "rlm-docker", "rlm-monty"}


def test_host_permission_harnesses_name_host_permissions():
    """The harnesses that run tools as the SuperQode process say so up front."""
    items = {item.id: item for item in harness_picker_items(include_all=True)}

    for harness_id in ("pipy", "prime-agent-python", "rlm"):
        assert "permissions" in items[harness_id].warning.lower()


def test_confined_rlm_kernels_name_their_boundary():
    """The sandboxed RLM kernels advertise the boundary, not host permissions."""
    items = {item.id: item for item in harness_picker_items(include_all=True)}

    assert "container" in items["rlm-docker"].warning.lower()
    assert "network" in items["rlm-monty"].warning.lower()


def test_pipy_appears_with_the_native_harnesses():
    items = [item for item in harness_picker_items(include_all=True) if item.id == "pipy"]

    assert len(items) == 1
    assert items[0].group == "SuperQode harnesses"
    assert items[0].available is True
    assert items[0].continuity == "exact-resume"


# -- extension bridge -------------------------------------------------------- #


def test_permission_request_is_not_bridged():
    """PiPy has no approval path, so the approval hook point stays unwired."""
    from superqode.agent.hooks import PERMISSION_REQUEST

    assert PERMISSION_REQUEST not in BRIDGED_HOOK_POINTS
    assert set(BRIDGED_HOOK_POINTS) == {
        SESSION_START,
        USER_PROMPT_SUBMIT,
        BEFORE_TOOL_CALL,
        AFTER_TOOL_CALL,
        AFTER_TURN_COMPLETE,
        STOP,
    }


async def test_session_start_fires():
    hooks = HookRegistry()
    seen: list[str] = []
    hooks.register(SESSION_START, lambda **kw: seen.append(kw["harness_id"]))

    await fire_session_start(hooks, session_id="s1")

    assert seen == ["pipy"]


async def test_prompt_submit_and_turn_hooks_fire(tmp_path):
    session = await open_session(tmp_path, [text_response("done")])
    hooks = HookRegistry()
    prompts: list[str] = []
    turns: list[str] = []
    stops: list[str] = []
    hooks.register(USER_PROMPT_SUBMIT, lambda **kw: prompts.append(kw["prompt"]))
    hooks.register(AFTER_TURN_COMPLETE, lambda **kw: turns.append(kw["stop_reason"]))
    hooks.register(STOP, lambda **kw: stops.append(kw["harness_id"]))
    attach_extension_hooks(session.harness, hooks, session_id="s1")

    await session.prompt("do the thing")

    assert prompts == ["do the thing"]
    assert turns == ["stop"]
    assert stops == ["pipy"]


async def test_an_extension_can_block_a_tool(tmp_path):
    session = await open_session(
        tmp_path, [tool_response(write_call()), text_response("blocked then")]
    )
    hooks = HookRegistry()
    hooks.register(
        BEFORE_TOOL_CALL,
        lambda **kw: HookDecision(action="deny", message="not allowed by policy extension"),
    )
    attach_extension_hooks(session.harness, hooks, session_id="s1")

    await session.prompt("write it")

    context = await session.session.build_context()
    result = next(m for m in context.messages if isinstance(m, ToolResultMessage))
    assert result.is_error is True
    assert result.text == "not allowed by policy extension"
    assert not (tmp_path / "b.txt").exists()


async def test_a_tool_runs_when_no_extension_objects(tmp_path):
    session = await open_session(tmp_path, [tool_response(write_call()), text_response("written")])
    hooks = HookRegistry()
    calls: list[str] = []
    results: list[bool] = []
    hooks.register(BEFORE_TOOL_CALL, lambda **kw: calls.append(kw["tool_name"]))
    hooks.register(AFTER_TOOL_CALL, lambda **kw: results.append(kw["success"]))
    attach_extension_hooks(session.harness, hooks, session_id="s1")

    await session.prompt("write it")

    assert calls == ["write"]
    assert results == [True]
    assert (tmp_path / "b.txt").read_text() == "x"


async def test_before_tool_call_sees_the_arguments(tmp_path):
    session = await open_session(tmp_path, [tool_response(write_call()), text_response("ok")])
    hooks = HookRegistry()
    seen: list[dict] = []
    hooks.register(BEFORE_TOOL_CALL, lambda **kw: seen.append(kw["arguments"]))
    attach_extension_hooks(session.harness, hooks, session_id="s1")

    await session.prompt("write it")

    assert seen == [{"path": "b.txt", "content": "x"}]


async def test_after_tool_call_reports_a_failure(tmp_path):
    bad = ToolCall(id="c1", name="read", arguments={"path": "missing.txt"})
    session = await open_session(tmp_path, [tool_response(bad), text_response("ok")])
    hooks = HookRegistry()
    results: list[bool] = []
    hooks.register(AFTER_TOOL_CALL, lambda **kw: results.append(kw["success"]))
    attach_extension_hooks(session.harness, hooks, session_id="s1")

    await session.prompt("read it")

    assert results == [False]


async def test_detaching_stops_the_hooks(tmp_path):
    session = await open_session(tmp_path, [text_response("one"), text_response("two")])
    hooks = HookRegistry()
    prompts: list[str] = []
    hooks.register(USER_PROMPT_SUBMIT, lambda **kw: prompts.append(kw["prompt"]))
    unsubscribes = attach_extension_hooks(session.harness, hooks, session_id="s1")

    await session.prompt("first")
    for unsubscribe in unsubscribes:
        unsubscribe()
    await session.prompt("second")

    assert prompts == ["first"]


async def test_a_misbehaving_hook_does_not_break_the_run(tmp_path):
    def explode(**kwargs):
        raise RuntimeError("extension is broken")

    session = await open_session(tmp_path, [text_response("still fine")])
    hooks = HookRegistry()
    hooks.register(USER_PROMPT_SUBMIT, explode)
    attach_extension_hooks(session.harness, hooks, session_id="s1")

    message = await session.prompt("go")

    assert message.text == "still fine"


# -- status line ------------------------------------------------------------- #


async def test_session_info_reports_the_leaf(tmp_path):
    session = await open_session(tmp_path, [text_response("ok")])
    await session.prompt("hi")

    info = await session.info()

    assert info.leaf_id
    assert info.model == MODEL.id
    entries = await session.session.get_entries()
    assert info.leaf_id == entries[-1].id


async def test_leaf_moves_with_tree_navigation(tmp_path):
    session = await open_session(
        tmp_path, [text_response("one"), text_response("two"), text_response("summary")]
    )
    await session.prompt("start")
    root = (await session.session.get_entries())[0].id
    await session.prompt("branch")
    before = (await session.info()).leaf_id

    await session.navigate_tree(root)

    after = (await session.info()).leaf_id
    assert after != before


async def test_pipy_never_imports_the_tui():
    """The brain stays free of Textual; only the harness layer touches the UI."""
    import ast

    root = Path(__import__("superqode.pipy", fromlist=["x"]).__file__).parent
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                assert not name.startswith("textual"), f"{path.name} imports {name}"
                assert not name.startswith("superqode.app"), f"{path.name} imports {name}"
