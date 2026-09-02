"""Connect an A2A agent from its published Agent Card.

Reached from ``:connect`` → Protocols → A2A, or ``:connect a2a``. The card
is remote, so this screen takes an origin and the credential the card asks
for (none, Bearer, API key, HTTP Basic, OAuth, or mutual TLS), then shows
the skills it advertises. Discovery runs in a worker because an agent that
never answers must not freeze the terminal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Button, Footer, Input, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from superqode.a2a.reply import task_reply as _task_reply


@dataclass(frozen=True)
class A2AConnectResult:
    """The agent the user chose to keep."""

    url: str
    token: str = ""
    name: str = ""
    binding: str = ""
    protocol_version: str = ""
    task_text: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    cert: str = ""
    key: str = ""


@dataclass(frozen=True)
class _Row:
    """One skill advertised on the Agent Card."""

    id: str
    name: str
    description: str
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ChatTurn:
    """One line in the on-screen conversation."""

    role: str
    text: str


def _origin(url: str) -> str:
    """Strip a pasted well-known card path so the client can append its own."""
    from superqode.a2a.connection import normalize_url

    return normalize_url(url)


# A2A 1.0 JSON-RPC streams a protobuf oneof (`task` / `artifactUpdate` /
# `statusUpdate`). A2A 0.3 puts `kind: artifact-update` on the result itself.
_STREAM_WRAPPERS = (
    "artifactUpdate",
    "statusUpdate",
    "task",
    "artifact_update",
    "status_update",
    "artifact-update",
    "status-update",
)


def _stream_payload(event) -> dict:
    """Unwrap a JSON-RPC stream event down to the result object."""
    data = getattr(event, "data", None)
    if not isinstance(data, dict):
        return {}
    result = data.get("result")
    if not isinstance(result, dict):
        return data
    for key in _STREAM_WRAPPERS:
        nested = result.get(key)
        if isinstance(nested, dict):
            return nested
    return result


def _text_parts(node) -> list[str]:
    """Collect text from A2A 0.3 and 1.0 message, artifact, and status shapes."""
    if isinstance(node, str) and node.strip():
        return [node]
    if not isinstance(node, dict):
        return []
    texts: list[str] = []
    if isinstance(node.get("text"), str) and node["text"]:
        texts.append(node["text"])
    for part in node.get("parts") or []:
        if isinstance(part, dict) and part.get("text"):
            texts.append(str(part["text"]))
        elif isinstance(part, str) and part.strip():
            texts.append(part)
    message = node.get("message")
    if message:
        texts.extend(_text_parts(message))
    artifact = node.get("artifact")
    if isinstance(artifact, dict):
        texts.extend(_text_parts(artifact))
    for item in node.get("artifacts") or []:
        texts.extend(_text_parts(item))
    status = node.get("status")
    if isinstance(status, dict):
        texts.extend(_text_parts(status))
    for key in _STREAM_WRAPPERS:
        nested = node.get(key)
        if isinstance(nested, dict):
            texts.extend(_text_parts(nested))
    collapsed: list[str] = []
    for item in texts:
        if not collapsed or collapsed[-1] != item:
            collapsed.append(item)
    return collapsed


def _coalesce_stream_text(chunks: list[str], piece: str) -> None:
    """Keep new deltas; drop completed-status echoes of the same artifact."""
    if not piece or not piece.strip():
        return
    stripped = piece.strip()
    if not chunks:
        chunks.append(piece)
        return
    joined = "".join(chunks)
    if stripped == joined.strip() or stripped == chunks[-1].strip():
        return
    if stripped in joined:
        return
    if joined.strip() and joined.strip() in stripped:
        chunks.clear()
        chunks.append(piece)
        return
    chunks.append(piece)


def _stream_delta(event) -> str:
    """Pull visible text out of a streaming event."""
    data = getattr(event, "data", None)
    if isinstance(data, str):
        return data
    return "".join(_text_parts(_stream_payload(event)))


def _stream_context_id(event) -> str:
    """Read contextId from a streaming event, if the agent sent one."""
    payload = _stream_payload(event)
    value = payload.get("contextId") or payload.get("context_id")
    return str(value) if value else ""


def _is_catalogue_card(rows: list[_Row]) -> bool:
    """True when the card only advertises a shortlist, not a runnable harness."""
    if not rows:
        return False
    return all(
        "shortlist" in row.id.casefold() or "shortlist" in row.name.casefold() for row in rows
    )


def _copy_text(text: str) -> bool:
    """Push text to the OS clipboard. OSC 52 is attempted by the caller too."""
    import subprocess
    import sys

    if not text:
        return False
    data = text.encode("utf-8")
    if sys.platform == "darwin":
        commands = [["pbcopy"]]
    elif sys.platform.startswith("linux"):
        commands = [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
    elif sys.platform.startswith("win"):
        commands = [["clip"]]
    else:
        commands = []
    for cmd in commands:
        try:
            proc = subprocess.run(cmd, input=data, check=False)
            if proc.returncode == 0:
                return True
        except FileNotFoundError:
            continue
        except Exception:  # noqa: BLE001 - clipboard backends are best-effort
            continue
    return False


_HINT = (
    "Empty credential is the public catalogue (anonymous, no model). "
    "For a real model chat, get a SUPERQODE_API_KEY at https://superqode.dev "
    "and paste it here, or export SUPERQODE_API_KEY."
)

_THINK_FRAMES = ("◇ ◇ ◇", "◆ ◇ ◇", "◇ ◆ ◇", "◇ ◇ ◆", "◇ ◆ ◇", "◆ ◇ ◇")
_THINK_COLORS = ("#e9d5ff", "#d8b4fe", "#c4b5fd", "#a78bfa", "#7c3aed", "#a78bfa")


class _A2AThinkingBar(Static):
    """SuperQode-style thinking bar: diamond pulse and a block sweep. No blue."""

    def __init__(self) -> None:
        super().__init__("", id="a2a-thinking")
        self._tick = 0
        self._label = "Thinking"
        self._timer: Timer | None = None
        self.display = False

    def start(self, label: str = "Thinking") -> None:
        self._label = label
        self._tick = 0
        self.display = True
        if self._timer is None:
            self._timer = self.set_interval(0.12, self._animate)
        self._paint()

    def stop(self) -> None:
        self.display = False
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self.update("")

    def _animate(self) -> None:
        self._tick += 1
        self._paint()

    def _paint(self) -> None:
        frame = _THINK_FRAMES[self._tick % len(_THINK_FRAMES)]
        color = _THINK_COLORS[self._tick % len(_THINK_COLORS)]
        width = max(self.size.width, 24)
        bar_width = max(width - 22, 12)
        pos = self._tick % bar_width
        bar = Text()
        for index in range(bar_width):
            dist = min((index - pos) % bar_width, (pos - index) % bar_width)
            if dist == 0:
                bar.append("█", style="bold #e9d5ff")
            elif dist == 1:
                bar.append("▓", style="#c4b5fd")
            elif dist == 2:
                bar.append("▒", style="#a78bfa")
            elif dist <= 4:
                bar.append("░", style="#7c3aed")
            else:
                bar.append("─", style="#1a1a1a")
        line = Text()
        line.append("💭 ", style="bold #e9d5ff")
        line.append(f"{frame}  ", style=f"bold {color}")
        line.append(f"{self._label}  ", style="italic #d4d4d4")
        line.append_text(bar)
        self.update(line)


class A2AConnectScreen(Screen[A2AConnectResult | None]):
    """Origin first, then the skills the Agent Card answers with."""

    BINDINGS = [
        Binding("escape", "cancel_or_close", "Back"),
        Binding("enter", "advance", "Connect / Use", priority=True),
        Binding("o", "toggle_oauth", "OAuth"),
        Binding("h", "toggle_headers", "Headers"),
        Binding("t", "toggle_tls", "mTLS"),
        Binding("i", "toggle_inspect", "Inspect"),
        Binding("y", "copy_reply", "Copy"),
        Binding("ctrl+y", "copy_reply", "Copy", show=False, priority=True),
        Binding("r", "resend", "Resend"),
        Binding("n", "clear_chat", "New chat"),
        Binding("l", "logout", "Logout"),
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
    #a2a-title { text-style: bold; color: #c4b5fd; background: #000000; }
    #a2a-subtitle { color: #d4d4d4; background: #000000; }
    #a2a-address, #a2a-credential-row, #a2a-options, #a2a-extra-row,
    #a2a-tls-row, #a2a-message-row {
        height: auto;
        padding: 0 2 1 2;
        background: #000000;
    }
    #a2a-address { padding: 1 2 1 2; }
    #a2a-options Button {
        margin-right: 1;
        min-width: 12;
        background: #1a1a1a;
        color: #d8d8d8;
        border: tall #3a3a3a;
    }
    #a2a-options Button:hover { background: #2a1a40; }
    #a2a-options Button.on {
        background: #3b1d7a;
        color: #f3e8ff;
        border: tall #c4b5fd;
        text-style: bold;
    }
    #a2a-oauth, #a2a-headers-btn, #a2a-tls-btn, #a2a-inspect-btn { min-width: 12; }
    #a2a-headers-panel, #a2a-tls-panel, #a2a-inspect-panel {
        display: none;
        height: auto;
        background: #000000;
    }
    #a2a-headers-panel.visible, #a2a-tls-panel.visible, #a2a-inspect-panel.visible {
        display: block;
    }
    #a2a-url, #a2a-token, #a2a-headers, #a2a-cert, #a2a-key, #a2a-message {
        background: #000000;
        color: #f0f0f0;
        border: tall #2a2a2a;
    }
    A2AConnectScreen .input--placeholder {
        color: #a8a8a8;
    }
    #a2a-url { width: 1fr; }
    #a2a-token { width: 1fr; }
    #a2a-headers { width: 1fr; }
    #a2a-cert, #a2a-key { width: 1fr; }
    #a2a-key { margin-left: 1; }
    #a2a-message { width: 1fr; }
    #a2a-url:focus, #a2a-token:focus, #a2a-headers:focus,
    #a2a-cert:focus, #a2a-key:focus, #a2a-message:focus {
        border: tall #7c3aed;
        background: #000000;
    }
    A2AConnectScreen.connected #a2a-subtitle,
    A2AConnectScreen.connected #a2a-hint {
        display: none;
    }
    A2AConnectScreen.connected #a2a-header,
    A2AConnectScreen.connected #a2a-address,
    A2AConnectScreen.connected #a2a-credential-row,
    A2AConnectScreen.connected #a2a-options {
        padding-bottom: 0;
    }
    #a2a-hint { padding: 0 2 1 2; height: auto; color: #c8c8c8; background: #000000; }
    #a2a-status { padding: 0 2 0 2; height: auto; color: #e6e6e6; background: #000000; }
    #a2a-thinking {
        height: 1;
        margin: 0 2;
        padding: 0 1;
        background: #000000;
        color: #e9d5ff;
        display: none;
    }
    #a2a-body {
        height: 1fr;
        background: #000000;
    }
    #a2a-examples {
        height: auto;
        max-height: 4;
        margin: 0 2 0 2;
        background: #000000;
        color: #d4d4d4;
        border: round #2a2a2a;
        display: none;
    }
    #a2a-examples.visible { display: block; }
    #a2a-chat {
        height: 1fr;
        min-height: 12;
        margin: 1 2 0 2;
        background: #000000;
        color: #e6e6e6;
        border: round #2a2a2a;
        scrollbar-background: #000000;
        scrollbar-color: #2a2a2a;
        overflow-x: hidden;
        overflow-y: auto;
    }
    #a2a-inspect {
        height: auto;
        max-height: 6;
        margin: 1 2 0 2;
        background: #000000;
        color: #d4d4d4;
        border: round #2a2a2a;
    }
    #a2a-actions { height: auto; padding: 0 2 1 2; background: #000000; }
    #a2a-actions Button, #a2a-connect {
        margin-right: 1;
        background: #000000;
        color: #e6e6e6;
        border: tall #2a2a2a;
    }
    #a2a-actions Button:hover, #a2a-connect:hover { background: #141414; }
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
        headers: dict[str, str] | None = None,
        cert: str = "",
        key: str = "",
    ) -> None:
        super().__init__()
        self._url = url
        self._default_url = default_url
        self._token = token
        self._headers = dict(headers or {})
        self._cert = cert
        self._key = key
        self._oauth = True
        self._name = ""
        self._binding = ""
        self._protocol_version = ""
        self._task_text = ""
        self._auth_line = ""
        self._rows: list[_Row] = []
        self._chat: list[_ChatTurn] = []
        self._busy = False
        self._connected = False
        self._show_headers = bool(self._headers)
        self._show_tls = bool(self._cert or self._key)
        self._inspect_open = False
        self._example_prompts: list[str] = []
        self._context_id = ""
        self._streaming = False
        self._catalogue_only = False
        self._generation = 0
        self._last_sent = ""
        self._cold_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        from superqode.a2a.connection import format_header_line

        with Vertical(id="a2a-header"):
            yield Static(
                Text.assemble(
                    ("Agent", "bold #e9d5ff"),
                    ("2", "bold #c4b5fd"),
                    ("Agent", "bold #a78bfa"),
                    (" (", "#c8c8c8"),
                    ("A2A", "bold #7c3aed"),
                    (")", "#c8c8c8"),
                ),
                id="a2a-title",
            )
            yield Static(
                "Talk to a remote agent from its published Agent Card.",
                id="a2a-subtitle",
            )
        with Horizontal(id="a2a-address"):
            yield Input(
                value=self._url,
                placeholder="https://agent.example",
                id="a2a-url",
            )
            yield Button("Connect", id="a2a-connect", variant="primary")
        with Horizontal(id="a2a-credential-row"):
            yield Input(
                value=self._token,
                placeholder="SUPERQODE_API_KEY (empty = catalogue)",
                password=True,
                id="a2a-token",
            )
        with Horizontal(id="a2a-options"):
            oauth = Button(self._oauth_label(), id="a2a-oauth")
            if self._oauth:
                oauth.add_class("on")
            yield oauth
            yield Button("Headers", id="a2a-headers-btn")
            yield Button("mTLS", id="a2a-tls-btn")
            yield Button("Inspect", id="a2a-inspect-btn")
        with Vertical(id="a2a-headers-panel"):
            with Horizontal(id="a2a-extra-row"):
                yield Input(
                    value=format_header_line(self._headers),
                    placeholder="extra headers  NAME:VALUE; NAME:VALUE",
                    id="a2a-headers",
                )
        with Vertical(id="a2a-tls-panel"):
            with Horizontal(id="a2a-tls-row"):
                yield Input(
                    value=self._cert,
                    placeholder="mTLS client cert PEM path",
                    id="a2a-cert",
                )
                yield Input(
                    value=self._key,
                    placeholder="mTLS client key PEM path",
                    password=True,
                    id="a2a-key",
                )
        with Vertical(id="a2a-inspect-panel"):
            yield Static(
                "Inspect: binding choice, advertised auth, and last HTTP.",
                id="a2a-inspect",
            )
            yield Button("Check", id="a2a-check")
        yield Static(_HINT, id="a2a-hint")
        yield Static("", id="a2a-status")
        with Vertical(id="a2a-body"):
            yield OptionList(id="a2a-examples")
            yield _A2AThinkingBar()
            yield RichLog(
                highlight=False,
                markup=False,
                wrap=True,
                auto_scroll=True,
                id="a2a-chat",
            )
        with Horizontal(id="a2a-message-row"):
            yield Input(
                placeholder="message to this agent, then Send",
                id="a2a-message",
            )
        with Horizontal(id="a2a-actions"):
            yield Button("Use", id="a2a-use", variant="primary")
            yield Button("Send", id="a2a-send")
            yield Button("Copy", id="a2a-copy")
            yield Button("Clear", id="a2a-clear")
            yield Button("Logout", id="a2a-logout")
            yield Button("Back", id="a2a-close")
        yield Footer()

    def on_mount(self) -> None:
        stored = self._stored_oauth_note(self._url)
        base = (
            "Paste an agent origin, then press Connect. "
            "Open Headers or mTLS when the card needs them."
        )
        self._set_status(f"{base} {stored}".strip())
        self.query_one("#a2a-url", Input).focus()
        self._sync_option_panels()

    def _oauth_label(self) -> str:
        return "OAuth on" if self._oauth else "OAuth off"

    def _refresh_oauth_button(self) -> None:
        self._set_chip("a2a-oauth", self._oauth, self._oauth_label())

    def _set_chip(self, widget_id: str, on: bool, label: str | None = None) -> None:
        try:
            button = self.query_one(f"#{widget_id}", Button)
            if label is not None:
                button.label = label
            button.set_class(on, "on")
        except Exception:  # noqa: BLE001 - screen may not be mounted in tests
            pass

    def _set_panel(self, panel_id: str, open_: bool) -> None:
        try:
            panel = self.query_one(f"#{panel_id}")
            panel.display = open_
            panel.set_class(open_, "visible")
        except Exception:  # noqa: BLE001
            pass

    def _sync_option_panels(self) -> None:
        self._set_chip("a2a-oauth", self._oauth, self._oauth_label())
        self._set_chip("a2a-headers-btn", self._show_headers)
        self._set_chip("a2a-tls-btn", self._show_tls)
        self._set_chip("a2a-inspect-btn", self._inspect_open)
        self._set_panel("a2a-headers-panel", self._show_headers)
        self._set_panel("a2a-tls-panel", self._show_tls)
        self._set_panel("a2a-inspect-panel", self._inspect_open)

    def action_toggle_headers(self) -> None:
        self._show_headers = not self._show_headers
        self._sync_option_panels()
        if self._show_headers:
            self._set_status("Headers open. NAME:VALUE; NAME:VALUE on each extra header.")
            try:
                self.query_one("#a2a-headers", Input).focus()
            except Exception:  # noqa: BLE001
                pass
        else:
            self._set_status("Headers hidden.")

    def action_toggle_tls(self) -> None:
        self._show_tls = not self._show_tls
        self._sync_option_panels()
        if self._show_tls:
            self._set_status("mTLS open. Paste client cert and key PEM paths.")
            try:
                self.query_one("#a2a-cert", Input).focus()
            except Exception:  # noqa: BLE001
                pass
        else:
            self._set_status("mTLS hidden.")

    def action_toggle_inspect(self) -> None:
        self._inspect_open = not self._inspect_open
        self._sync_option_panels()
        self._set_status("Inspect open." if self._inspect_open else "Inspect hidden.")

    def action_toggle_oauth(self) -> None:
        self._oauth = not self._oauth
        self._refresh_oauth_button()
        if self._oauth:
            self._set_status(
                "OAuth on. If the card requires it and no credential is set, "
                "Connect opens a browser or reuses a stored token."
            )
        else:
            self._set_status(
                "OAuth off. Connect still uses a stored token or client "
                "credentials; it will not open a browser."
            )

    # -- discovery ---------------------------------------------------------

    @work(exclusive=True)
    async def _discover(self, url: str) -> None:
        """Fetch the Agent Card without blocking the terminal."""
        from superqode.a2a.client import A2AClient, A2AClientError, AgentNotFoundError

        self._busy = True
        self._set_status(f"Connecting to {url} ...")
        self._thinking_bar().start("Connecting")
        self._arm_cold_start()
        token = self._current_token()
        inspect_log = None
        try:
            headers = self._current_headers()
            cert, key = self._tls_paths()
            async with A2AClient(
                url,
                bearer_token=token or None,
                extra_headers=headers or None,
                client_cert=cert or None,
                client_key=key or None,
                timeout=180.0,
            ) as client:
                inspect_log = client.inspect
                card = await client.get_agent_card()
                from superqode.a2a.oauth import satisfy_card_auth

                await satisfy_card_auth(
                    client,
                    url,
                    token=token,
                    headers=headers,
                    interactive=True,
                    skip_oauth=not self._oauth,
                    prompt_secret=self._prompt_secret,
                    on_status=self._set_status,
                )
                binding = client._binding or ""
                version = client._protocol_version or ""
                auth_line = self._auth_from_card(getattr(client, "_card_data", None), inspect_log)
        except (A2AClientError, AgentNotFoundError) as exc:
            self._busy = False
            self._disarm_cold_start()
            self._show_inspect(getattr(exc, "inspect", None) or inspect_log)
            self._thinking_bar().stop()
            self._fail(str(exc))
            return
        except ValueError as exc:
            self._busy = False
            self._disarm_cold_start()
            self._thinking_bar().stop()
            self._fail(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - any transport failure is the user's answer
            self._busy = False
            self._disarm_cold_start()
            self._thinking_bar().stop()
            self._show_inspect(inspect_log)
            self._fail(f"Could not reach {url}: {exc}")
            return

        self._busy = False
        self._disarm_cold_start()
        self._thinking_bar().stop()
        self._show_inspect(inspect_log)
        self._apply_card(url, card, binding, version, auth_line=auth_line)

    @work(exclusive=True)
    async def _send(self, url: str, message: str) -> None:
        """Send one message to the connected agent and show the reply."""
        from superqode.a2a.client import A2AClient, A2AClientError, AgentNotFoundError

        self._busy = True
        try:
            self.query_one("#a2a-message", Input).value = ""
        except Exception:  # noqa: BLE001
            pass
        self._set_status(f"Sending to {self._name or url} ...")
        self._thinking_bar().start(f"Thinking · {self._name or 'agent'}")
        self._arm_cold_start()
        token = self._current_token()
        inspect_log = None
        generation = self._generation + 1
        self._generation = generation
        self._last_sent = message
        try:
            headers = self._current_headers()
            cert, key = self._tls_paths()
            async with A2AClient(
                url,
                bearer_token=token or None,
                extra_headers=headers or None,
                client_cert=cert or None,
                client_key=key or None,
                timeout=180.0,
            ) as client:
                inspect_log = client.inspect
                card = await client.get_agent_card()
                from superqode.a2a.oauth import satisfy_card_auth

                await satisfy_card_auth(
                    client,
                    url,
                    token=token,
                    headers=headers,
                    interactive=True,
                    skip_oauth=not self._oauth,
                    prompt_secret=self._prompt_secret,
                    on_status=self._set_status,
                )
                if not self._connected:
                    self._apply_card(
                        url,
                        card,
                        client._binding or "",
                        client._protocol_version or "",
                        auth_line=self._auth_from_card(
                            getattr(client, "_card_data", None), inspect_log
                        ),
                    )
                self._write_you(message)
                text, task = await self._deliver(client, message)
        except (A2AClientError, AgentNotFoundError) as exc:
            if generation != self._generation:
                return
            self._busy = False
            self._disarm_cold_start()
            self._thinking_bar().stop()
            self._show_inspect(getattr(exc, "inspect", None) or inspect_log)
            self._write_note(str(exc))
            if "401" in str(exc) or "403" in str(exc) or "empty" in str(exc).lower():
                self._show_inspect_open()
            self._set_status(str(exc))
            return
        except ValueError as exc:
            if generation != self._generation:
                return
            self._busy = False
            self._disarm_cold_start()
            self._thinking_bar().stop()
            self._write_note(str(exc))
            self._set_status(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - any transport failure is the user's answer
            if generation != self._generation:
                return
            self._busy = False
            self._disarm_cold_start()
            self._thinking_bar().stop()
            self._show_inspect(inspect_log)
            self._write_note(f"Send failed: {exc}")
            self._set_status(f"Send failed: {exc}")
            return

        if generation != self._generation:
            return
        self._busy = False
        self._disarm_cold_start()
        self._thinking_bar().stop()
        self._show_inspect(inspect_log)
        if getattr(task, "context_id", None):
            self._context_id = str(task.context_id)
        state = (
            task.status.state.value
            if hasattr(task.status.state, "value")
            else str(task.status.state)
        )
        self._task_text = text
        self._chat.append(_ChatTurn(role="you", text=message))
        self._chat.append(_ChatTurn(role="agent", text=text or f"(empty reply · {state})"))
        self._set_examples_visible(False)
        who = self._name or "Agent"
        if text.strip():
            self._write_agent(who, text)
            if self._catalogue_only:
                self._write_note(
                    "Catalogue shortlist — no model. For a real model chat, get a "
                    "SUPERQODE_API_KEY at https://superqode.dev and paste it in the "
                    "credential field (or export SUPERQODE_API_KEY)."
                )
                self._set_status(
                    f"{who} replied ({state}). Catalogue. Get SUPERQODE_API_KEY for a real model chat."
                )
            else:
                self._set_status(f"{who} replied ({state}). n starts a new conversation.")
        else:
            self._write_note(f"{who} returned no text ({state}). Open Inspect for the HTTP trace.")
            self._set_status(f"{who} returned no text ({state}). Open Inspect for the HTTP trace.")
            self._show_inspect_open()
        try:
            self.query_one("#a2a-message", Input).focus()
        except Exception:  # noqa: BLE001
            pass

    async def _deliver(self, client, message: str):
        """Stream when the card allows it; otherwise one-shot. Keep contextId."""
        session = self._context_id or None
        if self._streaming:
            chunks: list[str] = []
            context_id = session or ""
            saw_event = False
            try:
                async for event in client.send_message_streaming(message, session_id=session):
                    if getattr(event, "type", "") == "error":
                        saw_event = False
                        break
                    saw_event = True
                    cid = _stream_context_id(event)
                    if cid:
                        context_id = cid
                    _coalesce_stream_text(chunks, _stream_delta(event))
            except Exception:  # noqa: BLE001 - fall back to a single reply
                saw_event = False
                chunks = []
            text = "".join(chunks)
            if saw_event and text.strip():
                task = type(
                    "Task",
                    (),
                    {
                        "context_id": context_id or session,
                        "status": type("S", (), {"state": "completed"})(),
                    },
                )()
                return text, task
        task = await client.send_message(message, session_id=session)
        return _task_reply(task), task

    @work(exclusive=True)
    async def _check(self, url: str) -> None:
        """Run the client checks without blocking the terminal."""
        from superqode.a2a.conformance import run_a2a_conformance
        from superqode.a2a.connection import A2ASettings

        self._busy = True
        self._set_status(f"Checking {url} ...")
        self._thinking_bar().start("Checking")
        token = self._current_token()
        probe = self._current_message() or None
        try:
            cert, key = self._tls_paths()
            report = await run_a2a_conformance(
                A2ASettings(
                    url=url,
                    token=token,
                    headers=self._current_headers(),
                    cert=cert,
                    key=key,
                ),
                message=probe,
            )
        except ValueError as exc:
            self._busy = False
            self._thinking_bar().stop()
            self._fail(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - any failure is the user's answer
            self._busy = False
            self._thinking_bar().stop()
            self._fail(f"Check failed: {exc}")
            return

        self._busy = False
        self._thinking_bar().stop()
        self._show_inspect(report.inspect)
        self._url = report.url
        self._connected = bool(report.binding)
        self._name = report.name
        self._binding = report.binding
        self._protocol_version = report.protocol_version
        self._set_status(
            f"A2A client checks: {'PASS' if report.passed else 'FAIL'}"
            + (f" · {report.name}" if report.name else "")
            + ". Client-fit, not an A2A TCK result."
        )
        self._render_checks(report.checks)

    def _render_checks(self, checks) -> None:
        self._rows = []
        lines = []
        for check in checks:
            if check.skipped:
                mark = "skip"
            elif check.passed:
                mark = "pass"
            else:
                mark = "FAIL"
            line = f"{mark}  {check.name}"
            if check.detail:
                line += f"\n  {check.detail}"
            lines.append(line)
        self._write_note("Client checks\n" + "\n".join(lines) if lines else "No checks.")

    def _apply_card(
        self, url: str, card, binding: str, version: str, *, auth_line: str = ""
    ) -> None:
        self._url = url
        self._name = card.name
        self._binding = binding
        self._protocol_version = version
        self._connected = True
        self.add_class("connected")
        self._auth_line = auth_line
        self._chat = []
        self._context_id = ""
        self._task_text = ""
        self._last_sent = ""
        self._streaming = bool(getattr(getattr(card, "capabilities", None), "streaming", False))
        self._rows = [
            _Row(
                id=skill.id,
                name=skill.name or skill.id,
                description=skill.description or "",
                examples=tuple(str(item) for item in (skill.examples or []) if str(item).strip()),
            )
            for skill in card.skills
        ]
        self._catalogue_only = _is_catalogue_card(self._rows)
        if auth_line:
            try:
                self.query_one("#a2a-hint", Static).update(auth_line + "  " + _HINT)
            except Exception:  # noqa: BLE001
                pass
        label = f"{card.name} ({card.version})"
        if binding:
            label += f" · {binding} {version or ''}".rstrip()
        if auth_line:
            label += f" · {auth_line}"
        skill_count = len(self._rows)
        if skill_count:
            label += f" · {skill_count} skill{'s' if skill_count != 1 else ''}"
        else:
            label += " · no skills advertised"
        stored = self._stored_oauth_note(url)
        lowered = auth_line.lower()
        if "header" in lowered or "query" in lowered:
            self._show_headers = True
        if "tls" in lowered or "mutual" in lowered:
            self._show_tls = True
        self._sync_option_panels()
        if self._catalogue_only:
            self._set_status(
                label + ". Catalogue without a key. "
                "Get a SUPERQODE_API_KEY at https://superqode.dev for a real model chat. "
                + stored
            )
        else:
            self._set_status(
                label + ". Type below and Send. n or Clear starts a new conversation. "
                + stored
            )
        try:
            self.query_one("#a2a-message", Input).placeholder = "message to this agent, then Send"
        except Exception:  # noqa: BLE001
            pass
        self._write_connected_banner()
        self._render_examples()
        try:
            self.query_one("#a2a-message", Input).focus()
        except Exception:  # noqa: BLE001
            pass

    def _thinking_bar(self) -> _A2AThinkingBar:
        return self.query_one("#a2a-thinking", _A2AThinkingBar)

    def _chat_log(self) -> RichLog:
        return self.query_one("#a2a-chat", RichLog)

    def _write_connected_banner(self) -> None:
        try:
            log = self._chat_log()
            log.clear()
        except Exception:  # noqa: BLE001
            return
        banner = Text()
        banner.append("◈  ", style="bold #e9d5ff")
        banner.append(self._name or "Agent", style="bold #f0f0f0")
        if self._binding:
            banner.append(
                f"  ·  {self._binding} {self._protocol_version}".rstrip(),
                style="#c8c8c8",
            )
        log.write(banner)
        if self._rows:
            skills = Text()
            skills.append("Skills  ", style="#a78bfa")
            skills.append(", ".join(row.name for row in self._rows), style="#d4d4d4")
            log.write(skills)
        if self._catalogue_only:
            note = Text()
            note.append("Catalogue  ", style="bold #c4b5fd")
            note.append(
                "Anonymous catalogue — not a model. The same kind of list is "
                "expected for most questions. For a real model chat, get a "
                "SUPERQODE_API_KEY at https://superqode.dev and paste it above "
                "(or export SUPERQODE_API_KEY).",
                style="#d4d4d4",
            )
            log.write(note)
        hint = Text()
        hint.append(
            "Type below and Send. Copy or ctrl+y copies the last reply. "
            "Clear or n starts a new conversation.",
            style="#a8a8a8",
        )
        log.write(hint)
        log.write("")

    def _write_you(self, message: str) -> None:
        body = Text()
        body.append("▸  You\n", style="bold #e9d5ff")
        body.append(message.strip() or "(empty)", style="#d4d4d4")
        try:
            self._chat_log().write(body)
            self._chat_log().write("")
        except Exception:  # noqa: BLE001
            pass

    def _write_agent(self, name: str, message: str) -> None:
        body = Text()
        body.append(f"◆  {name}\n", style="bold #f0f0f0")
        text = message.strip()
        if len(text) > 8000:
            text = text[:7997] + "..."
        body.append(text, style="#f0f0f0")
        try:
            self._chat_log().write(body)
            self._chat_log().write("")
        except Exception:  # noqa: BLE001
            pass

    def _render_examples(self) -> None:
        try:
            listing = self.query_one("#a2a-examples", OptionList)
        except Exception:  # noqa: BLE001
            return
        listing.clear_options()
        examples = []
        for row in self._rows:
            examples.extend(row.examples)
        seen: set[str] = set()
        unique: list[str] = []
        for item in examples:
            if item in seen:
                continue
            seen.add(item)
            unique.append(item)
        unique = unique[:6]
        self._example_prompts = unique
        if not unique:
            listing.display = False
            listing.remove_class("visible")
            return
        for index, item in enumerate(unique):
            label = Text()
            label.append("Try  ", style="#a78bfa")
            label.append(item, style="#e6e6e6")
            listing.add_option(Option(label, id=f"ex-{index}"))
        listing.display = True
        listing.add_class("visible")

    def _set_examples_visible(self, visible: bool) -> None:
        try:
            listing = self.query_one("#a2a-examples", OptionList)
        except Exception:  # noqa: BLE001
            return
        show = bool(visible and self._example_prompts)
        listing.display = show
        listing.set_class(show, "visible")

    def _arm_cold_start(self) -> None:
        self._disarm_cold_start()
        try:
            self._cold_timer = self.set_timer(8.0, self._note_cold_start)
        except Exception:  # noqa: BLE001
            self._cold_timer = None

    def _disarm_cold_start(self) -> None:
        timer = self._cold_timer
        self._cold_timer = None
        if timer is not None:
            try:
                timer.stop()
            except Exception:  # noqa: BLE001
                pass

    def _note_cold_start(self) -> None:
        if not self._busy:
            return
        self._thinking_bar().start("Host may be cold-starting")
        self._set_status("Still waiting — the host may be waking from idle.")

    def _write_note(self, message: str) -> None:
        body = Text()
        body.append("·  ", style="#a78bfa")
        body.append(message.strip(), style="#c8c8c8")
        try:
            self._chat_log().write(body)
            self._chat_log().write("")
        except Exception:  # noqa: BLE001
            pass

    def _show_inspect_open(self) -> None:
        self._inspect_open = True
        self._sync_option_panels()

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
        self.remove_class("connected")
        self._rows = []
        self._chat = []
        self._context_id = ""
        self._task_text = ""
        self._last_sent = ""
        self._catalogue_only = False
        self._streaming = False
        try:
            self._thinking_bar().stop()
            self._chat_log().clear()
            examples = self.query_one("#a2a-examples", OptionList)
            examples.clear_options()
            examples.display = False
        except Exception:  # noqa: BLE001
            pass
        self._write_note(message)
        self._set_status(message)
        self.query_one("#a2a-url", Input).focus()

    def _current_token(self) -> str:
        return self.query_one("#a2a-token", Input).value.strip()

    def _current_headers(self) -> dict[str, str]:
        from superqode.a2a.connection import parse_header_line

        try:
            field = self.query_one("#a2a-headers", Input).value
        except Exception:  # noqa: BLE001 - tests construct the screen unmounted
            return dict(self._headers)
        return parse_header_line(field)

    def _tls_paths(self) -> tuple[str, str]:
        import os

        from superqode.a2a.connection import CERT_ENV, KEY_ENV, load_saved_connection

        saved = load_saved_connection()
        try:
            cert = self.query_one("#a2a-cert", Input).value.strip()
            key = self.query_one("#a2a-key", Input).value.strip()
        except Exception:  # noqa: BLE001
            cert, key = self._cert, self._key
        cert = cert or (os.environ.get(CERT_ENV) or saved.cert or "").strip()
        key = key or (os.environ.get(KEY_ENV) or saved.key or "").strip()
        return cert, key

    def _prompt_secret(self, name: str) -> str:
        existing = self._current_token()
        if existing:
            return existing
        self._set_status(
            f"Card requires API key {name}. Paste it in the credential field and press Connect."
        )
        return ""

    def _current_message(self) -> str:
        return self.query_one("#a2a-message", Input).value.strip()

    def _auth_from_card(self, card_data, inspect_log) -> str:
        if isinstance(card_data, dict) and card_data:
            from superqode.a2a.inspect import auth_summary

            return auth_summary(card_data)
        if inspect_log is not None and hasattr(inspect_log, "events"):
            for event in inspect_log.events:
                if getattr(event, "kind", "") == "auth" and event.summary:
                    return event.summary
        return ""

    def _stored_oauth_note(self, url: str) -> str:
        if not url:
            return ""
        try:
            from superqode.a2a.oauth import oauth_storage

            stored = oauth_storage().load(_origin(url))
        except Exception:  # noqa: BLE001 - missing store must not block the screen
            return ""
        if stored.tokens:
            return "Stored OAuth token will be reused. Logout clears it."
        return ""

    # -- actions -----------------------------------------------------------

    def action_close(self) -> None:
        self.dismiss(None)

    def action_cancel_or_close(self) -> None:
        if self._busy:
            self._generation += 1
            self._busy = False
            self._disarm_cold_start()
            self._thinking_bar().stop()
            self._write_note("Cancelled.")
            self._set_status("Cancelled.")
            return
        self.dismiss(self._result() if self._connected else None)

    def action_copy_reply(self) -> None:
        text = self._task_text.strip()
        if not text:
            try:
                self._set_status("Nothing to copy yet. Send a message first.")
            except Exception:  # noqa: BLE001
                pass
            return
        copied = _copy_text(text)
        try:
            self.app.copy_to_clipboard(text)
            copied = True
        except Exception:  # noqa: BLE001
            pass
        try:
            self._set_status("Last reply copied." if copied else "Could not copy.")
        except Exception:  # noqa: BLE001
            pass

    def action_clear_chat(self) -> None:
        """Wipe the window and start a new A2A conversation (new contextId)."""
        if self._busy:
            try:
                self._set_status("Wait for the current reply, then Clear.")
            except Exception:  # noqa: BLE001
                pass
            return
        self._chat = []
        self._context_id = ""
        self._task_text = ""
        self._last_sent = ""
        try:
            if self._connected:
                self._write_connected_banner()
                self._render_examples()
            else:
                self._chat_log().clear()
            self._set_status("New conversation. Window and context cleared.")
            self.query_one("#a2a-message", Input).focus()
        except Exception:  # noqa: BLE001 - tests construct the screen unmounted
            pass

    def action_resend(self) -> None:
        if self._busy:
            return
        if not self._last_sent:
            self._set_status("Nothing to resend.")
            return
        url = self._require_origin()
        if url:
            self._send(url, self._last_sent)

    def action_reconnect(self) -> None:
        self._connect_from_input()

    def action_logout(self) -> None:
        self._logout_from_input()

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

    def _require_origin(self) -> str:
        raw = self.query_one("#a2a-url", Input).value.strip()
        if not raw:
            self._set_status("Paste an agent origin, then press Connect.")
            self.query_one("#a2a-url", Input).focus()
            return ""
        url = _origin(raw)
        self.query_one("#a2a-url", Input).value = url
        return url

    def _connect_from_input(self) -> None:
        url = self._require_origin()
        if not url:
            return
        self._discover(url)

    def _send_from_input(self) -> None:
        message = self._current_message()
        if not message:
            self.query_one("#a2a-message", Input).focus()
            return
        url = self._require_origin()
        if not url:
            return
        self._send(url, message)

    def _check_from_input(self) -> None:
        if self._busy:
            return
        url = self._require_origin()
        if not url:
            return
        self._check(url)

    def _use_connected(self) -> None:
        if not self._connected:
            self._connect_from_input()
            return
        result = self._result()
        if result is None:
            return
        from superqode.a2a.connection import A2ASettings, save_connection

        save_connection(
            A2ASettings(
                url=result.url,
                token=result.token,
                headers=dict(result.headers),
                cert=result.cert,
                key=result.key,
                name=result.name,
            )
        )
        app = self.app
        remember = getattr(app, "_remember_a2a_agent", None)
        if callable(remember):
            remember(result.name or result.url, result.url)
        self._set_status("Saved. Stay here to chat, or Back to return.")

    def _result(self) -> A2AConnectResult | None:
        cert, key = self._tls_paths()
        try:
            headers = self._current_headers()
        except ValueError as exc:
            self._set_status(str(exc))
            self.query_one("#a2a-headers", Input).focus()
            return None
        return A2AConnectResult(
            url=self._url,
            token=self._current_token(),
            name=self._name,
            binding=self._binding,
            protocol_version=self._protocol_version,
            task_text=self._task_text,
            headers=headers,
            cert=cert,
            key=key,
        )

    @on(Button.Pressed, "#a2a-connect")
    def _on_connect(self) -> None:
        self._connect_from_input()

    @on(Button.Pressed, "#a2a-oauth")
    def _on_oauth(self) -> None:
        self.action_toggle_oauth()

    @on(Button.Pressed, "#a2a-use")
    def _on_use(self) -> None:
        self._use_connected()

    @on(Button.Pressed, "#a2a-send")
    def _on_send(self) -> None:
        self._send_from_input()

    @on(Button.Pressed, "#a2a-copy")
    def _on_copy(self) -> None:
        self.action_copy_reply()

    @on(Button.Pressed, "#a2a-clear")
    def _on_clear(self) -> None:
        self.action_clear_chat()

    @on(OptionList.OptionSelected, "#a2a-examples")
    def _on_example(self, event: OptionList.OptionSelected) -> None:
        prompt = ""
        option_id = str(getattr(event, "option_id", "") or "")
        if option_id.startswith("ex-"):
            try:
                prompt = self._example_prompts[int(option_id.split("-", 1)[1])]
            except (ValueError, IndexError):
                prompt = ""
        if prompt:
            self.query_one("#a2a-message", Input).value = prompt
            self.query_one("#a2a-message", Input).focus()
            self._set_status("Example filled. Send to ask it.")

    @on(Button.Pressed, "#a2a-headers-btn")
    def _on_headers_btn(self) -> None:
        self.action_toggle_headers()

    @on(Button.Pressed, "#a2a-tls-btn")
    def _on_tls_btn(self) -> None:
        self.action_toggle_tls()

    @on(Button.Pressed, "#a2a-inspect-btn")
    def _on_inspect_btn(self) -> None:
        self.action_toggle_inspect()

    @on(Button.Pressed, "#a2a-check")
    def _on_check(self) -> None:
        self._check_from_input()

    @on(Button.Pressed, "#a2a-logout")
    def _on_logout(self) -> None:
        self._logout_from_input()

    @work(exclusive=True)
    async def _logout_from_input(self) -> None:
        from superqode.a2a.oauth import logout_origin

        url = self._require_origin()
        if not url:
            return
        self._busy = True
        self._set_status(f"Logging out of {url} ...")
        try:
            cleared, revoked = await logout_origin(url)
        except Exception as exc:  # noqa: BLE001
            self._busy = False
            self._set_status(f"Logout failed: {exc}")
            return
        self._busy = False
        if cleared and revoked:
            self._set_status(f"Deleted and revoked OAuth tokens for {url}")
        elif cleared:
            self._set_status(f"Deleted OAuth tokens for {url}")
        else:
            self._set_status(f"No stored OAuth tokens for {url}")

    @on(Button.Pressed, "#a2a-close")
    def _on_close(self) -> None:
        self.action_cancel_or_close()

    @on(Input.Submitted, "#a2a-url")
    def _on_submit(self) -> None:
        self._connect_from_input()

    @on(Input.Submitted, "#a2a-token")
    def _on_token_submit(self) -> None:
        self._connect_from_input()

    @on(Input.Submitted, "#a2a-headers")
    def _on_headers_submit(self) -> None:
        self._connect_from_input()

    @on(Input.Submitted, "#a2a-message")
    def _on_message_submit(self) -> None:
        self._send_from_input()
