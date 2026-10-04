"""Mounted delivery workflow, current permissions and candidate approval races."""

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner
from textual.widgets import Button, Input, OptionList, Select, TextArea

from superqode.app_main import SuperQodeApp, SelectionAwareInput
from superqode.app.widgets import ConversationLog
from superqode.commands.work import work
from superqode.harness.context_artifacts import ContextArtifactStore
from superqode.harness.context_policy import ContextItem, ContextPolicy, ContextPolicyEngine
from superqode.tools.permissions import Permission
from superqode.widgets.context_evidence import ContextEvidenceScreen
from superqode.widgets.panel_shortcuts import PanelShortcuts
from superqode.widgets.workorder_inspector import WorkOrderInspector
from superqode.workorders import WorkOrder, WorkOrderStore, WorkOrderTask
from superqode.workorders.inspection import inspect_work_order


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


def ready_store(root):
    store = WorkOrderStore(root / "work.sqlite")
    store.create(
        WorkOrder(
            "demo",
            "Fix the answer",
            str(root),
            acceptance_tests=("python test_answer.py",),
            tasks=(WorkOrderTask("fix", "Fix", "Fix the answer"),),
        )
    )
    store.queue("demo")
    store.claim_next_task(reference="demo", worker_id="worker")
    store.complete_task("demo", "fix", worker_id="worker")
    store.record_checks(
        "demo",
        [{"command": "python test_answer.py", "status": "passed", "stdout": "acceptance passed"}],
    )
    candidate = store.add_artifact(
        "demo",
        kind="integration_candidate",
        content="-return 41\n+return 42\n",
        digest=hashlib.sha256(b"-return 41\n+return 42\n").hexdigest(),
    )
    store.mark_ready_to_merge("demo", candidate_artifact_id=candidate.artifact_id, metadata={})
    return store, candidate


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_keyboard_review_requires_opened_diff_and_reason(size, tmp_path):
    store, candidate = ready_store(tmp_path)
    app = SuperQodeApp()
    results = []
    async with app.run_test(size=size) as pilot:
        screen = WorkOrderInspector(store.path, "demo")
        app.push_screen(screen, callback=results.append)
        await pilot.pause()
        assert screen.query_one("#work-rows", OptionList).has_focus
        assert screen.query_one("#work-approve", Button).disabled
        screen.query_one("#work-section", Select).value = "review"
        await pilot.pause()
        listing = screen.query_one("#work-rows", OptionList)
        listing.highlighted = next(
            i for i, (_, row) in enumerate(screen.rows) if row["kind"] == "integration_candidate"
        )
        await pilot.pause()
        await pilot.click("#work-open")
        await pilot.pause()
        assert "+return 42" in screen.query_one("#work-detail", TextArea).text
        assert not screen.query_one("#work-approve", Button).disabled
        await pilot.click("#work-approve")
        await pilot.pause()
        reason = screen.query_one("#work-reason", Input)
        assert reason.has_focus
        assert screen.query_one(PanelShortcuts).region.bottom <= size[1]
        assert screen.query_one("#work-back", Button).region.bottom <= size[1]
        await pilot.press("escape")
        assert results == [None]
        assert store.get("demo").decision is None


async def test_approval_dispatch_and_same_digest_new_candidate_race(tmp_path):
    store, candidate = ready_store(tmp_path)
    app = SuperQodeApp()
    parts = []
    async with app.run_test() as pilot:
        screen = WorkOrderInspector(store.path, "demo", on_action=parts.append)
        app.push_screen(screen)
        await pilot.pause()
        screen.query_one("#work-section", Select).value = "review"
        await pilot.pause()
        listing = screen.query_one("#work-rows", OptionList)
        listing.highlighted = next(
            i for i, (_, row) in enumerate(screen.rows) if row["kind"] == "integration_candidate"
        )
        await pilot.pause()
        await pilot.click("#work-open")
        await pilot.pause()
        await pilot.click("#work-approve")
        await pilot.pause()
        screen.query_one("#work-reason", Input).value = "Reviewed diff and passing acceptance"
        # Let the button release its active animation, as during actual typing.
        await pilot.pause(0.35)
        await pilot.click("#work-approve")
        assert parts[0][-4:] == [
            "--candidate-digest",
            candidate.digest,
            "--candidate-id",
            candidate.artifact_id,
        ]
        store.add_artifact(
            "demo", kind="integration_candidate", content=candidate.content, digest=candidate.digest
        )
        result = CliRunner().invoke(work, parts[0][1:])
        assert result.exit_code != 0 and "candidate changed" in result.output
        assert store.get("demo").decision is None
        await screen.reload()
        assert screen.query_one("#work-approve", Button).disabled
        assert screen.query_one("#work-reason", Input).value == ""


