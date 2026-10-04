"""Explicit optional A2A configuration for native RLM sessions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import os
import re

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Footer, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from superqode.rlm.delegation_policy import DelegationPeer, DelegationPolicy


@dataclass(frozen=True)
class RLMRoutingResult:
    action: str
    config: dict | None = None


class RLMRoutingScreen(Screen[RLMRoutingResult | None]):
    """Edit a new-session profile; never mutate an active worker's policy."""

    BINDINGS = [Binding("escape", "close", "Back")]
    CSS = """
    RLMRoutingScreen { background: #000000; }
    RLMRoutingScreen #routing-form { padding: 1 2; }
    RLMRoutingScreen Label { height: auto; margin-top: 1; }
    RLMRoutingScreen Static { height: auto; }
    RLMRoutingScreen Input { margin-bottom: 1; }
    RLMRoutingScreen #routing-peers { height: 7; }
    RLMRoutingScreen Horizontal { height: auto; }
    RLMRoutingScreen Button { margin-right: 1; }
    RLMRoutingScreen #routing-actions { dock: bottom; padding: 0 1; }
    RLMRoutingScreen #routing-error { color: #fca5a5; }
    RLMRoutingScreen Footer { dock: bottom; }
    """

    def __init__(
        self, config: dict | None = None, *, status: str = "", inspect_enabled: bool = True
    ) -> None:
        super().__init__()
        self.config = deepcopy(config or {})
        self.policy = DelegationPolicy.from_config(self.config)
        self.peers = deepcopy(self.config.get("peers", []))
        self.selected_name = ""
        self.status = status
        self.inspect_enabled = inspect_enabled

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="routing-form"):
            yield Static(Text("Optional A2A · Native RLM", style="bold #c4b5fd"))
            yield Static(
                "RLM keeps its Python tool, context selection and local recursion. "
                "Enable remote peers only when you want them. A key alone enables nothing."
            )
            yield Static(self.status or "No active worker inspected.", id="routing-status")
            yield Checkbox("Enable A2A routing", value=self.policy.enabled, id="routing-enabled")
            yield Checkbox(
                "Allow paid hosted peers", value=self.policy.hosted_enabled, id="routing-paid"
            )
            yield Label("Hosted credit limit per root (0 blocks paid routes)")
            yield Input(str(self.policy.max_hosted_credits), id="routing-budget", type="integer")
            yield Label("Maximum remote tasks / simultaneous remote tasks")
            with Horizontal():
                yield Input(str(self.policy.max_tasks), id="routing-max-tasks", type="integer")
                yield Input(str(self.policy.max_parallel), id="routing-parallel", type="integer")
            yield Static(
                "Remote token usage may be unknown. User-owned peers can still incur "
                "their own charges. There is no automatic paid fallback."
            )
            yield Label("Configured peers · select one to edit")
            yield OptionList(id="routing-peers")
            yield Label("Peer alias")
            yield Input(placeholder="reviewer", id="routing-name")
            yield Label("Agent URL")
            yield Input(placeholder="https://your-agent.example", id="routing-url")
            yield Label("Description for the RLM")
            yield Input(placeholder="Review selected source for defects", id="routing-description")
            yield Label("Key environment variable name (leave empty for anonymous peers)")
            yield Input(placeholder="SUPERQODE_A2A_KEY", id="routing-env")
            yield Static("", id="routing-key-status")
            yield Label("Agent skill")
            yield Input(placeholder="superqode-harness", id="routing-skill")
            yield Checkbox("This peer is a paid hosted service", id="routing-hosted")
            yield Label("Service tariff in credits per task")
            yield Input("0", id="routing-tariff", type="integer")
            with Horizontal():
                yield Button("Add / update peer", id="routing-upsert")
                yield Button("Remove peer", id="routing-remove")
                yield Button("New peer", id="routing-new")
            yield Static(
                "Save creates a project harness profile. Start new session saves and branches "
                "the current session with these settings. Existing workers keep their policy. "
                "Only environment variable names are saved; set keys before launching SuperQode."
            )
        yield Static("", id="routing-error")
        with Horizontal(id="routing-actions"):
            yield Button("Save profile", id="routing-save")
            yield Button("Start new session", id="routing-start", variant="primary")
            yield Button("Tasks", id="routing-tasks", disabled=not self.inspect_enabled)
            yield Button("Usage", id="routing-usage", disabled=not self.inspect_enabled)
            yield Button("Back", id="routing-close")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_peers()

    def _refresh_peers(self) -> None:
        listing = self.query_one("#routing-peers", OptionList)
        listing.clear_options()
        for peer in self.peers:
            credential = peer.get("credential_env", "")
            key = (
                "anonymous"
                if not credential
                else ("key set" if os.getenv(credential) else "key missing")
            )
            mode = "paid" if peer.get("hosted") else "user-owned"
            listing.add_option(Option(Text(f"{peer['name']} · {mode} · {key}"), id=peer["name"]))

    @on(OptionList.OptionSelected, "#routing-peers")
    def select_peer(self, event: OptionList.OptionSelected) -> None:
        peer = next(p for p in self.peers if p["name"] == event.option.id)
        self.selected_name = peer["name"]
        for name, field in (
            ("name", "name"),
            ("url", "url"),
            ("description", "description"),
            ("env", "credential_env"),
            ("skill", "skill"),
            ("tariff", "credits"),
        ):
            self.query_one(f"#routing-{name}", Input).value = str(
                peer.get(field, "0" if name == "tariff" else "")
            )
        self.query_one("#routing-hosted", Checkbox).value = bool(peer.get("hosted"))

    @on(Input.Changed, "#routing-env")
    def key_changed(self, event: Input.Changed) -> None:
        name = event.value.strip()
        status = (
            "Anonymous peer"
            if not name
            else (
                "Key is set on this host"
                if os.getenv(name)
                else f"Set {name} before launching SuperQode"
            )
        )
        self.query_one("#routing-key-status", Static).update(Text(status))

    def _config(self) -> dict:
        fields = self._peer_fields()
        if any(fields[name] for name in ("name", "url", "description", "credential_env", "skill")):
            existing = next((p for p in self.peers if p["name"] == self.selected_name), {})
            if any(
                fields[key]
                != existing.get(key, False if key == "hosted" else 0 if key == "credits" else "")
                for key in fields
            ):
                raise ValueError(
                    "Choose Add / update peer to retain the edited peer before saving."
                )
        config = {
            **self.config,
            "enabled": self.query_one("#routing-enabled", Checkbox).value,
            "hosted_enabled": self.query_one("#routing-paid", Checkbox).value,
            "max_hosted_credits": int(self.query_one("#routing-budget", Input).value),
            "max_tasks": int(self.query_one("#routing-max-tasks", Input).value),
            "max_parallel": int(self.query_one("#routing-parallel", Input).value),
            "peers": deepcopy(self.peers),
        }
        policy = DelegationPolicy.from_config(config)
        if policy.enabled and not policy.inventory():
            raise ValueError(
                "Add an allowed peer before enabling routing; paid peers also need paid opt-in and a positive credit limit."
            )
        if policy.hosted_enabled and not policy.max_hosted_credits:
            raise ValueError("Set a positive hosted credit limit or turn paid routing off.")
        return config

    def _peer_fields(self) -> dict:
        fields = {
            field: self.query_one(f"#routing-{name}", Input).value.strip()
            for name, field in (
                ("name", "name"),
                ("url", "url"),
                ("description", "description"),
                ("env", "credential_env"),
                ("skill", "skill"),
            )
        }
        fields["credits"] = int(self.query_one("#routing-tariff", Input).value)
        fields["hosted"] = self.query_one("#routing-hosted", Checkbox).value
        return fields

    def _clear_peer(self) -> None:
        self.selected_name = ""
        for name in ("name", "url", "description", "env", "skill", "tariff"):
            self.query_one(f"#routing-{name}", Input).value = "0" if name == "tariff" else ""
        self.query_one("#routing-hosted", Checkbox).value = False

    @on(Button.Pressed)
    def button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        action = str(event.button.id or "").removeprefix("routing-")
        try:
            if action == "upsert":
                fields = self._peer_fields()
                if fields["credential_env"] and not re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]*", fields["credential_env"]
                ):
                    raise ValueError(
                        "Enter an environment variable name for the key, not its value."
                    )
                existing = next((p for p in self.peers if p["name"] == self.selected_name), {})
                peer = {
                    **existing,
                    **fields,
                    "credits": int(self.query_one("#routing-tariff", Input).value),
                    "hosted": self.query_one("#routing-hosted", Checkbox).value,
                }
                DelegationPeer.parse(peer)
                if any(
                    p["name"] == peer["name"] and p["name"] != self.selected_name
                    for p in self.peers
                ):
                    raise ValueError("Peer alias already exists; select it to edit.")
                self.peers = [p for p in self.peers if p["name"] != self.selected_name] + [peer]
                self.selected_name = peer["name"]
                self._refresh_peers()
            elif action == "remove":
                self.peers = [p for p in self.peers if p["name"] != self.selected_name]
                self._clear_peer()
                self._refresh_peers()
            elif action == "new":
                self._clear_peer()
            elif action in {"save", "start"}:
                config = self._config()
                if action == "start":
                    allowed = {p["name"] for p in DelegationPolicy.from_config(config).inventory()}
                    missing = [
                        p["credential_env"]
                        for p in self.peers
                        if p["name"] in allowed
                        and p.get("credential_env")
                        and not os.getenv(p["credential_env"])
                    ]
                    if missing:
                        raise ValueError(
                            f"Set the key environment variables before starting: {', '.join(missing)}"
                        )
                self.dismiss(RLMRoutingResult(action, config))
            elif action in {"tasks", "usage"}:
                self.dismiss(RLMRoutingResult(action))
            elif action == "close":
                self.action_close()
            self.query_one("#routing-error", Static).update("")
        except ValueError as error:
            self.query_one("#routing-error", Static).update(Text(str(error)))

    def action_close(self) -> None:
        self.dismiss(None)
