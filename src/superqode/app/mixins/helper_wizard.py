"""Harness wizard flow state and prompts."""

from __future__ import annotations
from pathlib import Path
from rich.text import Text
from superqode.app.constants import (
    THEME,
)


class HelperWizardMixin:
    """Harness wizard flow state and prompts."""

    def _start_harness_wizard_flow(self, log) -> None:
        """Start the step-by-step HarnessSpec wizard in the TUI."""
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

        try:
            from superqode.harness import (
                WizardAnswers,
                build_wizard_spec,
                explain_harness,
                render_explanation,
                save_harness_spec,
            )

            answers = WizardAnswers(**answers_kwargs)
            spec = build_wizard_spec(answers)
            path = save_harness_spec(spec, output)
            (Path(".agents") / "skills").mkdir(parents=True, exist_ok=True)
            (Path(".agents") / "roles").mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.add_error(f"Could not create harness: {exc}")
            self._awaiting_harness_wizard = False
            self._harness_wizard_state = None
            return

        self._awaiting_harness_wizard = False
        self._harness_wizard_state = None

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
