"""Mounted supervision, stale request routing and delivery navigation."""

import asyncio
import hashlib
from types import SimpleNamespace

import pytest
from textual.widgets import Button, OptionList, Select, TextArea

from superqode.app_main import SuperQodeApp, SelectionAwareInput
from superqode.app.outcomes import Outcome
from superqode.app.supervision import SupervisionEntry, SupervisionSnapshot, approval_entry
from superqode.app.widgets import ConversationLog
from superqode.widgets.run_overview import RunOverviewScreen
from superqode.widgets.workorder_inspector import WorkOrderInspector
from superqode.workorders import WorkOrder, WorkOrderStore, WorkOrderTask


@pytest.fixture(autouse=True)
def quiet(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    for name in (
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
        "_prewarm_litellm",
    ):
        monkeypatch.setattr(SuperQodeApp, name, lambda *a, **k: None)


def fake_pure(requests):
    calls = []

    async def approve(index, always=False):
        calls.append((requests[index]["tool_call_id"], always))
        requests.pop(index)
        return SimpleNamespace(content="Executed", error=None, stopped_reason="complete")

    return SimpleNamespace(
        session=SimpleNamespace(connected=True),
        runtime_name="builtin",
        get_current_session_id=lambda: "main",
        get_pending_approvals=lambda: list(requests),
        approve_and_resume=approve,
    ), calls


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_navigation_preserves_draft_cursor_and_viewport(size):
    app = SuperQodeApp()
    async with app.run_test(size=size) as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "unfinished draft"
        prompt.cursor_position = 5
        await pilot.press("ctrl+o")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, RunOverviewScreen)
        assert screen.query_one("#run-list", OptionList).has_focus
        assert screen.query_one("#run-back", Button).region.bottom <= size[1]
        await pilot.click("#run-tab-approvals")
        await pilot.press("escape")
        await pilot.pause()
        assert prompt.value == "unfinished draft"
        assert prompt.cursor_position == 5
        assert prompt.has_focus


async def test_stale_request_cannot_approve_replacement():
    app = SuperQodeApp()
    requests = [
        {"index": 0, "tool_name": "bash", "tool_call_id": "a", "arguments": {"command": "pytest"}}
    ]
    pure, calls = fake_pure(requests)
    app._pure_mode = pure
    async with app.run_test() as pilot:
        _, approvals = app._live_supervision()
        original = approvals[0]
        requests[0] = {**requests[0], "tool_call_id": "b", "arguments": {"command": "npm test"}}
        message = await app._supervision_action("approve", original)
        assert "expired or changed" in message
        assert not calls
        row = app._live_supervision()[1][0]
        await app._supervision_action("approve", row)
        assert calls == [("b", False)]


async def test_request_reorder_routes_by_identity_not_old_index():
    app = SuperQodeApp()
    requests = [
        {"index": i, "tool_name": "probe", "tool_call_id": name, "arguments": {}}
        for i, name in enumerate(("a", "b"))
    ]
    pure, calls = fake_pure(requests)
    app._pure_mode = pure
    async with app.run_test():
        row = app._live_supervision()[1][1]
        requests.reverse()
        for index, request in enumerate(requests):
            request["index"] = index
        await app._supervision_action("approve", row)
        assert calls == [("b", False)]


async def test_inline_inbox_approve_once_preserves_saved_draft():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "next task"
        app._show_permission_prompt(
            "bash", {"command": "pytest"}, app.query_one("#log", ConversationLog)
        )
        app._open_supervision("approvals")
        await pilot.pause()
        await pilot.click("#run-approve")
        await pilot.pause()
        assert not app._permission_pending
        assert app._permission_response == "allow"
        assert not getattr(app, "_approved_tools", set())
        await pilot.press("escape")
        await pilot.pause()
        assert prompt.value == "next task"


async def test_escape_from_inbox_does_not_reject_inline_request():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        app._show_permission_prompt(
            "bash", {"command": "pytest"}, app.query_one("#log", ConversationLog)
        )
        app._open_supervision("approvals")
        await pilot.pause()
        await pilot.press("escape")
        assert app._permission_pending
        app._handle_permission_input("n")


