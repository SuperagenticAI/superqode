from __future__ import annotations

import asyncio
import json
import shlex
import sys

import pytest

from textual.app import App
from textual.widgets import Button, Input, Static, TextArea

from superqode.harness.refinement import RefinementCoordinator
from superqode.widgets.refinement_inspector import RefinementScreen


class Executor:
    def __init__(self, waiting=False, failing=False):
        self.waiting, self.failing = waiting, failing
        self.started = asyncio.Event()
        self.cancelled = False

    async def run(
        self, job, *, label, prompt, workspace, overlay, editor=False, event_callback=None
    ):
        self.started.set()
        if self.waiting:
            await asyncio.Event().wait()
        if editor:
            content = json.dumps(
                {"keep_base": True, "notes": "Retain the observed working procedure"}
            )
        else:
            (workspace / "result.txt").write_text("done")
            content = "Task completed"
        return {
            "status": "error" if self.failing else "complete",
            "content": content,
            "error": "Fixture failure" if self.failing else None,
            "events": [],
            "usage": {},
            "run_id": label,
        }

    async def cancel(self):
        self.cancelled = True


class RefinementApp(App):
    def __init__(self, screen):
        super().__init__()
        self.refinement = screen
        self.ticks = 0

    def on_mount(self):
        self.set_interval(0.01, lambda: setattr(self, "ticks", self.ticks + 1))
        self.push_screen(self.refinement)


def screen(tmp_path, executor):
    source = tmp_path / "source"
    source.mkdir()
    (source / "input.txt").write_text("source")
    return RefinementScreen(
        source=source,
        output=tmp_path / "job",
        model="gemma4:12b",
        task="Write result.txt",
        coordinator_factory=lambda request, callback: RefinementCoordinator(
            request, executor=executor, callback=callback
        ),
    )


async def finished(view):
    while view.running:
        await asyncio.sleep(0.01)


async def test_tui_launch_progress_inspect_and_reopen(tmp_path):
    view = screen(tmp_path, Executor())
    app = RefinementApp(view)
    async with app.run_test(size=(100, 34)) as pilot:
        await pilot.pause()
        assert await pilot.click("#refinement-plan")
        assert not view.query_one("#refinement-start", Button).disabled
        assert await pilot.click("#refinement-start")
        await asyncio.wait_for(finished(view), 5)
        await pilot.pause()
        assert "succeeded" in str(view.query_one("#refinement-status", Static).render())
        assert await pilot.click("#refinement-inspect")
        await pilot.pause()
        assert "result.txt" in view.query_one("#refinement-detail", TextArea).text
        assert "SELECTED HARNESS COMPONENTS" in view.query_one("#refinement-detail", TextArea).text
        assert view.query_one("#refinement-apply", Button).disabled  # no explicit checks
        assert await pilot.click("#refinement-open")
        await pilot.pause()
        assert not view.query_one("#refinement-resume", Button).disabled


async def test_tui_escape_stops_job_and_remains_responsive(tmp_path):
    executor = Executor(waiting=True)
    view = screen(tmp_path, executor)
    app = RefinementApp(view)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.click("#refinement-plan")
        await pilot.click("#refinement-start")
        await asyncio.wait_for(executor.started.wait(), 3)
        before = app.ticks
        await pilot.pause(0.15)
        assert app.ticks > before
        await pilot.press("escape")
        await asyncio.wait_for(finished(view), 3)
        await pilot.pause()
        assert executor.cancelled
        assert "cancelled" in str(view.query_one("#refinement-status", Static).render())
        assert (tmp_path / "job/result.json").exists()


async def test_tui_failure_is_visible(tmp_path):
    view = screen(tmp_path, Executor(failing=True))
    app = RefinementApp(view)
    async with app.run_test(size=(100, 34)) as pilot:
        await pilot.pause()
        await pilot.click("#refinement-plan")
        await pilot.click("#refinement-start")
        await asyncio.wait_for(finished(view), 3)
        await pilot.pause()
        assert "failed" in str(view.query_one("#refinement-status", Static).render())


async def test_tui_resume_and_explicit_checked_application(tmp_path):
    view = screen(tmp_path, Executor())
    app = RefinementApp(view)
    async with app.run_test(size=(100, 34)) as pilot:
        await pilot.pause()
        view.query_one("#refinement-check", Input).value = shlex.join(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; assert Path('result.txt').read_text() == 'done'",
            ]
        )
        await pilot.click("#refinement-plan")
        await pilot.click("#refinement-start")
        await asyncio.wait_for(finished(view), 5)
        await pilot.pause()
        await pilot.click("#refinement-inspect")
        await pilot.pause()
        assert not view.query_one("#refinement-apply", Button).disabled
        assert not (tmp_path / "source/result.txt").exists()
        await pilot.click("#refinement-resume")
        await asyncio.wait_for(finished(view), 5)
        await pilot.pause()
        assert json.loads((tmp_path / "job/result.json").read_text())["new_sessions"] == 0
        await pilot.click("#refinement-inspect")
        await pilot.pause()
        await pilot.click("#refinement-apply")
        await pilot.pause()
        assert (tmp_path / "source/result.txt").read_text() == "done"
        assert view.query_one("#refinement-apply", Button).disabled


@pytest.mark.parametrize("size", [(100, 34), (80, 24)])
async def test_harness_hub_has_refinement_entry(size):
    from superqode.app.harness_picker import HarnessPickerItem
    from superqode.widgets.harness_hub import HarnessHubResult, HarnessHubScreen

    class HubApp(App):
        selected = None

        def on_mount(self):
            self.push_screen(
                HarnessHubScreen(
                    [
                        HarnessPickerItem(
                            id="codegem",
                            display_name="CodeGem",
                            description="Native",
                            runtime="codegem",
                            source="built-in",
                            group="SuperQode harnesses",
                            available=True,
                            issue="",
                            continuity="exact-resume",
                        )
                    ]
                ),
                callback=lambda result: setattr(self, "selected", result),
            )

    app = HubApp()
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        assert await pilot.click("#hub-refine")
        assert app.selected == HarnessHubResult("refine", "codegem")
