"""Keyboard, pointer, and asynchronous search behavior in existing TUI surfaces."""

from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from superqode.app.inputs import SelectionAwareInput
from superqode.app_main import SuperQodeApp
from superqode.sidebar import (
    CodebaseSearch,
    CodeSearchResult,
    CodeSearchResults,
    CollapsibleSidebar,
    ColorfulDirectoryTree,
    FilePreviewScroll,
    FilePreview,
    FileSearch,
    FileSearchResults,
    search_codebase,
)


@pytest.fixture(autouse=True)
def isolate_startup(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in ("SUPERQODE_CONNECT", "SUPERQODE_HARNESS", "SUPERQODE_VIM"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    for name in (
        "_prewarm_litellm",
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
    ):
        monkeypatch.setattr(SuperQodeApp, name, lambda self: None)


@pytest.mark.asyncio
async def test_composer_accepts_the_first_key_before_the_startup_focus_timer(monkeypatch):
    monkeypatch.setattr(SuperQodeApp, "_focus_input_on_ready", lambda self: None)
    app = SuperQodeApp()
    async with app.run_test(size=(120, 40)) as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        assert app.focused is prompt
        await pilot.press("d", "r", "a", "f", "t")
        assert prompt.value == "draft"


@pytest.mark.asyncio
async def test_ready_focus_does_not_interrupt_a_sidebar_open_in_progress(monkeypatch):
    app = SuperQodeApp()
    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause()
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        calls = []
        monkeypatch.setattr(prompt, "focus", lambda *args, **kwargs: calls.append("composer"))
        # Visibility records the user's intent before the next layout applies
        # the sidebar's deferred focus request.
        app.sidebar_visible = True
        assert not app._sidebar_has_focus()
        app._focus_input_on_ready()
        assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(80, 24), (110, 30)])
async def test_sidebar_keyboard_search_preview_back_and_draft(tmp_path, size):
    (tmp_path / "alpha.py").write_text("print('alpha')\n")
    (tmp_path / "beta.py").write_text("print('beta')\n")
    app = SuperQodeApp()
    async with app.run_test(size=size) as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.load_text("Keep my draft")
        search = app.query_one("#file-search", FileSearch)
        assert not search._files_loading and not search._files_loaded
        await pilot.press("ctrl+2")
        assert isinstance(app.focused, ColorfulDirectoryTree)
        app._focus_input_on_ready()
        app._ensure_input_focus()
        assert isinstance(app.focused, ColorfulDirectoryTree)
        await pilot.press("ctrl+f")
        assert app.focused.id == "search-input"
        await search._file_worker.wait()
        await pilot.press("p", "y")
        await pilot.pause()
        results = search.query_one(FileSearchResults)
        assert len(results.results) == 2
        await pilot.press("down")
        selected = results.get_selected()
        await pilot.press("enter")
        await pilot.pause()
        sidebar = app.query_one(CollapsibleSidebar)
        assert sidebar.current_view == "code"
        assert sidebar._current_file == selected
        assert isinstance(app.focused, FilePreviewScroll)
        await pilot.press("escape")
        assert sidebar.current_view == "files"
        assert isinstance(app.focused, ColorfulDirectoryTree)
        await pilot.press("escape")
        await pilot.pause()
        assert not app.sidebar_visible
        assert app.focused is prompt
        assert prompt.value == "Keep my draft"


@pytest.mark.asyncio
async def test_file_search_mouse_selection_and_sidebar_reopen(tmp_path):
    path = tmp_path / "click me.py"
    path.write_text("pass\n")
    app = SuperQodeApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("ctrl+2", "ctrl+f")
        search = app.query_one(FileSearch)
        await search._file_worker.wait()
        search.query_one(Input).value = "click"
        await pilot.pause()
        await pilot.click("#search-results-content", offset=(5, 0))
        await pilot.pause()
        sidebar = app.query_one(CollapsibleSidebar)
        assert sidebar.current_view == "code"
        assert sidebar._current_file == path
        await pilot.press("ctrl+b", "ctrl+b")
        assert sidebar.current_view == "code"
        assert isinstance(app.focused, FilePreviewScroll)


@pytest.mark.asyncio
async def test_ctrl_f_transcript_search_stashes_draft():
    app = SuperQodeApp()
    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt-input", SelectionAwareInput)
        prompt.load_text("Unfinished thought")
        prompt.focus()
        await pilot.press("ctrl+f")
        assert prompt.value == ":search "
        assert app._draft_stash[-1] == "Unfinished thought"
        await pilot.press("ctrl+f")
        assert app._draft_stash == ["Unfinished thought"]


