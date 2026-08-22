"""Connect a Unified Harness Protocol server and pick one of its harnesses.

A UHP server is a remote catalog, so this screen does the two steps that
ordering forces: take an address, then show what came back.  Discovery runs in
a worker because a server that never answers must not freeze the terminal.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, OptionList, Static
from textual.widgets.option_list import Option


@dataclass(frozen=True)
class UHPConnectResult:
    """The server and harness the user chose."""

    base_url: str
    harness_id: str
    harness_name: str = ""
    max_output_tokens: int | None = None


@dataclass(frozen=True)
class _Row:
    """One harness advertised by the server."""

    id: str
    name: str
    base_label: str
    model: str


class UHPConnectScreen(Screen[UHPConnectResult | None]):
    """Address first, then the catalog the server answers with."""

    BINDINGS = [
        Binding("escape", "close", "Back"),
        Binding("enter", "advance", "Connect / Use", priority=True),
        Binding("r", "reconnect", "Reconnect", show=False),
    ]

    CSS = """
    /* Every surface is painted black. Textual gives Input, OptionList and
       Button their own grey panels otherwise, which read as a different app. */
    UHPConnectScreen {
        background: #000000;
        color: #e6e6e6;
    }
    UHPConnectScreen > * { background: #000000; }
    #uhp-header { height: auto; padding: 1 2 0 2; background: #000000; }
    #uhp-title { text-style: bold; color: #7c3aed; background: #000000; }
    #uhp-subtitle { color: #8a8a8a; background: #000000; }
    #uhp-address { height: auto; padding: 1 2 0 2; background: #000000; }
    #uhp-url {
        width: 1fr;
        background: #000000;
        color: #e6e6e6;
        border: tall #2a2a2a;
    }
    #uhp-url:focus { border: tall #7c3aed; background: #000000; }
    #uhp-cap {
        width: 18;
        margin-left: 1;
        background: #000000;
        color: #e6e6e6;
        border: tall #2a2a2a;
    }
    #uhp-cap:focus { border: tall #7c3aed; background: #000000; }
    #uhp-hint { padding: 0 2 0 2; height: auto; color: #5a5a5a; background: #000000; }
    #uhp-status { padding: 1 2 0 2; height: auto; color: #8a8a8a; background: #000000; }
    #uhp-list {
        height: 1fr;
        margin: 1 2;
        background: #000000;
        border: round #2a2a2a;
        scrollbar-background: #000000;
        scrollbar-color: #2a2a2a;
    }
    #uhp-list > .option-list--option-highlighted {
        background: #1a1030;
        color: #e6e6e6;
    }
    #uhp-list:focus > .option-list--option-highlighted {
        background: #241542;
        color: #ffffff;
    }
    #uhp-actions { height: auto; padding: 0 2 1 2; background: #000000; }
    #uhp-actions Button {
        margin-right: 1;
        background: #000000;
        color: #e6e6e6;
        border: tall #2a2a2a;
    }
    #uhp-actions Button:hover { background: #141414; }
    #uhp-actions Button.-primary { background: #000000; border: tall #7c3aed; color: #b794f6; }
    #uhp-connect { background: #000000; border: tall #7c3aed; color: #b794f6; }
    Footer { background: #000000; }
    """

    def __init__(
        self,
        *,
        base_url: str,
        default_url: str,
        max_output_tokens: int | None = None,
    ) -> None:
        super().__init__()
        self._url = base_url or default_url
        self._default_url = default_url
        self._cap = str(max_output_tokens) if max_output_tokens else ""
        self._rows: list[_Row] = []
        self._busy = False

    def compose(self) -> ComposeResult:
        with Vertical(id="uhp-header"):
            yield Static("Unified Harness Protocol", id="uhp-title")
            yield Static(
                "Run a harness that lives on a UHP server. The server owns the "
                "model, the tools, and the workspace.",
                id="uhp-subtitle",
            )
        with Horizontal(id="uhp-address"):
            yield Input(value=self._url, placeholder="https://your-server", id="uhp-url")
            yield Input(value=self._cap, placeholder="max tokens", id="uhp-cap")
            yield Button("Connect", id="uhp-connect", variant="primary")
        yield Static(
            "Leave max tokens empty to use the server's budget. Set it when a "
            "provider bills against the budget a task reserves.",
            id="uhp-hint",
        )
        yield Static("", id="uhp-status")
        yield OptionList(id="uhp-list")
        with Horizontal(id="uhp-actions"):
            yield Button("Use", id="uhp-use", variant="primary")
            yield Button("Back", id="uhp-close")
        yield Footer()

    def on_mount(self) -> None:
        self._set_status(
            f"Enter a server address, or press Connect for {self._default_url}",
        )
        self.query_one("#uhp-url", Input).focus()

    # -- discovery ---------------------------------------------------------

    @work(exclusive=True)
    async def _discover(self, base_url: str) -> None:
        """Fetch the catalog without blocking the terminal."""
        from superqode.harness.uhp_client import UHPClient, UHPError

        self._busy = True
        self._set_status(f"Connecting to {base_url} ...")
        version = ""
        conformance = ""
        try:
            async with UHPClient(base_url) as client:
                try:
                    discovery = await client.discover()
                    version = discovery.default_version
                    conformance = discovery.conformance_class
                except UHPError:
                    # Discovery is optional; a catalog is what this screen needs.
                    pass
                harnesses = await client.list_harnesses()
        except UHPError as exc:
            self._busy = False
            self._fail(f"{exc.message}")
            return
        except Exception as exc:  # noqa: BLE001 - any transport failure is the user's answer
            self._busy = False
            self._fail(f"Could not reach {base_url}: {exc}")
            return

        self._busy = False
        self._url = base_url
        self._rows = [
            _Row(
                id=harness.id,
                name=harness.name or harness.id,
                base_label=harness.base_label or harness.base,
                model=harness.default_model,
            )
            for harness in harnesses
        ]
        if not self._rows:
            self._fail("Connected, but this server advertises no harnesses.")
            return
        label = f"UHP {version or 'unknown'}"
        if conformance:
            label += f" ({conformance})"
        self._set_status(
            f"{label} · {len(self._rows)} harness"
            f"{'es' if len(self._rows) != 1 else ''}. Choose one."
        )
        self._render_rows()

    def _render_rows(self) -> None:
        option_list = self.query_one("#uhp-list", OptionList)
        option_list.clear_options()
        for row in self._rows:
            text = Text()
            text.append(f"{row.name}\n", style="bold")
            detail = row.base_label or "harness"
            if row.model:
                detail += f" · {row.model}"
            text.append(f"  {detail}\n", style="#8a8a8a")
            text.append(f"  {row.id}", style="#5a5a5a")
            option_list.add_option(Option(text, id=row.id))
        option_list.focus()
        if self._rows:
            option_list.highlighted = 0

    def _set_status(self, message: str) -> None:
        self.query_one("#uhp-status", Static).update(message)

    def _fail(self, message: str) -> None:
        self._rows = []
        self.query_one("#uhp-list", OptionList).clear_options()
        self._set_status(message)
        self.query_one("#uhp-url", Input).focus()

    # -- actions -----------------------------------------------------------

    def action_close(self) -> None:
        self.dismiss(None)

    def action_reconnect(self) -> None:
        self._connect_from_input()

    def action_advance(self) -> None:
        """Enter connects while the address is focused, and selects after."""
        if self._busy:
            return
        if self.focused is self.query_one("#uhp-url", Input) or not self._rows:
            self._connect_from_input()
            return
        self._use_highlighted()

    def _connect_from_input(self) -> None:
        url = self.query_one("#uhp-url", Input).value.strip() or self._default_url
        self.query_one("#uhp-url", Input).value = url
        self._discover(url)

    def _token_cap(self) -> int | None:
        """Read the cap field, treating anything unusable as unset."""
        try:
            value = int(self.query_one("#uhp-cap", Input).value.strip())
        except (ValueError, TypeError):
            return None
        return value if value > 0 else None

    def _use_highlighted(self) -> None:
        option_list = self.query_one("#uhp-list", OptionList)
        index = option_list.highlighted
        if index is None or not (0 <= index < len(self._rows)):
            return
        row = self._rows[index]
        self.dismiss(UHPConnectResult(self._url, row.id, row.name, self._token_cap()))

    @on(Button.Pressed, "#uhp-connect")
    def _on_connect(self) -> None:
        self._connect_from_input()

    @on(Button.Pressed, "#uhp-use")
    def _on_use(self) -> None:
        self._use_highlighted()

    @on(Button.Pressed, "#uhp-close")
    def _on_close(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted, "#uhp-url")
    def _on_submit(self) -> None:
        self._connect_from_input()

    @on(Input.Submitted, "#uhp-cap")
    def _on_cap_submit(self) -> None:
        self._connect_from_input()

    @on(OptionList.OptionSelected, "#uhp-list")
    def _on_option(self, event: OptionList.OptionSelected) -> None:
        """A click selects, matching the Hub's mouse behaviour."""
        del event
        self._use_highlighted()
