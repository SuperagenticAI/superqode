"""Native Codex UI operations must yield to input while RPCs are pending."""

import asyncio
from types import SimpleNamespace

import pytest

from superqode.app_main import SuperQodeApp
from superqode.harness.events import HarnessEvent
from superqode.pure_mode import PureMode


class Log:
    def __init__(self):
        self.items = []

    def write(self, value):
        self.items.append(str(value))

    add_info = write
    add_error = write
    add_warning = write
    add_success = write


@pytest.fixture
def native_app(monkeypatch):
    app = SuperQodeApp()
    runtime = SimpleNamespace(name="codex-cli", model="", reasoning_effort=None)
    app._pure_mode = SimpleNamespace(_runtime=runtime, runtime_name="codex-cli")
    tasks = []
    monkeypatch.setattr(
        app, "run_worker", lambda coro, **kwargs: tasks.append(asyncio.create_task(coro))
    )
    monkeypatch.setattr(app, "_codex_runtime_or_connect", lambda log: runtime)
    monkeypatch.setattr(app, "_show_command_output", lambda log, text, **kwargs: log.write(text))
    return app, runtime, tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("picker", ["model", "effort"])
async def test_picker_rpc_yields_and_empty_catalog_does_not_refetch(native_app, picker):
    app, runtime, tasks = native_app
    reached, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def models():
        calls.append("models")
        reached.set()
        await release.wait()
        return {"data": []}

    runtime.models = models
    log = Log()
    getattr(app, f"_show_codex_{picker}_picker")(log)
    assert not log.items
    await reached.wait()
    assert not log.items  # No blocking RPC or early picker state.
    release.set()
    await asyncio.gather(*tasks)
    assert len(tasks) == 1
    assert calls == ["models"]
    assert log.items
    assert getattr(app, f"_awaiting_codex_{picker}")


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["models", "thread", "sessions", "account"])
async def test_metadata_commands_await_native_rpc(native_app, command):
    app, runtime, tasks = native_app
    reached, release = asyncio.Event(), asyncio.Event()

    async def read(**kwargs):
        reached.set()
        await release.wait()
        return {"data": [], "thread": {"id": "t1"}, "account": {"type": "chatgpt"}}

    runtime.models = runtime.read_thread = runtime.list_threads = runtime.account = read
    log = Log()
    if command == "sessions":
        app._codex_sessions_cmd("", log)
    else:
        getattr(app, f"_codex_{command}_cmd")(log)
    await reached.wait()
    assert not log.items
    release.set()
    await asyncio.gather(*tasks)
    assert log.items
    assert not any("failed" in item.lower() for item in log.items)


@pytest.mark.asyncio
async def test_stale_rpc_does_not_update_new_connection(native_app):
    app, runtime, tasks = native_app
    result = []

    async def models():
        await asyncio.sleep(0)
        return {"data": []}

    app._codex_async_read(Log(), "models", runtime, models, result.append)
    app._pure_mode._runtime = object()
    await asyncio.gather(*tasks)
    assert not result


@pytest.mark.asyncio
async def test_native_approval_cancellation_clears_composer(native_app, monkeypatch):
    app, _, _ = native_app
    app.approval_mode = "ask"
    app._active_plan_mode_for_current_message = False
    app._permission_pending = False
    pure = SimpleNamespace()
    shown, reset = [], []
    monkeypatch.setattr(app, "_show_permission_prompt", lambda *args: shown.append(args))
    monkeypatch.setattr(app, "_reset_input_placeholder", lambda: reset.append(True))
    app._install_pure_permission_bridge(pure, Log())
    pending = asyncio.create_task(pure.on_permission_request_async("bash", {"command": "echo ok"}))
    await asyncio.sleep(0)
    assert shown
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert app._permission_response_event is None
    assert app._permission_pending is False
    assert reset


