"""Codex SDK runtime support."""

from __future__ import annotations
import asyncio
import os
import re
import time
from pathlib import Path
from typing import Any
from rich.text import Text
from superqode.app.constants import (
    THEME,
)
from superqode.app.widgets import (
    ModeBadge,
    ConversationLog,
)

# --- helpers extracted from app_main (A1) ---
from superqode.app.recipes import PromptCompletionCandidate


class CodexMixin:
    """Codex SDK model/effort pickers and execution."""

    @property
    def codex_models(self) -> List[Dict]:
        """Lazy load Codex models."""
        if self._codex_models is None:
            self._codex_models = self._get_codex_models()
        return self._codex_models
    def _get_codex_models(self) -> List[Dict]:
        """Get live Codex models exposed to the local Codex account."""
        try:
            return self._fetch_live_codex_models()
        except Exception:
            # Empty model keeps Codex's local default; avoid stale hardcoded IDs.
            return [
                {
                    "id": "",
                    "name": "Codex default",
                    "context": 0,
                    "desc": "Use the model configured in ~/.codex",
                }
            ]
    def _fetch_live_codex_models(self) -> List[Dict]:
        existing = getattr(self, "_pure_mode", None)
        runtime = getattr(existing, "_runtime", None) if existing is not None else None
        if (
            runtime is not None
            and getattr(existing, "runtime_name", "") == "codex-sdk"
            and hasattr(runtime, "models")
        ):
            return self._models_from_codex_response(runtime.models())

        from superqode.codex import make_codex_runtime

        probe = make_codex_runtime(cwd=Path.cwd())
        try:
            return self._models_from_codex_response(probe.models())
        finally:
            probe.close()
    @staticmethod
    def _models_from_codex_response(models_response) -> List[Dict]:
        data = list(getattr(models_response, "data", []) or [])
        models: List[Dict] = []
        for model in data:
            model_id = str(getattr(model, "model", getattr(model, "id", model)) or "")
            if not model_id:
                continue
            label = str(
                getattr(model, "display_name", None)
                or getattr(model, "displayName", None)
                or model_id.replace("-", " ").replace("_", " ").title()
            )
            efforts = []
            for option in list(getattr(model, "supported_reasoning_efforts", []) or []):
                effort = getattr(option, "reasoning_effort", option)
                efforts.append(str(getattr(effort, "value", effort)))
            models.append(
                {
                    "id": model_id,
                    "name": label,
                    "context": 0,
                    "efforts": efforts,
                    "hidden": bool(getattr(model, "hidden", False)),
                }
            )
        from superqode.providers.models import sort_models_newest_first

        return sort_models_newest_first(models)
    @staticmethod
    def _codex_config_error_hint_text(exc) -> str | None:
        """Return an actionable hint for a rejected ``~/.codex/config.toml``.

        A newer standalone Codex CLI can write configuration values before the
        SDK's bundled app-server learns them.  Keep the parser independent of
        the TUI so cold connection, status probing, and stream errors all show
        the same recovery guidance.
        """

        message = str(exc)
        if "failed to load configuration" not in message.lower():
            return None
        location = re.search(r"(\S+config\.toml:\d+:\d+)", message)
        unknown = re.search(r"unknown variant `([^`]+)`", message)
        expected = re.search(r"expected one of (.+?)(?:\n|$)", message)
        source = location.group(1) if location else "~/.codex/config.toml"
        if unknown and expected:
            return (
                f"Codex's bundled app-server cannot read {source}: "
                f"`{unknown.group(1)}` is newer than it supports. Restart SuperQode to apply its "
                f"compatible per-process effort override; if that is unavailable, change the value to one of: "
                f"{expected.group(1).strip()}."
            )
        return f"Codex could not read {source}. Fix the reported config line, then retry."
    @staticmethod
    def _codex_error_hint(message: str) -> str:
        """Map common Codex SDK/app-server failures to user-facing recovery hints."""

        from superqode.app_main import SuperQodeApp
        config_hint = SuperQodeApp._codex_config_error_hint_text(message)
        if config_hint:
            return config_hint
        lowered = (message or "").lower()
        if "codex-sdk" in lowered and "install" in lowered:
            return 'Install the SDK extra: uv tool install "superqode[codex-sdk]".'
        if "not logged" in lowered or "login" in lowered or "auth" in lowered:
            return "Run `codex login`, then retry from SuperQode."
        if "auth.json" in lowered:
            return "Run `codex login`; SuperQode uses your ~/.codex auth."
        if "openai-codex-cli-bin" in lowered or "codex process" in lowered:
            return 'Reinstall the SDK extra so the app-server binary is present: uv tool install --reinstall "superqode[codex-sdk]".'
        if "untrusted" in lowered or "trust" in lowered:
            return "Trust this project or adjust policy in ~/.codex, then retry."
        if "model" in lowered and ("unavailable" in lowered or "not found" in lowered):
            return "Use `:codex status` to list models available to your Codex account."
        if "approval" in lowered or "permission" in lowered:
            return (
                "Use the TUI approval prompt, set `:mode auto`, or adjust Codex policy in ~/.codex."
            )
        if "turn/completed" in lowered:
            return "The Codex app-server stream ended unexpectedly. Retry; if it repeats, run `:codex status`."
        return "Run `:codex status` for SDK, app-server, auth, and model diagnostics."
    def action_navigate_codex_model_up(self):
        """Navigate to previous Codex SDK model."""
        if not getattr(self, "_awaiting_codex_model", False):
            return
        models = getattr(self, "_codex_models", None) or []
        if not models:
            return
        current_idx = getattr(self, "_codex_highlighted_model_index", 0)
        self._codex_highlighted_model_index = max(0, current_idx - 1)
        log = self.query_one("#log", ConversationLog)
        self._show_codex_model_picker(log, clear_log=False, refetch=False)
        self._scroll_to_highlighted_item(log, self._codex_highlighted_model_index, len(models))
        self.set_timer(0.05, self._ensure_input_focus)
    def action_navigate_codex_model_down(self):
        """Navigate to next Codex SDK model."""
        if not getattr(self, "_awaiting_codex_model", False):
            return
        models = getattr(self, "_codex_models", None) or []
        if not models:
            return
        current_idx = getattr(self, "_codex_highlighted_model_index", 0)
        self._codex_highlighted_model_index = min(len(models) - 1, current_idx + 1)
        log = self.query_one("#log", ConversationLog)
        self._show_codex_model_picker(log, clear_log=False, refetch=False)
        self._scroll_to_highlighted_item(log, self._codex_highlighted_model_index, len(models))
        self.set_timer(0.05, self._ensure_input_focus)
    def action_select_highlighted_codex_model(self):
        """Select the currently highlighted Codex SDK model."""
        if not getattr(self, "_awaiting_codex_model", False):
            return
        models = getattr(self, "_codex_models", None) or []
        idx = getattr(self, "_codex_highlighted_model_index", 0)
        if 0 <= idx < len(models):
            log = self.query_one("#log", ConversationLog)
            self._handle_codex_model_selection(str(idx + 1), log)
    def action_navigate_codex_effort_up(self):
        """Navigate to previous Codex SDK reasoning effort."""
        if not getattr(self, "_awaiting_codex_effort", False):
            return
        options = self._codex_effort_options()
        current_idx = getattr(self, "_codex_highlighted_effort_index", 0)
        self._codex_highlighted_effort_index = max(0, current_idx - 1)
        log = self.query_one("#log", ConversationLog)
        self._show_codex_effort_picker(log, clear_log=False)
        self._scroll_to_highlighted_item(log, self._codex_highlighted_effort_index, len(options))
        self.set_timer(0.05, self._ensure_input_focus)
    def action_navigate_codex_effort_down(self):
        """Navigate to next Codex SDK reasoning effort."""
        if not getattr(self, "_awaiting_codex_effort", False):
            return
        options = self._codex_effort_options()
        current_idx = getattr(self, "_codex_highlighted_effort_index", 0)
        self._codex_highlighted_effort_index = min(len(options) - 1, current_idx + 1)
        log = self.query_one("#log", ConversationLog)
        self._show_codex_effort_picker(log, clear_log=False)
        self._scroll_to_highlighted_item(log, self._codex_highlighted_effort_index, len(options))
        self.set_timer(0.05, self._ensure_input_focus)
    def action_select_highlighted_codex_effort(self):
        """Select the currently highlighted Codex SDK reasoning effort."""
        if not getattr(self, "_awaiting_codex_effort", False):
            return
        options = self._codex_effort_options()
        idx = getattr(self, "_codex_highlighted_effort_index", 0)
        if 0 <= idx < len(options):
            log = self.query_one("#log", ConversationLog)
            self._handle_codex_effort_selection(str(idx + 1), log)
    @staticmethod
    def _codex_subcommand_completion_candidates(value: str) -> list[PromptCompletionCandidate]:
        """Complete the real ``:codex`` command tree, in its useful order."""

        prefix = ":codex "
        partial = value[len(prefix) :].lower()
        subcommands = (
            ("status", "Show Codex SDK/app-server status"),
            ("model", "Pick or set the Codex model for future turns"),
            ("models", "List models available to this Codex account"),
            ("effort", "Pick or set Codex reasoning effort"),
            ("sandbox", "Set the Codex sandbox override"),
            ("review", "Run a read-only Codex diff review"),
            ("thread", "Show the current Codex thread"),
            ("sessions", "List Codex sessions for this repo"),
            ("resume", "Resume a Codex thread"),
            ("fork", "Fork a Codex thread"),
            ("compact", "Compact the current Codex thread"),
            ("rename", "Rename the current Codex thread"),
            ("archive", "Archive a Codex thread"),
            ("account", "Show the signed-in Codex account"),
            ("logout", "Sign out of Codex"),
        )
        return [
            PromptCompletionCandidate(
                value=f"{prefix}{subcommand}",
                label=subcommand,
                description=description,
                kind="codex",
            )
            for subcommand, description in subcommands
            if subcommand.startswith(partial) and f"{prefix}{subcommand}" != value
        ]
    def _codex_effort_completion_candidates(self, value: str) -> list[PromptCompletionCandidate]:
        """Offer valid SDK effort values without starting an app-server per keypress."""

        prefix = ":codex effort "
        partial = value[len(prefix) :].lower()
        return [
            PromptCompletionCandidate(
                value=f"{prefix}{option['id']}",
                label=option["id"],
                description=option["desc"],
                kind="effort",
            )
            for option in self._codex_effort_options()
            if option["id"].startswith(partial) and f"{prefix}{option['id']}" != value
        ]
    def _codex_model_completion_candidates(self, value: str) -> list[PromptCompletionCandidate]:
        """Complete cached account models; typing must never start a network probe."""

        prefix = ":codex model "
        partial = value[len(prefix) :].lower()
        candidates = [
            PromptCompletionCandidate(
                value=f"{prefix}default",
                label="default",
                description="Clear the override and use ~/.codex again",
                kind="model",
            )
        ]
        for model in list(getattr(self, "_codex_models", None) or []):
            model_id = str(model.get("id") or "").strip()
            if not model_id:
                continue
            name = str(model.get("name") or "").strip()
            efforts = ", ".join(str(effort) for effort in model.get("efforts") or [])
            description = name if name and name != model_id else ""
            if efforts:
                description = f"{description} · effort: {efforts}".strip(" ·")
            candidates.append(
                PromptCompletionCandidate(
                    value=f"{prefix}{model_id}",
                    label=model_id,
                    description=description or "Cached Codex account model",
                    kind="model",
                )
            )
        return [
            candidate
            for candidate in candidates
            if candidate.label.lower().startswith(partial) and candidate.value != value
        ]
    @staticmethod
    def _codex_sandbox_completion_candidates(value: str) -> list[PromptCompletionCandidate]:
        prefix = ":codex sandbox "
        partial = value[len(prefix) :].lower()
        options = (
            ("read-only", "Read files without allowing edits"),
            ("workspace-write", "Allow edits inside the workspace"),
            ("full-access", "Allow unrestricted local access"),
            ("default", "Clear the override and use Codex config"),
        )
        return [
            PromptCompletionCandidate(
                value=f"{prefix}{mode}", label=mode, description=description, kind="sandbox"
            )
            for mode, description in options
            if mode.startswith(partial) and f"{prefix}{mode}" != value
        ]
    async def _resolve_codex_active_model(self, log: ConversationLog) -> None:
        """Query the live thread's resolved model and surface it.

        ``model/list`` is a catalogue, not a source of truth for the model a
        thread actually resolved from ``~/.codex``. In particular, an older
        app-server can have a stale catalogue while still honoring a newer
        configured model.
        """
        try:
            pure = getattr(self, "_pure_mode", None)
            runtime = getattr(pure, "_runtime", None) if pure is not None else None
            if runtime is None:
                return
            model_id = str(
                await asyncio.to_thread(lambda: getattr(runtime, "active_model", "")) or ""
            )
            if not model_id and hasattr(runtime, "models"):
                # Compatibility fallback for third-party runtime shims that
                # have not yet exposed ``active_model``.
                resp = await asyncio.to_thread(runtime.models)
                data = list(getattr(resp, "data", []) or [])
                chosen = next(
                    (m for m in data if getattr(m, "is_default", False)),
                    data[0] if data else None,
                )
                if chosen is not None:
                    model_id = str(getattr(chosen, "model", getattr(chosen, "id", "")) or "")
            if not model_id:
                return
            self._set_status_model(model_id)
            log.add_info(f"Active Codex model: {model_id}  ·  switch with :codex model")
        except Exception:  # noqa: BLE001 — best-effort, never fatal
            pass
    def _codex_cmd(self, args: str, log) -> None:
        """Handle :codex and Codex SDK runtime subcommands."""
        raw = (args or "").strip()
        parts = raw.split(maxsplit=1)
        sub = parts[0].lower() if parts else "connect"
        rest = parts[1].strip() if len(parts) > 1 else ""
        if sub in {"", "connect", "start"}:
            self._runtime_cmd("codex-sdk", log)
            return
        status_expr = f"{sub} {rest}".strip()
        if status_expr in {"status", "doctor", "status --probe", "status probe", "status models"}:
            self._codex_status(log, probe=status_expr not in {"status", "doctor"})
            return
        if sub in {"models", "model-list"}:
            self._codex_models_cmd(log, include_hidden="--hidden" in rest.split())
            return
        if sub == "model":
            self._codex_model_cmd(rest, log)
            return
        if sub in {"effort", "reasoning"}:
            self._codex_effort_cmd(rest, log)
            return
        if sub == "sandbox":
            self._codex_sandbox_cmd(rest, log)
            return
        if sub == "compact":
            self._codex_runtime_action(log, "compact", lambda runtime: runtime.compact_thread())
            return
        if sub in {"thread", "info"}:
            self._codex_thread_cmd(log)
            return
        if sub in {"sessions", "threads"}:
            self._codex_sessions_cmd(rest, log)
            return
        if sub == "resume":
            self._codex_resume_cmd(rest, log)
            return
        if sub == "fork":
            self._codex_fork_cmd(rest, log)
            return
        if sub == "rename":
            self._codex_rename_cmd(rest, log)
            return
        if sub == "archive":
            self._codex_archive_cmd(rest, log)
            return
        if sub == "account":
            self._codex_account_cmd(log)
            return
        if sub == "logout":
            self._codex_runtime_action(log, "logout", lambda runtime: runtime.logout())
            return
        if sub == "review":
            self._codex_review_cmd(rest, log)
            return
        log.add_error(f"Unknown codex command: {sub}")
        log.add_info(
            "Usage: :codex [status|models|model|effort|sandbox|review|compact|thread|sessions|resume|fork|rename|archive|account|logout]"
        )
    def _codex_runtime_or_connect(self, log):
        pure = getattr(self, "_pure_mode", None)
        runtime = getattr(pure, "_runtime", None) if pure is not None else None
        if (
            runtime is not None
            and getattr(pure, "runtime_name", "") == "codex-sdk"
            and getattr(getattr(pure, "session", None), "connected", False)
        ):
            return runtime
        self._runtime_cmd("codex-sdk", log)
        pure = getattr(self, "_pure_mode", None)
        runtime = getattr(pure, "_runtime", None) if pure is not None else None
        if runtime is None or getattr(pure, "runtime_name", "") != "codex-sdk":
            raise RuntimeError("Codex runtime is not connected")
        return runtime
    @staticmethod
    def _codex_obj_dict(obj) -> dict:
        if obj is None:
            return {}
        if isinstance(obj, dict):
            return dict(obj)
        if hasattr(obj, "model_dump"):
            dumped = obj.model_dump(mode="json", by_alias=True)
            return dumped if isinstance(dumped, dict) else {}
        return {
            key: getattr(obj, key)
            for key in dir(obj)
            if not key.startswith("_") and not callable(getattr(obj, key))
        }
    def _codex_runtime_action(self, log, label: str, action) -> None:
        try:
            runtime = self._codex_runtime_or_connect(log)
            action(runtime)
            log.add_success(f"Codex {label} complete.")
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Codex {label} failed: {exc}")
            self._codex_config_error_hint(log, exc)
    def _codex_effort_options(self) -> list[dict[str, str]]:
        """Return stable efforts plus newer values advertised by this account.

        The Codex app-server owns which reasoning levels a subscription model
        supports. Keep the normal SDK values available offline, then add newer
        values (currently ``max``/``ultra``) only after the live model catalogue
        has advertised them.
        """

        options = [
            {
                "id": "default",
                "name": "Codex default",
                "desc": "Use the effort configured in ~/.codex or selected by Codex.",
            },
            {
                "id": "none",
                "name": "None",
                "desc": "Disable extra reasoning for the fastest direct responses.",
            },
            {
                "id": "minimal",
                "name": "Minimal",
                "desc": "Fastest reasoning for small edits and straightforward prompts.",
            },
            {
                "id": "low",
                "name": "Low",
                "desc": "Light reasoning for simple coding tasks.",
            },
            {
                "id": "medium",
                "name": "Medium",
                "desc": "Balanced reasoning for normal development work.",
            },
            {
                "id": "high",
                "name": "High",
                "desc": "Deeper reasoning for complex changes and reviews.",
            },
            {
                "id": "xhigh",
                "name": "Extra high",
                "desc": "Maximum reasoning when latency is less important.",
            },
        ]
        known = {option["id"] for option in options}
        supported = {
            str(effort).strip().lower().replace("-", "_")
            for model in list(getattr(self, "_codex_models", None) or [])
            for effort in list(model.get("efforts") or [])
        }
        for option in (
            {
                "id": "max",
                "name": "Maximum",
                "desc": "More reasoning than xhigh when the selected Codex model supports it.",
            },
            {
                "id": "ultra",
                "name": "Ultra",
                "desc": "Highest reasoning level exposed by the local Codex CLI for supported models.",
            },
        ):
            if option["id"] in supported and option["id"] not in known:
                options.append(option)
        return options
    @staticmethod
    def _codex_config_error_hint(log, exc) -> None:
        """Write the shared configuration recovery hint, when applicable."""

        from superqode.app_main import SuperQodeApp
        hint = SuperQodeApp._codex_config_error_hint_text(exc)
        if hint:
            log.add_info(hint)
    def _codex_picker_line(
        self,
        text: Text,
        number: int,
        primary: str,
        secondary: str,
        desc: str,
        *,
        highlighted: bool,
    ) -> None:
        pointer = "> " if highlighted else "  "
        number_style = self._picker_link_style(
            f"bold {THEME['success'] if highlighted else THEME['cyan']}", number
        )
        primary_style = f"bold {THEME['success'] if highlighted else THEME['text']}"
        text.append("  ")
        text.append(pointer, style=f"bold {THEME['success']}" if highlighted else THEME["dim"])
        text.append(f"[{number}]", style=number_style)
        text.append(" ")
        text.append(primary, style=primary_style)
        if secondary:
            text.append(f"  {secondary}", style=THEME["muted"])
        if desc:
            text.append(f"\n       {desc}", style=THEME["dim"])
        if highlighted:
            text.append("  selected", style=f"bold {THEME['success']}")
        text.append("\n")
    def _show_codex_model_picker(
        self, log, *, clear_log: bool = True, refetch: bool = True
    ) -> None:
        try:
            if refetch or not getattr(self, "_codex_models", None):
                runtime = self._codex_runtime_or_connect(log)
                response = runtime.models()
                self._codex_models = self._models_from_codex_response(response)
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Could not list Codex models: {exc}")
            self._codex_config_error_hint(log, exc)
            return

        models = list(getattr(self, "_codex_models", None) or [])
        if not models:
            models = [
                {
                    "id": "",
                    "name": "Codex default",
                    "desc": "Use the model configured in ~/.codex.",
                    "efforts": [],
                }
            ]
            self._codex_models = models

        self._reset_connect_selection_states()
        self._awaiting_codex_model = True
        self._codex_highlighted_model_index = min(
            getattr(self, "_codex_highlighted_model_index", 0), len(models) - 1
        )

        current_runtime = getattr(getattr(self, "_pure_mode", None), "_runtime", None)
        current = getattr(current_runtime, "model", None) or ""
        text = Text()
        text.append("\n  Codex model\n\n", style=f"bold {THEME['cyan']}")
        if current:
            text.append("  Current override: ", style=THEME["muted"])
            text.append(current, style=f"bold {THEME['text']}")
            text.append("\n\n")
        else:
            text.append("  Current: Codex default from ~/.codex\n\n", style=THEME["muted"])
        catalog_source = str(getattr(current_runtime, "app_server_source", "") or "")
        if catalog_source:
            text.append("  Catalog source: ", style=THEME["muted"])
            text.append(f"{catalog_source}\n\n", style=THEME["dim"])

        for idx, model in enumerate(models):
            model_id = str(model.get("id") or "")
            name = str(model.get("name") or model_id or "Codex default")
            efforts = ", ".join(model.get("efforts") or [])
            secondary = model_id if model_id and model_id != name else ""
            desc = f"effort: {efforts}" if efforts else str(model.get("desc") or "")
            self._codex_picker_line(
                text,
                idx + 1,
                name,
                secondary,
                desc,
                highlighted=idx == self._codex_highlighted_model_index,
            )

        text.append(
            "\n  Use Up/Down + Enter, click a number, or type a model id.\n", style=THEME["muted"]
        )
        text.append("  Esc cancels. ", style=THEME["muted"])
        text.append(":codex models", style=THEME["cyan"])
        text.append(" shows a plain list.\n", style=THEME["muted"])
        self._show_command_output(log, text, clear_log=clear_log)
    def _show_codex_effort_picker(self, log, *, clear_log: bool = True) -> None:
        self._reset_connect_selection_states()
        self._awaiting_codex_effort = True
        try:
            runtime = self._codex_runtime_or_connect(log)
            # Refresh once when opening the picker so newly-added Codex
            # effort values are offered, without probing while the user types.
            self._codex_models = self._models_from_codex_response(runtime.models())
            current = runtime.reasoning_effort or "default"
        except Exception:
            current = "default"
        options = self._codex_effort_options()
        self._codex_highlighted_effort_index = min(
            getattr(self, "_codex_highlighted_effort_index", 0), len(options) - 1
        )

        text = Text()
        text.append("\n  Codex reasoning effort\n\n", style=f"bold {THEME['cyan']}")
        text.append("  Current: ", style=THEME["muted"])
        text.append(current, style=f"bold {THEME['text']}")
        text.append("\n\n")
        for idx, option in enumerate(options):
            label = option["name"]
            option_id = option["id"]
            if option_id == current:
                label = f"{label} (current)"
            self._codex_picker_line(
                text,
                idx + 1,
                label,
                option_id,
                option["desc"],
                highlighted=idx == self._codex_highlighted_effort_index,
            )

        text.append(
            "\n  Use Up/Down + Enter, click a number, or type an effort name.\n",
            style=THEME["muted"],
        )
        text.append("  Esc cancels.\n", style=THEME["muted"])
        self._show_command_output(log, text, clear_log=clear_log)
    def _handle_codex_model_selection(self, selection: str, log) -> bool:
        if not getattr(self, "_awaiting_codex_model", False):
            return False
        raw = (selection or "").strip()
        models = list(getattr(self, "_codex_models", None) or [])
        if not raw:
            self.action_select_highlighted_codex_model()
            return True

        selected = None
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(models):
                selected = models[idx]
            else:
                log.add_error(f"Invalid Codex model selection. Choose 1-{len(models)}.")
                return True
        else:
            lowered = raw.lower()
            for model in models:
                model_id = str(model.get("id") or "")
                name = str(model.get("name") or "")
                if lowered in {model_id.lower(), name.lower()}:
                    selected = model
                    break
            if selected is None:
                matches = [
                    model
                    for model in models
                    if lowered in str(model.get("id") or "").lower()
                    or lowered in str(model.get("name") or "").lower()
                ]
                if len(matches) == 1:
                    selected = matches[0]
                elif len(matches) > 1:
                    log.add_error(
                        f"'{raw}' matches multiple Codex models. Type the exact model id."
                    )
                    return True
            if selected is None:
                log.add_error(f"Codex model '{raw}' not found.")
                return True

        self._awaiting_codex_model = False
        self._apply_codex_model_override(str(selected.get("id") or ""), log)
        return True
    def _handle_codex_effort_selection(self, selection: str, log) -> bool:
        if not getattr(self, "_awaiting_codex_effort", False):
            return False
        raw = (selection or "").strip().lower()
        options = self._codex_effort_options()
        if not raw:
            self.action_select_highlighted_codex_effort()
            return True

        selected = None
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                selected = options[idx]
            else:
                log.add_error(f"Invalid Codex effort selection. Choose 1-{len(options)}.")
                return True
        else:
            for option in options:
                if raw in {option["id"], option["name"].lower()}:
                    selected = option
                    break
            if selected is None:
                choices = ", ".join(option["id"] for option in options)
                log.add_error(f"Invalid Codex effort. Choose one of: {choices}.")
                return True

        self._awaiting_codex_effort = False
        self._codex_effort_cmd(selected["id"], log)
        return True
    def _codex_models_cmd(self, log, *, include_hidden: bool = False) -> None:
        try:
            runtime = self._codex_runtime_or_connect(log)
            response = runtime.models(include_hidden=include_hidden)
            self._codex_models = self._models_from_codex_response(response)
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Could not list Codex models: {exc}")
            self._codex_config_error_hint(log, exc)
            return

        text = Text()
        text.append("\n  Codex models\n\n", style=f"bold {THEME['cyan']}")
        catalog_source = str(getattr(runtime, "app_server_source", "") or "")
        if catalog_source:
            text.append("  Catalog source: ", style=THEME["muted"])
            text.append(f"{catalog_source}\n\n", style=THEME["dim"])
        for model in self._codex_models[:30]:
            text.append("  ")
            text.append(str(model.get("id") or ""), style=f"bold {THEME['text']}")
            name = model.get("name")
            if name and name != model.get("id"):
                text.append(f"  {name}", style=THEME["muted"])
            efforts = model.get("efforts") or []
            if efforts:
                text.append(f"  effort: {', '.join(efforts)}", style=THEME["dim"])
            text.append("\n")
        if len(self._codex_models) > 30:
            text.append(
                f"\n  +{len(self._codex_models) - 30} more hidden/listed models\n",
                style=THEME["dim"],
            )
        text.append("\n  Use ", style=THEME["muted"])
        text.append(":codex model <id>", style=THEME["cyan"])
        text.append(" to switch future turns.\n", style=THEME["muted"])
        log.write(text)
    def _codex_model_cmd(self, model: str, log) -> None:
        if not model:
            self._show_codex_model_picker(log)
            return
        if model.lower() in {"default", "none", "auto"}:
            self._apply_codex_model_override("", log)
            return
        self._apply_codex_model_override(model, log)
    def _apply_codex_model_override(self, model: str, log) -> None:
        try:
            runtime = self._codex_runtime_or_connect(log)
            runtime.set_model(model)
            if getattr(self, "_pure_mode", None) is not None:
                self._pure_mode.session.model = model
            label = model or "Codex default"
            self._set_status_model(model)  # reflect in the status-bar badge
            log.add_success(f"Codex model set to {label}")
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Could not set Codex model: {exc}")
            self._codex_config_error_hint(log, exc)
    def _codex_effort_cmd(self, effort: str, log) -> None:
        if not effort:
            self._show_codex_effort_picker(log)
            return
        try:
            runtime = self._codex_runtime_or_connect(log)
            runtime.set_reasoning_effort(effort)
            current = runtime.reasoning_effort or "default"
            log.add_success(f"Codex reasoning effort set to {current}")
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Could not set Codex effort: {exc}")
            self._codex_config_error_hint(log, exc)
    def _codex_sandbox_cmd(self, mode: str, log) -> None:
        if not mode:
            log.add_info("Usage: :codex sandbox <read-only|workspace-write|full-access|default>")
            return
        try:
            runtime = self._codex_runtime_or_connect(log)
            runtime.set_sandbox_backend(None if mode in {"default", "none"} else mode)
            log.add_success(f"Codex sandbox set to {mode}")
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Could not set Codex sandbox: {exc}")
            self._codex_config_error_hint(log, exc)
    def _codex_thread_cmd(self, log) -> None:
        try:
            runtime = self._codex_runtime_or_connect(log)
            thread = runtime.read_thread(include_turns=False).thread
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Could not read Codex thread: {exc}")
            self._codex_config_error_hint(log, exc)
            return
        data = self._codex_obj_dict(thread)
        text = Text()
        text.append("\n  Codex thread\n\n", style=f"bold {THEME['cyan']}")
        for key in ("id", "name", "model", "modelProvider", "preview", "path", "cwd"):
            value = data.get(key)
            if value:
                text.append(f"  {key:<14}", style=THEME["muted"])
                text.append(str(value), style=THEME["text"])
                text.append("\n")
        log.write(text)
    def _codex_sessions_cmd(self, args: str, log) -> None:
        archived = "archived" in args.split() or "--archived" in args.split()
        try:
            runtime = self._codex_runtime_or_connect(log)
            response = runtime.list_threads(limit=20, archived=archived)
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Could not list Codex sessions: {exc}")
            self._codex_config_error_hint(log, exc)
            return
        threads = list(getattr(response, "data", []) or getattr(response, "threads", []) or [])
        text = Text()
        text.append("\n  Codex sessions\n\n", style=f"bold {THEME['cyan']}")
        if not threads:
            text.append("  No Codex sessions returned.\n", style=THEME["muted"])
        for thread in threads:
            data = self._codex_obj_dict(thread)
            tid = str(data.get("id") or "")
            text.append(f"  {tid[:12]:<14}", style=f"bold {THEME['cyan']}")
            text.append(
                str(data.get("name") or data.get("preview") or "(unnamed)")[:80],
                style=THEME["text"],
            )
            text.append("\n")
        text.append("\n  Use ", style=THEME["muted"])
        text.append(":codex resume <thread_id>", style=THEME["cyan"])
        text.append(" or ", style=THEME["muted"])
        text.append(":codex fork <thread_id>", style=THEME["cyan"])
        text.append(".\n", style=THEME["muted"])
        log.write(text)
    def _codex_resume_cmd(self, thread_id: str, log) -> None:
        if not thread_id:
            log.add_info("Usage: :codex resume <thread_id>")
            return
        self._codex_runtime_action(
            log, f"resume {thread_id[:12]}", lambda runtime: runtime.resume_thread(thread_id)
        )
    def _codex_fork_cmd(self, thread_id: str, log) -> None:
        if not thread_id:
            log.add_info("Usage: :codex fork <thread_id>")
            return
        self._codex_runtime_action(
            log, f"fork {thread_id[:12]}", lambda runtime: runtime.fork_thread(thread_id)
        )
    def _codex_rename_cmd(self, name: str, log) -> None:
        if not name:
            log.add_info("Usage: :codex rename <thread name>")
            return
        self._codex_runtime_action(log, "rename", lambda runtime: runtime.rename_thread(name))
    def _codex_archive_cmd(self, thread_id: str, log) -> None:
        try:
            runtime = self._codex_runtime_or_connect(log)
            target = thread_id or runtime.thread_id
            if not target:
                log.add_info("Usage: :codex archive [thread_id]")
                return
            runtime.archive_thread(target)
            log.add_success(f"Codex archived {str(target)[:12]}.")
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Could not archive Codex thread: {exc}")
            self._codex_config_error_hint(log, exc)
    def _codex_account_cmd(self, log) -> None:
        try:
            runtime = self._codex_runtime_or_connect(log)
            response = runtime.account()
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Could not read Codex account: {exc}")
            self._codex_config_error_hint(log, exc)
            return
        data = self._codex_obj_dict(response)
        account = self._codex_obj_dict(data.get("account"))
        text = Text()
        text.append("\n  Codex account\n\n", style=f"bold {THEME['cyan']}")
        for key, value in {**data, **account}.items():
            if value in (None, "", [], {}):
                continue
            text.append(f"  {str(key):<24}", style=THEME["muted"])
            text.append(str(value)[:120], style=THEME["text"])
            text.append("\n")
        log.write(text)
    def _codex_review_cmd(self, prompt: str, log) -> None:
        try:
            runtime = self._codex_runtime_or_connect(log)
            runtime.set_next_turn_sandbox("read-only")
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Could not start Codex review: {exc}")
            self._codex_config_error_hint(log, exc)
            return
        review_prompt = prompt or (
            "Review the current uncommitted diff only. Do not edit files or run commands that modify state. "
            "Prioritize correctness bugs, regressions, safety risks, and missing tests. "
            "Return findings first with file/line references where possible."
        )
        log.add_user(f":codex review\n{review_prompt}")
        self._last_user_message = review_prompt
        self._update_terminal_title("Codex review")
        self.is_busy = True
        self._cancel_requested = False
        self._send_to_pure_mode(review_prompt, log)
    def _codex_status(self, log, *, probe: bool = False) -> None:
        """Show Codex SDK/app-server/auth status."""
        from importlib import metadata
        from superqode.runtime import list_runtimes

        info = next((item for item in list_runtimes() if item.name == "codex-sdk"), None)
        text = Text()
        text.append("\n  Codex SDK status\n\n", style=f"bold {THEME['cyan']}")

        installed = bool(info and info.installed)
        text.append("  Runtime     ", style=THEME["muted"])
        text.append(
            "ready\n" if installed else "missing\n",
            style=THEME["success" if installed else "error"],
        )

        for package in ("openai-codex", "openai-codex-cli-bin"):
            text.append(f"  {package:<12}", style=THEME["muted"])
            try:
                text.append(f"{metadata.version(package)}\n", style=THEME["text"])
            except metadata.PackageNotFoundError:
                text.append("not installed\n", style=THEME["error"])

        text.append("  Config      ", style=THEME["muted"])
        text.append(str(Path.home() / ".codex"), style=THEME["text"])
        text.append("\n")

        active = (
            getattr(getattr(self, "_pure_mode", None), "runtime_name", "") == "codex-sdk"
            and getattr(getattr(self, "_pure_mode", None), "session", None) is not None
            and getattr(self._pure_mode.session, "connected", False)
        )
        text.append("  TUI bridge  ", style=THEME["muted"])
        text.append(
            "connected\n" if active else "not connected\n",
            style=THEME["success" if active else "warning"],
        )
        runtime = getattr(getattr(self, "_pure_mode", None), "_runtime", None)
        thread_id = getattr(runtime, "thread_id", None) if active else None
        sessions_dir = getattr(
            runtime, "codex_sessions_dir", str(Path.home() / ".codex" / "sessions")
        )
        text.append("  Sessions    ", style=THEME["muted"])
        text.append(str(sessions_dir), style=THEME["text"])
        text.append("\n")
        if thread_id:
            text.append("  Thread      ", style=THEME["muted"])
            text.append(str(thread_id), style=THEME["text"])
            text.append("\n")
        if active and getattr(runtime, "_client", None) is not None:
            source = str(getattr(runtime, "_app_server_source", "") or "")
            if source:
                text.append("  App-server  ", style=THEME["muted"])
                text.append(f"{source}\n", style=THEME["text"])

        if not installed:
            text.append("\n  Install     ", style=THEME["muted"])
            text.append('uv tool install "superqode[codex-sdk]"\n', style=THEME["cyan"])
            log.write(text)
            return

        if not probe:
            text.append("  Probe       ", style=THEME["muted"])
            text.append("skipped (fast status)\n", style=THEME["dim"])
            text.append("  Next        ", style=THEME["muted"])
            text.append(":codex status --probe", style=THEME["cyan"])
            text.append(" to start the SDK app-server and list models\n", style=THEME["muted"])
            log.write(text)
            return

        try:
            models = self._fetch_live_codex_models()
            self._codex_models = models
            text.append("  Auth/probe  ", style=THEME["muted"])
            text.append("ok\n", style=THEME["success"])
            text.append("  Models      ", style=THEME["muted"])
            if models:
                names = [str(model.get("id") or model.get("name")) for model in models[:5]]
                text.append(", ".join(names), style=THEME["text"])
                if len(models) > 5:
                    text.append(f" (+{len(models) - 5} more)", style=THEME["dim"])
                text.append("\n")
            else:
                text.append("none returned\n", style=THEME["warning"])
        except Exception as exc:  # noqa: BLE001
            text.append("  Auth/probe  ", style=THEME["muted"])
            text.append("failed\n", style=THEME["error"])
            text.append("  Hint        ", style=THEME["muted"])
            text.append(self._codex_error_hint(str(exc)), style=THEME["warning"])
            text.append("\n")
            text.append("  Error       ", style=THEME["muted"])
            text.append(str(exc), style=THEME["text"])
            text.append("\n")

        log.write(text)
    def _run_codex_acp(
        self,
        message: str,
        model: str,
        display_name: str,
        log: ConversationLog,
        persona_context=None,
    ):
        """
        Run Codex CLI using the ACP protocol via codex-acp adapter.

        This ACP path uses the full bidirectional JSON-RPC protocol.
        This method uses subprocess with JSON-RPC communication.
        """
        import subprocess
        import json
        from time import monotonic

        try:
            start_time = monotonic()

            # Build command - codex-acp is the ACP adapter
            # Try npx first, then global install
            cmd = ["npx", "@openai/codex-acp"]

            model_display = f"codex/{model}" if model else "codex/auto"

            # Show info with approval mode
            mode_label = {"auto": "🟢 AUTO", "ask": "🟡 ASK", "deny": "🔴 DENY"}.get(
                self.approval_mode, "🟡 ASK"
            )
            session_type = "new session" if self._is_first_message else "continuing session"
            self._call_ui(
                log.add_info, f"Using model: {model_display} | Mode: {mode_label} ({session_type})"
            )

            # Show persona info if available
            if persona_context and persona_context.is_valid:
                self._call_ui(log.add_info, f"🎭 Persona active: {persona_context.role_name}")

            # Build environment - need OPENAI_API_KEY or CODEX_API_KEY
            env = {
                **os.environ,
                "PYTHONUNBUFFERED": "1",
            }

            # Check for API key
            if "OPENAI_API_KEY" not in env and "CODEX_API_KEY" not in env:
                self._call_ui(self._stop_thinking)
                self._call_ui(
                    log.add_error, "❌ OPENAI_API_KEY or CODEX_API_KEY not set. Export one first:"
                )
                self._call_ui(log.add_info, "  export OPENAI_API_KEY=sk-...")
                self._call_ui(log.add_info, "  or export CODEX_API_KEY=sk-...")
                return

            # Start process with bidirectional communication
            process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=os.getcwd(),
                text=True,
                bufsize=1,
                env=env,
            )

            # Store process reference for cancellation
            self._agent_process = process

            # Stop thinking, start streaming animation
            self._call_ui(self._stop_thinking)
            self._call_ui(self._start_stream_animation, log)

            # Show header
            self._call_ui(self._show_agent_header_with_model, display_name, model_display, log)

            # Collect output
            text_parts = []
            tool_actions = []
            files_modified = []
            files_read = []

            # Terminal tracking for this session
            terminals = {}
            terminal_counter = 0

            # JSON-RPC request ID counter
            request_id = 0
            session_id = None

            def send_request(method: str, params: dict = None) -> int:
                """Send a JSON-RPC request to the agent."""
                nonlocal request_id
                request_id += 1
                request = {
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": params or {},
                    "id": request_id,
                }
                try:
                    process.stdin.write(json.dumps(request) + "\n")
                    process.stdin.flush()
                except Exception as e:
                    self._call_ui(self._show_thinking_line, f"⚠️ Send error: {e}", log)
                return request_id

            def send_response(req_id: int, result: dict):
                """Send a JSON-RPC response to the agent."""
                response = {
                    "jsonrpc": "2.0",
                    "result": result,
                    "id": req_id,
                }
                try:
                    process.stdin.write(json.dumps(response) + "\n")
                    process.stdin.flush()
                except Exception:
                    pass

            # Step 1: Initialize the protocol
            self._call_ui(self._show_thinking_line, "🔌 Initializing ACP protocol...", log)
            send_request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": True, "writeTextFile": True},
                        "terminal": True,
                    },
                    "clientInfo": {
                        "name": "SuperQode",
                        "title": "SuperQode - Multi-Agent Coding Team",
                        "version": "0.1.0",
                    },
                },
            )

            # Read and process messages
            pending_requests = {}
            initialized = False
            session_created = False
            prompt_sent = False

            while True:
                if self._cancel_requested:
                    process.terminate()
                    self._call_ui(log.add_info, "🛑 Agent operation cancelled")
                    break

                # Read a line from stdout
                try:
                    line = process.stdout.readline()
                    if not line and process.poll() is not None:
                        break
                    if not line:
                        continue

                    line = line.strip()
                    if not line:
                        continue

                    # Parse JSON-RPC message
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        # Not JSON - might be debug output
                        if line and not line.startswith("Loaded"):
                            self._call_ui(self._show_thinking_line, f"📋 {line}", log)
                        continue

                    # Handle response to our request
                    if "result" in msg or "error" in msg:
                        msg_id = msg.get("id")

                        if "error" in msg:
                            error = msg["error"]
                            error_msg = error.get("message", "Unknown error")
                            self._call_ui(log.add_error, f"❌ ACP Error: {error_msg}")
                            break

                        result = msg.get("result", {})

                        # Handle initialize response
                        if not initialized:
                            initialized = True
                            agent_info = result.get("agentInfo", {})
                            agent_name = agent_info.get("title", "Codex CLI")
                            self._call_ui(
                                self._show_thinking_line, f"✅ Connected to {agent_name}", log
                            )

                            # Step 2: Create a new session
                            send_request(
                                "session/new",
                                {
                                    "cwd": os.getcwd(),
                                    "mcpServers": [],
                                },
                            )
                            continue

                        # Handle session/new response
                        if not session_created:
                            session_id = result.get("sessionId", "")
                            session_created = True

                            # Check available models
                            models = result.get("models", {})
                            available_models = models.get("availableModels", [])
                            if available_models:
                                model_names = [
                                    m.get("name", m.get("modelId", ""))
                                    for m in available_models[:3]
                                ]
                                self._call_ui(
                                    self._show_thinking_line,
                                    f"📊 Models: {', '.join(model_names)}",
                                    log,
                                )

                            # Step 2.5: Set the model if specified (for Codex ACP)
                            if model:
                                # Try to set the model - codex-acp expects model ID without prefix
                                model_id = model
                                # Remove any codex/ prefix if present
                                if model_id.startswith("codex/"):
                                    model_id = model_id[6:]
                                # Send set_model request
                                send_request(
                                    "session/set_model",
                                    {
                                        "sessionId": session_id,
                                        "modelId": model_id,
                                    },
                                )
                                self._call_ui(
                                    self._show_thinking_line, f"🎯 Setting model: {model_id}", log
                                )

                            self._call_ui(self._show_thinking_line, f"🚀 Session started", log)

                            # Step 3: Send the prompt
                            send_request(
                                "session/prompt",
                                {
                                    "sessionId": session_id,
                                    "prompt": [{"type": "text", "text": message}],
                                },
                            )
                            prompt_sent = True
                            continue

                        # Handle prompt response (completion)
                        if prompt_sent:
                            stop_reason = result.get("stopReason", "end_turn")
                            self._call_ui(
                                self._show_thinking_line, f"✅ Completed ({stop_reason})", log
                            )
                            break

                    # Handle request from agent (notifications/requests)
                    elif "method" in msg:
                        method = msg.get("method", "")
                        params = msg.get("params", {})
                        req_id = msg.get("id")

                        if method == "session/update":
                            # Handle session updates (streaming content)
                            update = params.get("update", params)
                            update_type = update.get("sessionUpdate", "")

                            if update_type == "agent_message_chunk":
                                content = update.get("content", {})
                                text = content.get("text", "")
                                if text:
                                    text_parts.append(text)
                                    # Show full text, no truncation
                                    self._call_ui(self._show_thinking_line, f"💬 {text}", log)

                            elif update_type == "agent_thought_chunk":
                                content = update.get("content", {})
                                text = content.get("text", "")
                                if text:
                                    # Show full thinking text, no truncation
                                    self._call_ui(self._show_thinking_line, f"🧠 {text}", log)

                            elif update_type == "tool_call":
                                tool_id = update.get("toolCallId", "")
                                title = update.get("title", "")
                                raw_input = update.get("rawInput", {})
                                status = update.get("status", "")

                                # Track tool_id to title mapping for detailed logging
                                if not hasattr(self, "_tool_id_map"):
                                    self._tool_id_map = {}
                                self._tool_id_map[tool_id] = {"title": title, "input": raw_input}

                                tool_actions.append({"tool": title, "input": raw_input})

                                # Track files
                                file_path = raw_input.get("path", raw_input.get("filePath", ""))
                                if file_path:
                                    kind = update.get("kind", "")
                                    if kind in ("edit", "write", "delete"):
                                        if file_path not in files_modified:
                                            files_modified.append(file_path)
                                    elif kind == "read":
                                        if file_path not in files_read:
                                            files_read.append(file_path)

                                msg_text = self._format_tool_message_rich(title, raw_input)
                                self._call_ui(self._show_thinking_line, msg_text, log)

                            elif update_type == "tool_call_update":
                                tool_id = update.get("toolCallId", "")
                                status = update.get("status", "")
                                output = update.get("output", update.get("result", ""))
                                # Get tool info from our tracking map
                                tool_info = getattr(self, "_tool_id_map", {}).get(tool_id, {})
                                tool_title = tool_info.get("title", "Tool")
                                if status == "completed":
                                    if output:
                                        output_str = str(output)
                                        # Show full output, no truncation
                                        self._call_ui(
                                            self._show_thinking_line,
                                            f"✅ {tool_title}: {output_str}",
                                            log,
                                        )
                                    else:
                                        self._call_ui(
                                            self._show_thinking_line,
                                            f"✅ {tool_title} completed",
                                            log,
                                        )
                                elif status == "failed":
                                    # Show full error message, no truncation
                                    error_msg = str(output) if output else "failed"
                                    self._call_ui(
                                        self._show_thinking_line,
                                        f"❌ {tool_title} failed: {error_msg}",
                                        log,
                                    )

                            elif update_type == "plan":
                                entries = update.get("entries", [])
                                if entries:
                                    self._call_ui(
                                        self._show_thinking_line,
                                        f"📋 Plan: {len(entries)} tasks",
                                        log,
                                    )

                        elif method == "session/request_permission":
                            # Handle permission request
                            options = params.get("options", [])
                            tool_call = params.get("toolCall", {})
                            tool_name = tool_call.get("title", "unknown")
                            tool_input = tool_call.get("rawInput", {})

                            # Handle based on approval mode
                            if self.approval_mode == "deny":
                                # Reject
                                self._call_ui(
                                    self._show_thinking_line,
                                    f"🔴 BLOCKED: {tool_name} (DENY mode)",
                                    log,
                                )
                                reject_option = next(
                                    (o for o in options if o.get("kind") == "reject_once"),
                                    options[0] if options else {"optionId": ""},
                                )
                                send_response(
                                    req_id,
                                    {
                                        "outcome": {
                                            "outcome": "selected",
                                            "optionId": reject_option.get("optionId", ""),
                                        }
                                    },
                                )
                            elif self.approval_mode == "auto":
                                # Auto-allow
                                allow_option = next(
                                    (o for o in options if o.get("kind") == "allow_once"),
                                    options[0] if options else {"optionId": ""},
                                )
                                send_response(
                                    req_id,
                                    {
                                        "outcome": {
                                            "outcome": "selected",
                                            "optionId": allow_option.get("optionId", ""),
                                        }
                                    },
                                )
                                self._call_ui(
                                    self._show_thinking_line, f"✅ Auto-allowed: {tool_name}", log
                                )
                            else:
                                # ASK mode - check if needs permission
                                needs_permission = self._tool_needs_permission(
                                    tool_name, tool_input
                                )
                                if needs_permission:
                                    self._call_ui(
                                        self._show_permission_prompt, tool_name, tool_input, log
                                    )
                                    self._permission_pending = True
                                    self._permission_response = None

                                    wait_start = monotonic()
                                    timeout = 60
                                    while (
                                        self._permission_pending
                                        and (monotonic() - wait_start) < timeout
                                    ):
                                        if self._cancel_requested:
                                            self._permission_pending = False
                                            break
                                        time.sleep(0.1)

                                    if (
                                        self._permission_response == "deny"
                                        or self._permission_response is None
                                    ):
                                        reject_option = next(
                                            (o for o in options if o.get("kind") == "reject_once"),
                                            options[0] if options else {"optionId": ""},
                                        )
                                        send_response(
                                            req_id,
                                            {
                                                "outcome": {
                                                    "outcome": "selected",
                                                    "optionId": reject_option.get("optionId", ""),
                                                }
                                            },
                                        )
                                        self._call_ui(log.add_info, f"Denied: {tool_name}")
                                    else:
                                        allow_option = next(
                                            (o for o in options if o.get("kind") == "allow_once"),
                                            options[0] if options else {"optionId": ""},
                                        )
                                        send_response(
                                            req_id,
                                            {
                                                "outcome": {
                                                    "outcome": "selected",
                                                    "optionId": allow_option.get("optionId", ""),
                                                }
                                            },
                                        )
                                        self._call_ui(
                                            self._show_thinking_line,
                                            f"✅ Allowed: {tool_name}",
                                            log,
                                        )
                                        if self._permission_response == "allow_all":
                                            self.approval_mode = "auto"
                                            self._call_ui(self._sync_approval_mode)
                                else:
                                    # Auto-allow safe operations
                                    allow_option = next(
                                        (o for o in options if o.get("kind") == "allow_once"),
                                        options[0] if options else {"optionId": ""},
                                    )
                                    send_response(
                                        req_id,
                                        {
                                            "outcome": {
                                                "outcome": "selected",
                                                "optionId": allow_option.get("optionId", ""),
                                            }
                                        },
                                    )

                        elif method == "fs/read_text_file":
                            # Handle file read request
                            path = params.get("path", "")
                            if path not in files_read:
                                files_read.append(path)

                            try:
                                read_path = Path(os.getcwd()) / path
                                content = read_path.read_text(encoding="utf-8", errors="ignore")
                                send_response(req_id, {"content": content})
                            except Exception:
                                send_response(req_id, {"content": ""})

                        elif method == "fs/write_text_file":
                            # Handle file write request
                            path = params.get("path", "")
                            content = params.get("content", "")

                            if path not in files_modified:
                                files_modified.append(path)

                            try:
                                write_path = Path(os.getcwd()) / path
                                write_path.parent.mkdir(parents=True, exist_ok=True)
                                write_path.write_text(content, encoding="utf-8")
                                send_response(req_id, {})
                            except Exception as e:
                                send_response(req_id, {"error": str(e)})

                        elif method.startswith("terminal/"):
                            # Handle terminal methods using helper
                            terminal_counter_ref = [terminal_counter]
                            result, handled = self._handle_terminal_method(
                                method, params, terminals, terminal_counter_ref, log
                            )
                            terminal_counter = terminal_counter_ref[0]
                            if handled:
                                send_response(req_id, result)
                            else:
                                if req_id is not None:
                                    send_response(req_id, {})

                        else:
                            # Unknown method - send empty response if it has an ID
                            if req_id is not None:
                                send_response(req_id, {})

                except Exception as e:
                    self._call_ui(self._show_thinking_line, f"⚠️ Read error: {e}", log)
                    break

            # Cleanup terminals
            self._cleanup_terminals(terminals)

            self._agent_process = None
            self._call_ui(self._stop_stream_animation)

            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

            duration = monotonic() - start_time
            self._is_first_message = False

            # Compute file diffs for modified files
            file_diffs = self._compute_file_diffs(files_modified)

            # Build summary
            action_summary = {
                "tool_count": len(tool_actions),
                "files_modified": files_modified,
                "files_read": files_read,
                "duration": duration,
                "file_diffs": file_diffs,  # NEW: Store diff data
            }

            # Show final response
            if text_parts:
                response_text = "".join(text_parts)
                if response_text.strip():
                    self._call_ui(
                        self._show_final_outcome, response_text, display_name, action_summary, log
                    )
                else:
                    self._call_ui(self._show_completion_summary, display_name, action_summary, log)
            elif not self._cancel_requested:
                self._call_ui(self._show_completion_summary, display_name, action_summary, log)

        except FileNotFoundError:
            self._agent_process = None
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            self._call_ui(log.add_error, "❌ codex-acp not found. Install it first:")
            self._call_ui(log.add_info, "  npm install -g @openai/codex")
            self._call_ui(log.add_info, "  or npx @openai/codex-acp")
        except Exception as e:
            self._agent_process = None
            self._call_ui(self._stop_thinking)
            self._call_ui(self._stop_stream_animation)
            self._call_ui(log.add_error, f"❌ Error: {str(e)}")
    def _show_codex_models_selection(self, agent: Dict[str, Any], log: ConversationLog):
        """Show Codex CLI available models for selection."""
        name = agent.get("name", "Codex CLI")
        color = THEME["green"]
        icon = "📜"

        t = Text()
        t.append(f"\n  ╭{'─' * 58}╮\n", style=color)
        t.append(f"  │  {icon} ", style=color)
        t.append("Connected to ", style=THEME["text"])
        t.append("CODEX CLI", style=f"bold {color}")
        t.append(f"{'':>33}│\n", style=color)
        t.append(f"  ├{'─' * 58}┤\n", style=color)

        # Show available models
        t.append(f"  │  🤖 ", style=color)
        t.append("SELECT A MODEL", style=f"bold {THEME['cyan']}")
        t.append(f"{'':>38}│\n", style=color)
        t.append(f"  ├{'─' * 58}┤\n", style=color)

        for i, model in enumerate(self.codex_models):
            model_id = model.get("id", "")
            model_name = model.get("name", "")
            desc = model.get("desc", "")
            is_recommended = model.get("recommended", False)
            is_highlighted = i == getattr(self, "_opencode_highlighted_model_index", 0)

            # Number for selection
            num = i + 1
            t.append(f"  │  ", style=color)
            if is_highlighted:
                t.append(f"▶ ", style=f"bold {THEME['success']}")
                number_style = self._picker_link_style(f"bold {THEME['success']}", num)
                name_style = f"bold {THEME['success']}"
            else:
                t.append("  ", style="")
                number_style = self._picker_link_style(f"bold {THEME['cyan']}", num)
                name_style = f"bold {THEME['text']}"
            t.append(f"[{num}]", style=number_style)
            t.append(f" {model_name:<18}", style=name_style)

            if is_recommended:
                t.append("⭐ ", style=THEME["gold"])
            else:
                t.append("   ", style="")

            # Truncate desc to fit
            desc_short = desc[:25] + ".." if len(desc) > 25 else desc
            if is_highlighted:
                t.append("  ← SELECTED", style=f"bold {THEME['success']}")
            padding = 27 - len(desc_short) - (12 if is_highlighted else 0)
            t.append(f"{desc_short}{' ' * padding}│\n", style=THEME["dim"])

        t.append(f"  ├{'─' * 58}┤\n", style=color)

        # Show how to select
        t.append(f"  │  ⌨️  ", style=color)
        t.append("Type ", style=THEME["muted"])
        t.append("1", style=f"bold {THEME['cyan']}")
        t.append("-", style=THEME["muted"])
        t.append(f"{len(self._codex_models)}", style=f"bold {THEME['cyan']}")
        t.append(" in prompt and press Enter", style=THEME["muted"])
        t.append(f"{'':>14}│\n", style=color)

        t.append(f"  ╰{'─' * 58}╯\n", style=color)

        # Show API key requirement
        t.append(f"\n  💡 ", style=THEME["gold"])
        t.append("Requires ", style=THEME["muted"])
        t.append("OPENAI_API_KEY", style=f"bold {THEME['cyan']}")
        t.append(" or ", style=THEME["muted"])
        t.append("CODEX_API_KEY", style=f"bold {THEME['cyan']}")
        t.append(" environment variable\n", style=THEME["muted"])

        log.write(t)

        # Set flag to await model selection
        self._awaiting_model_selection = True
        self._codex_agent_data = agent

        # No model selected yet
        self.current_model = ""
        self.current_provider = "codex"

        badge = self.query_one("#mode-badge", ModeBadge)
        badge.agent = self.current_agent
        badge.mode = ""
        badge.role = ""
        badge.model = ""
        badge.provider = "codex"
    def _auto_select_codex_model(
        self, model_hint: str, agent: Dict[str, Any], log: ConversationLog
    ):
        """Auto-select a Codex model based on user hint."""
        model_hint_lower = model_hint.lower().strip()

        # Try to find a matching model
        matched_model = None
        for model in self._codex_models:
            model_id = model.get("id", "").lower()
            model_name = model.get("name", "").lower()

            # Check various match patterns
            if model_hint_lower in model_id or model_hint_lower in model_name:
                matched_model = model
                break

            # Check for partial matches
            if "o3" in model_hint_lower and "o3" in model_name:
                matched_model = model
                break
            if "o4" in model_hint_lower and "o4" in model_name:
                matched_model = model
                break
            if "gpt" in model_hint_lower and "gpt" in model_name:
                matched_model = model
                break
            if "mini" in model_hint_lower and "mini" in model_name:
                matched_model = model
                break

        if matched_model:
            model_id = matched_model.get("id", "")
            model_name = matched_model.get("name", "")

            self.current_model = model_id
            self.current_provider = "codex"
            self._awaiting_model_selection = False

            badge = self.query_one("#mode-badge", ModeBadge)
            badge.agent = self.current_agent
            badge.model = model_id
            badge.provider = "codex"

            t = Text()
            t.append(f"\n  📜 ", style=THEME["green"])
            t.append("Model selected: ", style=THEME["text"])
            t.append(f"{model_name}", style=f"bold {THEME['green']}")
            t.append(f" ({model_id})\n", style=THEME["dim"])
            t.append(f"  💬 Ready! Type your message.\n", style=THEME["success"])
            log.write(t)
        else:
            # No match found, show available models
            log.add_info(f"Model '{model_hint}' not found. Available models:")
            self._show_codex_models_selection(agent, log)
