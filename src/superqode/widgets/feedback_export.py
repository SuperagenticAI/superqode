"""Review an immutable, redacted snapshot before exporting it locally."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Static, TextArea

from superqode.app.feedback_bundle import feedback_bundle
from superqode.theming import atomic_json


class FeedbackExportScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Back", priority=True)]
    CSS = """
    FeedbackExportScreen { align: center middle; }
    FeedbackExportScreen > Vertical { width: 88; max-width: 96%; height: 92%; background: $sq-bg; border: round $sq-purple; padding: 0 1; }
    FeedbackExportScreen .title { height: 1; color: $sq-purple; text-style: bold; }
    FeedbackExportScreen #feedback-body { height: 1fr; }
    FeedbackExportScreen Label { height: auto; margin-top: 1; }
    FeedbackExportScreen #feedback-description { height: 4; }
    FeedbackExportScreen #feedback-preview { height: 12; }
    FeedbackExportScreen Checkbox, FeedbackExportScreen Checkbox:focus {
        height: 1; min-height: 1; border: none; padding: 0; margin: 0; color: $sq-text;
    }
    FeedbackExportScreen #feedback-status { height: 2; color: $sq-muted; }
    FeedbackExportScreen #feedback-actions { height: 3; }
    FeedbackExportScreen Button { width: auto; min-width: 9; margin-right: 1; }
    """

    def __init__(self):
        super().__init__()
        self._ready = False
        self._bundle = None

    def compose(self) -> ComposeResult:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        with Vertical():
            yield Static("Developer feedback · review before export", classes="title")
            with VerticalScroll(id="feedback-body"):
                yield Static(
                    "Local JSON only. Prompts, source files, credentials and session IDs are excluded."
                )
                yield Label("What happened? What did you expect?")
                yield TextArea(id="feedback-description")
                yield Checkbox("Include recent errors", value=True, id="feedback-errors")
                yield Checkbox("Include harness and model names", value=True, id="feedback-route")
                yield Label("Export file · an existing file will be retained")
                yield Input(
                    str(
                        Path.cwd() / ".superqode" / "feedback" / f"superqode-feedback-{stamp}.json"
                    ),
                    id="feedback-path",
                )
                yield Label("Redacted JSON · Tab here, then use arrows or Page Down to review")
                yield TextArea(read_only=True, id="feedback-preview")
            yield Checkbox("I reviewed this diagnostic bundle", id="feedback-reviewed")
            yield Static("Nothing is uploaded automatically.", id="feedback-status", markup=False)
            with Horizontal(id="feedback-actions"):
                yield Button("Export JSON", id="feedback-export", variant="primary", disabled=True)
                yield Button("Refresh", id="feedback-refresh")
                yield Button("Back", id="feedback-back")

    def on_mount(self):
        self._ready = True
        self._refresh_bundle()

    def _refresh_bundle(self):
        if not self._ready:
            return
        try:
            self._bundle = feedback_bundle(
                self.app,
                self.query_one("#feedback-description", TextArea).text,
                include_errors=self.query_one("#feedback-errors", Checkbox).value,
                include_route=self.query_one("#feedback-route", Checkbox).value,
            )
        except (OSError, ValueError, LookupError):
            self._bundle = None
            self.query_one("#feedback-status", Static).update(
                "Diagnostics could not be captured. Return to the workspace and retry."
            )
        self.query_one("#feedback-preview", TextArea).load_text(
            json.dumps(self._bundle, indent=2) + "\n"
        )
        self.query_one("#feedback-reviewed", Checkbox).value = False
        self.query_one("#feedback-export", Button).disabled = True

    def on_text_area_changed(self, event: TextArea.Changed):
        if event.text_area.id == "feedback-description":
            self._refresh_bundle()

    def on_checkbox_changed(self, event: Checkbox.Changed):
        if event.checkbox.id == "feedback-reviewed":
            self.query_one("#feedback-export", Button).disabled = not (event.value and self._bundle)
        else:
            self._refresh_bundle()

    def on_input_changed(self, event: Input.Changed):
        if self._ready and event.input.id == "feedback-path":
            self.query_one("#feedback-reviewed", Checkbox).value = False
            self.query_one("#feedback-export", Button).disabled = True

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "feedback-export":
            self.action_export()
        elif event.button.id == "feedback-refresh":
            self._refresh_bundle()
        elif event.button.id == "feedback-back":
            self.action_close()

    def action_export(self):
        if not self._bundle or not self.query_one("#feedback-reviewed", Checkbox).value:
            self.query_one("#feedback-status", Static).update(
                "Review the JSON and select the review checkbox before exporting."
            )
            return
        value = self.query_one("#feedback-path", Input).value.strip()
        if not value:
            self.query_one("#feedback-status", Static).update("Choose an export path first.")
            return
        path = Path(value).expanduser()
        try:
            atomic_json(path, self._bundle, overwrite=False)
        except (OSError, ValueError) as exc:
            self.query_one("#feedback-status", Static).update(f"Could not export: {exc}")
            return
        self.query_one("#feedback-status", Static).update(
            f"Exported to {path}\nYou can attach this file when reporting an issue."
        )
        self.app._announce_transition(
            title="Feedback exported",
            primary=path.name,
            detail="Saved locally after review",
            severity="success",
            popup=True,
            modal=False,
            persist=False,
            timeout=3,
        )

    def action_close(self):
        self.dismiss(None)
