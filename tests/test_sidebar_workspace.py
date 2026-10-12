"""Read-only workspace navigation, Git fidelity, and bounded previews."""

import asyncio
import json
import subprocess
from pathlib import Path
from threading import Event

import pytest
from textual.widgets import Input, Select, Static

from superqode.app_main import SuperQodeApp
from superqode.app.inputs import SelectionAwareInput
from superqode.app.widgets import ConversationLog
from superqode.sidebar import CollapsibleSidebar, GitChangesPanel, get_git_changes, get_file_diff
from superqode.sidebar import ColorfulDirectoryTree
from superqode.sidebar import GitChange
from superqode.sidebar import detect_language
from superqode.widgets.sidebar_panels import DiffPanel, HarnessPanel
from superqode.widgets.workspace_viewer import (
    PAGE_BYTES,
    PAGE_LINES,
    SourcePage,
    WorkspaceViewer,
    read_source_page,
)


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    from superqode.app import theme_bridge as bridge

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "0")
    monkeypatch.setattr(bridge, "_CONFIG_PATH", tmp_path / "settings.json")
    bridge.apply_theme("superqode")
    for name in (
        "_prewarm_litellm",
        "_start_models_dev_refresh",
        "_start_acp_registry_refresh",
        "_report_catalog_freshness",
        "_run_startup_connect",
    ):
        monkeypatch.setattr(SuperQodeApp, name, lambda self: None)
    yield
    bridge.apply_theme("superqode")


async def settled(viewer, pilot):
    async with asyncio.timeout(5):
        while any(w.is_running for w in viewer.workers if w.node is viewer):
            await pilot.pause(0.02)
    await pilot.pause()


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True).stdout


def repo(root):
    git(root, "init", "-q")
    (root / "alpha.py").write_text("old\n")
    (root / "leading space ü.py").write_text("old\n")
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "base",
    )


def test_git_paths_scopes_renames_untracked_and_no_writes(tmp_path):
    repo(tmp_path)
    (tmp_path / "alpha.py").write_text("new\n")
    git(tmp_path, "mv", "leading space ü.py", "renamed ü.py")
    (tmp_path / "new [file].py").write_text("fresh\n")
    changes = get_git_changes(tmp_path)
    assert {(c.path, c.status, c.staged) for c in changes} == {
        ("alpha.py", "M", False),
        ("renamed ü.py", "R", True),
        ("new [file].py", "?", False),
    }
    index = (tmp_path / ".git/index").read_bytes()
    assert "+new" in get_file_diff(tmp_path, "alpha.py")
    assert "+fresh" in get_file_diff(tmp_path, "new [file].py")
    assert get_file_diff(tmp_path, "new [file].py", staged=True) == ""
    assert "renamed" in get_file_diff(tmp_path, "renamed ü.py", staged=True)
    assert (tmp_path / ".git/index").read_bytes() == index
    git(tmp_path, "add", "alpha.py")
    (tmp_path / "alpha.py").write_text("newer\n")
    entries = [c for c in get_git_changes(tmp_path) if c.path == "alpha.py"]
    assert [c.staged for c in entries] == [True, False]
    assert "+newer" in get_file_diff(tmp_path, "alpha.py")
    assert "+new\n" in get_file_diff(tmp_path, "alpha.py", staged=True)


@pytest.mark.parametrize("text", ["x\n" * 950, "ä" * (PAGE_BYTES + 20)])
def test_source_paging_is_bounded_and_lossless(tmp_path, text):
    path = tmp_path / "large.py"
    path.write_text(text)
    page = read_source_page(path)
    output = page.text
    assert len(page.text.encode()) <= PAGE_BYTES
    assert page.text.count("\n") <= PAGE_LINES
    while page.next_offset is not None:
        page = read_source_page(path, page.next_offset, page.next_line)
        output += page.text
        assert len(page.text.encode()) <= PAGE_BYTES
    assert output == text
    path.write_bytes(b"binary\0file")
    assert "Binary" in read_source_page(path).note


