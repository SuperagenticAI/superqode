"""Connect an A2A agent from its published Agent Card.

The card is remote, so this screen does the two steps that ordering forces:
take an origin and an optional Bearer, then show the skills the card
advertises. Discovery runs in a worker because an agent that never answers
must not freeze the terminal.
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
class A2AConnectResult:
    """The agent the user chose to keep."""

    url: str
    token: str = ""
    name: str = ""
    binding: str = ""
    protocol_version: str = ""
    task_text: str = ""


@dataclass(frozen=True)
class _Row:
    """One skill advertised on the Agent Card."""

    id: str
    name: str
    description: str


def _origin(url: str) -> str:
    """Strip a pasted well-known card path so the client can append its own."""
    from superqode.a2a.connection import normalize_url

    return normalize_url(url)


class A2AConnectScreen(Screen[A2AConnectResult | None]):
    """Origin first, then the skills the Agent Card answers with."""

    BINDINGS = [
        Binding("escape", "close", "Back"),
        Binding("enter", "advance", "Connect / Use", priority=True),
        Binding("r", "reconnect", "Reconnect", show=False),
    ]

    CSS = """
    /* Every surface is painted black. Textual gives Input, OptionList and
       Button their own grey panels otherwise, which read as a different app. */
    A2AConnectScreen {
        background: #000000;
        color: #e6e6e6;
    }
    A2AConnectScreen > * { background: #000000; }
    #a2a-header { height: auto; padding: 1 2 0 2; background: #000000; }
    #a2a-title { text-style: bold; color: #7c3aed; background: #000000; }
    #a2a-subtitle { color: #8a8a8a; background: #000000; }
    #a2a-address { height: auto; padding: 1 2 0 2; background: #000000; }
    #a2a-url {
        width: 1fr;
        background: #000000;
        color: #e6e6e6;
        border: tall #2a2a2a;
    }
    #a2a-url:focus { border: tall #7c3aed; background: #000000; }
    #a2a-token {
        width: 28;
        margin-left: 1;
        background: #000000;
        color: #e6e6e6;
        border: tall #2a2a2a;
    }
    #a2a-token:focus { border: tall #7c3aed; background: #000000; }
    #a2a-message-row { height: auto; padding: 1 2 0 2; background: #000000; }
    #a2a-message {
        width: 1fr;
        background: #000000;
        color: #e6e6e6;
        border: tall #2a2a2a;
    }
    #a2a-message:focus { border: tall #7c3aed; background: #000000; }
    #a2a-hint { padding: 0 2 0 2; height: auto; color: #5a5a5a; background: #000000; }
    #a2a-status { padding: 1 2 0 2; height: auto; color: #8a8a8a; background: #000000; }
    #a2a-list {
        height: 1fr;
        margin: 1 2 0 2;
        background: #000000;
        border: round #2a2a2a;
        scrollbar-background: #000000;
        scrollbar-color: #2a2a2a;
    }
    #a2a-list > .option-list--option-highlighted {
        background: #1a1030;
        color: #e6e6e6;
    }
    #a2a-list:focus > .option-list--option-highlighted {
        background: #241542;
        color: #ffffff;
    }
    #a2a-inspect {
        height: 7;
        margin: 1 2 0 2;
        background: #000000;
        color: #8a8a8a;
        border: round #2a2a2a;
    }
    #a2a-actions { height: auto; padding: 0 2 1 2; background: #000000; }
    #a2a-actions Button {
        margin-right: 1;
        background: #000000;
        color: #e6e6e6;
        border: tall #2a2a2a;
    }
    #a2a-actions Button:hover { background: #141414; }
    #a2a-actions Button.-primary { background: #000000; border: tall #7c3aed; color: #b794f6; }
    #a2a-connect { background: #000000; border: tall #7c3aed; color: #b794f6; }
    Footer { background: #000000; }
    """

    def __init__(
        self,
        *,
        url: str,
        default_url: str,
        token: str = "",
    ) -> None:
        super().__init__()
        self._url = url or default_url
        self._default_url = default_url
        self._token = token
        self._name = ""
        self._binding = ""
        self._protocol_version = ""
        self._task_text = ""
        self._rows: list[_Row] = []
        self._busy = False
        self._connected = False

    def compose(self) -> ComposeResult:
        with Vertical(id="a2a-header"):
            yield Static("Agent2Agent", id="a2a-title")
            yield Static(
                "Talk to a remote agent from its published Agent Card. The "
                "agent owns its model, its tools, and its execution.",
                id="a2a-subtitle",
            )
        with Horizontal(id="a2a-address"):
            yield Input(
                value=self._url,
                placeholder="https://your-agent",
                id="a2a-url",
            )
            yield Input(
                value=self._token,
                placeholder="optional bearer",
                password=True,
                id="a2a-token",
            )
            yield Button("Connect", id="a2a-connect", variant="primary")
        yield Static(
            "Leave the token empty when the card is open. Bearer is sent as "
            "Authorization.",
            id="a2a-hint",
        )
        with Horizontal(id="a2a-message-row"):
            yield Input(
                placeholder="optional test message",
                id="a2a-message",
            )
        yield Static("", id="a2a-status")
        yield OptionList(id="a2a-list")
        yield Static(
            "Binding choice and HTTP appear here.",
            id="a2a-inspect",
        )
        with Horizontal(id="a2a-actions"):
            yield Button("Use", id="a2a-use", variant="primary")
            yield Button("Send", id="a2a-send")
            yield Button("Check", id="a2a-check")
            yield Button("Back", id="a2a-close")
        yield Footer()

    def on_mount(self) -> None:
        self._set_status(
            f"Enter an agent origin, or press Connect for {self._default_url}",
        )
        self.query_one("#a2a-url", Input).focus()

    # -- discovery ---------------------------------------------------------

    @work(exclusive=True)
    async def _discover(self, url: str) -> None:
        """Fetch the Agent Card without blocking the terminal."""
        from superqode.a2a.client import A2AClient, A2AClientError, AgentNotFoundError

        self._busy = True
        self._set_status(f"Connecting to {url} ...")
        token = self._current_token()
        inspect_log = None
        try:
            async with A2AClient(
                url, bearer_token=token or None, timeout=180.0
            ) as client:
                inspect_log = client.inspect
                card = await client.get_agent_card()
                binding = client._binding or ""
                version = client._protocol_version or ""
        except (A2AClientError, AgentNotFoundError) as exc:
            self._busy = False
            self._show_inspect(getattr(exc, "inspect", None) or inspect_log)
            self._fail(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - any transport failure is the user's answer
            self._busy = False
            self._show_inspect(inspect_log)
            self._fail(f"Could not reach {url}: {exc}")
            return

        self._busy = False
        self._show_inspect(inspect_log)
        self._apply_card(url, card, binding, version)

    @work(exclusive=True)
    async def _send(self, url: str, message: str) -> None:
        """Send one message to the connected agent and show the reply."""
        from superqode.a2a.client import A2AClient, A2AClientError, AgentNotFoundError

        self._busy = True
        self._set_status(f"Sending to {url} ...")
        token = self._current_token()
        inspect_log = None
        try:
            async with A2AClient(
                url, bearer_token=token or None, timeout=180.0
            ) as client:
                inspect_log = client.inspect
                if not self._connected:
                    card = await client.get_agent_card()
                    self._apply_card(
                        url,
                        card,
                        client._binding or "",
                        client._protocol_version or "",
                    )
                task = await client.send_message(message)
        except (A2AClientError, AgentNotFoundError) as exc:
            self._busy = False
            self._show_inspect(getattr(exc, "inspect", None) or inspect_log)
            self._set_status(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - any transport failure is the user's answer
            self._busy = False
            self._show_inspect(inspect_log)
            self._set_status(f"Send failed: {exc}")
            return

        self._busy = False
        self._show_inspect(inspect_log)
        text = ""
        if task.artifacts and task.artifacts[0].parts:
            text = task.artifacts[0].parts[0].text or ""
        state = (
            task.status.state.value
            if hasattr(task.status.state, "value")
            else str(task.status.state)
        )
        self._task_text = text
        preview = text.strip().replace("\n", " ")
        if len(preview) > 240:
            preview = preview[:237] + "..."
        if preview:
            self._set_status(f"{state}: {preview}")
        else:
            self._set_status(f"{state}: (empty reply)")

    @work(exclusive=True)
    async def _check(self, url: str) -> None:
        """Run the client checks without blocking the terminal."""
        from superqode.a2a.conformance import run_a2a_conformance
        from superqode.a2a.connection import A2ASettings

        self._busy = True
        self._set_status(f"Checking {url} ...")
        token = self._current_token()
        probe = self._current_message() or None
        try:
            report = await run_a2a_conformance(
                A2ASettings(url=url, token=token),
                message=probe,
            )
        except Exception as exc:  # noqa: BLE001 - any failure is the user's answer
            self._busy = False
            self._fail(f"Check failed: {exc}")
            return

        self._busy = False
        self._show_inspect(report.inspect)
        self._url = report.url
        self._connected = bool(report.binding)
        self._name = report.name
        self._binding = report.binding
        self._protocol_version = report.protocol_version
        self._set_status(
            f"A2A client checks: {'PASS' if report.passed else 'FAIL'}"
            + (f" · {report.name}" if report.name else "")
        )
        self._render_checks(report.checks)

    def _render_checks(self, checks) -> None:
        option_list = self.query_one("#a2a-list", OptionList)
        option_list.clear_options()
        self._rows = []
        for check in checks:
            text = Text()
            if check.skipped:
                mark, style = "skip", "#5a5a5a"
            elif check.passed:
                mark, style = "pass", "#8a8a8a"
            else:
                mark, style = "FAIL", "bold"
            text.append(f"{mark}  {check.name}\n", style=style)
            if check.detail:
                text.append(f"  {check.detail}", style="#5a5a5a")
            option_list.add_option(Option(text, id=check.name))
        if checks:
            option_list.highlighted = 0
            option_list.focus()

    def _apply_card(self, url: str, card, binding: str, version: str) -> None:
        self._url = url
        self._name = card.name
        self._binding = binding
        self._protocol_version = version
        self._connected = True
        self._rows = [
            _Row(
                id=skill.id,
                name=skill.name or skill.id,
                description=skill.description or "",
            )
            for skill in card.skills
        ]
        label = f"{card.name} ({card.version})"
        if binding:
            label += f" · {binding} {version or ''}".rstrip()
        skill_count = len(self._rows)
        if skill_count:
            label += f" · {skill_count} skill{'s' if skill_count != 1 else ''}"
        else:
            label += " · no skills advertised"
        self._set_status(label + ". Use to save, or send a test message.")
        self._render_rows()

    def _render_rows(self) -> None:
        option_list = self.query_one("#a2a-list", OptionList)
        option_list.clear_options()
        for row in self._rows:
            text = Text()
            text.append(f"{row.name}\n", style="bold")
            if row.description:
                text.append(f"  {row.description}\n", style="#8a8a8a")
            text.append(f"  {row.id}", style="#5a5a5a")
            option_list.add_option(Option(text, id=row.id))
        if self._rows:
            option_list.highlighted = 0
            option_list.focus()
        else:
            self.query_one("#a2a-message", Input).focus()

    def _set_status(self, message: str) -> None:
        self.query_one("#a2a-status", Static).update(message)

    def _show_inspect(self, inspect_log) -> None:
        """Replace the inspect pane with the latest trace summaries."""
        widget = self.query_one("#a2a-inspect", Static)
        if inspect_log is None:
            return
        if hasattr(inspect_log, "lines"):
            lines = inspect_log.lines()
        elif isinstance(inspect_log, dict):
            lines = [
                str(event.get("summary") or "")
                for event in inspect_log.get("events") or []
                if isinstance(event, dict)
            ]
        else:
            lines = []
        if not lines:
            return
        widget.update("\n".join(lines[-12:]))

    def _fail(self, message: str) -> None:
        self._connected = False
        self._rows = []
        self.query_one("#a2a-list", OptionList).clear_options()
        self._set_status(message)
        self.query_one("#a2a-url", Input).focus()

    def _current_token(self) -> str:
        return self.query_one("#a2a-token", Input).value.strip()

    def _current_message(self) -> str:
        return self.query_one("#a2a-message", Input).value.strip()

    # -- actions -----------------------------------------------------------

    def action_close(self) -> None:
        self.dismiss(None)

    def action_reconnect(self) -> None:
        self._connect_from_input()

    def action_advance(self) -> None:
        """Enter connects while the address is focused, and saves after."""
        if self._busy:
            return
        focused = self.focused
        message_input = self.query_one("#a2a-message", Input)
        if focused is message_input:
            if self._current_message():
                self._send_from_input()
            elif not self._connected:
                self._connect_from_input()
            else:
                self._use_connected()
            return
        if focused is self.query_one("#a2a-url", Input) or not self._connected:
            self._connect_from_input()
            return
        self._use_connected()

    def _connect_from_input(self) -> None:
        url = _origin(
            self.query_one("#a2a-url", Input).value.strip() or self._default_url
        )
        self.query_one("#a2a-url", Input).value = url
        self._discover(url)

    def _send_from_input(self) -> None:
        message = self._current_message()
        if not message:
            self.query_one("#a2a-message", Input).focus()
            return
        url = _origin(
            self.query_one("#a2a-url", Input).value.strip() or self._url or self._default_url
        )
        self.query_one("#a2a-url", Input).value = url
        self._send(url, message)

    def _check_from_input(self) -> None:
        if self._busy:
            return
        url = _origin(
            self.query_one("#a2a-url", Input).value.strip() or self._url or self._default_url
        )
        self.query_one("#a2a-url", Input).value = url
        self._check(url)

    def _use_connected(self) -> None:
        if not self._connected:
            self._connect_from_input()
            return
        self.dismiss(
            A2AConnectResult(
                url=self._url,
                token=self._current_token(),
                name=self._name,
                binding=self._binding,
                protocol_version=self._protocol_version,
                task_text=self._task_text,
            )
        )

    @on(Button.Pressed, "#a2a-connect")
    def _on_connect(self) -> None:
        self._connect_from_input()

    @on(Button.Pressed, "#a2a-use")
    def _on_use(self) -> None:
        self._use_connected()

    @on(Button.Pressed, "#a2a-send")
    def _on_send(self) -> None:
        self._send_from_input()

    @on(Button.Pressed, "#a2a-check")
    def _on_check(self) -> None:
        self._check_from_input()

    @on(Button.Pressed, "#a2a-close")
    def _on_close(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted, "#a2a-url")
    def _on_submit(self) -> None:
        self._connect_from_input()

    @on(Input.Submitted, "#a2a-token")
    def _on_token_submit(self) -> None:
        self._connect_from_input()

    @on(Input.Submitted, "#a2a-message")
    def _on_message_submit(self) -> None:
        self._send_from_input()
