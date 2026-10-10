"""Slow filesystem work must leave the composer usable and reject stale results."""

import asyncio
import threading
from pathlib import Path

import pytest

from superqode.app.inputs import SelectionAwareInput
from superqode.app.recipes import PromptCompletionCandidate
from superqode.app.widgets import ConversationLog
from superqode.app_main import SuperQodeApp


@pytest.fixture(autouse=True)
def quiet(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    monkeypatch.delenv("SUPERQODE_CONNECT", raising=False)
    for name in (
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
        "_prewarm_litellm",
    ):
        monkeypatch.setattr(SuperQodeApp, name, lambda *a, **k: None)


async def test_slow_completion_does_not_block_typing_or_restore_stale_results(monkeypatch):
    started, release = threading.Event(), threading.Event()
    original = SuperQodeApp._prompt_completion_candidates_for

    def candidates(self, value):
        if value == "@slow":
            started.set()
            assert release.wait(5)
            return [PromptCompletionCandidate("@slow.py", "slow.py", "file", "file")]
        return original(self, value)

    monkeypatch.setattr(SuperQodeApp, "_prompt_completion_candidates_for", candidates)
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "@slow"
        try:
            assert await asyncio.to_thread(started.wait, 2)
            prompt.value = "new draft"
            prompt.focus()
            await pilot.press("end", "!")
            assert prompt.value == "new draft!"
        finally:
            release.set()
        await asyncio.wait_for(
            asyncio.gather(
                *(worker.wait() for worker in app.workers if worker.group == "prompt-completion"),
                return_exceptions=True,
            ),
            timeout=2,
        )
        await pilot.pause()
        assert not app._prompt_completion_visible
        assert prompt.value == "new draft!"


async def test_slow_file_search_keeps_composer_usable_and_delivers_output(monkeypatch):
    started, release = threading.Event(), threading.Event()

    def search(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return [(Path("found.py"), "found.py", 1)]

    monkeypatch.setattr("superqode.file_explorer.fuzzy_find_files", search)
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        worker = app._find_files("found", log)
        try:
            assert await asyncio.to_thread(started.wait, 2)
            prompt = app.query_one("#prompt-input", SelectionAwareInput)
            prompt.focus()
            await pilot.press("h", "i")
            assert prompt.value == "hi"
        finally:
            release.set()
        await worker.wait()
        await pilot.pause()
        assert "found.py" in "\n".join(line.text for line in log.lines)


async def test_background_preview_keeps_line_count_and_only_first_fifty_lines(tmp_path):
    source = tmp_path / "preview.py"
    source.write_text("\n".join(f"print({i})" for i in range(100)) + "\n")
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        await app._view_file(str(source), log).wait()
        await pilot.pause()
        rendered = "\n".join(line.text for line in log.lines)
        assert "print(49)" in rendered
        assert "print(50)" not in rendered
        assert "Showing first 50 of 100 lines" in rendered


def test_path_completion_snapshot_reuses_metadata_and_refreshes(monkeypatch, tmp_path):
    from superqode.app.mixins import helper_completion_helpers as module

    module._directory_completion_snapshot.cache_clear()
    monkeypatch.setattr(module, "monotonic", lambda: 100)
    (tmp_path / "first.py").write_text("x")
    helper = module.HelperCompletionHelpersMixin
    assert helper._path_token_candidates("fi") == [("first.py", "1 bytes")]
    (tmp_path / "fresh.py").write_text("xx")
    assert helper._path_token_candidates("fr") == []
    monkeypatch.setattr(module, "monotonic", lambda: 101)
    assert helper._path_token_candidates("fr") == [("fresh.py", "2 bytes")]


@pytest.mark.parametrize("query", ["~superqode_missing_test_user_490a/", "bad\x00dir/file"])
def test_invalid_paths_do_not_break_either_prompt_completer(query):
    from superqode.app.mixins.helper_completion_helpers import HelperCompletionHelpersMixin
    from superqode.widgets.prompt import SmartPrompt

    assert HelperCompletionHelpersMixin._path_token_candidates(query) == []
    assert SmartPrompt()._get_path_completions(query) == []


@pytest.mark.parametrize("path", ["~superqode_missing_test_user_490a/", "bad\x00dir/file"])
async def test_invalid_attachment_path_completion_keeps_composer_usable(path):
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = ":attach " + path
        await pilot.pause()
        workers = [worker for worker in app.workers if worker.group == "prompt-completion"]
        await asyncio.gather(*(worker.wait() for worker in workers))
        await pilot.pause()
        assert not app._prompt_completion_visible
        prompt.value = "continue writing"
        prompt.focus()
        await pilot.press("end", "!")
        assert prompt.value == "continue writing!"


async def test_directory_search_preserves_match_limits_and_line_numbers(tmp_path):
    (tmp_path / "match.py").write_text("skip\n" + "needle\n" * 100)
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        await app._search_in_directory("needle", log).wait()
        await pilot.pause()
        rendered = "\n".join(line.text for line in log.lines)
        assert "50 match(es)" in rendered
        assert "match.py" in rendered
        assert "   2: needle" in rendered
        assert "  52: needle" not in rendered


async def test_escape_discards_pending_completion(monkeypatch):
    started, release = threading.Event(), threading.Event()
    original = SuperQodeApp._prompt_completion_candidates_for

    def candidates(self, value):
        if value == "@slow":
            started.set()
            assert release.wait(5)
            return [PromptCompletionCandidate("@slow.py", "slow.py", "file", "file")]
        return original(self, value)

    monkeypatch.setattr(SuperQodeApp, "_prompt_completion_candidates_for", candidates)
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "@slow"
        prompt.focus()
        try:
            assert await asyncio.to_thread(started.wait, 2)
            await pilot.press("escape")
        finally:
            release.set()
        await pilot.pause(0.15)
        assert not app._prompt_completion_visible
        assert prompt.value == "@slow"


async def test_tab_accepts_single_file_completion_after_background_load(tmp_path, monkeypatch):
    import time

    original = SuperQodeApp._prompt_completion_candidates_for

    def candidates(self, value):
        if value == "@uniq":
            time.sleep(0.2)
        return original(self, value)

    monkeypatch.setattr(SuperQodeApp, "_prompt_completion_candidates_for", candidates)
    (tmp_path / "unique.py").write_text("x")
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.value = "@uniq"
        prompt.focus()
        app._complete_prompt_input(prompt)
        await pilot.pause()
        await asyncio.wait_for(
            asyncio.gather(
                *(worker.wait() for worker in app.workers if worker.group == "prompt-completion"),
                return_exceptions=True,
            ),
            timeout=2,
        )
        await pilot.pause()
        assert prompt.value == "@unique.py"


async def test_late_completion_ignores_an_unmounted_composer(monkeypatch):
    started, release = threading.Event(), threading.Event()

    def candidates(self, value):
        started.set()
        assert release.wait(5)
        return [PromptCompletionCandidate("@unique.py", "unique.py", "file", "file")]

    monkeypatch.setattr(SuperQodeApp, "_prompt_completion_candidates_for", candidates)
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        revision = getattr(app, "_completion_revision", 0)
        app._completion_revision = revision
        worker = app._load_prompt_completions("@uniq", revision)
        try:
            assert await asyncio.to_thread(started.wait, 2)
            await prompt.remove()
        finally:
            release.set()
        await asyncio.wait_for(worker.wait(), timeout=2)
        assert not app._prompt_completion_visible


async def test_slow_diff_review_keeps_typing_responsive(monkeypatch):
    started, release = threading.Event(), threading.Event()

    def collect(self, pending):
        started.set()
        assert release.wait(5)
        return [
            (
                "Working tree",
                "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new",
            )
        ]

    monkeypatch.setattr(SuperQodeApp, "_collect_diff_sections", collect)
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        worker = app._handle_diff("files", log)
        try:
            assert await asyncio.to_thread(started.wait, 2)
            prompt = app.query_one("#prompt-input", SelectionAwareInput)
            prompt.focus()
            await pilot.press("h", "i")
            assert prompt.value == "hi"
        finally:
            release.set()
        await worker.wait()
        await pilot.pause()
        assert "a.py" in "\n".join(line.text for line in log.lines)
