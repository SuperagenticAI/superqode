"""Rich terminal Harness Hub.

The Hub is a real Textual screen rather than text drawn into the conversation
transcript.  It keeps search, filters, selection, details and actions in one
focal surface and supports the same flow with a mouse or keyboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, OptionList, Static
from textual.widgets.option_list import Option

from superqode.app.harness_picker import HarnessPickerItem
from superqode.harness.hub import REFERENCE_ONLY_KINDS, hub_record, readiness_label


@dataclass(frozen=True)
class HarnessHubResult:
    """An action chosen from the Hub."""

    action: str
    item_id: str = ""


class HarnessHubScreen(Screen[HarnessHubResult | None]):
    """Searchable, clickable browser for every SuperQode harness route."""

    BINDINGS = [
        Binding("escape", "close", "Back"),
        Binding("q", "close", "Back", show=False),
        Binding("/", "search", "Search"),
        # Handle Enter before the focused child. OptionList otherwise turns
        # Enter into OptionSelected, which would make keyboard and mouse
        # selection share the same (surprising) activation behaviour.
        Binding("enter", "use", "Use", priority=True),
        Binding("i", "inspect", "Inspect"),
        Binding("b", "build", "Build"),
        Binding("a", "filter_all", "All", show=False),
        Binding("r", "filter_ready", "Ready", show=False),
    ]

    CSS = """
    HarnessHubScreen {
        background: #050505;
    }
    HarnessHubScreen #hub-header {
        height: 5;
        min-height: 5;
        max-height: 5;
        padding: 1 2;
        border-bottom: solid #27272a;
        background: #090909;
    }
    HarnessHubScreen #hub-heading {
        height: 3;
    }
    HarnessHubScreen #hub-title {
        width: 1fr;
        height: 1;
        color: #a855f7;
        text-style: bold;
    }
    HarnessHubScreen #hub-subtitle {
        width: 1fr;
        height: 1;
        color: #a1a1aa;
    }
    HarnessHubScreen #hub-search {
        width: 48;
        height: 3;
        max-width: 46%;
    }
    HarnessHubScreen #hub-filters {
        height: 3;
        padding: 0 2;
        background: #090909;
        border-bottom: solid #1f1f23;
    }
    HarnessHubScreen #hub-filters Button {
        min-width: 10;
        margin-right: 1;
    }
    HarnessHubScreen #hub-body {
        height: 1fr;
        min-height: 8;
    }
    HarnessHubScreen #hub-list {
        width: 54%;
        height: 100%;
        background: #050505;
        border-right: solid #27272a;
    }
    HarnessHubScreen #hub-detail {
        width: 1fr;
        height: 100%;
        padding: 2 3;
        background: #080808;
        overflow-y: auto;
    }
    HarnessHubScreen #hub-actions {
        height: 4;
        padding: 0 2;
        align-horizontal: right;
        background: #090909;
        border-top: solid #27272a;
    }
    HarnessHubScreen #hub-actions Button {
        min-width: 13;
        margin-left: 1;
    }

    HarnessHubScreen.narrow #hub-list {
        width: 100%;
    }
    HarnessHubScreen.narrow #hub-detail {
        display: none;
    }
    HarnessHubScreen.narrow #hub-search {
        width: 28;
        max-width: 48%;
    }
    """

    FILTERS = ("all", "ready", "setup", "custom", "coming")

    def __init__(
        self,
        items: Iterable[HarnessPickerItem],
        *,
        current_id: str = "",
        query: str = "",
        initial_filter: str = "all",
    ) -> None:
        super().__init__()
        self.items = list(items)
        self.current_id = current_id
        self.search_query = query.strip()
        self.filter_name = initial_filter if initial_filter in self.FILTERS else "all"
        self.filtered_items: list[HarnessPickerItem] = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="hub-header"):
            with Vertical(id="hub-heading"):
                yield Static("Harness Hub", id="hub-title")
                yield Static(
                    "Discover, trust, run, compare and build coding harnesses",
                    id="hub-subtitle",
                )
            yield Input(value=self.search_query, placeholder="Search harnesses...", id="hub-search")

        with Horizontal(id="hub-filters"):
            yield Button("All", id="hub-filter-all")
            yield Button("Ready", id="hub-filter-ready")
            yield Button("Needs setup", id="hub-filter-setup")
            yield Button("Your harnesses", id="hub-filter-custom")
            yield Button("Coming soon", id="hub-filter-coming")

        with Horizontal(id="hub-body"):
            yield OptionList(id="hub-list")
            yield Static(id="hub-detail")

        with Horizontal(id="hub-actions"):
            yield Button("Build your own", id="hub-build")
            yield Button("Inspect", id="hub-inspect")
            yield Button("Use", id="hub-use", variant="primary")
            yield Button("Back", id="hub-close")
        yield Footer()

    def on_mount(self) -> None:
        self.set_class(self.size.width < 82, "narrow")
        self._refresh_items()
        search = self.query_one("#hub-search", Input)
        if self.search_query:
            search.focus()
        else:
            self.query_one("#hub-list", OptionList).focus()

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 82, "narrow")

    def _matches_filter(self, item: HarnessPickerItem) -> bool:
        if self.filter_name == "ready":
            return item.available
        if self.filter_name == "setup":
            return not item.available and item.kind not in REFERENCE_ONLY_KINDS
        if self.filter_name == "custom":
            return item.group == "Project harnesses" or item.source in {"file", "registry"}
        if self.filter_name == "coming":
            return item.kind == "ecosystem"
        return True

    def _matches_query(self, item: HarnessPickerItem) -> bool:
        if not self.search_query:
            return True
        haystack = " ".join(
            (
                item.id,
                item.display_name,
                item.description,
                item.runtime,
                item.group,
                item.source,
                item.provider,
                item.model,
            )
        ).casefold()
        return all(part in haystack for part in self.search_query.casefold().split())

    def _refresh_items(self) -> None:
        self.filtered_items = [
            item for item in self.items if self._matches_filter(item) and self._matches_query(item)
        ]
        option_list = self.query_one("#hub-list", OptionList)
        previous_id = self._selected_id()
        option_list.clear_options()
        self._update_filter_buttons()
        for item in self.filtered_items:
            option_list.add_option(Option(self._option_label(item), id=item.id))

        if not self.filtered_items:
            option_list.add_option(
                Option("No harnesses match this view", id="hub-empty", disabled=True)
            )
            self.query_one("#hub-detail", Static).update(
                Text("Try another search or filter.", style="#a1a1aa")
            )
            primary = self.query_one("#hub-use", Button)
            primary.label = "No selection"
            primary.disabled = True
            return

        index = 0
        if previous_id:
            index = next(
                (i for i, item in enumerate(self.filtered_items) if item.id == previous_id),
                0,
            )
        elif self.current_id:
            index = next(
                (i for i, item in enumerate(self.filtered_items) if item.id == self.current_id),
                0,
            )
        option_list.highlighted = index
        self._update_detail(self.filtered_items[index])
        self._update_primary_action(self.filtered_items[index])

    def _option_label(self, item: HarnessPickerItem) -> Text:
        text = Text()
        active = item.id == self.current_id
        text.append(
            "● " if item.available else "○ ", style="#22c55e" if item.available else "#f59e0b"
        )
        text.append(item.display_name, style="bold #f4f4f5")
        if active:
            text.append("  ACTIVE", style="bold #38bdf8")
        text.append(f"\n    {item.group} · ", style="#71717a")
        status = (
            "coming soon"
            if item.kind == "ecosystem"
            else "ready"
            if item.available
            else "needs setup"
        )
        status_color = (
            "#f97316" if item.kind == "ecosystem" else "#22c55e" if item.available else "#f59e0b"
        )
        text.append(status, style=status_color)
        if item.runtime:
            text.append(f" · {item.runtime}", style="#a1a1aa")
        return text

    def _selected_id(self) -> str:
        try:
            option_list = self.query_one("#hub-list", OptionList)
            if option_list.highlighted is None:
                return ""
            option = option_list.get_option_at_index(option_list.highlighted)
            return str(option.id or "")
        except Exception:
            return ""

    def _selected_item(self) -> HarnessPickerItem | None:
        selected_id = self._selected_id()
        return next((item for item in self.filtered_items if item.id == selected_id), None)

    def _update_detail(self, item: HarnessPickerItem) -> None:
        record = hub_record(item, include_local_paths=True)
        text = Text()
        text.append(f"{item.display_name}\n", style="bold #f4f4f5")
        text.append(f"{item.description}\n", style="#d4d4d8")
        text.append("\n")
        rows = (
            ("Status", readiness_label(record.readiness)),
            ("Type", item.group),
            ("Runtime", item.runtime or "Defined by the harness"),
            ("Continuity", item.continuity.replace("-", " ")),
            ("Source", item.source),
        )
        for label, value in rows:
            text.append(f"{label:<13}", style="#71717a")
            text.append(f"{value}\n", style="#e4e4e7")
        if item.provider or item.model:
            text.append(f"{'Model route':<13}", style="#71717a")
            text.append(f"{item.provider}/{item.model}\n", style="#e4e4e7")
        if item.issue and not item.available:
            text.append("\nSetup\n", style="bold #f59e0b")
            text.append(f"{item.issue}\n", style="#fbbf24")
        if item.warning:
            text.append("\nImportant\n", style="bold #f59e0b")
            text.append(f"{item.warning}\n", style="#fbbf24")
        if record.based_on:
            text.append("\nBased on\n", style="bold #38bdf8")
            text.append(f"{record.based_on}\n", style="#bae6fd")
        if record.support_note:
            text.append("\nSuperQode support\n", style="bold #f97316")
            text.append(f"{record.support_note}\n", style="#fdba74")
        if record.tools:
            text.append("\nTools\n", style="bold #a855f7")
            text.append(" · ".join(record.tools), style="#d8b4fe")
            text.append("\n")
        if record.policies:
            text.append("\nPolicies\n", style="bold #a855f7")
            for policy in record.policies:
                text.append(f"• {policy}\n", style="#d4d4d8")
        if record.tui_commands:
            text.append("\nUse in the TUI\n", style="bold #22c55e")
            for command in record.tui_commands:
                text.append(f"{command}\n", style="#86efac")
        if record.eval_commands:
            text.append("\nEvaluate\n", style="bold #38bdf8")
            for command in record.eval_commands:
                text.append(f"{command}\n", style="#7dd3fc")
        if record.optimize_commands:
            text.append("\nOptimize\n", style="bold #a855f7")
            for command in record.optimize_commands:
                text.append(f"{command}\n", style="#d8b4fe")
        if record.setup_steps:
            heading = (
                "Official installation (external)"
                if record.readiness == "not-supported"
                else "Installation and authentication"
            )
            text.append(f"\n{heading}\n", style="bold #f59e0b")
            for index, step in enumerate(record.setup_steps, 1):
                text.append(f"{index}. {step.title}\n", style="#e4e4e7")
                if step.command:
                    text.append(f"   {step.command}\n", style="#fbbf24")
                if step.description:
                    text.append(f"   {step.description}\n", style="#a1a1aa")
        elif record.install_command:
            text.append("\nInstallation and authentication\n", style="bold #f59e0b")
            text.append(f"{record.install_command}\n", style="#e4e4e7")
        if record.docs_url:
            text.append("\nDocumentation\n", style="bold #38bdf8")
            text.append(record.docs_url, style=f"#7dd3fc link {record.docs_url}")
            text.append("\n")
        if item.kind in REFERENCE_ONLY_KINDS:
            text.append("\nMouse: select, then choose Learn more\n", style="#71717a")
            text.append(
                "Keyboard: / search · Enter learn more · I inspect · B build", style="#71717a"
            )
        else:
            text.append("\nMouse: select and use the buttons\n", style="#71717a")
            text.append("Keyboard: / search · Enter use · I inspect · B build", style="#71717a")
        self.query_one("#hub-detail", Static).update(text)

    def _update_filter_buttons(self) -> None:
        for filter_name in self.FILTERS:
            button = self.query_one(f"#hub-filter-{filter_name}", Button)
            button.variant = "primary" if filter_name == self.filter_name else "default"

    @on(Input.Changed, "#hub-search")
    def on_search_changed(self, event: Input.Changed) -> None:
        self.search_query = event.value.strip()
        self._refresh_items()

    @on(Input.Submitted, "#hub-search")
    def on_search_submitted(self, event: Input.Submitted) -> None:
        if self.filtered_items:
            self.query_one("#hub-list", OptionList).focus()

    @on(OptionList.OptionHighlighted, "#hub-list")
    def on_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        item = next(
            (candidate for candidate in self.filtered_items if candidate.id == event.option.id),
            None,
        )
        if item is not None:
            self._update_detail(item)
            self._update_primary_action(item)

    @on(OptionList.OptionSelected, "#hub-list")
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        # A click selects and previews; it never activates a harness. Keeping
        # activation behind the explicit Use button prevents accidental
        # switches while someone is browsing with a mouse.
        item = next(
            (candidate for candidate in self.filtered_items if candidate.id == event.option.id),
            None,
        )
        if item is not None:
            self._update_detail(item)
            self._update_primary_action(item)

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button_id = str(event.button.id or "")
        if button_id.startswith("hub-filter-"):
            self.filter_name = button_id.removeprefix("hub-filter-")
            self._refresh_items()
            return
        if button_id == "hub-use":
            self._use_selected()
        elif button_id == "hub-inspect":
            self.action_inspect()
        elif button_id == "hub-build":
            self.action_build()
        elif button_id == "hub-close":
            self.action_close()

    def action_search(self) -> None:
        self.query_one("#hub-search", Input).focus()

    def action_use(self) -> None:
        focused = self.focused
        if isinstance(focused, Button):
            focused.press()
            return
        # Enter in search means "show me the results". A second Enter, once
        # the list has focus, activates the highlighted harness.
        if focused is self.query_one("#hub-search", Input):
            if self.filtered_items:
                self.query_one("#hub-list", OptionList).focus()
            return
        self._use_selected()

    def _use_selected(self) -> None:
        item = self._selected_item()
        if item is not None:
            action = "inspect" if item.kind in REFERENCE_ONLY_KINDS else "use"
            self.dismiss(HarnessHubResult(action, item.id))

    def _update_primary_action(self, item: HarnessPickerItem) -> None:
        button = self.query_one("#hub-use", Button)
        button.disabled = False
        button.label = "Learn more" if item.kind in REFERENCE_ONLY_KINDS else "Use"

    def action_inspect(self) -> None:
        item = self._selected_item()
        if item is not None:
            self.dismiss(HarnessHubResult("inspect", item.id))

    def action_build(self) -> None:
        self.dismiss(HarnessHubResult("build"))

    def action_filter_all(self) -> None:
        self.filter_name = "all"
        self._refresh_items()

    def action_filter_ready(self) -> None:
        self.filter_name = "ready"
        self._refresh_items()

    def action_close(self) -> None:
        self.dismiss(None)


__all__ = ["HarnessHubResult", "HarnessHubScreen"]
