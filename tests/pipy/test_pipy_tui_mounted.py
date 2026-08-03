"""PiPy driven through the mounted TUI.

Unit tests cover the harness and the adapter separately. This file runs the real
app: it opens the harness picker, selects PiPy, sends a prompt and checks what a
user would actually see. It is the test that would have caught a broken
`PureMode` route or tool cards that never render.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from superqode.app.widgets import ConversationLog
from superqode.app_main import SuperQodeApp

pytestmark = pytest.mark.usefixtures("_pipy_tui_env")


@pytest.fixture
def _pipy_tui_env(tmp_path, monkeypatch):
    """Keep the app, the provider and the session store out of the real world."""
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    monkeypatch.setenv("SUPERQODE_PIPY_DIR", str(tmp_path / "pipy"))
    # Selecting a harness in the TUI writes SUPERQODE_HARNESS so a later
    # PureMode picks the choice up. That is deliberate, and it means these
    # tests have to contain it or every later PureMode() in the run inherits
    # PiPy instead of core.
    monkeypatch.setenv("SUPERQODE_HARNESS", "core")
    monkeypatch.setattr(SuperQodeApp, "_prewarm_litellm", lambda self: None)
    monkeypatch.setattr(SuperQodeApp, "_start_models_dev_refresh", lambda self: None)


@pytest.fixture
def stub_pipy(monkeypatch):
    """Answer the model locally, so a TUI run needs no network."""
    import superqode.harness.pipy_adapter as adapter_module

    from superqode.pipy import ToolCall
    from superqode.pipy.ai import FakeStream, text_response, tool_response
    from superqode.pipy.coding_session import CodingSessionOptions, PiPyCodingSession
    from superqode.pipy.stream import Model

    script = [
        tool_response(
            ToolCall(id="c1", name="bash", arguments={"command": "echo hello-from-pipy"})
        ),
        text_response("I ran the command and it printed hello-from-pipy."),
    ]

    async def factory(request, working_directory, session_path):
        options = CodingSessionOptions(
            cwd=working_directory,
            model=Model(id="stub-1", provider="stub", api="stub"),
            stream_fn=FakeStream(list(script)),
        )
        if session_path and Path(session_path).is_file():
            return await PiPyCodingSession.resume(options, session_path=session_path)
        return await PiPyCodingSession.create(options)

    original = adapter_module.PiPyHarnessProtocolAdapter.__init__

    def patched(self, *, session_factory=None):
        original(self, session_factory=factory)

    monkeypatch.setattr(adapter_module.PiPyHarnessProtocolAdapter, "__init__", patched)


async def select_pipy(app, pilot):
    """Open the picker, arrow to PiPy and press enter, as a user would."""
    log = app.query_one("#log", ConversationLog)
    app._harness_cmd("", log)
    await pilot.pause()

    ids = [entry.id for entry in app._harness_selection_list]
    index = ids.index("pipy")
    app._move_harness_selection(index - app._harness_highlighted_index)
    await pilot.pause()

    app.action_select_highlighted_harness()
    for _ in range(6):
        await pilot.pause()
    return log


async def test_the_picker_offers_pipy_with_its_warning():
    app = SuperQodeApp()
    async with app.run_test(size=(110, 40)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._harness_cmd("", log)
        await pilot.pause()

        ids = [entry.id for entry in app._harness_selection_list]
        index = ids.index("pipy")
        entry = app._harness_selection_list[index]
        assert entry.display_name == "PiPy (pi twin)"
        assert entry.runtime == "pipy"

        app._move_harness_selection(index - app._harness_highlighted_index)
        await pilot.pause()

        rendered = "\n".join(line.text for line in log.lines)
        assert "Pure host permissions" in rendered
        assert "no sandbox" in rendered


async def test_selecting_pipy_routes_through_the_harness_kernel(stub_pipy):
    """The PureMode routing fix, exercised in the real app rather than a unit."""
    app = SuperQodeApp()
    async with app.run_test(size=(110, 40)) as pilot:
        await select_pipy(app, pilot)

        pure = app._ensure_pure_mode()
        assert pure._harness_definition.id == "pipy"
        assert pure._harness_spec is not None, "PiPy fell through to the builtin AgentLoop"
        assert pure._harness_spec.runtime.backend == "pipy"


async def test_a_turn_renders_text_and_tool_cards(stub_pipy):
    """Tool calls and results must reach the TUI, not just the deltas."""
    app = SuperQodeApp()
    async with app.run_test(size=(110, 40)) as pilot:
        await select_pipy(app, pilot)

        pure = app._ensure_pure_mode()
        pure.connect("stub", "stub-1", working_directory=Path.cwd())

        calls: list[tuple[str, dict]] = []
        results: list[tuple[str, bool, str]] = []
        pure.on_tool_call = lambda name, args: calls.append((name, dict(args)))
        pure.on_tool_result = lambda name, result: results.append(
            (name, bool((result.metadata or {}).get("partial")), (result.output or "").strip())
        )

        chunks = [chunk async for chunk in pure.run_streaming("say hello")]
        for _ in range(4):
            await pilot.pause()

        assert "".join(chunks) == "I ran the command and it printed hello-from-pipy."
        assert calls == [("bash", {"command": "echo hello-from-pipy"})]

        finals = [entry for entry in results if not entry[1]]
        assert len(finals) == 1, f"expected one completed tool card, got {results}"
        assert finals[0][0] == "bash"
        assert "hello-from-pipy" in finals[0][2]


async def test_the_turn_is_written_to_a_pipy_session_file(stub_pipy, tmp_path):
    app = SuperQodeApp()
    async with app.run_test(size=(110, 40)) as pilot:
        await select_pipy(app, pilot)
        pure = app._ensure_pure_mode()
        pure.connect("stub", "stub-1", working_directory=Path.cwd())

        async for _ in pure.run_streaming("say hello"):
            pass
        await pilot.pause()

        files = list((tmp_path / "pipy").rglob("*.jsonl"))
        assert len(files) == 1
        header = files[0].read_text(encoding="utf-8").splitlines()[0]
        assert '"version":3' in header.replace(" ", "")


async def test_switching_to_core_and_back_leaves_pipy_routing_intact(stub_pipy):
    app = SuperQodeApp()
    async with app.run_test(size=(110, 40)) as pilot:
        await select_pipy(app, pilot)
        pure = app._ensure_pure_mode()
        assert pure._harness_spec is not None

        pure.select_harness("core")
        assert pure._harness_spec is None, "core must use the builtin loop"

        pure.select_harness("pipy")
        assert pure._harness_spec is not None
        assert pure._harness_spec.runtime.backend == "pipy"