@pytest.mark.parametrize(
    "filename, code, language",
    [
        ("source.py", "return 'hello'", "python"),
        ("app.tsx", "export const App = () => <div>hello</div>", "tsx"),
        ("module.mts", "export const greeting: string = 'hello'", "typescript"),
        ("module.cts", "export const greeting: string = 'hello'", "typescript"),
        ("module.cjs", "const greeting = 'hello'", "javascript"),
        ("Program.cs", 'public class Example { string greeting = "hello"; }', "csharp"),
        ("main.dart", "class Example { String greeting = 'hello'; }", "dart"),
        ("main.zig", 'const greeting = "hello";', "zig"),
        ("build.nix", 'let greeting = "hello"; in greeting', "nixos"),
        ("Dockerfile.dev", "FROM python:3.13\nRUN echo 'hello'", "dockerfile"),
        ("Containerfile", "FROM python:3.13\nRUN echo 'hello'", "dockerfile"),
        ("App.svelte", '<script>const greeting = "hello";</script><h1>Hello</h1>', "html"),
    ],
)
def test_source_filename_detection_produces_syntax_colors(filename, code, language):
    from rich.console import Console
    from superqode.app.constants import THEME
    from superqode.code_theme import SemanticSyntaxTheme, SourceSyntax

    assert detect_language(Path(filename)) == language
    syntax = SourceSyntax(code, detect_language(Path(filename)), theme=SemanticSyntaxTheme())
    segments = list(Console(width=100, color_system="truecolor").render(syntax))
    assert any(
        segment.text.strip()
        and segment.style
        and segment.style.meta.get("sq_fg") == "syntax_keyword"
        and segment.style.color.name == THEME["syntax_keyword"]
        for segment in segments
    )
    assert detect_language(Path("unknown.extension-with-no-lexer")) == "text"


@pytest.mark.asyncio
@pytest.mark.parametrize("width", [80, 120, 180])
async def test_main_viewer_preserves_draft_tree_and_chat(tmp_path, width):
    path = tmp_path / "source.py"
    path.write_text("line = 1\n" * 100)
    app = SuperQodeApp()
    async with app.run_test(size=(width, 36)) as pilot:
        prompt = app.query_one(SelectionAwareInput)
        prompt.load_text("My unsubmitted task")
        prompt.cursor_position = 4
        log = app.query_one(ConversationLog)
        for i in range(80):
            log.add_info(f"message {i}")
        log.lock_viewport()
        log.scroll_to(y=10, animate=False)
        await pilot.pause()
        old_scroll = log.scroll_y
        app.action_sidebar_files()
        sidebar = app.query_one(CollapsibleSidebar)
        tree_node = sidebar.query_one("#file-tree").cursor_node
        app._open_workspace_file(path)
        viewer = app.query_one(WorkspaceViewer)
        await settled(viewer, pilot)
        assert viewer._page.text == path.read_text()
        assert sidebar.current_view == "files"
        assert app.focused.id == "workspace-reader"
        assert viewer.size.width > 45
        assert viewer.query_one("#workspace-copy-path").region.right <= viewer.region.right
        assert prompt.value == "My unsubmitted task" and prompt.cursor_position == 4
        assert app.sidebar_visible == (width >= 100)
        assert sidebar.query_one("#file-tree").cursor_node is tree_node
        app._focus_input_on_ready()
        app._ensure_input_focus()
        assert app.focused.id == "workspace-reader"
        await pilot.press("escape")
        await pilot.pause()
        assert not viewer.has_class("visible")
        assert app.query_one(ConversationLog) is log and log.scroll_y == old_scroll
        assert prompt.value == "My unsubmitted task" and prompt.cursor_position == 4
        if app.sidebar_visible:
            await pilot.press("escape")
        assert app.focused is prompt


@pytest.mark.asyncio
async def test_split_narrow_drawer_and_file_reading_state(tmp_path):
    path = tmp_path / "source.py"
    path.write_text("print(1)\n" * 100)
    other = tmp_path / "other.py"
    other.write_text("pass\n")
    app = SuperQodeApp()
    async with app.run_test(size=(180, 40)) as pilot:
        app.action_sidebar_files()
        app._open_workspace_file(path)
        viewer = app.query_one(WorkspaceViewer)
        await settled(viewer, pilot)
        await pilot.click("#workspace-split")
        assert app.query_one("#workspace-output").has_class("split")
        reader = viewer.query_one("#workspace-reader")
        reader.scroll_to(y=12, animate=False)
        await pilot.pause()
        viewer.open_file(other)
        await settled(viewer, pilot)
        viewer.open_file(path)
        await settled(viewer, pilot)
        assert reader.scroll_y == 12
        await pilot.resize_terminal(80, 30)
        await pilot.pause()
        assert not app.query_one("#workspace-output").has_class("split")
        assert app.query_one("#main-grid").has_class("workspace-drawer")
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert viewer.size.width >= 78
        assert app.focused is reader