@pytest.mark.asyncio
async def test_native_steering_failure_keeps_user_message(native_app, monkeypatch):
    app, runtime, tasks = native_app
    app.is_busy = True
    app._awaiting_agent_question = False
    monkeypatch.setattr(app, "_in_selection_mode", lambda: False)
    drafts = []
    monkeypatch.setattr(app, "_set_prompt_prefill", drafts.append)

    async def steer(text):
        raise RuntimeError("turn already completed")

    runtime.steer = steer
    log = Log()
    assert app._steer_message("keep this instruction", log)
    await asyncio.gather(*tasks)
    assert drafts == ["keep this instruction"]
    assert any("Could not steer" in item for item in log.items)


def test_interleaved_command_output_keeps_item_identity():
    pure = PureMode()
    received = []
    pure.on_tool_result = lambda name, result: received.append(result)
    for item, text in [("a", "first"), ("b", "second")]:
        pure._handle_runtime_harness_event(
            HarnessEvent(
                type="tool_delta", data={"tool_name": "bash", "tool_call_id": item, "text": text}
            )
        )
    pure._flush_runtime_tool_delta_buffers(force=True)
    assert [(r.metadata["tool_call_id"], r.output) for r in received] == [
        ("a", "first"),
        ("b", "second"),
    ]


@pytest.mark.asyncio
async def test_mounted_native_picker_keeps_input_responsive(monkeypatch):
    from superqode.app.widgets import ConversationLog
    from superqode.app.inputs import SelectionAwareInput

    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    app = SuperQodeApp()
    reached, release = asyncio.Event(), asyncio.Event()
    selected = []

    async def models():
        reached.set()
        await release.wait()
        return {
            "data": [
                {"model": "first", "displayName": "First"},
                {"model": "second", "displayName": "Second"},
            ]
        }

    runtime = SimpleNamespace(name="codex-cli", models=models, model="")
    async with app.run_test(size=(120, 40)) as pilot:
        pure = PureMode()
        pure.runtime_name = "codex-cli"
        pure._runtime = runtime
        app._pure_mode = pure
        monkeypatch.setattr(app, "_codex_runtime_or_connect", lambda log: runtime)
        monkeypatch.setattr(
            app, "_apply_codex_model_override", lambda model, log: selected.append(model)
        )
        app._show_codex_model_picker(app.query_one("#log", ConversationLog))
        await asyncio.wait_for(reached.wait(), 2)
        await pilot.press("d", "r", "a", "f", "t")
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        assert prompt.value == "draft"
        prompt.value = ""
        release.set()
        await pilot.pause()
        assert app._awaiting_codex_model
        await pilot.press("down", "enter")
        await pilot.pause()
        assert selected == ["second"]


@pytest.mark.asyncio
@pytest.mark.parametrize("profile_id,runtime", [("codex", "codex-cli"), ("codex-sdk", "codex-sdk")])
async def test_connect_menu_navigates_to_distinct_codex_subscription_routes(
    monkeypatch, profile_id, runtime
):
    from superqode.app.widgets import ConversationLog
    from superqode.providers.connection_profiles import display_ordered_profiles

    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    app = SuperQodeApp()
    selected = []
    monkeypatch.setattr(
        app,
        "_runtime_cmd",
        lambda name, log: selected.append((name, app._requested_runtime_billing)),
    )
    async with app.run_test(size=(120, 45)) as pilot:
        log = app.query_one("#log", ConversationLog)
        app._show_connect_type_picker(log)
        await pilot.press("enter")
        await pilot.pause()
        assert app._connect_menu == "agents"
        await pilot.press("enter")
        await pilot.pause()
        assert app._connect_menu == "vendors"
        rendered = "\n".join(line.text for line in log.lines)
        assert "Codex CLI" in rendered and "Codex SDK" in rendered
        index = next(
            i
            for i, profile in enumerate(display_ordered_profiles("vendors"))
            if profile.id == profile_id
        )
        await pilot.press(*(["down"] * index), "enter")
        await pilot.pause()
        assert selected == [(runtime, "subscription")]
