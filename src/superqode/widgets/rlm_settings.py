"""Native RLM profile and allowance settings for a new durable session."""

from copy import deepcopy
from dataclasses import dataclass

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, Select, Static

from superqode.rlm.budget import BudgetPolicy
from superqode.rlm.profile import RLMProfile
from superqode.rlm.sandbox import RLMSandboxConfig


@dataclass(frozen=True)
class RLMSettingsResult:
    action: str
    config: dict


class RLMSettingsScreen(Screen[RLMSettingsResult | None]):
    BINDINGS = [Binding("escape", "close", "Back")]
    CSS = """
    RLMSettingsScreen { background: #000000; }
    RLMSettingsScreen VerticalScroll { padding: 1 2; }
    RLMSettingsScreen Label { height: auto; margin-top: 1; }
    RLMSettingsScreen Static { height: auto; }
    RLMSettingsScreen Horizontal { height: auto; }
    RLMSettingsScreen Button { margin-right: 1; }
    RLMSettingsScreen #rlm-settings-actions { dock: bottom; padding: 0 1; }
    RLMSettingsScreen #rlm-settings-error { color: #fca5a5; }
    RLMSettingsScreen Footer { dock: bottom; }
    """

    def __init__(self, config=None):
        super().__init__()
        self.config = deepcopy(config or {})
        self.profile = RLMProfile.from_config(self.config)
        self.budget = BudgetPolicy.from_config(self.config.get("budget"))
        self.sandbox = RLMSandboxConfig.from_config(self.config)

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static("RLM profile and budgets")
            yield Static(
                "Settings apply to a new session. Existing workers retain their profile and allowance."
            )
            yield Label("Tool profile")
            yield Select(
                [("Persistent Python", "python"), ("Python + Bash · experimental", "python-bash")],
                value=self.profile.tool_surface,
                allow_blank=False,
                id="rlm-tool-surface",
            )
            yield Label("Execution environment")
            yield Select(
                [
                    ("Host · process permissions", "host"),
                    ("Docker · container boundary", "docker"),
                    ("Monty · restricted analysis", "monty"),
                ],
                value=self.sandbox.backend,
                allow_blank=False,
                id="rlm-execution",
            )
            yield Label("Model observations")
            yield Select(
                [
                    ("Conversation transcript", "transcript"),
                    ("Selective stored observations · experimental", "selective"),
                ],
                value=self.profile.observations,
                allow_blank=False,
                id="rlm-observations",
            )
            yield Label("Shared model-call allowance (0 = unlimited)")
            yield Input(str(self.budget.max_calls), type="integer", id="rlm-call-limit")
            yield Label("Reported token threshold (0 = unlimited)")
            yield Input(str(self.budget.max_tokens), type="integer", id="rlm-token-limit")
            yield Label("Reported USD threshold (0 = unlimited)")
            yield Input(str(self.budget.max_cost_usd), type="number", id="rlm-cost-limit")
            yield Static(
                "Call admission is shared across root, coding children and semantic queries. Token/USD thresholds stop new requests after reported spend; a request can cross the threshold. Missing usage blocks further capped requests. A2A credits are configured separately."
            )
            yield Static(
                "Python+Bash needs Bash in host or Docker. Monty keeps no shell or repository writes. New Docker profiles are offline by default. Optional A2A settings are preserved."
            )
            yield Static(
                "Inspect usage with :rlm usage; jobs with :rlm jobs; stop a command with :rlm job cancel <id>."
            )
        yield Static("", id="rlm-settings-error")
        with Horizontal(id="rlm-settings-actions"):
            yield Button("Save profile", id="rlm-settings-save")
            yield Button("Start new session", variant="primary", id="rlm-settings-start")
            yield Button("Back", id="rlm-settings-close")
        yield Footer()

    def _config(self):
        config = {
            **self.config,
            "tool_surface": self.query_one("#rlm-tool-surface", Select).value,
            "observations": self.query_one("#rlm-observations", Select).value,
            "sandbox": self.query_one("#rlm-execution", Select).value,
            "budget": BudgetPolicy.from_config(
                {
                    "max_calls": self.query_one("#rlm-call-limit", Input).value,
                    "max_tokens": self.query_one("#rlm-token-limit", Input).value,
                    "max_cost_usd": self.query_one("#rlm-cost-limit", Input).value,
                }
            ).to_dict(),
        }
        previous = self.sandbox.backend
        if config["sandbox"] != previous:
            config.update(
                allow_network=config["sandbox"] == "host",
                allow_write=config["sandbox"] != "monty",
                allow_shell=config["sandbox"] != "monty",
            )
        RLMProfile.from_config(config).validate_sandbox(RLMSandboxConfig.from_config(config))
        return config

    @on(Button.Pressed)
    def pressed(self, event):
        identity = event.button.id
        if identity == "rlm-settings-close":
            self.action_close()
        elif identity in {"rlm-settings-save", "rlm-settings-start"}:
            try:
                self.dismiss(
                    RLMSettingsResult(
                        "start" if identity.endswith("start") else "save", self._config()
                    )
                )
            except (ValueError, TypeError) as error:
                self.query_one("#rlm-settings-error", Static).update(str(error))

    def action_close(self):
        self.dismiss(None)
