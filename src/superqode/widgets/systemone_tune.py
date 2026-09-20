"""Guided decision tuning; all experiment semantics live in systemone.tune."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Select, Static

from superqode.systemone import tune


class SystemOneTuneScreen(Screen[str | None]):
    """Prepare, review, run and inspect a frozen decision-pack experiment."""

    BINDINGS = [Binding("escape", "close", "Back / Stop")]
    CSS = """
    SystemOneTuneScreen { background: #000000; color: #e6e6e6; }
    SystemOneTuneScreen VerticalScroll { padding: 1 2; }
    SystemOneTuneScreen Vertical { height: auto; }
    SystemOneTuneScreen Static { height: auto; margin-bottom: 1; }
    SystemOneTuneScreen Input, SystemOneTuneScreen Select {
        margin-bottom: 1; background: #141414; color: #e6e6e6;
    }
    SystemOneTuneScreen Horizontal { height: auto; }
    SystemOneTuneScreen Button { margin: 0 1 1 0; }
    SystemOneTuneScreen #tune-status { color: #c4b5fd; }
    SystemOneTuneScreen #tune-diff { border: round #3b1d7a; padding: 1; }
    """

    def __init__(self, *, spec: str = ""):
        super().__init__()
        self.spec_path = spec
        self.output: Path | None = None
        self.manifest: dict | None = None
        self.pending: list[dict] = []
        self.report: dict | None = None
        self.running = False
        self.installing = False
        self.cancel = threading.Event()

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static("SystemOne Tune · Improve decisions", id="tune-title")
            yield Static(
                "Review examples, improve decision criteria, then compare on reserved examples. Your active harness stays unchanged."
            )
            with Vertical(id="tune-setup"):
                yield Static("Decision pack or harness")
                yield Input(
                    value="factory_route",
                    placeholder="Built-in pack ID or question-pack path",
                    id="tune-pack",
                )
                yield Input(
                    value=self.spec_path,
                    placeholder="Harness YAML (optional; overrides pack)",
                    id="tune-spec",
                )
                yield Static("Examples")
                yield Input(
                    placeholder="CSV / JSONL / JSON / YAML path (empty = routing demo)",
                    id="tune-data",
                )
                yield Input(value="state", placeholder="Input column", id="tune-input")
                yield Input(
                    value="label", placeholder="Expected-answer column", id="tune-label-column"
                )
                yield Input(
                    placeholder="Saved experiment directory (optional; resumes review/results)",
                    id="tune-resume",
                )
                yield Button("Prepare examples", variant="primary", id="tune-prepare")
            with Vertical(id="tune-limits"):
                yield Static("Experiment limits")
                yield Input(
                    value=tune.preferred_reflection_model(),
                    placeholder="Reflection model: provider/model",
                    id="tune-model",
                )
                yield Input(
                    value="120", placeholder="Maximum optimization evaluations", id="tune-evals"
                )
                yield Input(
                    value="2.00",
                    placeholder="Reflection dollar limit (Jev usage additional)",
                    id="tune-cost",
                )
                yield Button("Install tuning support", id="tune-install")
            with Vertical(id="tune-review"):
                yield Static("", id="tune-example")
                yield Select([], prompt="Which decision is correct?", id="tune-choice")
                yield Input(placeholder="Why? Optional explanation", id="tune-rationale")
                yield Button("Save judgment", variant="primary", id="tune-save")
            yield Static("", id="tune-status")
            yield Static("", id="tune-summary")
            yield Static("", id="tune-diff")
            with Horizontal():
                yield Button("Start experiment", variant="primary", id="tune-start")
                yield Button("Use this version", variant="primary", id="tune-use")
                yield Button("Back", id="tune-back")
        yield Footer()

    def on_mount(self) -> None:
        for selector in ("#tune-review", "#tune-start", "#tune-use", "#tune-diff"):
            self.query_one(selector).display = False
        prefs = tune.load_tune_preferences()
        model = str(prefs.get("reflection_lm") or tune.preferred_reflection_model()).strip()
        if model:
            self.query_one("#tune-model", Input).value = model
        if "max_evals" in prefs:
            self.query_one("#tune-evals", Input).value = str(prefs["max_evals"])
        if "max_reflection_cost" in prefs:
            self.query_one("#tune-cost", Input).value = str(prefs["max_reflection_cost"])
        self._refresh_support_status()

    def _credential_status(self) -> str:
        model = self._value("model") if self.is_mounted else ""
        model = model or tune.preferred_reflection_model()
        api_key_env = "TYPESAFE_API_KEY"
        try:
            from types import SimpleNamespace
            from superqode.systemone.config import resolve_systemone

            probe = resolve_systemone(
                spec=None, explicit=SimpleNamespace(enabled=True, client="live")
            )
            api_key_env = getattr(probe, "api_key_env", api_key_env) or api_key_env
        except Exception:
            pass
        missing = tune.missing_tune_credentials(reflection_lm=model, api_key_env=api_key_env)
        return tune.format_missing_tune_credentials(missing)

    def _refresh_support_status(self) -> None:
        ready = tune.tuning_support_available()
        install_btn = self.query_one("#tune-install", Button)
        install_btn.disabled = ready
        if ready:
            creds = self._credential_status()
            if creds:
                self._status(creds)
            else:
                self._status("Tuning support is ready. Fill the pack and examples, then Prepare.")
        else:
            self._status(
                "Tuning support (GEPA) is not installed yet. Click Install tuning support before Start. Prepare and labeling work without it."
            )
            install_btn.variant = "primary"

    def _remember_preferences(self) -> None:
        model = self._value("model") or tune.preferred_reflection_model()
        updates: dict = {}
        if model:
            updates["reflection_lm"] = model
        try:
            updates["max_evals"] = int(self._value("evals"))
        except ValueError:
            pass
        try:
            updates["max_reflection_cost"] = float(self._value("cost"))
        except ValueError:
            pass
        if updates:
            tune.save_tune_preferences(**updates)

    def _value(self, name: str) -> str:
        return self.query_one(f"#tune-{name}", Input).value.strip()

    def _status(self, text: str) -> None:
        self.query_one("#tune-status", Static).update(Text(text))

    @on(Button.Pressed, "#tune-prepare")
    def prepare(self) -> None:
        try:
            self._remember_preferences()
            resume = self._value("resume")
            if resume:
                self.output = Path(resume).expanduser()
                self.manifest = tune.load_run(self.output)
            else:
                options = tune.TuneOptions(
                    pack=self._value("pack"),
                    spec=self._value("spec"),
                    reflection_lm=self._value("model") or tune.preferred_reflection_model(),
                    max_evals=int(self._value("evals")),
                    max_reflection_cost=float(self._value("cost")),
                )
                data = self._value("data")
                if not data and (options.spec or options.pack != "factory_route"):
                    raise ValueError(
                        "Provide your example file for this pack. The empty-file demo uses factory_route."
                    )
                rows = (
                    tune.read_examples(
                        data,
                        input_column=self._value("input"),
                        label_column=self._value("label-column"),
                    )
                    if data
                    else tune.demo_examples()
                )
                self.output = tune.new_output()
                self.manifest = tune.prepare_run(options, rows, self.output)
            if self.manifest["status"] == "completed":
                self._finished(json.loads((self.output / "report.json").read_text()))
                return
            if self.manifest["status"] != "review":
                raise ValueError(
                    "This experiment already started. Its evidence is saved; prepare a new experiment for a new budget."
                )
            saved_options = self.manifest["options"]
            for name, key in (
                ("model", "reflection_lm"),
                ("evals", "max_evals"),
                ("cost", "max_reflection_cost"),
            ):
                self.query_one(f"#tune-{name}", Input).value = str(saved_options[key])
            self.pending = [row for row in self.manifest["examples"] if row.get("label") is None]
            labels = list(next(iter(self.manifest["pack"]["questions"].values()))["criteria"])
            self.query_one("#tune-choice", Select).set_options([(label, label) for label in labels])
            self.query_one("#tune-setup").display = False
            self._next_example()
        except (ValueError, OSError, KeyError) as exc:
            self._status(str(exc))

    def _next_example(self) -> None:
        self.query_one("#tune-review").display = bool(self.pending)
        if self.pending:
            row = self.pending[0]
            split = (
                "Reserved test · excluded from optimization"
                if row["split"] == "test"
                else "Development example"
            )
            self.query_one("#tune-example", Static).update(
                Text(
                    f"{split}\n{len(self.pending)} judgments remaining\n\n"
                    + json.dumps(row["state"], ensure_ascii=False, indent=2)
                )
            )
            self.query_one("#tune-choice", Select).clear()
            self.query_one("#tune-rationale", Input).value = ""
            self._status(f"Labels save after each judgment. Resume from: {self.output}")
        else:
            options = self.manifest["options"]
            test_count = sum(row["split"] == "test" for row in self.manifest["examples"])
            creds = self._credential_status()
            self._status(
                f"Ready · {len(self.manifest['examples'])} reviewed examples\n"
                f"Up to {options['max_evals']} optimization evaluations + {2 * test_count} final test evaluations.\n"
                f"Reflection: {options['reflection_lm'] or 'not configured'} · ceiling ${options['max_reflection_cost']:.2f}. Jev usage/retries are additional.\n"
                "Jev receives example inputs and criteria. The reflection provider also receives development examples and rationales.\n"
                f"Saved experiment: {self.output}\nSmall demos are pilots and cannot qualify for adoption."
                + (("\n" + creds) if creds else "")
            )
            self.query_one("#tune-start").display = True

    @on(Button.Pressed, "#tune-save")
    def save(self) -> None:
        choice = self.query_one("#tune-choice", Select).value
        if choice is Select.BLANK:
            self._status("Choose the correct decision before saving.")
            return
        try:
            self.manifest = tune.save_label(
                self.output, self.pending[0]["id"], str(choice), self._value("rationale")
            )
            self.pending.pop(0)
            self._next_example()
        except (ValueError, OSError) as exc:
            self._status(str(exc))

    @on(Button.Pressed, "#tune-start")
    def start(self) -> None:
        if self.running:
            return
        try:
            self._remember_preferences()
            creds = self._credential_status()
            if creds:
                self._status(creds)
                return
            if not tune.tuning_support_available():
                self._status(
                    "Install tuning support first, then Start. No restart is usually required after Install succeeds."
                )
                return
            self.manifest["options"].update(
                reflection_lm=self._value("model") or tune.preferred_reflection_model(),
                max_evals=int(self._value("evals")),
                max_reflection_cost=float(self._value("cost")),
            )
            tune.write_json(self.output / "run.json", self.manifest)
            details = tune.preflight(self.manifest)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self._status(str(exc))
            return
        except Exception as exc:
            self._status(f"Could not start the experiment: {exc}")
            return
        self.cancel.clear()
        self.running = True
        self.query_one("#tune-start", Button).disabled = True
        self.query_one("#tune-limits").display = False
        self.query_one("#tune-back", Button).label = "Stop"
        self._status(
            "Starting · reflection "
            f"{details.get('reflection_model') or details.get('model')} · "
            f"Jev {details.get('model')} at {details.get('endpoint')}"
        )
        self._run()

    @work(thread=True, exclusive=True)
    def _run(self) -> None:
        try:
            report = tune.run_tune(
                self.output,
                cancel=self.cancel,
                progress=lambda text: self.app.call_from_thread(self._status, text),
            )
            self.app.call_from_thread(self._finished, report)
        except Exception as exc:
            self.app.call_from_thread(self._failed, str(exc))

    def _failed(self, message: str) -> None:
        self.running = False
        self.query_one("#tune-start").display = False
        self.query_one("#tune-back", Button).label = "Back"
        self._status(f"{message}\nSaved experiment: {self.output}")

    @on(Button.Pressed, "#tune-install")
    def install(self) -> None:
        if self.running:
            return
        self._remember_preferences()
        self.running = True
        self.installing = True
        for name in ("install", "start", "prepare", "back"):
            self.query_one(f"#tune-{name}", Button).disabled = True
        self._status(
            "Installing tested tuning support into SuperQode's Python environment. No model calls are made."
        )
        self._install()

    @work(thread=True, group="tune-install")
    def _install(self) -> None:
        try:
            message = tune.install_support()
        except ValueError as exc:
            message = str(exc)
        self.app.call_from_thread(self._installation_finished, message)

    def _installation_finished(self, message: str) -> None:
        self.running = False
        self.installing = False
        for name in ("install", "start", "prepare", "back"):
            try:
                self.query_one(f"#tune-{name}", Button).disabled = False
            except Exception:
                pass
        self._refresh_support_status()
        self._status(message + ("\nSaved judgments: " + str(self.output) if self.output else ""))

    def _finished(self, report: dict) -> None:
        self.report = report
        self.running = False
        for selector in ("#tune-setup", "#tune-review", "#tune-start", "#tune-limits"):
            self.query_one(selector).display = False
        self.query_one("#tune-back", Button).label = "Keep current / Back"
        self.query_one("#tune-summary", Static).update(Text(tune.render_report(report)))
        self.query_one("#tune-diff", Static).update(Text(report["diff"] or "No question changes."))
        self.query_one("#tune-diff").display = True
        self.query_one("#tune-use").display = bool(report["eligible"])
        self._status("Review the comparison and criteria changes below.")

    @on(Button.Pressed, "#tune-use")
    def use_version(self) -> None:
        if self.report and self.report["eligible"]:
            try:
                self.dismiss(tune.candidate_use_path(self.report))
            except (ValueError, OSError) as exc:
                self._status(str(exc))

    @on(Button.Pressed, "#tune-back")
    def back(self) -> None:
        self.action_close()

    def action_close(self) -> None:
        if self.installing:
            self._status("Installation is still running. You can return when it finishes.")
            return
        if self.running:
            self.cancel.set()
            self._status("Stopping after the in-flight operation. Completed evaluations are saved.")
            return
        self.dismiss(None)
