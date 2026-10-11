"""Live MCP controls; closing the panel does not disconnect shared servers."""

from __future__ import annotations

import asyncio

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, Static, TextArea
from textual.widgets.option_list import Option

from superqode.cli_output import sanitize_diagnostic
from superqode.mcp.config import MCPHttpConfig, MCPSSEConfig
from superqode.widgets.panel_shortcuts import PanelShortcutMixin, PanelShortcuts


class MCPConnectionsScreen(PanelShortcutMixin, ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Back", priority=True)]
    CSS = """
    MCPConnectionsScreen { align: center middle; }
    #mcp-panel { width: 96%; height: 94%; padding: 0 1; background: $sq-bg; border: round $sq-purple; }
    #mcp-title { height: 1; text-style: bold; color: $sq-purple; }
    #mcp-servers { height: 5; }
    #mcp-detail { height: 1fr; }
    #mcp-notice { height: 2; color: $sq-muted; }
    #mcp-controls { height: 3; }
    #mcp-controls Button { min-width: 8; width: 1fr; padding: 0; }
    """

    class Changed(Message):
        pass

    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self._ids = []
        self._signature = None
        self._detail = None
        self._tasks = {}
        self._listener = lambda *_: self.post_message(self.Changed())

    def compose(self) -> ComposeResult:
        with Vertical(id="mcp-panel"):
            yield Static("MCP connections · live status", id="mcp-title")
            yield OptionList(id="mcp-servers")
            yield TextArea("", read_only=True, id="mcp-detail")
            yield Static(
                "Choose a server. Closing this panel keeps connections running.", id="mcp-notice"
            )
            with Horizontal(id="mcp-controls"):
                for action in ("connect", "retry", "login", "disconnect", "cancel", "back"):
                    yield Button(
                        action.capitalize(), id=f"mcp-action-{action}", disabled=action != "back"
                    )
            yield PanelShortcuts(
                {"mcp-servers": "↑↓ Select · Tab Controls · Esc Back"},
                "Tab Next control · Enter Activate · Esc Back",
            )

    def on_mount(self):
        self.manager.on_state_change(self._listener)
        self.refresh_servers()
        self.set_interval(1, self.refresh_servers)
        self.query_one("#mcp-servers", OptionList).focus()

    def on_unmount(self):
        self.manager.remove_state_callback(self._listener)
        for task in tuple(self._tasks.values()):
            task.cancel()

    @on(Changed)
    def state_changed(self):
        self.refresh_servers()

    def selected(self):
        index = self.query_one("#mcp-servers", OptionList).highlighted
        return self._ids[index] if index is not None and index < len(self._ids) else None

    def diagnostic(self, name, value):
        """Opaque MCP credentials may not match provider token patterns."""
        from superqode.tools.env_policy import is_secret_name

        config = self.manager.get_server_configs().get(name)
        transport = config.config if config else None
        secrets = [
            value for key, value in getattr(transport, "env", {}).items() if is_secret_name(key)
        ]
        for header in getattr(transport, "headers", {}).values():
            secrets.extend((header, header.split(" ", 1)[-1]))
        if isinstance(transport, (MCPHttpConfig, MCPSSEConfig)):
            try:
                from superqode.mcp.auth_storage import get_auth_storage

                credentials = get_auth_storage().for_server(name).get_credentials(transport.url)
                if credentials:
                    secrets.extend((credentials.api_key or "", credentials.bearer_token or ""))
                    if credentials.oauth_tokens:
                        secrets.extend(
                            (
                                credentials.oauth_tokens.access_token,
                                credentials.oauth_tokens.refresh_token or "",
                            )
                        )
            except (OSError, ValueError, TypeError, AttributeError, RecursionError):
                return "Diagnostics unavailable: stored credentials could not be checked for redaction."
        return sanitize_diagnostic(value, extra_secrets=secrets)

    def refresh_servers(self):
        # Mount handlers run before is_mounted becomes true; their child
        # controls are already attached and can be initialized safely.
        if not self.is_attached or self not in self.app.screen_stack:
            return
        configs = self.manager.get_server_configs()
        previous = self.selected()
        rows = [
            (
                name,
                "disabled" if not config.enabled else self.manager.get_connection_state(name).value,
            )
            for name, config in configs.items()
        ]
        signature = tuple(rows)
        if signature != self._signature:
            self._signature = signature
            self._ids = [name for name, _ in rows]
            listing = self.query_one("#mcp-servers", OptionList)
            listing.clear_options()
            listing.add_options(Option(Text(f"{name} · {state}"), id=name) for name, state in rows)
            listing.highlighted = (
                self._ids.index(previous) if previous in self._ids else (0 if rows else None)
            )
        self.show_selected()

    @on(OptionList.OptionHighlighted, "#mcp-servers")
    def highlighted(self):
        self.show_selected()

    def show_selected(self):
        name = self.selected()
        configs = self.manager.get_server_configs()
        summary = self.manager.get_status_summary().get("servers", {}).get(name, {})
        active = name in self._tasks or summary.get("state") == "connecting"
        enabled = bool(name in configs and configs[name].enabled)
        detail = (
            f"{name}\nState: {'disabled' if not enabled else summary.get('state', 'disconnected')}\n"
            f"Tools: {summary.get('tools', 0)} · Resources: {summary.get('resources', 0)} · Prompts: {summary.get('prompts', 0)}\n"
            f"{self.diagnostic(name, summary.get('error') or '')}\n"
            f"{self.diagnostic(name, self.manager.get_server_stderr(name))}"
            if name
            else "No MCP servers configured. Add a server with :mcp add, then open this panel again."
        )
        if detail != self._detail:
            self._detail = detail
            self.query_one("#mcp-detail", TextArea).load_text(detail)
        for action in ("connect", "retry", "login"):
            self.query_one(f"#mcp-action-{action}", Button).disabled = not enabled or active
        self.query_one("#mcp-action-login", Button).disabled = (
            not enabled
            or active
            or not isinstance(configs[name].config, (MCPHttpConfig, MCPSSEConfig))
        )
        self.query_one("#mcp-action-cancel", Button).disabled = not active
        self.query_one("#mcp-action-disconnect", Button).disabled = not name or active

    @on(Button.Pressed, "#mcp-controls Button")
    def action_pressed(self, event):
        event.stop()
        action = event.button.id.removeprefix("mcp-action-")
        if action == "back":
            self.action_close()
            return
        name = self.selected()
        if not name:
            return
        if action == "cancel":
            previous = self._tasks.get(name)
            task = asyncio.create_task(self._cancel(name, previous))
            self._tasks[name] = task
            task.add_done_callback(lambda finished: self._finished(name, finished))
        elif name not in self._tasks:
            task = asyncio.create_task(self._perform(action, name))
            self._tasks[name] = task
            task.add_done_callback(lambda finished: self._finished(name, finished))
            self.query_one("#mcp-notice", Static).update(Text(f"{action.capitalize()}: {name}…"))
            self.show_selected()

    def _finished(self, name, task):
        if self._tasks.get(name) is task:
            self._tasks.pop(name, None)
        if not task.cancelled():
            task.exception()  # Retrieve failures even if the panel has already closed.
        if self.is_mounted:
            self.refresh_servers()

    async def _cancel(self, name, previous):
        if previous:
            previous.cancel()
            await asyncio.gather(previous, return_exceptions=True)
        try:
            await self.manager.disconnect(name)
        except Exception as exc:
            notice = f"{name}: cancellation failed: {self.diagnostic(name, str(exc))}"
        else:
            notice = f"{name}: operation cancelled; disconnected"
        if self.is_mounted:
            self.query_one("#mcp-notice", Static).update(Text(notice))

    async def _perform(self, action, name):
        try:
            if action == "login":
                ok = await self.manager.authenticate_server(name)
                if ok:
                    ok = await self.manager.reconnect(name)
            elif action == "retry":
                ok = await self.manager.reconnect(name)
            elif action == "disconnect":
                await self.manager.disconnect(name)
                ok = True
            else:
                ok = await self.manager.connect(name)
            notice = (
                f"{name}: {action} {'completed' if ok else 'failed; inspect the server details'}"
            )
        except asyncio.CancelledError:
            notice = f"{name}: operation cancelled"
        except Exception as exc:
            notice = f"{name}: {self.diagnostic(name, str(exc))}"
        if self.is_mounted and self in self.app.screen_stack:
            self.query_one("#mcp-notice", Static).update(Text(notice))

    def action_close(self):
        self.dismiss(None)