async def test_child_approval_routes_to_child_and_tree_is_visible():
    app = SuperQodeApp()
    request = {"index": 0, "tool_name": "probe", "arguments": {}, "tool_call_id": "child-call"}
    calls = []
    peer = SimpleNamespace(pending_approvals=[request], loop=SimpleNamespace(_current_messages=[]))

    async def approve(target, index=0, always=False):
        calls.append((target, index, always))
        peer.pending_approvals.clear()
        return {"result": "child executed"}

    manager = SimpleNamespace(
        list_agents=lambda: [
            {
                "agent_id": "child",
                "task_name": "tests",
                "session_id": "child-sid",
                "status": "needs_approval",
                "queued_inputs": 0,
                "pending_approvals": peer.pending_approvals,
            }
        ],
        resolve=lambda target: peer,
        approve=approve,
    )
    pure, _ = fake_pure([])
    pure._agent = SimpleNamespace(_peer_manager=manager)
    app._pure_mode = pure
    async with app.run_test():
        runs, approvals = app._live_supervision()
        assert any("tests" in row.label and row.state == "Waiting for approval" for row in runs)
        await app._supervision_action("approve", approvals[0])
        assert calls == [("child", 0, False)]


def ready_store(root):
    store = WorkOrderStore(root / "work.sqlite")
    store.create(
        WorkOrder(
            "demo",
            "Fix answer",
            str(root),
            acceptance_tests=("pytest",),
            tasks=(WorkOrderTask("fix", "Fix", "Fix answer"),),
        )
    )
    store.queue("demo")
    store.claim_next_task(reference="demo", worker_id="worker")
    store.complete_task("demo", "fix", worker_id="worker")
    store.record_checks("demo", [{"command": "pytest", "status": "passed", "stdout": "passed"}])
    patch = "-41\n+42\n"
    candidate = store.add_artifact(
        "demo",
        kind="integration_candidate",
        content=patch,
        digest=hashlib.sha256(patch.encode()).hexdigest(),
    )
    store.mark_ready_to_merge("demo", candidate_artifact_id=candidate.artifact_id, metadata={})
    return store


async def test_delivery_and_human_review_open_existing_candidate_inspector(tmp_path):
    store = ready_store(tmp_path)
    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        app._open_supervision("delivery", f"--store {store.path}")
        await pilot.pause()
        await pilot.pause()
        screen = app.screen
        assert screen.rows[0].target == "demo"
        assert any(row.target == "demo" for row in screen.snapshot.approvals)
        await pilot.click("#run-open")
        await pilot.pause()
        inspector = app.screen
        assert isinstance(inspector, WorkOrderInspector)
        assert inspector.query_one("#work-section", Select).value == "delivery"
        assert "integration_candidate" in [row.get("kind") for _, row in inspector.rows]
        assert inspector.query_one("#work-approve", Button).disabled
        assert "Last checks: passed" in inspector.query_one("#work-detail", TextArea).text


async def test_delivery_keeps_unrecorded_tests_explicit_and_no_store_creation(tmp_path):
    app = SuperQodeApp()
    async with app.run_test():
        app._outcome_store().add(
            Outcome("Done", "No tests recorded", ("Tests\nNot recorded",), source="task")
        )
        snapshot = await app._load_supervision(tmp_path / "missing.sqlite")
        assert "Not recorded" in snapshot.delivery[0].detail
        assert not (tmp_path / "missing.sqlite").exists()


async def test_refresh_keeps_selected_request_and_background_action_allows_back():
    app = SuperQodeApp()
    request = {"tool_name": "probe", "arguments": {}, "tool_call_id": "a"}
    row = approval_entry("pure", "main", "Main", request)
    state = [row]
    release = asyncio.Event()
    started = asyncio.Event()

    async def loader():
        return SupervisionSnapshot(approvals=tuple(state))

    async def action(name, entry):
        started.set()
        await release.wait()
        return "Done"

    async with app.run_test() as pilot:
        screen = RunOverviewScreen(loader, action, section="approvals")
        app.push_screen(screen)
        await pilot.pause()
        state.insert(0, approval_entry("pure", "main", "Other", {**request, "tool_call_id": "b"}))
        await screen.reload()
        assert screen.selected().id == row.id
        await pilot.click("#run-approve")
        await asyncio.wait_for(started.wait(), 2)
        await pilot.press("escape")
        assert app.screen is not screen
        release.set()
        await pilot.pause()


async def test_replacement_runtime_cannot_reuse_old_inbox_request():
    app = SuperQodeApp()
    request = {"index": 0, "tool_name": "probe", "tool_call_id": "reused", "arguments": {}}
    old, _ = fake_pure([request])
    app._pure_mode = old
    async with app.run_test():
        row = app._live_supervision()[1][0]
        replacement, calls = fake_pure([request])
        app._pure_mode = replacement
        result = await app._supervision_action("approve", row)
        assert "expired or changed" in result
        assert not calls


