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
from superqode.harness.hub import (
    REFERENCE_ONLY_KINDS,
    hub_record,
    is_open_source,
    language_of,
    language_label,
    openness_label,
    readiness_label,
)


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
        Binding("s", "filter_setup", "Setup", show=False),
        Binding("o", "filter_open", "Open source", show=False),
        Binding("c", "filter_custom", "Yours", show=False),
        Binding("n", "filter_coming", "Coming", show=False),
        Binding("l", "cycle_language", "Language", show=False),
    ]

    CSS = """
    HarnessHubScreen {
        background: #000000;
    }
    HarnessHubScreen Footer {
        background: #000000;
        dock: bottom;
        height: 1;
    }
    HarnessHubScreen #hub-header {
        height: 5;
        min-height: 5;
        max-height: 5;
        padding: 1 2 0 2;
        background: #000000;
    }
    HarnessHubScreen #hub-heading {
        width: 1fr;
        height: 3;
    }
    HarnessHubScreen #hub-title {
        width: 1fr;
        height: 1;
        color: #c4b5fd;
        text-style: bold;
    }
    HarnessHubScreen #hub-subtitle {
        width: 1fr;
        height: 1;
        color: #d4d4d4;
    }
    HarnessHubScreen #hub-search {
        width: 1fr;
        max-width: 36;
        height: 3;
        background: #000000;
        color: #f0f0f0;
        border: tall #2a2a2a;
    }
    HarnessHubScreen #hub-search:focus {
        border: tall #7c3aed;
    }
    HarnessHubScreen #hub-filters {
        height: auto;
        padding: 0 1;
        background: #000000;
    }
    HarnessHubScreen #hub-filters Button {
        min-width: 10;
        height: 3;
        margin-right: 1;
        background: #1a1a1a;
        color: #d8d8d8;
        border: tall #3a3a3a;
    }
    HarnessHubScreen #hub-filters Button:hover {
        background: #2a1a40;
    }
    HarnessHubScreen #hub-filters Button.on {
        background: #3b1d7a;
        color: #f3e8ff;
        border: tall #c4b5fd;
        text-style: bold;
    }
    HarnessHubScreen #hub-languages {
        height: auto;
        padding: 0 1;
        background: #000000;
    }
    HarnessHubScreen .hub-language-row {
        height: auto;
        background: #000000;
    }
    HarnessHubScreen #hub-languages Button {
        min-width: 6;
        height: 3;
        margin-right: 1;
        background: #141414;
        color: #b8b8b8;
        border: tall #2f2f2f;
    }
    HarnessHubScreen #hub-languages Button:hover {
        background: #2a1a40;
    }
    HarnessHubScreen #hub-languages Button.on {
        background: #3b1d7a;
        color: #f3e8ff;
        border: tall #c4b5fd;
        text-style: bold;
    }
    HarnessHubScreen #hub-body {
        height: 1fr;
        min-height: 8;
        padding: 1 1 1 1;
    }
    HarnessHubScreen OptionList {
        border: round #27272a;
    }
    HarnessHubScreen #hub-list {
        width: 54%;
        height: 100%;
        background: #000000;
        border: round #27272a;
        scrollbar-background: #000000;
        scrollbar-color: #2a2a2a;
        overflow-x: hidden;
        margin-right: 1;
    }
    HarnessHubScreen #hub-list > .option-list--option {
        padding: 0 1;
    }
    HarnessHubScreen #hub-list > .option-list--option-highlighted {
        background: #1a1030;
    }
    HarnessHubScreen #hub-list:focus > .option-list--option-highlighted {
        background: #241542;
    }
    HarnessHubScreen #hub-detail {
        width: 1fr;
        height: 100%;
        padding: 1 2;
        background: #000000;
        overflow-y: auto;
        overflow-x: hidden;
        border: round #27272a;
    }
    HarnessHubScreen #hub-actions {
        height: auto;
        padding: 0 1;
        background: #000000;
        align: right middle;
    }
    HarnessHubScreen #hub-actions Button {
        min-width: 13;
        height: 3;
        margin-left: 1;
        background: #000000;
        color: #e6e6e6;
        border: tall #2a2a2a;
    }
    HarnessHubScreen #hub-actions Button.-primary {
        background: #3b1d7a;
        color: #f3e8ff;
        border: tall #c4b5fd;
    }

    HarnessHubScreen.narrow #hub-body {
        layout: vertical;
    }
    HarnessHubScreen.narrow #hub-list {
        width: 100%;
        height: 1fr;
    }
    HarnessHubScreen.narrow #hub-detail {
        display: block;
        width: 100%;
        height: 8;
        padding: 1 2;
    }
    HarnessHubScreen.narrow #hub-search {
        width: 28;
        max-width: 48%;
    }
    """

    FILTERS = ("all", "ready", "setup", "open", "custom", "coming")
    #: Language buttons per row. Six fits an 80-column terminal.
    LANGUAGES_PER_ROW = 6

    def __init__(
        self,
        items: Iterable[HarnessPickerItem],
        *,
        current_id: str = "",
        query: str = "",
        initial_filter: str = "all",
        session_connected: bool = False,
        session_model: str = "",
    ) -> None:
        super().__init__()
        self.items = list(items)
        self.current_id = current_id
        self.search_query = query.strip()
        self.filter_name = initial_filter if initial_filter in self.FILTERS else "all"
        # Language is a second, independent axis rather than another mutually
        # exclusive filter: "ready" and "Rust" are useful together, and nine
        # languages would not fit the button row as exclusive options.
        self.language_filter = ""
        self.session_connected = session_connected
        self.session_model = session_model.strip()
        self.filtered_items: list[HarnessPickerItem] = []
        self._inspect_expanded = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="hub-header"):
            with Vertical(id="hub-heading"):
                yield Static(
                    Text.assemble(
                        ("Harness", "bold #e9d5ff"),
                        (" Hub", "bold #a78bfa"),
                    ),
                    id="hub-title",
                )
                yield Static(
                    "Browse harnesses. :connect starts one; :connect acp lists ACP agents.",
                    id="hub-subtitle",
                )
            yield Input(value=self.search_query, placeholder="Search harnesses...", id="hub-search")

        with Horizontal(id="hub-filters"):
            yield Button("All", id="hub-filter-all")
            yield Button("Ready", id="hub-filter-ready")
            yield Button("Needs setup", id="hub-filter-setup")
            yield Button("Open source", id="hub-filter-open")
            yield Button("Your harnesses", id="hub-filter-custom")
            yield Button("Coming soon", id="hub-filter-coming")

        # Named languages rather than one cycling control: a button reading
        # "Language: All" tells you the current value but not that it can be
        # changed, nor what the options are. They wrap across rows because a
        # Horizontal cannot scroll, so anything past the right edge of a narrow
        # terminal would simply be unreachable.
        with Vertical(id="hub-languages"):
            buttons = [("Any language", "all")]
            buttons += [
                (
                    f"{name} {sum(1 for i in self.items if language_of(i).language == name)}",
                    self._language_slug(name),
                )
                for name in self._languages_present()
            ]
            for start in range(0, len(buttons), self.LANGUAGES_PER_ROW):
                row = buttons[start : start + self.LANGUAGES_PER_ROW]
                with Horizontal(classes="hub-language-row"):
                    for label, slug in row:
                        yield Button(label, id=f"hub-language-{slug}")

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
        if self.filter_name == "open":
            return is_open_source(item)
        if self.filter_name == "custom":
            return item.group == "Project harnesses" or item.source in {"file", "registry"}
        if self.filter_name == "coming":
            return item.kind == "ecosystem"
        return True

    @staticmethod
    def _language_slug(name: str) -> str:
        """A Textual-safe id fragment for a language name."""
        return "".join(char if char.isalnum() else "-" for char in name).lower()

    def _matches_language(self, item: HarnessPickerItem) -> bool:
        if not self.language_filter:
            return True
        return language_of(item).language == self.language_filter

    def _languages_present(self) -> list[str]:
        """Languages in the current list, commonest first, for the cycle order."""
        counts: dict[str, int] = {}
        for item in self.items:
            name = language_of(item).language
            counts[name] = counts.get(name, 0) + 1
        return sorted(counts, key=lambda name: (-counts[name], name))

    def action_cycle_language(self) -> None:
        """Step to the next language, wrapping back to All after the last."""
        order = ["", *self._languages_present()]
        try:
            nxt = order[(order.index(self.language_filter) + 1) % len(order)]
        except ValueError:
            nxt = ""
        self.language_filter = nxt
        self._refresh_items()

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
                language_of(item).language,
            )
        ).casefold()
        return all(part in haystack for part in self.search_query.casefold().split())

    def _refresh_items(self, *, keep_position: bool = False) -> None:
        """Rebuild the list. Changing what is shown starts at the top again.

        Only searching keeps the highlight: narrowing a list you are reading
        should not throw away your place. Switching filter or language is a new
        view, and restoring the old highlight there lands the user in the middle
        of it -- or, since the active harness is now sorted last, at the bottom.
        """
        self.filtered_items = [
            item
            for item in self.items
            if self._matches_filter(item)
            and self._matches_language(item)
            and self._matches_query(item)
        ]
        option_list = self.query_one("#hub-list", OptionList)
        previous_id = self._selected_id() if keep_position else ""
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
        option_list.highlighted = index
        if index == 0:
            # Rebuilding keeps the old scroll offset, so a fresh view can open
            # part-way down a list whose first row is highlighted.
            option_list.scroll_to(y=0, animate=False)
        self._update_detail(self.filtered_items[index])
        self._update_primary_action(self.filtered_items[index])

    def _session_has_model(self) -> bool:
        return bool(self.session_connected and self.session_model)

    def _run_state(self, item: HarnessPickerItem) -> str:
        """How far this row is from actually running.

        Built-in SuperQode harnesses (Core, RLM, PiPy, Workbench) are always
        *installed*, but they still need a model. Coding agents that are
        logged in can Use immediately.
        """
        if item.kind in REFERENCE_ONLY_KINDS:
            return "coming"
        if not item.available:
            return "setup"
        if item.kind == "harness" and not (item.provider and item.model):
            if not self._session_has_model():
                return "choose-model"
        return "use"

    def _option_label(self, item: HarnessPickerItem) -> Text:
        text = Text()
        active = item.id == self.current_id
        state = self._run_state(item)
        mark = "● " if state == "use" else "○ "
        mark_color = {
            "use": "#22c55e",
            "choose-model": "#c4b5fd",
            "setup": "#f59e0b",
            "coming": "#f97316",
        }.get(state, "#f59e0b")
        text.append(mark, style=mark_color)
        text.append(item.display_name, style="bold #f4f4f5")
        if active:
            text.append("  ACTIVE", style="bold #c4b5fd")
        text.append(f"\n    {item.group} · ", style="#71717a")
        status = {
            "use": "ready",
            "choose-model": "needs a model",
            "setup": "needs setup",
            "coming": "coming soon",
        }.get(state, "needs setup")
        text.append(status, style=mark_color)
        if item.runtime:
            text.append(f" · {item.runtime}", style="#a1a1aa")
        text.append(f" · {language_of(item).language}", style="#a1a1aa")
        return text

    @staticmethod
    def _has_more_detail(record) -> bool:
        """Whether Inspect would actually add anything, so the hint never lies."""
        return any(
            (
                record.based_on,
                record.support_note,
                record.tools,
                record.policies,
                record.tui_commands,
                record.eval_commands,
                record.optimize_commands,
                record.setup_steps,
                record.cli_commands,
            )
        )

    @staticmethod
    def _launch_command(record, state: str) -> str:
        """The single command that starts this harness, or "" if there is none.

        Inside SuperQode that is the TUI command; for an entry SuperQode cannot
        run it is the vendor's own CLI, which is the only thing that would
        actually launch it.
        """
        if state != "coming" and record.tui_commands:
            return record.tui_commands[0]
        if record.cli_commands:
            return record.cli_commands[0]
        return ""

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
        state = self._run_state(item)
        if state == "coming":
            text.append(
                "\nComing soon in SuperQode. Inspect stays on this screen.\n", style="#c8c8c8"
            )
        elif state == "choose-model":
            text.append(
                "\nThis harness is installed. It still needs a model. "
                "Choose model opens Local, an API key, or a plan.\n",
                style="#c4b5fd",
            )
        elif state == "use":
            text.append("\nEnter or Use starts this harness.\n", style="#c4b5fd")
        else:
            text.append("\nNeeds setup before Use.\n", style="#fbbf24")
        text.append("\n")
        status_value = {
            "use": "Ready",
            "choose-model": "Needs a model",
            "setup": "Needs setup",
            "coming": "Coming soon",
        }.get(state, readiness_label(record.readiness))
        rows = (
            ("Status", status_value),
            ("Type", item.group),
            ("Runtime", item.runtime or "Defined by the harness"),
            ("Continuity", item.continuity.replace("-", " ")),
            ("Source", item.source),
            # The license is the more useful half when it is known, so show it
            # rather than repeating the word "Open source" next to itself.
            (
                "Licensing",
                record.license if record.license else openness_label(record.openness),
            ),
            # What the harness is actually written in. An inferred reading is
            # marked as such rather than presented with the same confidence as
            # one taken from the project's own build manifest.
            ("Language", language_label(record.language, record.language_confidence)),
        )
        for label, value in rows:
            text.append(f"{label:<13}", style="#71717a")
            text.append(f"{value}\n", style="#e4e4e7")
        if item.provider or item.model:
            text.append(f"{'Model route':<13}", style="#71717a")
            text.append(f"{item.provider}/{item.model}\n", style="#e4e4e7")
        # The launcher. "Use" is only meaningful for something SuperQode can
        # drive, so an entry it cannot run shows the vendor's own command
        # instead of a button that would do nothing.
        launcher = self._launch_command(record, state)
        if launcher:
            text.append("\nLaunch\n", style="bold #22c55e")
            text.append(f"{launcher}\n", style="#86efac")
        if item.issue and not item.available:
            text.append("\nSetup\n", style="bold #f59e0b")
            text.append(f"{item.issue}\n", style="#fbbf24")
        if item.warning:
            text.append("\nImportant\n", style="bold #f59e0b")
            text.append(f"{item.warning}\n", style="#fbbf24")
        # Everything above stays in the preview: it is what the highlight is
        # for -- what this is, what it is written in, and how to start it.
        # Depth moves behind Inspect so the pane stays readable while arrowing
        # through a long list, and so Links below is reachable without a scroll.
        if self._inspect_expanded:
            if record.based_on:
                text.append("\nBased on\n", style="bold #a78bfa")
                text.append(f"{record.based_on}\n", style="#e9d5ff")
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
                text.append("\nEvaluate\n", style="bold #a78bfa")
                for command in record.eval_commands:
                    text.append(f"{command}\n", style="#e9d5ff")
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
            if record.cli_commands:
                text.append("\nCLI\n", style="bold #a78bfa")
                for command in record.cli_commands:
                    text.append(f"{command}\n", style="#e9d5ff")
        elif not record.setup_steps and record.install_command:
            # Nothing SuperQode can launch: the vendor's own command is the
            # only actionable thing on the screen, so it is not hidden.
            text.append("\nInstall\n", style="bold #f59e0b")
            text.append(f"{record.install_command}\n", style="#e4e4e7")
        # One Links block rather than scattered sections. Several catalogue
        # entries repeat a single URL across repository, homepage and docs, so
        # the first label to claim a URL keeps it and the rest are dropped --
        # otherwise the panel prints the same address three times.
        links: list[tuple[str, str]] = []
        seen: set[str] = set()
        for label, url in (
            ("Official repo", record.repository),
            ("Homepage", record.homepage),
            ("Documentation", record.docs_url),
        ):
            if url and url not in seen:
                seen.add(url)
                links.append((label, url))
        if links:
            text.append("\nLinks\n", style="bold #a78bfa")
            for label, url in links:
                text.append(f"{label:<15}", style="#71717a")
                text.append(f"{url}\n", style="#c4b5fd")
        if not self._inspect_expanded and self._has_more_detail(record):
            text.append("\ni  ", style="bold #a78bfa")
            text.append("setup steps, tools, policies and commands\n", style="#71717a")
        self.query_one("#hub-detail", Static).update(text)

    def _update_filter_buttons(self) -> None:
        for filter_name in self.FILTERS:
            button = self.query_one(f"#hub-filter-{filter_name}", Button)
            button.set_class(filter_name == self.filter_name, "on")
            button.variant = "default"
        for button in self.query("#hub-languages Button"):
            wanted = str(button.id or "").removeprefix("hub-language-")
            active = (
                not self.language_filter
                if wanted == "all"
                else self._language_slug(self.language_filter) == wanted
            )
            button.set_class(active, "on")
            button.variant = "default"

    @on(Input.Changed, "#hub-search")
    def on_search_changed(self, event: Input.Changed) -> None:
        self.search_query = event.value.strip()
        self._refresh_items(keep_position=True)

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
        if button_id.startswith("hub-language-"):
            wanted = button_id.removeprefix("hub-language-")
            if wanted == "all":
                self.language_filter = ""
            else:
                self.language_filter = next(
                    (
                        name
                        for name in self._languages_present()
                        if self._language_slug(name) == wanted
                    ),
                    "",
                )
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
        if item is None:
            return
        if item.kind in REFERENCE_ONLY_KINDS:
            self.action_inspect()
            return
        self.dismiss(HarnessHubResult("use", item.id))

    def _update_primary_action(self, item: HarnessPickerItem) -> None:
        button = self.query_one("#hub-use", Button)
        button.disabled = False
        state = self._run_state(item)
        button.label = {
            "coming": "Learn more",
            "choose-model": "Choose model",
            "setup": "Set up",
            "use": "Use",
        }.get(state, "Use")

    def action_inspect(self) -> None:
        item = self._selected_item()
        if item is None:
            return
        self._inspect_expanded = True
        self._update_detail(item)
        try:
            self.query_one("#hub-detail", Static).focus()
        except Exception:  # noqa: BLE001
            pass

    def action_build(self) -> None:
        self.dismiss(HarnessHubResult("build"))

    def action_filter_all(self) -> None:
        self.filter_name = "all"
        self._refresh_items()

    def action_filter_ready(self) -> None:
        self.filter_name = "ready"
        self._refresh_items()

    def action_filter_setup(self) -> None:
        self.filter_name = "setup"
        self._refresh_items()

    def action_filter_open(self) -> None:
        self.filter_name = "open"
        self._refresh_items()

    def action_filter_custom(self) -> None:
        self.filter_name = "custom"
        self._refresh_items()

    def action_filter_coming(self) -> None:
        self.filter_name = "coming"
        self._refresh_items()

    def action_close(self) -> None:
        self.dismiss(None)


__all__ = ["HarnessHubResult", "HarnessHubScreen"]
