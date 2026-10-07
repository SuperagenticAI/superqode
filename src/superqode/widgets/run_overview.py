"""Live run, approval and delivery inspector, with a persistent navigation strip."""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, Static, TextArea
from textual.widgets.option_list import Option

from superqode.app.constants import THEME
from superqode.app.supervision import SupervisionSnapshot
from .panel_shortcuts import PanelShortcutMixin, PanelShortcuts


class SupervisionBar(Horizontal):
    DEFAULT_CSS = """
    SupervisionBar { height: 1; padding: 0 1; }
    SupervisionBar Button { height: 1; min-width: 1; width: auto; border: none; padding: 0 1; }
    """

    def compose(self) -> ComposeResult:
        yield Button("◆ Runs", id="supervision-runs")
        yield Button("Approvals: 0", id="supervision-approvals")
        yield Button("Delivery", id="supervision-delivery")
        yield Button("Queue: 0", id="supervision-queue")

    def refresh_theme_colors(self):
        self.styles.background = THEME["surface2"]
        for control in self.query(Button):
            control.styles.background = THEME["surface2"]
            control.styles.color = THEME["muted"]

    def update_counts(self, runs: int, approvals: int, queued: int) -> None:
        self.query_one("#supervision-runs", Button).label = f"◆ Runs: {runs}"
        button = self.query_one("#supervision-approvals", Button)
        button.label = f"Approvals: {approvals}"
        button.styles.color = THEME["warning"] if approvals else THEME["muted"]
        self.query_one("#supervision-queue", Button).label = f"Queue: {queued}"
        self.styles.background = THEME["surface2"]
        for control in self.query(Button):
            control.styles.background = THEME["surface2"]
        self.query_one("#supervision-runs", Button).styles.color = THEME["purple"]


