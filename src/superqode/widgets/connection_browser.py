"""Search connections without changing the active session or prompt draft."""

from __future__ import annotations

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static, Button, Footer
from textual.widgets.option_list import Option

from superqode.app.project_ui_state import get_connection_preferences, set_connection_favorites


def load_connection_profiles():
    from superqode.providers.connection_profiles import ConnectionProfile, list_connection_profiles
    from superqode.app.harness_picker import acp_picker_items

    profiles = list_connection_profiles()
    profiles.extend(
        ConnectionProfile(
            id=item.id,
            label=item.display_name,
            description=item.description,
            connector="acp",
            acp_agent=str(item.target.get("short_name") or ""),
            detect=lambda available=item.available: available,
            unavailable_hint=item.issue,
            transport="ACP",
            verify_on_connect=True,
        )
        for item in acp_picker_items(include_registry=True)
    )
    return list({profile.id: profile for profile in profiles}.values())


def filter_connections(profiles, query: str, favorites: list[str], recent: list[str]):
    words = query.casefold().split()
    matches = [
        p
        for p in profiles
        if all(word in f"{p.id} {p.label} {p.description}".casefold() for word in words)
    ]
    return sorted(
        matches,
        key=lambda p: (
            p.id not in favorites,
            p.id not in recent,
            recent.index(p.id) if p.id in recent else len(recent),
            p.label.casefold(),
            p.id,
        ),
    )