async def test_work_view_dispatch_preserves_draft_and_missing_store(tmp_path):
    store, _ = ready_store(tmp_path)
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "unfinished\ndraft"
        prompt.cursor_position = 3
        log = app.query_one("#log", ConversationLog)
        assert app._open_work_inspector(f"view demo --store {store.path}", log)
        await pilot.pause()
        assert isinstance(app.screen, WorkOrderInspector)
        await pilot.press("escape")
        await pilot.pause()
        assert (
            prompt.has_focus and prompt.value == "unfinished\ndraft" and prompt.cursor_position == 3
        )
        missing = tmp_path / "missing.sqlite"
        app._open_work_inspector(f"view demo --store {missing}", log)
        assert not missing.exists()


async def test_context_excerpt_original_paging_and_permission_revocation(tmp_path):
    store = ContextArtifactStore(tmp_path / "context.sqlite")
    engine = ContextPolicyEngine(store, "owner", ContextPolicy(mode="enforce", recent_messages=1))
    plan = await engine.prepare(
        [
            ContextItem("task", "user", "inspect"),
            ContextItem(
                "old", "tool", "evidence\n" * 3000, "read_file", "call", {"path": "app.py"}
            ),
            ContextItem("next", "assistant", "Continue"),
        ]
    )
    assert plan.trace["decisions"] and plan.trace["decisions"][0]["excerpt"]
    allowed = [True]
    manager = SimpleNamespace(
        check_permission=lambda *a: Permission.ALLOW if allowed[0] else Permission.DENY
    )
    app = SuperQodeApp()
    async with app.run_test(size=(80, 24)) as pilot:
        screen = ContextEvidenceScreen(plan.trace, tmp_path, permission_manager=manager)
        app.push_screen(screen)
        await pilot.pause()
        assert "context artifact" in screen.query_one("#context-evidence-detail", TextArea).text
        await pilot.click("#context-evidence-open")
        await pilot.pause()
        assert "Characters 0–4000" in screen.query_one("#context-evidence-detail", TextArea).text
        allowed[0] = False
        await pilot.click("#context-evidence-next")
        await pilot.pause()
        assert "denied" in screen.query_one("#context-evidence-detail", TextArea).text
        assert screen.query_one("#context-evidence-next", Button).disabled
        assert screen.query_one(PanelShortcuts).region.bottom <= 24


