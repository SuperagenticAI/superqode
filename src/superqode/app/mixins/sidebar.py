"""Sidebar panel updates, resize handling, and sidebar keybinding actions for SuperQodeApp."""

from __future__ import annotations
from textual import on
from superqode.app.widgets import (
    ConversationLog,
)
from superqode.sidebar import (
    CollapsibleSidebar,
)

# --- helpers extracted from app_main (A1) ---


class SidebarMixin:
    """Sidebar panels, resize, and Ctrl+1..6 / toggle sidebar actions."""

    def _init_sidebar_resize(self):
        """Initialize sidebar resize handling."""
        try:
            sidebar = self.query_one("#sidebar", CollapsibleSidebar)
            sidebar._width = 80  # Initial width
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
        """Navigate sidebar to Changes tab and highlight modified files."""
        try:
            # Find the sidebar
            sidebar = self.query_one("CollapsibleSidebar", raise_on_error=False)
            if not sidebar:
                return

            # Find the tabs widget
            tabs = sidebar.query_one("SidebarTabs", raise_on_error=False)
            if tabs:
                # Switch to changes tab
                tabs.active_tab = "changes"
                tabs.post_message(tabs.TabChanged("changes"))

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

    def action_toggle_sidebar(self):
        self.sidebar_visible = not self.sidebar_visible
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        divider = self.query_one("#sidebar-divider")
        if self.sidebar_visible:
            sidebar.add_class("visible")
            divider.remove_class("-hidden")
            sidebar.focus_tree()
        else:
            sidebar.remove_class("visible")
            divider.add_class("-hidden")
            # Return focus to input when sidebar is closed
            self.set_timer(0.1, self._ensure_input_focus)

    def action_shrink_sidebar(self):
        """Shrink sidebar width."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        current_width = getattr(sidebar, "_width", 80)
        new_width = max(30, current_width - 10)
        sidebar.styles.width = new_width
        sidebar._width = new_width

    def action_expand_sidebar(self):
        """Expand sidebar width."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        current_width = getattr(sidebar, "_width", 80)
        new_width = min(150, current_width + 10)
        sidebar.styles.width = new_width
        sidebar._width = new_width

    def action_sidebar_files(self):
        """Switch sidebar to files view."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        sidebar.current_view = "files"
        if not self.sidebar_visible:
            self.action_toggle_sidebar()

    def action_sidebar_harness(self):
        """Switch sidebar to harness overview."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        sidebar.current_view = "harness"
        self._refresh_harness_panel()
        if not self.sidebar_visible:
            self.action_toggle_sidebar()

    def action_sidebar_agent(self):
        """Switch sidebar to agent panel."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        sidebar.current_view = "agent"
        if not self.sidebar_visible:
            self.action_toggle_sidebar()

    def action_sidebar_context(self):
        """Switch sidebar to context panel."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        sidebar.current_view = "context"
        if not self.sidebar_visible:
            self.action_toggle_sidebar()

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

    def action_sidebar_history(self):
        """Switch sidebar to history panel."""
        sidebar = self.query_one("#sidebar", CollapsibleSidebar)
        sidebar.current_view = "history"
        if not self.sidebar_visible:
            self.action_toggle_sidebar()

    @on(CollapsibleSidebar.FileOpened)
    def on_sidebar_file_opened(self, event: CollapsibleSidebar.FileOpened) -> None:
        """Handle file opened from sidebar - show in conversation."""
        event.stop()
        log = self.query_one("#log", ConversationLog)
        self._view_file(str(event.path), log)