class RunOverviewScreen(PanelShortcutMixin, ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "close", "Back", priority=True),
        Binding("ctrl+o", "close", "Back", priority=True),
        Binding("r", "reload", "Refresh"),
    ]
    CSS = """
    RunOverviewScreen { align: center middle; }
    #run-overview { width: 96%; height: 94%; padding: 0 1; border: round $primary; }
    #run-title { height: 1; text-style: bold; }
    #run-tabs { height: 1; }
    #run-tabs Button { height: 1; width: 1fr; min-width: 1; border: none; }
    #run-body { height: 1fr; }
    #run-list { width: 34; height: 1fr; }
    #run-detail { width: 1fr; height: 1fr; }
    #run-notice { height: 2; }
    #run-actions { height: 3; }
    #run-actions Button { width: 1fr; min-width: 8; }
    """

    def __init__(self, loader, on_action, *, section="runs", reference=""):
        super().__init__()
        self.loader = loader
        self.on_action = on_action
        self.section = section
        self.reference = reference
        self.snapshot = SupervisionSnapshot()
        self.rows = ()
        self._loading = False
        self._acting = False
        self._signature = None
        self._detail_identity = None
        self._overview_closed = False

    def _available(self):
        return self.is_mounted and not self._overview_closed and self in self.app.screen_stack

    def compose(self) -> ComposeResult:
        with Vertical(id="run-overview"):
            yield Static("SuperQode · Run Overview", id="run-title")
            with Horizontal(id="run-tabs"):
                for name in ("runs", "approvals", "delivery"):
                    yield Button(name.capitalize(), id=f"run-tab-{name}")
            with Horizontal(id="run-body"):
                yield OptionList(id="run-list")
                yield TextArea("Loading observed state…", read_only=True, id="run-detail")
            yield Static("", id="run-notice")
            with Horizontal(id="run-actions"):
                yield Button("Open", id="run-open", disabled=True)
                yield Button("Approve once", id="run-approve", disabled=True)
                yield Button("Reject", id="run-reject", disabled=True)
                yield Button("Refresh", id="run-refresh")
                yield Button("Back", id="run-back")
            yield PanelShortcuts(
                {
                    "run-list": "↑↓ Select · Enter Inspect · Tab Actions · Esc Back",
                    "run-detail": "↑↓ Scroll · Tab Actions · Esc Back",
                },
                "Tab Next control · Esc Back",
            )

    def on_mount(self):
        self._adapt_layout()
        self.run_worker(self.reload())
        self.set_interval(2, self.reload)
        self.query_one("#run-list", OptionList).focus()

    def on_resize(self):
        if self._available():
            self._adapt_layout()

    def refresh_theme_colors(self):
        self._adapt_layout()
        self._render_entries()

    def _adapt_layout(self):
        narrow = self.size.width < 100
        self.query_one("#run-body").styles.layout = "vertical" if narrow else "horizontal"
        listing = self.query_one("#run-list", OptionList)
        listing.styles.width = "1fr" if narrow else 34
        listing.styles.height = 4 if narrow else "1fr"
        self.query_one("#run-overview").styles.background = THEME["surface2"]
        self.query_one("#run-overview").styles.border = ("round", THEME["purple"])
        self.query_one("#run-title").styles.color = THEME["magenta"]
        self.query_one("#run-notice").styles.color = THEME["muted"]
        for control in self.query(Button):
            control.styles.background = THEME["surface2"]
            control.styles.color = THEME["text"]
        self.query_one("#run-approve").styles.color = THEME["success"]
        self.query_one("#run-reject").styles.color = THEME["error"]

    async def reload(self):
        if self._loading or not self._available():
            return
        self._loading = True
        try:
            snapshot = await self.loader()
            if not self._available():
                return
            self.snapshot = snapshot
            self._render_entries()
            if not self._acting:
                self.query_one("#run-notice", Static).update(Text(snapshot.notice))
        except Exception as exc:
            if self._available():
                self.query_one("#run-notice", Static).update(Text(f"Could not refresh: {exc}"))
        finally:
            self._loading = False

    def selected(self):
        index = self.query_one("#run-list", OptionList).highlighted
        return self.rows[index] if index is not None and 0 <= index < len(self.rows) else None

    def _render_entries(self):
        previous = self.selected()
        selected_id = previous.id if previous else ""
        rows = self.snapshot.entries(self.section)
        if self.reference and self.section == "delivery":
            rows = tuple(row for row in rows if row.target == self.reference)
        self.rows = rows
        signature = (self.section, tuple((row.id, row.label, row.state) for row in rows))
        listing = self.query_one("#run-list", OptionList)
        if signature != self._signature:
            self._signature = signature
            listing.clear_options()
            listing.add_options(
                Option(
                    Text(f"{row.label}\n{row.state}", no_wrap=True, overflow="ellipsis"), id=row.id
                )
                for row in rows
            )
            listing.highlighted = next(
                (i for i, row in enumerate(rows) if row.id == selected_id), 0 if rows else None
            )
        for name in ("runs", "approvals", "delivery"):
            button = self.query_one(f"#run-tab-{name}", Button)
            button.label = f"{name.capitalize()} ({len(self.snapshot.entries(name))})"
            button.styles.color = THEME["purple"] if name == self.section else THEME["muted"]
        self._show_selected()

    def _show_selected(self):
        row = self.selected()
        detail = (
            row.detail
            if row
            else {
                "runs": "No observed runs. Connect a harness or create a WorkOrder.",
                "approvals": "No pending approval requests.",
                "delivery": "No delivery evidence yet. Completed task reviews and project WorkOrders appear here.",
            }[self.section]
        )
        identity = (row.id if row else "", detail)
        if identity != self._detail_identity:
            viewer = self.query_one("#run-detail", TextArea)
            scroll = viewer.scroll_offset
            same_entry = bool(self._detail_identity and self._detail_identity[0] == identity[0])
            self._detail_identity = identity
            viewer.load_text(detail)
            if same_entry:
                viewer.scroll_to(scroll.x, scroll.y, animate=False, immediate=True)
        approval = bool(
            row and row.source in {"pure", "peer", "inline"} and self.section == "approvals"
        )
        for action in ("approve", "reject"):
            self.query_one(f"#run-{action}", Button).disabled = self._acting or not approval
        self.query_one("#run-open", Button).disabled = self._acting or not bool(
            row and (row.command or row.source == "workorder")
        )

    @on(OptionList.OptionHighlighted, "#run-list")
    def highlighted(self):
        self._show_selected()

    @on(OptionList.OptionSelected, "#run-list")
    def inspect_selected(self):
        self.query_one("#run-detail", TextArea).focus()

    @on(Button.Pressed)
    def button_pressed(self, event):
        event.stop()
        name = event.button.id or ""
        if name.startswith("run-tab-"):
            self.section = name.removeprefix("run-tab-")
            self.reference = ""
            self._render_entries()
        elif name == "run-back":
            self.action_close()
        elif name == "run-refresh":
            self.run_worker(self.reload())
        elif name in {"run-approve", "run-reject", "run-open"} and not self._acting:
            row = self.selected()
            if row is None:
                return
            self._acting = True
            self._show_selected()
            self.app.run_worker(self._perform_action(name.removeprefix("run-"), row))

    async def _perform_action(self, action, row):
        try:
            message = await self.on_action(action, row)
            await self.reload()
            if self._available():
                self.query_one("#run-notice", Static).update(Text(message or ""))
        except Exception as exc:
            if self._available():
                self.query_one("#run-notice", Static).update(Text(f"Action failed: {exc}"))
        finally:
            self._acting = False
            if self._available():
                self._show_selected()

    async def action_reload(self):
        await self.reload()

    def action_close(self):
        self._overview_closed = True
        self.dismiss(None)