def test_recovery_metadata_excludes_outcomes_and_records_only_admitted_reuse(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite")
    store.create(
        WorkOrder("demo", "Recover", str(tmp_path), tasks=(WorkOrderTask("fix", "Fix", "Fix"),))
    )
    store.queue("demo")
    _, task = store.claim_next_task(reference="demo", worker_id="worker")
    args = dict(
        worker_id="worker",
        attempt=task.attempts,
        invocation_id="read",
        operation="read",
        fingerprint="input",
        replay_safe=True,
    )
    store.begin_invocation("demo", "fix", **args)
    store.finish_invocation(
        "demo",
        "fix",
        worker_id="worker",
        attempt=task.attempts,
        invocation_id="read",
        result={"private": "never-display-this"},
    )
    before = inspect_work_order(store.path, "demo")
    assert before["recovery"][0]["state"] == "committed"
    assert "never-display-this" not in str(before)
    assert "result" not in store.invocation_records("demo")[0]
    with pytest.raises(ValueError):
        store.begin_invocation("demo", "fix", **{**args, "fingerprint": "different"})
    assert store.invocation_records("demo")[0]["reuse_count"] == 0
    store.begin_invocation("demo", "fix", **args)
    assert inspect_work_order(store.path, "demo")["recovery"][0]["state"] == "reuse admitted"
    with pytest.raises(ValueError):
        store.invocation_records("demo", limit=501)


async def test_inspector_runs_public_action_and_stays_open(tmp_path):
    store = WorkOrderStore(tmp_path / "work.sqlite")
    store.create(
        WorkOrder("demo", "Queue", str(tmp_path), tasks=(WorkOrderTask("fix", "Fix", "Fix"),))
    )
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        app._open_work_inspector(
            f"view demo --store {store.path}", app.query_one("#log", ConversationLog)
        )
        await pilot.pause()
        screen = app.screen
        screen.query_one("#work-operation", Select).value = "queue"
        await pilot.pause()
        await pilot.click("#work-execute")
        for _ in range(30):
            await pilot.pause(0.1)
            if screen.snapshot["status"] == "queued":
                break
        await pilot.pause()
        assert app.screen is screen
        assert store.get("demo").status.value == "queued"
        assert screen.snapshot["status"] == "queued"


async def test_tui_interrupts_real_coding_process_then_restart_shows_reuse(tmp_path, monkeypatch):
    import asyncio
    import os
    import sys
    from test_pipy_run_recovery import SCRIPT, process as resume_process

    path = tmp_path / ".superqode" / "work.sqlite3"
    WorkOrderStore(path)
    script = SCRIPT.replace(
        "  os._exit(72)\nstore.finish_invocation=finish",
        "  (control/'ready').write_text('committed'); time.sleep(300); os._exit(72)\nstore.finish_invocation=finish",
    )
    assert script != SCRIPT
    original_spawn = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        return await original_spawn(
            sys.executable, "-c", script, str(tmp_path), "after-write", **kwargs
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        app._open_work_inspector(
            f"view work --store {path}", app.query_one("#log", ConversationLog)
        )
        screen = app.screen
        worker = app.run_worker(
            app._work_inspector_action(
                ["work", "--store", str(path), "run", "work"],
                path,
                "work",
                app.query_one("#log", ConversationLog),
            )
        )
        for _ in range(100):
            await pilot.pause(0.1)
            if (tmp_path / ".superqode" / "ready").exists():
                break
        assert (tmp_path / ".superqode" / "ready").exists()
        await screen.reload()
        screen.query_one("#work-section", Select).value = "recovery"
        await pilot.pause()
        assert any(row["state"] == "committed" for _, row in screen.rows)
        assert not screen.query_one("#work-interrupt", Button).disabled
        owned = app._work_inspector_processes[(str(path), "work")]
        await pilot.click("#work-interrupt")
        await worker.wait()
        assert owned.returncode == (-9 if os.name == "posix" else 1)
        assert app.screen is screen
        resumed = await asyncio.to_thread(resume_process, tmp_path, "resume")
        assert resumed.returncode == 0, resumed.stderr
        await screen.reload()
        assert any(row["state"] == "reuse admitted" for _, row in screen.rows)
        assert (tmp_path / ".superqode" / "writes.log").read_text().splitlines() == [
            "original-write"
        ]


async def test_assigned_evidence_pages_and_source_changes_are_visible(tmp_path, monkeypatch):
    from test_workorder_evidence import setup
    from superqode.workorders.evidence import publish_evidence

    root, store, order, investigator, dependent = setup(tmp_path, monkeypatch)
    publish_evidence(
        store, order, investigator, "The failing assertion points to app.py.\n" * 400, root
    )
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        screen = WorkOrderInspector(store.path, order.work_order_id)
        app.push_screen(screen)
        await pilot.pause()
        screen.query_one("#work-section", Select).value = "evidence"
        await pilot.pause()
        assert screen.snapshot["selected_task"] == dependent.task_id
        assert "Sources: current" in screen.query_one("#work-detail", TextArea).text
        assert "Verification: reported" in screen.query_one("#work-detail", TextArea).text
        await pilot.click("#work-open")
        await pilot.pause()
        assert not screen.query_one("#work-next", Button).disabled
        (root / "app.py").write_text("changed after investigation")
        await screen.reload()
        assert "Sources: stale" in screen.query_one("#work-detail", TextArea).text
        assert "Verification: reported" in screen.query_one("#work-detail", TextArea).text


async def test_context_view_dispatch_shows_persisted_decision_reuse(tmp_path, monkeypatch):
    store = ContextArtifactStore(tmp_path / "context.sqlite")
    policy = ContextPolicy(mode="enforce", selector="jev", recent_messages=1)
    from test_context_policy import SelectingClient

    client = SelectingClient()
    items = [
        ContextItem("task", "user", "inspect"),
        ContextItem("old", "tool", "evidence\n" * 3000, "read_file", "call", {"path": "app.py"}),
        ContextItem("next", "assistant", "Continue"),
    ]
    first = await ContextPolicyEngine(store, "owner", policy, client=client).prepare(items)
    restarted = ContextPolicyEngine(
        ContextArtifactStore(store.path), "owner", policy, client=client
    )
    plan = await restarted.prepare([*items, ContextItem("small", "assistant", "Keep working")])
    assert not first.trace["cache_hit"] and plan.trace["cache_hit"] and client.calls == 1
    agent = SimpleNamespace(last_context_selection=plan.trace, permission_manager=None)
    app = SuperQodeApp()
    monkeypatch.setattr(app, "_active_agent_loop", lambda: agent)
    async with app.run_test() as pilot:
        app._open_context_evidence(app.query_one("#log", ConversationLog))
        await pilot.pause()
        assert isinstance(app.screen, ContextEvidenceScreen)
        assert app.screen.trace["cache_hit"]
        assert "context artifact" in app.screen.query_one("#context-evidence-detail", TextArea).text
        await pilot.press("escape")
        assert app.query_one("#prompt-input", SelectionAwareInput).has_focus


def test_live_demo_setup_is_offline_and_recovery_is_explicit(tmp_path):
    import importlib.util
    import subprocess
    from superqode.harness.loader import load_harness_spec

    path = Path(__file__).resolve().parents[1] / "examples/workorders/tui_demo.py"
    spec = importlib.util.spec_from_file_location("tui_demo", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for enabled in (False, True):
        root = module.prepare(
            tmp_path / str(enabled), provider="fixture", model="fixed", recovery=enabled
        )
        order = WorkOrderStore(root / ".superqode/workorders/store.sqlite3").get("tui-demo")
        assert order.tasks[1].dependencies == ("investigate",)
        assert load_harness_spec(order.harness).runtime.config["recovery"]["enabled"] is enabled
        assert load_harness_spec(order.tasks[0].harness).execution_policy.allow_write is False
        assert (
            subprocess.run(
                order.acceptance_tests[0].split(), cwd=root, capture_output=True
            ).returncode
            != 0
        )
        with pytest.raises(FileExistsError):
            module.prepare(root, provider="fixture", model="fixed")


def test_candidate_preview_cannot_enable_approval_when_incomplete_or_corrupt(tmp_path):
    from superqode.workorders.inspection import inspected_diff

    store, _ = ready_store(tmp_path)
    content = "diff body\n" * 8000
    store.add_artifact(
        "demo",
        kind="integration_candidate",
        content=content,
        digest=hashlib.sha256(content.encode()).hexdigest(),
    )
    text, digest, ident, complete = inspected_diff(store.path, "demo")
    assert not complete and "Preview truncated" in text and len(text) < 65000
    store.add_artifact("demo", kind="integration_candidate", content="tampered", digest=digest)
    with pytest.raises(ValueError, match="integrity"):
        inspected_diff(store.path, "demo")


async def test_exiting_tui_stops_inspector_owned_process(tmp_path, monkeypatch):
    import asyncio
    import sys

    store, _ = ready_store(tmp_path)
    original_spawn = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        return await original_spawn(sys.executable, "-c", "import time; time.sleep(300)", **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        worker = app.run_worker(
            app._work_inspector_action(
                ["work", "run", "demo"], store.path, "demo", app.query_one("#log", ConversationLog)
            )
        )
        for _ in range(30):
            await pilot.pause(0.1)
            owned = app._work_inspector_processes.get((str(store.path), "demo"))
            if owned is not None:
                break
        assert owned is not None and owned.returncode is None
    from textual.worker import WorkerCancelled

    with pytest.raises(WorkerCancelled):
        await worker.wait()
    assert owned.returncode is not None and worker.is_cancelled