class ConnectionBrowserScreen(ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape", "close", "Back", priority=True),
        Binding("ctrl+s", "favorite", "Favorite", priority=True),
        Binding("down", "next", "Next", show=False, priority=True),
        Binding("up", "previous", "Previous", show=False, priority=True),
    ]
    CSS = """
    ConnectionBrowserScreen { align: center middle; }
    #connection-browser { width: 90%; max-width: 100; height: 90%; background: $surface; border: round $primary; padding: 1 2; }
    #connection-title { height: auto; text-style: bold; margin-bottom: 1; }
    #connection-search { margin-bottom: 1; }
    #connection-results { height: 1fr; }
    #connection-detail { height: auto; margin: 1 0; }
    #connection-detail-scroll { height: auto; max-height: 8; margin: 1 0; }
    #connection-detail-scroll #connection-detail { margin: 0; }
    #connection-buttons { height: 3; }
    #connection-buttons Button { margin-right: 1; min-width: 8; width: auto; padding: 0 1; }
    #connection-browser.compact { padding: 0 1; }
    #connection-browser.compact #connection-title { height: 1; margin: 0; }
    #connection-browser.compact #connection-search { margin: 0; }
    #connection-browser.compact #connection-detail-scroll { height: 5; max-height: 5; margin: 0; }
    #connection-browser.compact #connection-detail { height: auto; }
    """

    def __init__(self, *, query: str = "", loader=load_connection_profiles, cwd=None):
        super().__init__()
        self.initial_query = query
        self.loader = loader
        self.cwd = cwd
        self.profiles = []
        self.matching_profiles = []
        self.readiness = {}
        self.catalog_loaded = False
        self.load_failed = False
        self.favorites, self.recent = get_connection_preferences(cwd)

    def compose(self) -> ComposeResult:
        with Vertical(id="connection-browser"):
            yield Static("Search harnesses and connections", id="connection-title")
            yield Input(
                value=self.initial_query,
                placeholder="Name, provider, account or harness…",
                id="connection-search",
            )
            yield OptionList(id="connection-results")
            with VerticalScroll(id="connection-detail-scroll", can_focus=True):
                yield Static("Loading local connection catalog…", id="connection-detail")
            with Horizontal(id="connection-buttons"):
                yield Button("Connect", id="connection-select", variant="primary", disabled=True)
                yield Button("Favorite", id="connection-favorite", disabled=True)
                yield Button("Last used", id="connection-last")
            yield Footer()

    def on_mount(self):
        self.query_one("#connection-browser").set_class(self.size.height < 26, "compact")
        self.query_one("#connection-search", Input).focus()
        self._load_profiles()

    def on_resize(self, event):
        if self.is_mounted:
            self.query_one("#connection-browser").set_class(event.size.height < 26, "compact")

    @work(thread=True, exclusive=True)
    def _load_profiles(self):
        try:
            profiles = self.loader()
            readiness = {
                p.id: (
                    getattr(p, "available", True),
                    getattr(p, "unavailable_hint", ""),
                    getattr(p, "verify_on_connect", False),
                )
                for p in profiles
            }
        except Exception:
            self.app.call_from_thread(self._load_failed)
            return
        self.app.call_from_thread(self._loaded, profiles, readiness)

    def _load_failed(self):
        if not self.is_mounted:
            return
        self.load_failed = True
        self._detail()

    def _loaded(self, profiles, readiness):
        if not self.is_mounted:
            return
        self.catalog_loaded = True
        self.profiles = profiles
        self.readiness = readiness
        self._refresh_results()

    def _selected(self):
        index = self.query_one("#connection-results", OptionList).highlighted
        return (
            self.matching_profiles[index]
            if index is not None and 0 <= index < len(self.matching_profiles)
            else None
        )

    def _refresh_results(self, *, keep_id: str = ""):
        query = self.query_one("#connection-search", Input).value
        self.matching_profiles = filter_connections(
            self.profiles, query, self.favorites, self.recent
        )
        options = self.query_one("#connection-results", OptionList)
        options.clear_options()
        for profile in self.matching_profiles:
            marker = "★ " if profile.id in self.favorites else "  "
            suffix = " · recent" if profile.id in self.recent else ""
            options.add_option(Option(Text(f"{marker}{profile.label}{suffix}"), id=profile.id))
        if self.matching_profiles:
            options.highlighted = next(
                (i for i, p in enumerate(self.matching_profiles) if p.id == keep_id), 0
            )
        self._detail()

    def _detail(self):
        selected = self._selected()
        text = Text()
        if selected:
            text.append(selected.label + "\n", style="bold")
            text.append(selected.description + "\n")
            command = (
                selected.id.replace("acp:", "acp ", 1)
                if selected.id.startswith("acp:")
                else selected.id
            )
            text.append(f":connect {command}")
            available, hint, verify = self.readiness.get(selected.id, (True, "", False))
            if not available:
                text.append(
                    "\nSetup: " + (hint or "Install/configure this route before connecting")
                )
            elif verify:
                text.append("\nInstalled; account access is verified on first use")
            if selected.badges:
                text.append("\n" + " · ".join(selected.badges))
        elif self.load_failed:
            text.append("Could not load the catalog. Go back and retry :connect search.")
        elif self.catalog_loaded:
            text.append("No matching connections. Try a shorter search or clear the filter.")
        else:
            text.append("Loading local connection catalog…")
        self.query_one("#connection-detail", Static).update(text)
        self.query_one("#connection-detail-scroll").scroll_home(animate=False)
        self.query_one("#connection-select", Button).disabled = selected is None
        favorite = self.query_one("#connection-favorite", Button)
        favorite.disabled = selected is None
        favorite.label = "Unfavorite" if selected and selected.id in self.favorites else "Favorite"

    @on(Input.Changed, "#connection-search")
    def search_changed(self):
        self._refresh_results()

    @on(OptionList.OptionHighlighted, "#connection-results")
    def highlighted(self):
        self._detail()

    @on(Input.Submitted, "#connection-search")
    @on(OptionList.OptionSelected, "#connection-results")
    @on(Button.Pressed, "#connection-select")
    def select(self):
        selected = self._selected()
        if selected:
            self.dismiss(selected.id)

    @on(Button.Pressed, "#connection-favorite")
    def action_favorite(self):
        selected = self._selected()
        if not selected:
            return
        if selected.id in self.favorites:
            self.favorites.remove(selected.id)
        else:
            self.favorites.append(selected.id)
        try:
            set_connection_favorites(self.favorites, cwd=self.cwd)
        except OSError:
            self.notify(
                "Favorite could not be saved. Check project directory permissions.",
                severity="warning",
            )
        self._refresh_results(keep_id=selected.id)

    @on(Button.Pressed, "#connection-last")
    def reconnect_last(self):
        self.dismiss("__last__")

    def action_next(self):
        self.query_one("#connection-results", OptionList).action_cursor_down()

    def action_previous(self):
        self.query_one("#connection-results", OptionList).action_cursor_up()

    def action_close(self):
        self.dismiss(None)
