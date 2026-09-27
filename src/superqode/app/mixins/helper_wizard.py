"""Harness wizard flow state and prompts."""

from __future__ import annotations
from pathlib import Path
from rich.text import Text
from superqode.app.constants import (
    THEME,
)


class HelperWizardMixin:
    """Harness wizard flow state and prompts."""

    def _cancel_harness_wizard(self, log=None, *, announce: bool = False) -> bool:
        """Invalidate wizard work and return whether a wizard was active."""
        was_active = bool(
            getattr(self, "_awaiting_harness_wizard", False)
            or getattr(self, "_harness_wizard_finishing", False)
        )
        # Workers cannot safely be interrupted during a file write. A generation
        # token prevents an obsolete completion from repainting or loading itself.
        self._harness_wizard_generation = getattr(self, "_harness_wizard_generation", 0) + 1
        self._awaiting_harness_wizard = False
        self._harness_wizard_finishing = False
        self._harness_wizard_state = None
        if was_active and announce and log is not None:
            try:
                log.add_info("Harness wizard cancelled.")
            except Exception:
                pass
        return was_active

    def _start_harness_wizard_flow(self, log) -> None:
        """Start the step-by-step HarnessSpec wizard in the TUI."""
        self._cancel_harness_wizard()
        self._awaiting_harness_wizard = True
        self._harness_wizard_state = {
            "step": "name",
            "history": [],
            "answers": {
                "name": "my-harness",
                "starter": "qwen-coding",
                "provider": "",
                "model": "",
                "allow_write": True,
                "allow_shell": True,
                "allow_network": False,
                "approval_profile": "balanced",
                "tool_call_format": "auto",
                "workflow_preset": "single",
            },
            "output": self._default_harness_wizard_output(),
            "load": True,
            "force": False,
        }
        self._render_harness_wizard_step(log)

    @staticmethod
    def _default_harness_wizard_output() -> str:
        base = Path("harness.yaml")
        if not base.exists():
            return str(base)
        for index in range(2, 1000):
            candidate = Path(f"harness-{index}.yaml")
            if not candidate.exists():
                return str(candidate)
        return "harness-new.yaml"

    @staticmethod
    def _parse_yes_no(raw: str) -> bool | None:
        lowered = raw.strip().lower()
        if lowered in {"y", "yes", "true", "1"}:
            return True
        if lowered in {"n", "no", "false", "0"}:
            return False
        return None

    @staticmethod
    def _wizard_starters() -> tuple[tuple[str, str], ...]:
        from superqode.harness import WIZARD_STARTERS

        return WIZARD_STARTERS

    def _finish_harness_wizard_flow(self, log) -> None:
        state = getattr(self, "_harness_wizard_state", None)
        if not state:
            return
        answers_kwargs = dict(state["answers"])
        output = Path(state["output"]).expanduser()
        load_after_write = bool(state.get("load", True))

        if output.exists() and not state.get("force", False):
            state["output"] = self._default_harness_wizard_output()
            log.add_error(
                f"{output} already exists. Suggested next available path: {state['output']}"
            )
            state["step"] = "output"
            self._render_harness_wizard_step(log)
            return

        # Building + saving + loading touches the filesystem and the harness
        # machinery; do it in a worker so the TUI never freezes on Enter.
        # Snapshot + clear state first so typed input is normal chat again.
        self._awaiting_harness_wizard = False
        self._harness_wizard_finishing = True
        self._harness_wizard_state = None
        generation = getattr(self, "_harness_wizard_generation", 0)
        log.add_info(f"Creating harness at {output}…")
        runner = getattr(self, "run_worker", None)
        if callable(runner):
            try:
                import asyncio as _asyncio_check

                _asyncio_check.get_running_loop()
            except RuntimeError:
                runner = None
        if callable(runner):
            try:
                runner(
                    self._finish_harness_wizard_worker(
                        answers_kwargs, output, load_after_write, log, generation
                    )
                )
                return
            except Exception:
                pass
        try:
            result = self._run_harness_wizard_finish(answers_kwargs, output, load_after_write, None)
        except Exception as exc:  # noqa: BLE001 - synchronous fallback must surface failures
            self._harness_wizard_finishing = False
            log.add_error(f"Could not create harness: {exc}")
            return
        if result is not None and generation == getattr(self, "_harness_wizard_generation", 0):
            self._harness_wizard_finishing = False
            self._show_harness_wizard_result(log, *result)

    async def _finish_harness_wizard_worker(
        self, answers_kwargs, output, load_after_write, log, generation
    ) -> None:
        import asyncio as _asyncio

        try:
            result = await _asyncio.to_thread(
                self._run_harness_wizard_finish, answers_kwargs, output, load_after_write, None
            )
        except Exception as exc:  # noqa: BLE001 - worker failures still surface
            if generation == getattr(self, "_harness_wizard_generation", 0):
                self._harness_wizard_finishing = False
                log.add_error(f"Could not create harness: {exc}")
            return
        if result is None:
            return
        if generation != getattr(self, "_harness_wizard_generation", 0):
            return
        self._harness_wizard_finishing = False
        spec, path, answers, load = result
        self._show_harness_wizard_result(log, spec, path, answers, load)

    def _run_harness_wizard_finish(self, answers_kwargs, output, load_after_write, log):
        """Blocking build step. Returns (spec, path, answers, load) or None."""
        from superqode.harness import (
            WizardAnswers,
            build_wizard_spec,
            save_harness_spec,
        )

        answers = WizardAnswers(**answers_kwargs)
        spec = build_wizard_spec(answers)
        path = save_harness_spec(spec, output)
        (Path(".agents") / "skills").mkdir(parents=True, exist_ok=True)
        (Path(".agents") / "roles").mkdir(parents=True, exist_ok=True)
        return spec, path, answers, load_after_write

    def _show_harness_wizard_result(self, log, spec, path, answers, load_after_write) -> None:
        from superqode.harness import explain_harness, render_explanation

        t = Text()
        t.append("\n  ▣ ", style=f"bold {THEME['purple']}")
        t.append("Harness Created\n\n", style=f"bold {THEME['text']}")
        t.append("  Wrote       ", style=THEME["muted"])
        t.append(str(path), style=f"bold {THEME['cyan']}")
        t.append("\n  Name        ", style=THEME["muted"])
        t.append(spec.name, style=THEME["text"])
        t.append("\n  Runtime     ", style=THEME["muted"])
        t.append(spec.runtime.backend, style=THEME["text"])
        t.append("\n  Model       ", style=THEME["muted"])
        t.append(spec.model_policy.primary or "active connection", style=THEME["text"])
        t.append("\n\n")
        explanation = render_explanation(
            explain_harness(
                spec,
                provider=answers.provider,
                model=answers.model,
            )
        )
        for line in explanation.splitlines()[:14]:
            t.append("  ", style="")
            t.append(line, style=THEME["text"])
            t.append("\n")
        t.append("\n  Next        ", style=THEME["muted"])
        t.append(f":harness {path}", style=THEME["cyan"])
        t.append("  ", style="")
        t.append(":harness doctor", style=THEME["cyan"])
        t.append("\n")
        self._show_command_output(log, t)

        if load_after_write:
            self._harness_cmd(f"load {path}", log)

    def _active_harness_spec(self):
        """Return the active HarnessSpec and source path, if one is configured."""
        import os as _os

        pure = getattr(self, "_pure_mode", None)
        spec = getattr(pure, "_harness_spec", None) if pure is not None else None
        path = getattr(pure, "_harness_path", "") if pure is not None else ""
        if spec is not None:
            return spec, path

        env_path = _os.getenv("SUPERQODE_HARNESS", "").strip()
        if not env_path:
            return None, ""
        try:
            from superqode.harness import load_harness_spec

            return load_harness_spec(env_path), env_path
        except Exception:
            return None, env_path
