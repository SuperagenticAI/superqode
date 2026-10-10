"""A first successful task using the same connection, prompt and review flows."""

from __future__ import annotations

import asyncio
from pathlib import Path
import shlex

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static, TextArea

from superqode.app.developer_trial import default_context, project_context
from superqode.app.widgets import ConversationLog


class DeveloperTrialScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Back", priority=True)]
    CSS = """
    DeveloperTrialScreen { align: center middle; }
    DeveloperTrialScreen > Vertical { width: 86; max-width: 96%; height: 92%; background: $sq-bg; border: round $sq-purple; padding: 0 1; }
    DeveloperTrialScreen .title { height: 1; color: $sq-purple; text-style: bold; }
    DeveloperTrialScreen #trial-body { height: 1fr; }
    DeveloperTrialScreen Label { height: auto; color: $sq-purple; text-style: bold; margin-top: 1; }
    DeveloperTrialScreen Static { height: auto; }
    DeveloperTrialScreen #trial-task { height: 5; }
    DeveloperTrialScreen #trial-status { height: 2; color: $sq-muted; }
    DeveloperTrialScreen Horizontal { height: 3; }
    DeveloperTrialScreen Button { width: auto; min-width: 9; margin-right: 1; }
    """

    def __init__(self, state):
        super().__init__()
        self.state = state
        self._checking = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Your first successful task", classes="title")
            with VerticalScroll(id="trial-body"):
                yield Static(
                    "Use your own project and coding route. Esc returns to your draft; :trial reopens this guide."
                )
                yield Label("1. Choose a harness and model")
                yield Static("", id="trial-route", markup=False)
                yield Button("Choose connection", id="trial-connect")
                yield Label("2. Validate the connection")
                yield Static(self.state.check_message, id="trial-check", markup=False)
                yield Button("Validate setup", id="trial-validate")
                yield Label("3. Attach project context")
                yield Static(
                    "Choose a small project text file. Its content is sent only when you run the task."
                )
                yield Input(
                    self.state.context or default_context(Path.cwd()),
                    placeholder="README.md",
                    id="trial-context",
                )
                yield Button("Attach context", id="trial-attach")
                yield Label("4. Run a small task")
                yield TextArea(self.state.task, id="trial-task")
                yield Static(
                    "Run uses your selected route and may consume account usage. Your current approval policy applies; Esc cancels in the workspace."
                )
                yield Button("Run this task", id="trial-run", variant="primary", disabled=True)
                yield Label("5. Review the result")
                yield Static(self.state.result, id="trial-result", markup=False)
                with Horizontal():
                    yield Button(
                        "Review answer", id="trial-answer", disabled=not self.state.completed
                    )
                    yield Button(
                        "Activity / changes", id="trial-review", disabled=not self.state.completed
                    )
            yield Static(
                "Scroll or Tab through each step. Nothing runs until you choose Run.",
                id="trial-status",
                markup=False,
            )
            with Horizontal():
                yield Button("Back to workspace", id="trial-back")
                yield Button("Feedback", id="trial-feedback")

    def on_mount(self):
        self._refresh_state()

    def _refresh_state(self):
        kind, provider, model = self.app._connection_target()
        self.query_one("#trial-route", Static).update(
            f"{kind.upper()} · {provider} · {model or 'agent default'}"
            if provider
            else "No connection selected yet."
        )
        if (
            self.state.route_ready
            and self.state.checked_route != self.app._connection_fingerprint()
        ):
            self.state.route_ready = False
            self.state.check_message = "Validate the selected route before running."
        if self.state.pending and not self.app.is_busy:
            self.state.result = (
                "No successful answer recorded yet. Check Activity, or validate and retry."
            )
        self.query_one("#trial-check", Static).update(self.state.check_message)
        self.query_one("#trial-result", Static).update(self.state.result)
        from superqode.widgets.file_reference import format_file_reference

        attached = format_file_reference(self.state.context) if self.state.context else ""
        ready = self.state.route_ready and attached in getattr(self.app, "_attached_refs", [])
        self.query_one("#trial-run", Button).disabled = (
            not ready or self.app.is_busy or self._checking
        )
        self.query_one("#trial-validate", Button).disabled = self.app.is_busy or self._checking

    def on_button_pressed(self, event: Button.Pressed):
        action = event.button.id
        if action == "trial-connect":
            log = self.app.query_one("#log", ConversationLog)
            self.state.awaiting_connection = True
            self.action_close()

            def connect():
                self.app._open_connection_browser(log)
                log.add_info(
                    "After connecting, use :trial to validate and continue your first task."
                )

            self.app.call_later(connect)
        elif action == "trial-validate":
            self.validate_setup()
        elif action == "trial-attach":
            self.attach_context()
        elif action == "trial-run":
            self.action_run()
        elif action in {"trial-answer", "trial-review"}:
            if not self.state.completed:
                return
            self.state.reviewed = True
            self.action_close()
            if self.state.outcome:
                self.app.call_later(self.app._present_outcome, self.state.outcome, receipt=False)
            else:
                self.app.call_later(
                    self.app.query_one("#log", ConversationLog).scroll_end, animate=False
                )
        elif action == "trial-feedback":
            self.action_close()
            self.app.call_later(self.app._feedback_cmd, self.app.query_one("#log", ConversationLog))
        elif action == "trial-back":
            self.action_close()

    @work(exclusive=True)
    async def validate_setup(self):
        from superqode.providers.connection_diagnostics import (
            check_model_connection,
            failure_message,
        )

        if self.app.is_busy or self._checking:
            return
        self._checking = True
        self.state.route_ready = False
        fingerprint = self.app._connection_fingerprint()
        kind, provider, model = self.app._connection_target()
        self.state.check_message = "Checking setup; no inference request is sent…"
        self._refresh_state()
        try:
            if not provider or (kind == "model" and not self.app._has_live_connection()):
                ready, message = False, "Choose a connection first."
            elif kind == "model":
                check = await asyncio.wait_for(
                    check_model_connection(provider, model, infer=False), timeout=25
                )
                ready = check.status in {"configured", "reachable", "verified"}
                message = check.message
            else:
                ready = True
                message = "Route selected. The first task verifies the agent's sign-in, account and model access."
        except Exception as exc:
            _, message = failure_message(exc)
            ready = False
        finally:
            self._checking = False
        if not self.is_mounted:
            return
        if fingerprint != self.app._connection_fingerprint():
            self.state.route_ready = False
            self.state.check_message = (
                "The connection changed during validation. Validate the new route."
            )
        else:
            self.state.checked_route = fingerprint
            self.state.route_ready = ready
            self.state.check_message = message
            if kind == "model" and "check" in locals():
                self.app._last_connection_check = (fingerprint, check)
        self._refresh_state()

    def attach_context(self):
        try:
            path = project_context(
                self.query_one("#trial-context", Input).value.strip(), Path.cwd()
            )
        except (OSError, ValueError) as exc:
            self.query_one("#trial-status", Static).update(f"Could not attach: {exc}")
            return
        self.app._attach_cmd(shlex.quote(str(path)), self.app.query_one("#log", ConversationLog))
        self.state.context = str(path.relative_to(Path.cwd().resolve()))
        self.query_one("#trial-status", Static).update(
            f"Attached {self.state.context}. Your draft is retained."
        )
        self._refresh_state()

    def action_run(self):
        from superqode.app.inputs import SelectionAwareInput

        self._refresh_state()
        if self.query_one("#trial-run", Button).disabled or self.app._trial_setup_pending():
            self.query_one("#trial-status", Static).update(
                "Validate the connection and attach context first; finish any pending setup or approval."
            )
            return
        task = self.query_one("#trial-task", TextArea).text.strip()
        if not task or task.startswith((":", "/", "!", ">")):
            self.query_one("#trial-status", Static).update(
                "Describe a small coding task in plain text."
            )
            return
        try:
            project_context(self.state.context, Path.cwd())
        except (OSError, ValueError) as exc:
            self.query_one("#trial-status", Static).update(f"Project context changed: {exc}")
            return
        prompt = self.app.query_one("#prompt-input", SelectionAwareInput)
        if prompt.value.strip():
            self.app._draft_stash = [*getattr(self.app, "_draft_stash", []), prompt.value][-20:]
            self.app.query_one("#log", ConversationLog).add_info(
                "Your original draft is saved. Use :stash to restore it after this task."
            )
        self.state.task = task
        self.state.submitted_route = self.app._trial_route_identity()
        self.state.task_id = ""
        self.state.pending = True
        self.state.completed = False
        self.state.reviewed = False
        self.state.result = (
            "Task submitted. Return with :trial after it finishes to review the result."
        )
        self.action_close()

        def submit():
            self.app._set_prompt_prefill(task)
            self.app._sync_attachment_prefill()
            prompt.post_message(Input.Submitted(prompt, prompt.value))

        self.app.call_later(submit)

    def action_close(self):
        self.state.task = self.query_one("#trial-task", TextArea).text
        if self._checking:
            self.state.route_ready = False
            self.state.check_message = "Validation was interrupted. Validate again to continue."
        self.dismiss(None)