@pytest.mark.asyncio
async def test_delayed_focus_callbacks_are_safe_after_shutdown():
    app = SuperQodeApp()
    async with app.run_test():
        pass
    assert not app.screen_stack
    app._focus_input_on_ready()
    app._ensure_input_focus()
    assert not app._sidebar_has_focus()


def test_file_search_can_navigate_beyond_first_ten_matches():
    results = FileSearchResults()
    results.results = [Path(f"src/file_{index}.py") for index in range(30)]
    for _ in range(24):
        results.move_selection(1)
    assert results.get_selected() == Path("src/file_24.py")
    rendered = results._render_results()
    indices = [
        span.style.meta.get("file_index") for span in rendered.spans if hasattr(span.style, "meta")
    ]
    assert 24 in indices
    assert 0 not in indices


def test_code_search_can_navigate_beyond_first_thirty_matches():
    results = CodeSearchResults()
    results.results = [CodeSearchResult(Path("a.py"), i + 1, "match", 0, 5) for i in range(50)]
    for _ in range(44):
        results.move_selection(1)
    assert results.get_selected().line_no == 45
    rendered = results._render_results()
    indices = [
        span.style.meta.get("code_index") for span in rendered.spans if hasattr(span.style, "meta")
    ]
    assert 44 in indices and 0 not in indices


class SearchApp(App):
    def __init__(self, root):
        super().__init__()
        self.root = root

    def compose(self) -> ComposeResult:
        yield CodebaseSearch(self.root)


@pytest.mark.asyncio
async def test_code_search_debounces_and_ignores_stale_results(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(CodebaseSearch, "_do_search", lambda self, query: calls.append(query))
    app = SearchApp(tmp_path)
    async with app.run_test() as pilot:
        search = app.query_one(CodebaseSearch)
        field = search.query_one(Input)
        field.value = "old"
        await pilot.pause(0.01)
        field.value = "new"
        await pilot.pause(0.25)
        assert calls == ["new"]
        match = CodeSearchResult(tmp_path / "a.py", 1, "new", 0, 3)
        search._show_results("old", [match])
        assert search.query_one(CodeSearchResults).results == []
        search._show_results("new", [match])
        assert search.query_one(CodeSearchResults).results == [match]
        search.action_close_search()
        search._show_results("new", [match])
        assert search.query_one(CodeSearchResults).results == []
        assert search.query_one("#search-status", Static).render().plain == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("use_mouse", [False, True])
async def test_code_search_opens_matching_line_in_existing_preview(
    tmp_path, monkeypatch, use_mouse
):
    path = tmp_path / "source.py"
    path.write_text("\n".join(f"value_{i} = {i}" for i in range(100)))
    monkeypatch.setattr(CodebaseSearch, "_do_search", lambda self, query: None)
    app = SuperQodeApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.press("ctrl+2")
        sidebar = app.query_one(CollapsibleSidebar)
        sidebar.action_show_search()
        await pilot.pause()
        search = sidebar.query_one(CodebaseSearch)
        search.query_one(Input).value = "value_49"
        await pilot.pause(0.2)
        match = CodeSearchResult(path, 50, "value_49 = 49", 0, 8)
        search._show_results("value_49", [match])
        await pilot.pause()
        if use_mouse:
            await pilot.click("#code-results-content", offset=(8, 1))
        else:
            await pilot.press("enter")
        await pilot.pause()
        preview = sidebar.query_one(FilePreview)
        await preview._preview_worker.wait()
        await pilot.pause()
        assert sidebar.current_view == "code"
        assert preview.current_file == path
        assert preview._preview_line == 50
        assert isinstance(app.focused, FilePreviewScroll)
        assert app.focused.scroll_y > 0
        await pilot.press("escape")
        assert sidebar.current_view == "files"


def test_code_search_prunes_ignored_trees_and_supports_cancellation(tmp_path, monkeypatch):
    ignored = tmp_path / "node_modules" / "deep"
    ignored.mkdir(parents=True)
    (ignored / "ignored.py").write_text("needle")
    (tmp_path / "source.py").write_text("needle\n")
    (tmp_path / ".env").write_text("needle\n")
    visited = []
    from superqode import sidebar

    walk = sidebar.os.walk

    def counted(*args, **kwargs):
        for item in walk(*args, **kwargs):
            visited.append(Path(item[0]).name)
            yield item

    monkeypatch.setattr(sidebar.os, "walk", counted)
    assert {result.path.name for result in search_codebase(tmp_path, "needle")} == {
        "source.py",
        ".env",
    }
    assert "node_modules" not in visited and "deep" not in visited
    assert search_codebase(tmp_path, "needle", cancelled=lambda: True) == []