async def test_live_detail_update_retains_reading_position():
    app = SuperQodeApp()
    details = ["\n".join(f"Line {i}" for i in range(100))]

    async def loader():
        return SupervisionSnapshot(runs=(SupervisionEntry("same", "Main", "Running", details[0]),))

    async with app.run_test() as pilot:
        screen = RunOverviewScreen(loader, lambda *args: None)
        app.push_screen(screen)
        await pilot.pause()
        viewer = screen.query_one("#run-detail", TextArea)
        viewer.scroll_to(y=20, animate=False, immediate=True)
        await pilot.pause()
        offset = viewer.scroll_offset
        details[0] += "\nNew observed event"
        await screen.reload()
        await pilot.pause()
        assert viewer.scroll_offset == offset


async def test_merge_requires_accepted_candidate_and_explicit_confirmation(tmp_path):
    store = ready_store(tmp_path)
    app = SuperQodeApp()
    actions = []
    async with app.run_test(size=(80, 24)) as pilot:
        screen = WorkOrderInspector(
            store.path, "demo", section="delivery", on_action=actions.append
        )
        app.push_screen(screen)
        await pilot.pause()
        screen.query_one("#work-operation", Select).value = "merge"
        await pilot.pause()
        assert screen.query_one("#work-execute", Button).disabled
        store.accept("demo", actor="reviewer", reason="Reviewed exact candidate")
        await screen.reload()
        assert not screen.query_one("#work-execute", Button).disabled
        await pilot.click("#work-execute")
        await pilot.pause()
        assert not actions
        await pilot.pause(0.35)
        await pilot.click("#work-execute")
        await pilot.pause()
        assert actions == [["work", "--store", str(store.path), "merge", "demo"]]


async def test_candidate_replacement_invalidates_pending_merge_confirmation(tmp_path):
    store = ready_store(tmp_path)
    store.accept("demo", reason="Reviewed")
    app = SuperQodeApp()
    actions = []
    async with app.run_test() as pilot:
        screen = WorkOrderInspector(
            store.path, "demo", section="delivery", on_action=actions.append
        )
        app.push_screen(screen)
        await pilot.pause()
        screen.query_one("#work-operation", Select).value = "merge"
        await pilot.pause()
        await pilot.click("#work-execute")
        candidate = store.add_artifact(
            "demo",
            kind="integration_candidate",
            content="new",
            digest=hashlib.sha256(b"new").hexdigest(),
        )
        store.mark_ready_to_merge("demo", candidate_artifact_id=candidate.artifact_id, metadata={})
        await pilot.pause(0.35)
        await pilot.click("#work-execute")
        await pilot.pause()
        assert not actions
        assert screen.query_one("#work-execute", Button).disabled


async def test_corrupt_store_reports_unavailable_without_crashing(tmp_path):
    app = SuperQodeApp()
    path = tmp_path / "corrupt.sqlite"
    path.write_bytes(b"not a SQLite database")
    async with app.run_test():
        snapshot = await app._load_supervision(str(path))
        assert "WorkOrder state unavailable" in snapshot.notice
        assert not snapshot.delivery


def test_approval_preview_puts_command_before_metadata():
    row = approval_entry(
        "peer",
        "child",
        "Reviewer",
        {
            "tool_name": "bash",
            "arguments": {"command": "pytest tests/test_delivery.py"},
            "tool_call_id": "request-1",
            "reason": "Consent required",
            "risk": "medium",
        },
    )
    assert row.detail.splitlines()[1] == "command: pytest tests/test_delivery.py"
    assert row.detail.index("command:") < row.detail.index("Invocation:")


def test_supervision_reuses_read_only_store_without_initialization(tmp_path, monkeypatch):
    from superqode.app.mixins.supervision import SupervisionMixin

    path = tmp_path / "workorders.sqlite3"
    store = WorkOrderStore(path)
    store.create(
        WorkOrder(
            work_order_id="poll-check",
            goal="Inspect",
            repository=str(tmp_path),
            tasks=(WorkOrderTask(task_id="check", title="Check", goal="Check"),),
        )
    )
    monkeypatch.setattr(
        WorkOrderStore, "_initialize", lambda *_: pytest.fail("Polling initialized the store")
    )
    app = SimpleNamespace()
    first = SupervisionMixin._work_supervision(app, path, tmp_path)
    cached = app._supervision_read_store[1]
    second = SupervisionMixin._work_supervision(app, path, tmp_path)
    assert [entry.id for entry in second[0]] == [entry.id for entry in first[0]]
    assert app._supervision_read_store[1] is cached
    with pytest.raises(Exception, match="readonly"):
        with cached._connect() as connection:
            connection.execute("CREATE TABLE forbidden (id INTEGER)")
    missing = tmp_path / "missing.sqlite3"
    assert SupervisionMixin._work_supervision(app, missing, tmp_path) == ([], [])
    assert not missing.exists()