@pytest.mark.asyncio
async def test_file_find_line_pages_and_read_only(tmp_path):
    path = tmp_path / "source.py"
    text = "\n".join(f"line_{i} = {i}" for i in range(1000)) + "\n"
    path.write_text(text)
    app = SuperQodeApp()
    async with app.run_test(size=(120, 36)) as pilot:
        app._open_workspace_file(path)
        viewer = app.query_one(WorkspaceViewer)
        await settled(viewer, pilot)
        prompt = app.query_one(SelectionAwareInput)
        prompt.load_text("untouched draft")
        await pilot.press("]")
        await settled(viewer, pilot)
        assert viewer._page.line == 401
        await pilot.press("[")
        await settled(viewer, pilot)
        assert viewer._page.line == 1
        await pilot.press("ctrl+g")
        assert app.focused.id == "workspace-query"
        await pilot.press("8", "0", "0", "enter")
        await settled(viewer, pilot)
        assert viewer._page.line == 800
        await pilot.press("ctrl+f")
        assert app.focused.id == "workspace-query"
        app.focused.value = "line_900"
        await pilot.press("enter")
        await settled(viewer, pilot)
        assert viewer._page.line == 901
        await pilot.press("e", "ctrl+s")
        assert len(app.screen_stack) == 1
        assert path.read_text() == text and prompt.value == "untouched draft"


@pytest.mark.asyncio
async def test_stale_load_cannot_replace_selected_file_or_reopen_chat(tmp_path, monkeypatch):
    from superqode.widgets import workspace_viewer as module

    old, new = tmp_path / "old.py", tmp_path / "new.py"
    old.write_text("old\n")
    new.write_text("new\n")
    entered, release = Event(), Event()
    read = module.read_source_page

    def delayed(path, *args):
        if path == old:
            entered.set()
            release.wait(3)
        return read(path, *args)

    monkeypatch.setattr(module, "read_source_page", delayed)
    app = SuperQodeApp()
    async with app.run_test(size=(120, 36)) as pilot:
        app._open_workspace_file(old)
        assert await asyncio.to_thread(entered.wait, 3)
        app._open_workspace_file(new)
        viewer = app.query_one(WorkspaceViewer)
        await settled(viewer, pilot)
        assert viewer._page.text == "new\n"
        release.set()
        await pilot.pause()
        assert viewer.path == new and viewer._page.text == "new\n"
        await pilot.press("escape")
        viewer._show(viewer._generation - 1, SourcePage("late"))
        assert not viewer.has_class("visible") and viewer._page.text == "new\n"


@pytest.mark.asyncio
async def test_sidebar_git_mouse_rows_task_keyboard_and_section_selector(tmp_path):
    repo(tmp_path)
    (tmp_path / "alpha.py").write_text("staged\n")
    git(tmp_path, "add", "alpha.py")
    (tmp_path / "leading space ü.py").write_text("unstaged\n")
    app = SuperQodeApp()
    async with app.run_test(size=(120, 36)) as pilot:
        app.action_sidebar_files()
        sidebar = app.query_one(CollapsibleSidebar)
        sidebar.current_view = "changes"
        changes = sidebar.query_one(GitChangesPanel)
        await changes._refresh_worker.wait()
        await pilot.pause()
        # Group headers and blank separators must not select a different file.
        await pilot.click("#changes-content", offset=(8, 4))
        viewer = app.query_one(WorkspaceViewer)
        await settled(viewer, pilot)
        assert viewer.path == tmp_path / "leading space ü.py"
        assert viewer.baseline == "working" and "+unstaged" in viewer._page.text
        assert len(app.query("#diff-view")) == 1
        await pilot.press("escape")
        assert app.focused is changes
        await pilot.press("up", "enter")
        await settled(viewer, pilot)
        assert viewer.path == tmp_path / "alpha.py" and viewer.baseline == "staged"
        await pilot.press("escape")
        panel = sidebar.query_one(DiffPanel)
        panel.add_file("alpha.py", diff_text="@@ -1 +1 @@\n-old\n+task\n")
        selector = sidebar.query_one("#sidebar-section", Select)
        selector.value = "diff"
        await pilot.pause()
        sidebar.focus_current_view()
        await pilot.press("down", "enter")
        await settled(viewer, pilot)
        assert viewer.baseline == "task" and "+task" in viewer._page.text


