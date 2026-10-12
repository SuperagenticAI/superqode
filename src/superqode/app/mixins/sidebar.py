"""Sidebar panel updates, resize handling, and sidebar keybinding actions for SuperQodeApp."""

from __future__ import annotations
from pathlib import Path
from textual.widgets import Button
from superqode.sidebar import (
    CollapsibleSidebar,
)
from superqode.widgets.workspace_viewer import WorkspaceViewer

# --- helpers extracted from app_main (A1) ---


class SidebarMixin:
    """Sidebar panels, resize, and Ctrl+1..6 / toggle sidebar actions."""

    def _workspace_has_focus(self):
        if not self.screen_stack:
            return False
        focused = self.focused
        return focused is not None and any(
            isinstance(node, WorkspaceViewer) for node in focused.ancestors_with_self
        )

    def _open_workspace_file(self, path, *, line=1, mode="contents", baseline="working"):
        viewer = self.query_one(WorkspaceViewer)
        viewer.open_file(Path(path), line=line, mode=mode, baseline=baseline)
        if self.size.width < 100 and self.sidebar_visible:
            self.action_toggle_sidebar()
        self._layout_workspace_viewer()
        viewer.call_after_refresh(viewer.focus_reader)

    def _layout_workspace_viewer(self, terminal_width=None):
        viewer = self.query_one(WorkspaceViewer)
        width = terminal_width or self.size.width
        visible = viewer.has_class("visible")
        output = self.query_one("#workspace-output")
        output.set_class(visible, "reviewing")
        self.query_one("#content").set_class(visible, "reviewing-file")
        prompt_visible = visible and getattr(self, "_workspace_prompt_visible", False)
        self.query_one("#content").set_class(prompt_visible, "with-workspace-prompt")
        if viewer.is_mounted:
            button = viewer.query_one("#workspace-prompt", Button)
            button.label = "Hide prompt" if prompt_visible else "Prompt"
            button.set_class(prompt_visible, "active")
        output.set_class(
            visible and width >= 160 and getattr(self, "_workspace_split", False), "split"
        )
        self.query_one("#main-grid").set_class(
            visible and self.sidebar_visible and width < 100, "workspace-drawer"
        )
        preferred = getattr(self, "_preferred_sidebar_width", 34)
        self._set_sidebar_width(preferred, width)
        self.query_one("#status-bar").sidebar_open = self.sidebar_visible

    def _show_workspace_chat(self):
        """Return from source inspection without changing the task draft."""
        if not self.is_running:
            return
        viewer = self.query_one(WorkspaceViewer)
        if viewer.has_class("visible"):
            viewer.suspend()
        self._layout_workspace_viewer()

    def on_workspace_viewer_chat_requested(self, event):
        event.stop()
        self._show_workspace_chat()
        sidebar = self.query_one(CollapsibleSidebar)
        if self.sidebar_visible:
            sidebar.call_after_refresh(sidebar.focus_current_view)
        else:
            self.call_after_refresh(self.query_one("#prompt-input").focus)

    def _show_workspace_prompt(self):
        """Expose the composer while retaining the current source/diff view."""
        self._workspace_prompt_visible = True
        if self.query_one("#main-grid").has_class("workspace-drawer"):
            self.action_toggle_sidebar(focus=False)
        self._layout_workspace_viewer()
        prompt = self.query_one("#prompt-input")
        prompt.call_after_refresh(prompt.focus)

    def action_toggle_workspace_prompt(self):
        if not self.check_action("toggle_workspace_prompt", ()):
            return
        visible = self.query_one("#main-grid").has_class("workspace-drawer") or not getattr(
            self, "_workspace_prompt_visible", False
        )
        if self._vim_enabled():
            self._restore_vim_draft(cancel_line=True)
            self._set_vim_state("insert" if visible else "normal")
        if visible:
            self._show_workspace_prompt()
        else:
            self._workspace_prompt_visible = False
            self._layout_workspace_viewer()
            viewer = self.query_one(WorkspaceViewer)
            viewer.call_after_refresh(viewer.focus_reader)

    def on_workspace_viewer_prompt_requested(self, event):
        event.stop()
        self.action_toggle_workspace_prompt()

    def on_workspace_viewer_split_requested(self, event):
        event.stop()
        self._workspace_split = not getattr(self, "_workspace_split", False)
        self._layout_workspace_viewer()
        if self._workspace_split and self.size.width < 160:
            self.notify("Split enabled for terminals at least 160 columns wide")

    def on_git_changes_panel_file_selected(self, event):
        event.stop()
        self._open_workspace_file(
            self.query_one(CollapsibleSidebar).root_path / event.path,
            mode="changes",
            baseline="staged" if event.staged else "working",
        )

    def on_diff_panel_file_selected(self, event):
        event.stop()
        self._open_workspace_file(
            self.query_one(CollapsibleSidebar).root_path / event.path,
            mode="changes",
            baseline="task",
        )

    def on_collapsible_sidebar_dismiss(self, event: CollapsibleSidebar.Dismiss) -> None:
        event.stop()
        if self.sidebar_visible:
            self.action_toggle_sidebar()

    def _init_sidebar_resize(self):
        """Initialize sidebar resize handling."""
        try:
            from superqode.app.project_ui_state import get_sidebar_width

            sidebar = self.query_one("#sidebar", CollapsibleSidebar)
            preferred = get_sidebar_width(default=34)
            self._preferred_sidebar_width = preferred
            self._set_sidebar_width(preferred)
        except Exception:
            pass

    def _set_sidebar_width(
        self,
        requested: int,
        terminal_width: int | None = None,
        *,
        persist: bool = False,
    ) -> None:
        """Keep space for the prompt and transcript when the terminal narrows."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        maximum = max(30, min(150, (terminal_width or self.size.width) - 41))
        width = max(30, min(maximum, requested))
        if self.query_one("#main-grid").has_class("workspace-drawer"):
            width = terminal_width or self.size.width
        sidebar.styles.width = width
        sidebar._width = width
        if persist:
            self._persist_sidebar_width(width)

    def _persist_sidebar_width(self, width: int | None = None) -> None:
        """Persist an intentional resize, never a temporary terminal clamp."""
        try:
            from superqode.app.project_ui_state import set_sidebar_width

            if width is None:
                sidebar = self.query_one("#sidebar", CollapsibleSidebar)
                width = getattr(sidebar, "_width", 34)
            self._preferred_sidebar_width = width
            set_sidebar_width(width)
        except Exception:
            pass

    def _update_sidebar_agent_panel(self, **kwargs):
        """Update the agent panel in sidebar with current agent info."""
        try:
            sidebar = self.query_one("#sidebar", CollapsibleSidebar)
            agent_panel = sidebar.get_agent_panel()
            if agent_panel:
                agent_panel.update_agent(**kwargs)
        except Exception:
            pass

    def _update_sidebar_context_panel(self, path: str, token_count: int = 0):
        """Add a file to the context panel."""
        try:
            sidebar = self.query_one("#sidebar", CollapsibleSidebar)
            context_panel = sidebar.get_context_panel()
            if context_panel:
                context_panel.add_file(path, token_count)
        except Exception:
            pass

    def _update_sidebar_history_panel(self, role: str, content: str, agent_name: str = ""):
        """Add a message to the history panel."""
        try:
            sidebar = self.query_one("#sidebar", CollapsibleSidebar)
            history_panel = sidebar.get_history_panel()
            if history_panel:
                history_panel.add_message(role, content, agent_name)
        except Exception:
            pass

    def _update_sidebar_diff_panel(
        self,
        path: str,
        status: str = "modified",
        additions: int = 0,
        deletions: int = 0,
        diff_text: str = "",
    ):
        """Add a file to the diff panel."""
        try:
            sidebar = self.query_one("#sidebar", CollapsibleSidebar)
            diff_panel = sidebar.get_diff_panel()
            if diff_panel:
                diff_panel.add_file(path, status, additions, deletions, diff_text)
        except Exception:
            pass

    def _run_sidebar_terminal_command(self, cmd: str, output: str = "", success: bool = True):
        """Run a command in the sidebar terminal panel."""
        try:
            sidebar = self.query_one("#sidebar", CollapsibleSidebar)
            terminal_panel = sidebar.get_terminal_panel()
            if terminal_panel:
                terminal_panel.add_command(cmd, output, success)
        except Exception:
            pass

    def _navigate_to_sidebar_changes(self, files_modified: list):
        """Record session edits and refresh Changes without stealing the current view."""
        try:
            # Find the sidebar
            sidebar = self.query_one("CollapsibleSidebar", raise_on_error=False)
            if not sidebar:
                return

            sidebar.mark_session_modified(files_modified)

            # Find the GitChangesPanel and refresh it
            changes_panel = sidebar.query_one("GitChangesPanel", raise_on_error=False)
            if changes_panel:
                # Refresh to get latest changes from git (this will update UI after refresh completes)
                changes_panel.refresh_changes()

                # After refresh completes, highlight the files
                # Use a small delay to ensure git changes are loaded
                def highlight_after_refresh():
                    try:
                        if files_modified:
                            changes_panel.highlight_files(files_modified)
                    except Exception:
                        pass

                # Wait a bit for refresh to complete, then highlight
                self.set_timer(0.3, highlight_after_refresh)
        except Exception:
            # Silently fail - sidebar might not be available
            pass

    def _record_sidebar_session_files(self, files: list[str]) -> None:
        """Update live session markers without navigating the sidebar."""
        try:
            self.query_one("#sidebar", CollapsibleSidebar).mark_session_modified(files)
            viewer = self.query_one(WorkspaceViewer)
            if viewer.has_class("visible") and viewer.relative(viewer.path) in files:
                viewer.reload()
        except Exception:
            pass

    def _clear_sidebar_session_files(self) -> None:
        try:
            self.query_one("#sidebar", CollapsibleSidebar).clear_session_modified()
        except Exception:
            pass

    def action_toggle_sidebar(self, *, focus=True):
        self.sidebar_visible = not self.sidebar_visible
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        divider = self.query_one("#sidebar-divider")
        if self.sidebar_visible:
            sidebar.add_class("visible")
            divider.remove_class("-hidden")
            if focus:
                sidebar.focus_current_view()
        else:
            sidebar.remove_class("visible")
            divider.add_class("-hidden")
            # Return focus to input when sidebar is closed
            viewer = self.query_one(WorkspaceViewer)
            if focus and viewer.has_class("visible"):
                viewer.call_after_refresh(viewer.focus_reader)
            elif focus:
                self.query_one("#prompt-input").focus()
                self.set_timer(0.1, self._ensure_input_focus)
        self._layout_workspace_viewer()

    def action_shrink_sidebar(self):
        """Shrink sidebar width."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        current_width = getattr(sidebar, "_width", 34)
        self._set_sidebar_width(current_width - 10, persist=True)

    def action_expand_sidebar(self):
        """Expand sidebar width."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        current_width = getattr(sidebar, "_width", 34)
        self._set_sidebar_width(current_width + 10, persist=True)

    def action_sidebar_files(self):
        """Switch sidebar to files view."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        sidebar.current_view = "files"
        if not self.sidebar_visible:
            self.action_toggle_sidebar()
        sidebar.focus_tree()

    def action_sidebar_harness(self):
        """Switch sidebar to harness overview."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        sidebar.current_view = "harness"
        self._refresh_harness_panel()
        if not self.sidebar_visible:
            self.action_toggle_sidebar()
        sidebar.focus_current_view()

    def action_sidebar_agent(self):
        """Switch sidebar to agent panel."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        sidebar.current_view = "agent"
        if not self.sidebar_visible:
            self.action_toggle_sidebar()
        sidebar.focus_current_view()

    def action_sidebar_context(self):
        """Switch sidebar to context panel."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        sidebar.current_view = "context"
        if not self.sidebar_visible:
            self.action_toggle_sidebar()
        sidebar.focus_current_view()

    def action_sidebar_terminal(self):
        """Switch sidebar to terminal panel."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        sidebar.current_view = "terminal"
        if not self.sidebar_visible:
            self.action_toggle_sidebar()

    def action_sidebar_diff(self):
        """Switch sidebar to diff panel."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        sidebar.current_view = "diff"
        if not self.sidebar_visible:
            self.action_toggle_sidebar()
        sidebar.focus_current_view()

    def action_sidebar_history(self):
        """Switch sidebar to history panel."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        sidebar.current_view = "history"
        if not self.sidebar_visible:
            self.action_toggle_sidebar()
        sidebar.focus_current_view()

    def on_collapsible_sidebar_file_opened(self, event: CollapsibleSidebar.FileOpened) -> None:
        self.on_sidebar_file_opened(event)

    def on_sidebar_file_opened(self, event: CollapsibleSidebar.FileOpened) -> None:
        """Handle file opened from sidebar - show in conversation."""
        event.stop()
        self._open_workspace_file(event.path)
