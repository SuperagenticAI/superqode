"""Native Harness² launch, progress, cancellation, and saved-result inspection."""

from __future__ import annotations

import asyncio
import json
import shlex
from pathlib import Path
from uuid import uuid4

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, RichLog, Select, Static, TextArea

from superqode.harness.refinement import (
    RefinementCoordinator,
    RefinementRequest,
    apply_refinement,
    inspect_refinement,
)
from superqode.harness.refinement.models import refinement_options, resume_request
from superqode.harness.refinement.store import digest
from superqode.harness.templates import codegem_template


class RefinementScreen(ModalScreen):
    BINDINGS = [Binding("escape", "back", "Cancel job / Back", priority=True)]
    CSS = """
    RefinementScreen { align: center middle; }
    #refinement-panel { width: 96%; height: 94%; border: round #7c3aed; padding: 0 1; }
    #refinement-title { height: 1; text-style: bold; }
    #refinement-form { height: auto; max-height: 48%; }
    #refinement-form Horizontal { height: 3; }
    #refinement-form Input, #refinement-form Select { width: 1fr; }
    #refinement-task { height: 5; }
    #refinement-status { height: 2; }
    #refinement-log { height: 1fr; min-height: 3; }
    #refinement-detail { height: 1fr; min-height: 3; display: none; }
    #refinement-actions { height: 3; }
    #refinement-actions Button { width: 1fr; min-width: 7; padding: 0; }
    """

    def __init__(
        self,
        *,
        source=None,
        spec=None,
        provider="ollama",
        model="",
        task="",
        output=None,
        coordinator_factory=None,
    ):
        super().__init__()
        self.source = Path(source or Path.cwd()).resolve()
        self.spec = spec or codegem_template()
        self.defaults = refinement_options(self.spec)
        self.provider = provider
        self.model = model
        self.initial_task = task
        self.output = Path(output or self.source / ".superqode" / "refinements" / uuid4().hex[:12])
        self.factory = coordinator_factory or RefinementCoordinator
        self.coordinator = None
        self.running = False
        self.prepared = None
        self.saved = None

    def compose(self) -> ComposeResult:
        with Vertical(id="refinement-panel"):
            yield Static("Harness² · native task refinement", id="refinement-title")
            with VerticalScroll(id="refinement-form"):
                with Horizontal():
                    yield Select(
                        [
                            ("Ollama", "ollama"),
                            ("LM Studio", "lmstudio"),
                            ("llama.cpp / vLLM", "llamacpp"),
                            ("Gemini", "google"),
                        ],
                        value=self.provider
                        if self.provider in {"ollama", "lmstudio", "llamacpp", "google"}
                        else "ollama",
                        allow_blank=False,
                        id="refinement-provider",
                    )
                    yield Input(
                        self.model, placeholder="Model ID (required)", id="refinement-model"
                    )
                yield Input(
                    str(self.source), placeholder="Source directory", id="refinement-source"
                )
                yield Input(
                    str(self.output),
                    placeholder="New output directory or saved job",
                    id="refinement-output",
                )
                yield TextArea(self.initial_task, id="refinement-task")
                with Horizontal():
                    yield Select(
                        [("Sequential", "sequential"), ("Parallel", "parallel")],
                        value=self.defaults.get("mode", "sequential"),
                        allow_blank=False,
                        id="refinement-mode",
                    )
                    yield Select(
                        [(f"k={i}", i) for i in range(1, 5)],
                        value=self.defaults.get("k", 1),
                        allow_blank=False,
                        id="refinement-k",
                    )
                    yield Input(
                        str(self.defaults.get("max_wall_seconds", 900)),
                        placeholder="Max seconds",
                        id="refinement-seconds",
                    )
                yield Input(
                    placeholder="Optional public check, e.g. python -m pytest -q",
                    id="refinement-check",
                )
                yield Input(
                    placeholder="Protected relative files (space separated; quote names with spaces)",
                    id="refinement-protect",
                )
                yield Checkbox(
                    "I reconciled interrupted tool effects; allow retry", id="refinement-retry"
                )
            yield Static(
                "Enter a task and model, then review Plan. CodeGem uses host permissions.",
                id="refinement-status",
            )
            yield RichLog(wrap=True, highlight=False, markup=False, id="refinement-log")
            yield TextArea(read_only=True, id="refinement-detail")
            with Horizontal(id="refinement-actions"):
                for label, name in (
                    ("Plan", "plan"),
                    ("Start", "start"),
                    ("Cancel", "cancel"),
                    ("Inspect", "inspect"),
                    ("Open", "open"),
                    ("Resume", "resume"),
                    ("Apply", "apply"),
                    ("Back", "back"),
                ):
                    yield Button(
                        label,
                        id="refinement-" + name,
                        disabled=name in {"start", "cancel", "inspect", "resume", "apply"},
                    )

    def on_mount(self):
        from superqode.app.constants import THEME

        self.query_one("#refinement-panel").styles.background = THEME["surface2"]
        self.query_one("#refinement-panel").styles.border = ("round", THEME["purple"])
        self.query_one("#refinement-title").styles.color = THEME["magenta"]

    def _status(self, value):
        if self.is_mounted:
            self.query_one("#refinement-status", Static).update(value)

    def _log(self, value):
        if self.is_mounted:
            self.query_one("#refinement-log", RichLog).write(str(value))

    def _request(self):
        check = self.query_one("#refinement-check", Input).value.strip()
        return RefinementRequest(
            task=self.query_one("#refinement-task", TextArea).text,
            source=Path(self.query_one("#refinement-source", Input).value).expanduser().resolve(),
            output=Path(self.query_one("#refinement-output", Input).value).expanduser().resolve(),
            spec=self.spec,
            provider=str(self.query_one("#refinement-provider", Select).value),
            model=self.query_one("#refinement-model", Input).value.strip(),
            mode=str(self.query_one("#refinement-mode", Select).value),
            k=int(self.query_one("#refinement-k", Select).value),
            max_wall_seconds=float(self.query_one("#refinement-seconds", Input).value),
            max_parallel=self.defaults.get("max_parallel", 1),
            max_sessions=self.defaults.get("max_sessions", 64),
            max_turns=self.defaults.get("max_turns", 12),
            max_output_tokens=self.defaults.get("max_output_tokens", 4096),
            checks=(tuple(shlex.split(check)),) if check else (),
            protected_paths=tuple(shlex.split(self.query_one("#refinement-protect", Input).value)),
        )

    @staticmethod
    def _review_key(request):
        return digest({**request.plan(), "task": request.task})

    @on(Button.Pressed)
    async def buttons(self, event: Button.Pressed):
        event.stop()
        action = event.button.id.removeprefix("refinement-")
        try:
            if action == "plan":
                request = self._request()
                self.prepared = self._review_key(request)
                self._log(json.dumps(request.plan(), indent=2))
                self.query_one("#refinement-start", Button).disabled = False
                self._status(
                    "Plan ready. Start runs isolated candidates; results require inspection before application."
                )
            elif action == "start":
                request = self._request()
                if self.prepared != self._review_key(request):
                    raise ValueError("Settings changed; review Plan again")
                self._start(request)
            elif action == "cancel":
                await self.action_back()
            elif action == "back":
                await self.action_back()
            elif action in {"open", "inspect"}:
                await self.inspect_saved()
            elif action == "resume":
                root = (
                    Path(self.query_one("#refinement-output", Input).value).expanduser().resolve()
                )
                request = resume_request(
                    root,
                    retry_interrupted=self.query_one("#refinement-retry", Checkbox).value,
                    max_wall_seconds=float(self.query_one("#refinement-seconds", Input).value),
                )
                self._start(request)
            elif action == "apply":
                if self.saved is None:
                    raise ValueError("Inspect the saved result first")
                result = await asyncio.to_thread(apply_refinement, self.saved)
                self._log(json.dumps(result, indent=2))
                self._status("Checked patch applied to its unchanged source.")
                self.query_one("#refinement-apply", Button).disabled = True
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self._status(str(exc))

    def _start(self, request):
        if self.running:
            raise ValueError("A refinement is already running in this panel")
        self.coordinator = self.factory(request, callback=self._event)
        self.running = True
        for name in ("plan", "start", "open", "resume", "apply"):
            self.query_one("#refinement-" + name, Button).disabled = True
        self.query_one("#refinement-cancel", Button).disabled = False
        self.query_one("#refinement-detail").display = False
        self.query_one("#refinement-log").display = True
        self.query_one("#refinement-form").display = False
        self.run_worker(self._run_job(), exit_on_error=False)

    async def _run_job(self):
        try:
            result = await self.coordinator.run()
            self._status(
                f"{result['status']} · checks {result.get('validation', 'not completed')} · {result['new_sessions']} new sessions"
            )
            self._log(json.dumps(result.get("usage", {}), indent=2))
            if result.get("error"):
                self._log(result["error"])
        except Exception as exc:
            self._status(str(exc))
        finally:
            self.running = False
            if self.is_mounted:
                self.query_one("#refinement-form").display = True
                for name in ("plan", "open", "inspect", "resume"):
                    self.query_one("#refinement-" + name, Button).disabled = False
                self.query_one("#refinement-cancel", Button).disabled = True

    def _event(self, event):
        label = event["data"].get("label", "")
        self._log(f"{event['type']} {label}")
        if event["type"] == "stage.started":
            self._status(f"Running {label} · Escape cancels the complete job")

    async def inspect_saved(self):
        root = Path(self.query_one("#refinement-output", Input).value).expanduser().resolve()
        data = await asyncio.to_thread(inspect_refinement, root)
        self.saved = root
        patch = (
            (root / "selected.patch").read_text()
            if (root / "selected.patch").exists()
            else "No selected patch."
        )
        text = json.dumps(data["result"], indent=2) + "\n\n" + patch
        components = root / "selected-harness.json"
        if components.is_file():
            text += "\n\nSELECTED HARNESS COMPONENTS\n" + components.read_text()
        detail = self.query_one("#refinement-detail", TextArea)
        detail.load_text(text)
        detail.display = True
        self.query_one("#refinement-log").display = False
        result = data["result"]
        self.query_one("#refinement-apply", Button).disabled = (
            self.running
            or result.get("status") != "succeeded"
            or result.get("validation") != "passed"
        )
        self.query_one("#refinement-resume", Button).disabled = self.running
        self._status(
            f"Saved result: {result['status']} · checks {result.get('validation', 'not completed')}"
        )

    async def action_back(self):
        if self.running and self.coordinator:
            self._status("Cancelling all active refinement sessions…")
            await self.coordinator.cancel()
        else:
            self.dismiss(None)

    async def on_unmount(self):
        if self.running and self.coordinator:
            await self.coordinator.cancel()