@pytest.mark.asyncio
async def test_hidden_harness_is_lazy_and_preview_caches_are_bounded(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(HarnessPanel, "_render_summary", lambda self: calls.append(1) or "Harness")
    app = SuperQodeApp()
    async with app.run_test(size=(120, 36)) as pilot:
        assert not calls
        app._refresh_harness_panel()
        assert not calls
        app.action_sidebar_harness()
        await pilot.pause()
        assert calls
        viewer = app.query_one(WorkspaceViewer)
        for i in range(10):
            path = tmp_path / f"file_{i}.py"
            path.write_text(f"value = {i}\n")
            app._open_workspace_file(path)
            await settled(viewer, pilot)
            await pilot.click("#workspace-pin")
        assert len(viewer._cache) <= 4 and len(viewer._states) <= 8 and len(viewer._pinned) <= 4


@pytest.mark.asyncio
@pytest.mark.parametrize("vim", [False, True])
async def test_viewer_vim_focus_and_connection_return(tmp_path, monkeypatch, vim):
    monkeypatch.setenv("SUPERQODE_VIM_MODE", "1" if vim else "0")
    path = tmp_path / "source.py"
    path.write_text("pass\n" * 150)
    app = SuperQodeApp()
    async with app.run_test(size=(120, 36)) as pilot:
        app.action_sidebar_files()
        app._open_workspace_file(path)
        viewer = app.query_one(WorkspaceViewer)
        await settled(viewer, pilot)
        reader = viewer.query_one("#workspace-reader")
        if vim:
            app._set_vim_state("normal")
            await pilot.press("j", "j")
            assert reader.scroll_y > 0
            await pilot.press("h")
            assert app.focused.id == "file-tree"
            await pilot.press("l")
            assert app.focused is reader
            await pilot.press("ctrl+f")
            assert app.focused.id == "workspace-query"
            await pilot.press("escape")
            assert app.focused is reader and viewer.has_class("visible")
        prompt = app.query_one(SelectionAwareInput)
        prompt.focus()
        prompt.value = ":connect"
        await pilot.press("enter")
        await pilot.pause()
        assert not viewer.has_class("visible")
        assert app._in_selection_mode()
        assert app.sidebar_visible  # explicitly opened before :connect


@pytest.mark.asyncio
async def test_reader_theme_and_toolbar_remain_usable(tmp_path, monkeypatch):
    from rich.syntax import Syntax
    from textual.geometry import Region
    from superqode import design_system as ds
    from superqode.app.constants import THEME
    from superqode.app import theme_bridge as bridge
    from superqode.theming import load_theme_file, contrast

    # The tool environment disables colors. Check the terminal's actual
    # colored strips, rather than only checking the Syntax object's content.
    monkeypatch.delenv("NO_COLOR", raising=False)
    custom = tmp_path / "theme.json"
    custom.write_text(
        json.dumps(
            {
                "version": 1,
                "name": "workspace-custom",
                "appearance": "dark",
                "colors": {"code_bg": "#131722"},
                "tokens": {
                    "syntax_keyword": "#ff81b7",
                    "syntax_string": "#98e89c",
                    "syntax_number": "#ffd580",
                },
            }
        )
    )
    custom_theme = load_theme_file(custom)
    monkeypatch.setitem(ds.THEMES, custom_theme.name, custom_theme)

    path = tmp_path / "source.py"
    path.write_text(
        '# first comment\ndef greet(name):\n    return "hello" + str(42)\n' + "pass\n" * 100
    )
    app = SuperQodeApp()
    async with app.run_test(size=(100, 30)) as pilot:
        app.action_sidebar_files()
        await pilot.pause()
        tree = app.query_one(ColorfulDirectoryTree)
        node = next(node for node in tree.root.children if node.data.path == path)
        tree.move_cursor(node)
        app._open_workspace_file(path)
        viewer = app.query_one(WorkspaceViewer)
        await settled(viewer, pilot)
        reader = viewer.query_one("#workspace-reader")
        reader.scroll_to(y=20, animate=False)
        await pilot.pause()
        for name in ("light", "dracula", "workspace-custom", "superqode"):
            assert bridge.apply_theme(name)
            app._refresh_theme_view()
            await pilot.pause()
            source = viewer.query_one("#workspace-source", Static)
            rendered = source.content
            assert isinstance(rendered, Syntax) and rendered.code == path.read_text()
            assert source.styles.background.hex.lower() == THEME["code_bg"]
            assert reader.styles.background.hex.lower() == THEME["code_bg"]
            assert reader.scroll_y == 20
            assert app.focused is reader
            assert viewer.query_one("#workspace-copy-path").region.right <= viewer.region.right
            segments = [
                segment
                for strip in source.render_lines(Region(0, 0, source.size.width, 4))
                for segment in strip
                if segment.text.strip() and segment.style
            ]
            for role in (
                "syntax_keyword",
                "syntax_function",
                "syntax_string",
                "syntax_number",
                "syntax_comment",
            ):
                assert any(
                    segment.style.meta.get("sq_fg") == role
                    and segment.style.color.name == THEME[role]
                    and segment.style.bgcolor.name == THEME["code_bg"]
                    for segment in segments
                ), (name, role)
            number = next(segment for segment in segments if segment.text.strip() == "1")
            assert number.style.color.name == THEME["muted"]
            assert contrast(number.style.color.name, THEME["code_bg"]) >= 4.5
            assert tree.cursor_node is node
            rows = [
                segment
                for strip in tree.render_lines(tree.region.reset_offset)
                for segment in strip
            ]
            filename = next(segment for segment in rows if segment.text == path.name)
            assert filename.style.color.name == THEME["selected_text"]
            assert filename.style.bgcolor.name == THEME["selected_bg"]
        await pilot.click("#workspace-find")
        query = viewer.query_one("#workspace-query", Input)
        assert app.focused is query
        query.value = "first"
        await pilot.press("enter")
        await settled(viewer, pilot)
        assert viewer._page.line == 1  # searching includes the first line
        await pilot.click("#workspace-close")
        await pilot.pause()
        assert not viewer.has_class("visible")


@pytest.mark.asyncio
async def test_section_menu_keyboard_and_pinned_selector(tmp_path, monkeypatch):
    monkeypatch.setattr(HarnessPanel, "_render_summary", lambda self: "Harness")
    app = SuperQodeApp()
    async with app.run_test(size=(100, 30)) as pilot:
        app.action_sidebar_files()
        sidebar = app.query_one(CollapsibleSidebar)
        selector = sidebar.query_one("#sidebar-section", Select)
        selector.focus()
        await pilot.press("enter", "down", "enter")
        await pilot.pause()
        assert sidebar.current_view == "changes"
        for section in ("history", "context", "agent", "harness", "search", "files"):
            selector.value = section
            await pilot.pause()
            assert sidebar.current_view == section
            assert sidebar.query_one(f"#{section}-view").has_class("visible")
            assert selector.region.right <= sidebar.region.right
        viewer = app.query_one(WorkspaceViewer)
        paths = [tmp_path / "first.py", tmp_path / "second.py"]
        for path in paths:
            path.write_text(path.name + "\n")
            app._open_workspace_file(path)
            await settled(viewer, pilot)
            await pilot.click("#workspace-pin")
        files = viewer.query_one("#workspace-files", Select)
        files.focus()
        await pilot.press("enter", "up", "enter")
        await settled(viewer, pilot)
        assert viewer.path == paths[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("mouse", [False, True])
async def test_tree_file_selection_opens_main_view(tmp_path, mouse):
    path = tmp_path / "source.py"
    path.write_text("from_tree = True\n")
    app = SuperQodeApp()
    async with app.run_test(size=(120, 36)) as pilot:
        app.action_sidebar_files()
        tree = app.query_one(ColorfulDirectoryTree)
        async with asyncio.timeout(5):
            while not any(child.data.path == path for child in tree.root.children):
                await pilot.pause(0.02)
        node = next(child for child in tree.root.children if child.data.path == path)
        tree.move_cursor(node)
        tree.focus()
        await pilot.pause()
        if mouse:
            await pilot.click("#file-tree", offset=(8, tree.cursor_line))
        else:
            await pilot.press("enter")
        viewer = app.query_one(WorkspaceViewer)
        await settled(viewer, pilot)
        assert viewer.path == path and "from_tree" in viewer._page.text
        assert app.query_one(CollapsibleSidebar).current_view == "files"


@pytest.mark.asyncio
async def test_long_change_lists_follow_keyboard_selection():
    app = SuperQodeApp()
    async with app.run_test(size=(100, 26)) as pilot:
        app.action_sidebar_files()
        sidebar = app.query_one(CollapsibleSidebar)
        sidebar.current_view = "changes"
        changes = sidebar.query_one(GitChangesPanel)
        await changes._refresh_worker.wait()
        changes._update_changes([GitChange(f"long/path/to/file_{i}.py", "M") for i in range(40)])
        changes.focus()
        await pilot.press(*(["down"] * 30))
        await pilot.pause()
        assert changes.selected_index == 30
        assert changes.query_one("#changes-list").scroll_y > 0
        sidebar.current_view = "diff"
        panel = sidebar.query_one(DiffPanel)
        for i in range(40):
            panel.add_file(f"file_{i}.py")
        sidebar.focus_current_view()
        await pilot.press(*(["down"] * 31))
        await pilot.pause()
        assert panel._selected_index == 30
        assert panel.query_one("#diff-files").scroll_y > 0
