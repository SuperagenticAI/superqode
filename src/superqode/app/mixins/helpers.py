"""Assorted small app helpers."""

from __future__ import annotations
import asyncio
import json
import os
import subprocess
import shutil
import shlex
import time
import concurrent.futures
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from textual.widgets import Static, Input
from textual import work
from rich.text import Text
from rich.panel import Panel
from rich.box import ROUNDED
from superqode.providers.model_specs import (
    split_provider_model_ref,
)
from superqode.app.constants import (
    GRADIENT,
    THEME,
    COMMANDS,
)
from superqode.app.models import AgentStatus, AgentInfo
from superqode.app.widgets import (
    ModeBadge,
    HintsBar,
    ConversationLog,
)
from superqode.widgets.command_palette import PaletteCommand
from superqode.app.theme_bridge import (
    apply_theme as _apply_theme_palette,
    save_theme,
)
from superqode.plan import (
    TaskStatus,
    TaskPriority,
)
from superqode.atomic import atomic_read
from superqode.file_viewer import (
    get_file_info,
)
from superqode.sidebar import (
    get_file_diff,
    CollapsibleSidebar,
)
from superqode.undo_manager import UndoManager

# --- helpers extracted from app_main (A1) ---
from superqode.app.inputs import SelectionAwareInput
from superqode.app.welcome import render_welcome
from superqode.app.recipes import PromptCompletionCandidate, LocalRecipe
from superqode.app.session_state import get_session, set_mode


from superqode.app.mixins.helper_permissions import HelperPermissionsMixin


from superqode.app.mixins.helper_diff_review import HelperDiffReviewMixin


from superqode.app.mixins.helper_mcp_attach import HelperMcpAttachMixin


from superqode.app.mixins.helper_vim import HelperVimMixin


from superqode.app.mixins.helper_clipboard import HelperClipboardMixin


from superqode.app.mixins.helper_wizard import HelperWizardMixin


from superqode.app.mixins.helper_exit_lifecycle import HelperExitLifecycleMixin


from superqode.app.mixins.helper_startup import HelperStartupMixin


from superqode.app.mixins.helper_completion_helpers import HelperCompletionHelpersMixin


from superqode.app.mixins.helper_share import HelperShareMixin


from superqode.app.mixins.helper_todos_plan import HelperTodosPlanMixin


from superqode.app.mixins.helper_file_view import HelperFileViewMixin


from superqode.app.mixins.helper_interaction_mode import HelperInteractionModeMixin


from superqode.app.mixins.helper_recipes_skills import HelperRecipesSkillsMixin


from superqode.app.mixins.helper_message_queue import HelperMessageQueueMixin


class HelpersMixin(
    HelperMessageQueueMixin,
    HelperRecipesSkillsMixin,
    HelperInteractionModeMixin,
    HelperFileViewMixin,
    HelperTodosPlanMixin,
    HelperShareMixin,
    HelperCompletionHelpersMixin,
    HelperStartupMixin,
    HelperExitLifecycleMixin,
    HelperWizardMixin,
    HelperClipboardMixin,
    HelperVimMixin,
    HelperMcpAttachMixin,
    HelperDiffReviewMixin,
    HelperPermissionsMixin,
):
    """State/parsing/resolution/predicate helpers used across the app."""

    @property
    def agents(self) -> List[AgentInfo]:
        """Lazy load agents list."""
        if self._agents is None:
            self._agents = self._load_agents()
        return self._agents

    def _set_prompt_border_title(self) -> None:
        """Give the prompt box a neutral code-focused title."""
        try:
            input_box = self.query_one("#input-box")
            input_box.border_title = "✎ Code"
        except Exception:
            pass

    def _refresh_harness_panel(self) -> None:
        """Refresh the harness workbench sidebar, if mounted."""
        try:
            sidebar = self.query_one("#sidebar", CollapsibleSidebar)
            harness_panel = sidebar.get_harness_panel()
            if harness_panel:
                harness_panel.refresh_summary()
        except Exception:
            pass

    def _call_ui(self, func, *args):
        """Run a UI callback from either worker threads or the app thread."""
        try:
            return self.call_from_thread(func, *args)
        except RuntimeError as e:
            message = str(e).lower()
            if "different thread" in message or "app thread" in message:
                return func(*args)
            raise

    def _conversation_log(self) -> ConversationLog | None:
        try:
            return self.query_one("#log", ConversationLog)
        except Exception:
            return None

    def _create_checkpoint_before_agent(self, operation_name: str = "Agent operation"):
        """Create a checkpoint before an agent operation."""
        if hasattr(self, "_undo_manager") and self._undo_manager:
            self._undo_manager.create_checkpoint(f"Before: {operation_name}")

    def _queue_selection_digit(self, digit: str) -> None:
        """Queue a digit for multi-digit selection in provider/model pickers."""
        buf = getattr(self, "_selection_digit_buffer", "")
        buf += digit
        self._selection_digit_buffer = buf

        # Mirror buffer in prompt input for visibility
        try:
            prompt_input = self.query_one("#prompt-input", SelectionAwareInput)
            prompt_input.value = buf
            prompt_input.cursor_position = len(buf)
        except Exception:
            pass

    def _apply_selection_buffer(self) -> None:
        """Apply buffered numeric selection to the current picker."""
        buf = getattr(self, "_selection_digit_buffer", "")
        if not buf:
            return

        # Clear buffer and prompt
        self._selection_digit_buffer = ""
        self._selection_digit_timer = None
        try:
            prompt_input = self.query_one("#prompt-input", SelectionAwareInput)
            prompt_input.value = ""
            prompt_input.cursor_position = 0
        except Exception:
            pass

        log = self.query_one("#log", ConversationLog)

        if getattr(self, "_awaiting_acp_agent_selection", False):
            self._handle_acp_agent_selection(buf, log)
            return
        if getattr(self, "_awaiting_byok_provider", False):
            self._handle_byok_provider_selection(buf, log)
            return
        if getattr(self, "_awaiting_local_provider", False):
            self._handle_local_provider_selection(buf, log)
            return
        if getattr(self, "_awaiting_byok_model", False):
            self._handle_byok_model_selection(buf, log)
            return
        if getattr(self, "_awaiting_local_model", False):
            self._handle_local_model_selection(buf, log)
            return
        if getattr(self, "_awaiting_codex_model", False):
            self._handle_codex_model_selection(buf, log)
            return
        if getattr(self, "_awaiting_codex_effort", False):
            self._handle_codex_effort_selection(buf, log)
            return

        # Fallback to universal selection for other modes
        try:
            self._select_by_number_universal(int(buf))
        except Exception:
            pass

    @staticmethod
    def _scroll_to_rendered_selected_block(log: ConversationLog) -> bool:
        """Bring the selected row and its supporting content into view."""
        try:
            selected_y = next(
                index
                for index, line in enumerate(log.lines)
                if "SELECTED" in line.text or "▶" in line.text
            )
        except (AttributeError, StopIteration):
            return False

        try:
            # Follow-mode is disabled only around this managed scroll (a write
            # with auto_scroll on would yank to the footer). It is restored in
            # the finally so later feedback writes — errors, setup guidance —
            # scroll into view instead of landing invisibly below the picker.
            # Nothing writes between here and the next picker render, which
            # disables follow-mode itself before writing.
            log.auto_scroll = False

            from textual.geometry import Region

            visible_height = max(
                4,
                int(
                    getattr(getattr(log, "scrollable_content_region", None), "height", 0)
                    or getattr(getattr(log, "size", None), "height", 18)
                    or 18
                ),
            )
            block_height = min(visible_height, 5)
            log.scroll_to_region(
                Region(0, selected_y, 1, block_height),
                animate=False,
                x_axis=False,
                y_axis=True,
            )
            return True
        except Exception:
            return False
        finally:
            log.auto_scroll = True

    def _scroll_down_to_item(self, log: ConversationLog, target_offset: int, lines_per_item: int):
        """Helper to scroll down to show the highlighted item."""
        try:
            # Scroll down by the calculated amount
            scroll_steps = max(0, target_offset // 3)  # Approximate scroll steps
            for _ in range(min(scroll_steps, 30)):  # Limit to prevent excessive scrolling
                log.scroll_down(animate=False)
        except Exception:
            pass

    def _adjust_scroll_for_item(self, log: ConversationLog, highlighted_idx: int, total_items: int):
        """Adjust scroll position to show highlighted item (legacy, kept for compatibility)."""
        try:
            # Use the new simpler approach
            self._scroll_to_highlighted_item(log, highlighted_idx, total_items)
        except Exception:
            pass

    def _update_terminal_title(self, task: str = "") -> None:
        """Reflect the active model and current task in the terminal/tab title."""
        agent = getattr(self, "current_agent", "") or getattr(self, "current_model", "") or ""
        sub_parts = []
        if agent:
            sub_parts.append(str(agent))
        if task:
            compact = " ".join(str(task).split())
            sub_parts.append(compact[:40] + ("…" if len(compact) > 40 else ""))
        try:
            self.title = "SuperQode"
            # Textual emits the OS terminal-title escape from title/sub_title.
            self.sub_title = " · ".join(sub_parts)
        except Exception:
            pass

    def _resolve_context_window(self, provider: str, model: str) -> int:
        """Best-effort lookup of a model's context window for the usage meter."""
        if not model:
            return 0
        try:
            from superqode.providers.models import get_model_info

            info = get_model_info(provider, model)
            if info and getattr(info, "context_window", 0):
                return int(info.context_window)
        except Exception:
            pass
        return 0

    def _in_selection_mode(self) -> bool:
        return any(
            getattr(self, flag, False)
            for flag in (
                "_awaiting_acp_agent_selection",
                "_awaiting_byok_provider",
                "_awaiting_byok_model",
                "_awaiting_connect_type",
                "_awaiting_local_provider",
                "_awaiting_local_model",
                "_awaiting_local_connect_start",
                "_awaiting_local_server_start",
                "_awaiting_local_dep_install",
                "_awaiting_model_selection",
                "_awaiting_recommendation_selection",
                "_awaiting_session_resume",
                "_awaiting_mode_selection",
            )
        )

    def watch_is_busy(self, old: bool, new: bool) -> None:
        """When the agent becomes idle, drain any queued type-ahead messages."""
        if old and not new and getattr(self, "_typeahead_queue", []):
            # Small delay lets the completion render settle before the next turn.
            self.set_timer(0.2, self._drain_message_queue)

    @staticmethod
    def _env_flag(name: str) -> bool:
        value = os.environ.get(name, "").strip().lower()
        return value in {"1", "true", "yes", "on"}

    @staticmethod
    def _is_known_slash_input(text: str) -> bool:
        candidate = text.strip().lower()
        if not candidate.startswith("/"):
            return False
        try:
            from superqode.widgets.slash_complete import DEFAULT_COMMANDS

            known = {command.command.lower() for command in DEFAULT_COMMANDS}
        except Exception:
            known = {command.lower() for command in COMMANDS if command.startswith("/")}
        first_word = candidate.split(maxsplit=1)[0]
        return candidate in known or first_word in known

    def _try_acp_slash_command(self, name: str, args: str, log: ConversationLog) -> bool:
        """Dispatch a slash command through the ACP local registry if registered.

        Returns True if the registry handled it (so the caller should stop
        processing); False if the command isn't registered (fall through to
        the rest of ``_handle_command``).

        Output is written to the conversation log. Async handlers run on the
        dedicated ACP loop runner when present so we don't block the UI loop.
        """
        from superqode.acp.slash import (
            SlashRegistry,
            UnknownSlashCommandError,
            builtin_registry,
        )

        client = self._acp_client
        if client is None:
            return False

        registry: SlashRegistry
        if self._acp_slash_registry is None:
            self._acp_slash_registry = builtin_registry()
        registry = self._acp_slash_registry

        if not registry.has(name):
            return False

        # Reconstruct the input line the registry expects.
        line = f"/{name}" if not args else f"/{name} {args}"

        async def _run() -> str:
            try:
                return await registry.dispatch(client, line)
            except UnknownSlashCommandError:
                # Shouldn't happen given the has() guard, but stay defensive.
                return f"unknown local slash command: {name}"
            except Exception as exc:  # noqa: BLE001 - surface to log, don't crash UI
                return f"slash command {name!r} failed: {exc}"

        try:
            if self._acp_loop_runner is not None:
                output = self._acp_loop_runner.run(_run(), timeout=15.0)
            else:
                import asyncio as _asyncio

                output = _asyncio.run(_run())
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"slash command {name!r} dispatch error: {exc}")
            return True

        if output:
            log.write(output)
        return True

    def _user_message_history(self, log: ConversationLog) -> list[str]:
        """Return prior user messages (oldest first) for rewind/edit."""
        return [
            text for role, text, _agent in log._messages if role == "user" and str(text).strip()
        ]

    def _apply_and_persist_theme(self, name: str) -> bool:
        """Apply a theme palette live, persist it, and refresh the visible UI."""
        if not _apply_theme_palette(name):
            return False
        self._current_theme = name
        save_theme(name)
        # Re-render widgets that read THEME at render time.
        try:
            self.screen.refresh(layout=True)
        except Exception:
            pass
        return True

    def _perform_rewind(self, occurrence: int, log: ConversationLog) -> None:
        """Truncate context to before the Nth user message and reload it.

        ``occurrence`` is 1-based among user messages. Removes the stored agent
        history from that point on, trims the in-memory transcript record, and
        prefills the prompt so the user can edit and resend.
        """
        messages = self._user_message_history(log)
        total = len(messages)
        if not (1 <= occurrence <= total):
            log.add_info(f"No message #{occurrence} to rewind to.")
            return
        target_text = messages[occurrence - 1]

        # Truncate the agent's persisted history so it forgets later turns.
        removed = 0
        session_manager = getattr(self._pure_mode, "_session_manager", None)
        if session_manager is not None:
            try:
                removed = session_manager.rewind_to_user_message(occurrence)
            except Exception as exc:  # pragma: no cover - defensive
                log.add_error(f"Could not rewind stored history: {exc}")

        # Trim the in-memory transcript record to the chosen point so future
        # rewinds, copies and transcripts reflect the rewound conversation.
        self._trim_transcript_to_user_occurrence(log, occurrence)

        self._set_prompt_prefill(target_text)
        suffix = f" — cleared {removed} stored message(s)" if removed else ""
        log.add_info(
            f"↩ Rewound to message {occurrence}/{total}{suffix}. Edit and press Enter to resend."
        )

    @staticmethod
    def _trim_transcript_to_user_occurrence(log: ConversationLog, occurrence: int) -> None:
        """Drop transcript entries from the Nth user message onward."""
        records = getattr(log, "_messages", None)
        if records is None:
            return
        seen = 0
        cut = None
        for index, (role, _text, _agent) in enumerate(records):
            if role == "user" and str(_text).strip():
                seen += 1
                if seen == occurrence:
                    cut = index
                    break
        if cut is not None:
            del records[cut:]

    def _set_prompt_prefill(self, value: str) -> None:
        """Put text in the prompt input and focus it."""
        try:
            input_widget = self.query_one("#prompt-input", SelectionAwareInput)
            input_widget.value = value
            input_widget.cursor_position = len(value)
            input_widget.focus()
        except Exception:
            pass

    @staticmethod
    def _provider_description(provider_id: str) -> str:
        try:
            from superqode.providers.dynamic import resolve_provider_def

            provider = resolve_provider_def(provider_id)
            return provider.name if provider else ""
        except Exception:
            return ""

    @staticmethod
    def _all_provider_ids() -> list[str]:
        try:
            from superqode.providers.dynamic import all_provider_ids

            return all_provider_ids()
        except Exception:
            return []

    def _get_session_manager(self):
        """Get a local JSONL session manager."""
        from superqode.agent.session_manager import SessionManager

        return SessionManager(storage_dir=".superqode/sessions")

    def _current_session_id(self) -> str:
        """Resolve the active or most-recent local session id."""
        try:
            if hasattr(self, "_pure_mode") and self._pure_mode:
                sid = self._pure_mode.get_current_session_id()
                if sid:
                    return sid
        except Exception:
            pass
        try:
            sessions = self._get_session_manager().list_all_sessions()
            if sessions:
                return sessions[0].session_id
        except Exception:
            pass
        return ""

    async def _check_update_worker(self, current: str, log: ConversationLog):
        """Fetch the latest version from PyPI without blocking the UI."""
        import asyncio
        import json as _json
        import urllib.request

        def _fetch() -> str:
            with urllib.request.urlopen("https://pypi.org/pypi/superqode/json", timeout=8) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            return str(data.get("info", {}).get("version", ""))

        try:
            latest = await asyncio.to_thread(_fetch)
        except Exception as exc:
            self._call_ui(log.add_error, f"Could not check for updates: {exc}")
            return
        if not latest:
            self._call_ui(log.add_info, "Could not determine the latest version.")
            return
        if self._version_is_newer(latest, current):
            t = Text()
            t.append("\n  ⬆ ", style=f"bold {THEME['success']}")
            t.append(f"Update available: {current} → {latest}\n", style=f"bold {THEME['text']}")
            t.append("  Upgrade with ", style=THEME["muted"])
            t.append("uv tool upgrade superqode", style=f"bold {THEME['cyan']}")
            t.append(" or ", style=THEME["muted"])
            t.append("uv tool upgrade superqode", style=f"bold {THEME['cyan']}")
            t.append("\n", style="")
            self._call_ui(log.write, t)
        else:
            self._call_ui(log.add_success, f"SuperQode is up to date ({current}).")

    @staticmethod
    def _version_is_newer(latest: str, current: str) -> bool:
        """Compare dotted version strings; True if latest > current."""

        def parse(v: str) -> tuple:
            out = []
            for part in str(v).split("."):
                num = "".join(ch for ch in part if ch.isdigit())
                out.append(int(num) if num else 0)
            return tuple(out)

        try:
            return parse(latest) > parse(current)
        except Exception:
            return False

    def _factory(self):
        from superqode.session.factory import SoftwareFactory

        return SoftwareFactory(storage_dir=".superqode/sessions")

    def _ensure_project_trusted_for(self, log: ConversationLog, action: str) -> bool:
        """Require project trust before enabling project-local executable surfaces."""
        from superqode.project_trust import get_project_trust

        record = get_project_trust(Path.cwd())
        if record.trusted:
            return True
        log.add_error(f"Project is untrusted; refusing to {action}.")
        log.add_info(
            "Review this workspace, then run :trust yes to allow project-local plugins/MCP."
        )
        return False

    def _set_status_runtime(self, runtime_name: str) -> None:
        """Show the active runtime in the visible status bar (hidden for builtin)."""
        try:
            from superqode.app.widgets import ColorfulStatusBar

            display = "" if runtime_name in ("", "builtin") else runtime_name
            self.query_one("#status-bar", ColorfulStatusBar).active_runtime = display
        except Exception:  # noqa: BLE001
            pass

    def _subscription_login_in_progress(self) -> bool:
        return bool(getattr(self, "_subscription_login_busy", False))

    def _begin_subscription_login(
        self,
        product: str,
        log: ConversationLog,
        *,
        on_success: Optional[Any] = None,
        reason: str = "",
        force: bool = False,
    ) -> bool:
        """Start interactive vendor CLI login when credentials are missing.

        Returns True when a login worker was started (caller should stop), or
        False when the product is already signed in / cannot launch login.
        ``on_success`` is a zero-arg callback invoked on the UI thread after a
        successful login so connect can continue automatically.

        ``force=True`` re-runs login even when an auth file already exists
        (used for expired Grok sessions).
        """
        from superqode.providers.subscription_login import (
            get_login_spec,
            login_ready,
            binary_path,
        )

        try:
            spec = get_login_spec(product)
        except KeyError:
            log.add_error(f"Unknown subscription login: {product}")
            return False

        if not force and login_ready(spec):
            return False

        if self._subscription_login_in_progress():
            log.add_info(f"{spec.label} sign-in is already running — finish it, then retry.")
            return True

        if getattr(self, "_awaiting_subscription_login", None):
            log.add_info(
                "A sign-in prompt is already waiting — press Enter to start it or type 'n' to cancel."
            )
            return True

        if binary_path(spec) is None:
            log.add_error(
                f"The {spec.label} CLI is not installed, so the subscription route is unavailable."
            )
            for line in spec.install_hint.splitlines():
                if line.strip():
                    log.add_info(line)
            if spec.id == "codex":
                log.add_info("No subscription? Use BYOK instead: :connect byok openai <model>")
            elif spec.id == "grok":
                log.add_info("No subscription? Use BYOK instead: :connect byok xai grok-4.5")
            return True  # handled (failed setup); caller should not continue connect

        # Consent gate: never run the vendor login (or open a browser) without
        # an explicit go-ahead. Stash the intent; the prompt handler launches it
        # only after the user confirms.
        self._awaiting_subscription_login = {
            "product": spec.id,
            "on_success": on_success,
            "force": force,
        }

        t = Text()
        t.append("\n  🔐 ", style=f"bold {THEME['cyan']}")
        t.append(f"Sign in to {spec.label}?\n\n", style=f"bold {THEME['text']}")
        if reason:
            t.append(f"  {reason}\n\n", style=THEME["muted"])
        t.append("  SuperQode can run the official CLI login for you:\n", style=THEME["muted"])
        t.append(f"    {spec.binary} {' '.join(spec.login_args)}\n\n", style=THEME["cyan"])
        t.append(
            "  It prints a sign-in link and one-time code — you open the link yourself.\n"
            "  SuperQode will not open a browser automatically.\n\n",
            style=THEME["muted"],
        )
        t.append("  Press ", style=THEME["muted"])
        t.append("Enter", style=f"bold {THEME['success']}")
        t.append(" to start, or type ", style=THEME["muted"])
        t.append("n", style=f"bold {THEME['cyan']}")
        t.append(" to cancel.\n", style=THEME["muted"])
        t.append("  Prefer to do it yourself? Run ", style=THEME["dim"])
        t.append(f"{spec.binary} login", style=THEME["cyan"])
        t.append(" in a terminal, then retry.\n", style=THEME["dim"])
        try:
            log.write_feedback(t)
        except Exception:  # noqa: BLE001 - some logs only have write/add_*
            log.write(t)

        try:
            self._set_input_placeholder(f"Run `{spec.binary} login`?  Enter = yes, n = cancel")
        except Exception:  # noqa: BLE001 - placeholder is cosmetic
            pass
        return True

    def _handle_subscription_login_input(self, text: str, log: ConversationLog) -> bool:
        """Resolve the pending subscription-login consent prompt.

        Enter / yes launches the vendor CLI login worker; ``n`` cancels. Returns
        True when it handled the input (so the caller stops dispatching).
        """
        pending = getattr(self, "_awaiting_subscription_login", None)
        if not pending:
            return False

        from superqode.providers.subscription_login import get_login_spec

        product = pending["product"]
        try:
            spec = get_login_spec(product)
            label, binary = spec.label, spec.binary
        except KeyError:
            label = binary = product

        choice = (text or "").strip().lower()
        if choice in ("n", "no", "cancel", "skip", "q"):
            self._awaiting_subscription_login = None
            self._reset_input_placeholder()
            log.add_info(f"{label} sign-in cancelled. Run `{binary} login` yourself, then retry.")
            return True

        if choice not in ("", "y", "yes", "ok", "start", "go"):
            log.add_error("Press Enter to run the vendor login, or type 'n' to cancel.")
            try:
                self._set_input_placeholder(f"Run `{binary} login`?  Enter = yes, n = cancel")
            except Exception:  # noqa: BLE001
                pass
            return True

        # Confirmed → launch the vendor login worker.
        self._awaiting_subscription_login = None
        self._reset_input_placeholder()
        self._subscription_login_busy = True
        self._subscription_login_on_success = pending.get("on_success")
        self._subscription_login_product = product
        self._subscription_login_force = bool(pending.get("force"))

        t = Text()
        t.append("\n  🔐 ", style=f"bold {THEME['cyan']}")
        t.append(f"Starting {label} sign-in…\n", style=f"bold {THEME['text']}")
        t.append(
            "  Open the link printed below and enter the one-time code. "
            "Waiting up to 15 minutes.\n",
            style=THEME["dim"],
        )
        try:
            log.write_feedback(t)
        except Exception:  # noqa: BLE001
            log.write(t)

        self.run_worker(self._subscription_login_worker(product, log), exclusive=False)
        return True

    async def _subscription_login_worker(self, product: str, log: ConversationLog) -> None:
        """Background worker: run vendor device-auth login, then resume connect."""
        from superqode.providers.subscription_login import (
            get_login_spec,
            run_subscription_login,
        )

        try:
            spec = get_login_spec(product)
        except KeyError as exc:
            self._call_ui(log.add_error, str(exc))
            self._subscription_login_busy = False
            return

        def _on_line(line: str) -> None:
            # Device codes / URLs from the vendor CLI — surface them immediately.
            text = (line or "").rstrip()
            if not text:
                return

            def _write() -> None:
                try:
                    log.add_info(text)
                except Exception:  # noqa: BLE001
                    pass

            self._call_ui(_write)

        force = bool(getattr(self, "_subscription_login_force", False))
        try:
            # open_browser=False: honour user consent — surface the link/code and
            # let them open it, rather than launching a browser automatically.
            result = await run_subscription_login(
                product, on_line=_on_line, force=force, open_browser=False
            )
        except Exception as exc:  # noqa: BLE001
            self._call_ui(log.add_error, f"{spec.label} login failed: {exc}")
            self._subscription_login_busy = False
            self._subscription_login_on_success = None
            self._subscription_login_force = False
            return

        on_success = getattr(self, "_subscription_login_on_success", None)
        self._subscription_login_busy = False
        self._subscription_login_on_success = None
        self._subscription_login_force = False

        if not result.ok:
            self._call_ui(log.add_error, result.reason or f"{spec.label} login did not complete.")
            if spec.id == "codex":
                self._call_ui(
                    log.add_info,
                    "You can also run `codex login` in a terminal, then :connect codex.",
                )
            elif spec.id == "grok":
                self._call_ui(
                    log.add_info,
                    "You can also run `grok login` in a terminal, then :connect grok.",
                )
            return

        if result.opened_browser:
            self._call_ui(log.add_info, "Browser opened for sign-in.")
        self._call_ui(log.add_success, spec.success_hint)

        if callable(on_success):

            def _resume() -> None:
                try:
                    on_success()
                except Exception as exc:  # noqa: BLE001
                    log.add_error(f"Sign-in succeeded but reconnect failed: {exc}")

            self._call_ui(_resume)

    def _import_grok_token(self, log, *, on_login_success: Optional[Any] = None) -> bool:
        """Import the local `grok login` session into the auth store.

        Shared by connect and the model picker. Returns False (with guidance
        written to the log) when there is no usable CLI login.

        When credentials are missing (or expired) and the Grok CLI is installed,
        SuperQode launches ``grok login --device-auth`` (browser + one-time code)
        and returns False. Pass ``on_login_success`` to auto-retry the original
        action after the user finishes sign-in.
        """
        from superqode.providers import grok_cli_auth
        from superqode.providers.subscription_login import GROK_LOGIN, has_local_login

        # Someone without the product installed should get install steps, not
        # be told to run a command that does not exist on their machine.
        if shutil.which("grok") is None:
            log.add_error(
                "The Grok CLI is not installed, so the subscription route is unavailable."
            )
            log.add_info(
                "Install it (macOS/Linux/WSL): curl -fsSL https://x.ai/cli/install.sh | bash"
            )
            log.add_info("Windows PowerShell:           irm https://x.ai/cli/install.ps1 | iex")
            log.add_info("Then sign in with `grok login` and re-run :connect grok.")
            log.add_info("No subscription? Use BYOK instead: :connect byok xai grok-4.5")
            return False

        if not has_local_login(GROK_LOGIN):
            started = self._begin_subscription_login(
                "grok",
                log,
                on_success=on_login_success,
                reason="No local Grok login found (~/.grok/auth.json).",
            )
            if started:
                return False

        auth = grok_cli_auth.import_cli_token()
        if auth is None:
            log.add_error("No Grok CLI login found (~/.grok/auth.json).")
            log.add_info("Run `grok login` first, or use BYOK: :connect byok xai grok-4.5")
            log.add_info("For Grok Build ACP instead: :connect acp grok")
            return False
        if auth.is_expired():
            grok_cli_auth.remove_cli_token()
            started = self._begin_subscription_login(
                "grok",
                log,
                on_success=on_login_success,
                reason="The Grok CLI session looks expired (sessions last ~7 days).",
                force=True,
            )
            if started:
                return False
            log.add_error("The Grok CLI session looks expired (CLI sessions last ~7 days).")
            log.add_info("Run `grok login` again, then re-run :connect grok.")
            return False
        # Login state may have changed since the last catalog probe.
        grok_cli_auth.clear_cli_models_cache()
        return True

    def _active_agent_loop(self):
        """The live AgentLoop for the current BYOK/local session, if any."""
        pure = getattr(self, "_pure_mode", None)
        return getattr(pure, "_agent", None) if pure is not None else None

    async def _context_show_worker(self, agent, log, redetect: bool = False) -> None:
        try:
            if redetect:
                await agent._ensure_context_window()
            else:
                # Resolve once if it hasn't been (e.g. before the first turn).
                if not getattr(agent, "_cached_context_window", 0):
                    await agent._ensure_context_window()
            threshold, keep_recent, window = agent._compaction_budgets()
            source = getattr(agent, "_context_window_source", "unknown")
        except Exception as exc:
            self._call_ui(log.add_error, f"Context detection failed: {exc}")
            return

        t = Text()
        t.append("\n  🪟 ", style=f"bold {THEME['cyan']}")
        t.append("Context window\n\n", style=f"bold {THEME['text']}")
        t.append(f"    Window:      {window:,} tokens  ", style=THEME["text"])
        t.append(f"({source})\n", style=THEME["muted"])
        t.append(f"    Compact at:  {threshold:,} tokens\n", style=THEME["muted"])
        t.append(f"    Keep recent: ~{keep_recent:,} tokens\n", style=THEME["muted"])
        auto = os.environ.get("SUPERQODE_AUTO_COMPACT", "").strip().lower()
        on = auto not in ("0", "false", "no", "off")
        t.append(
            f"    Auto-compact: {'ON' if on else 'OFF'}\n",
            style=THEME["success" if on else "muted"],
        )
        t.append("\n    ", style="")
        t.append(":context <n>", style=f"bold {THEME['cyan']}")
        t.append(" to pin  ·  ", style=THEME["muted"])
        t.append(":context auto", style=f"bold {THEME['cyan']}")
        t.append(" to re-detect\n", style=THEME["muted"])
        self._call_ui(self._show_command_output, log, t)

    async def _ask_agent_question(self, question, log: ConversationLog):
        """Show an agent question in the TUI and await the next input submission."""
        from superqode.tools.question_tool import Answer

        future: concurrent.futures.Future = concurrent.futures.Future()

        def show_question():
            self._awaiting_agent_question = True
            self._pending_agent_question = question
            self._pending_agent_question_future = future
            self._permission_pending = True

            card = Text()
            card.append("🤔 Agent needs your input\n\n", style=f"bold {THEME['warning']}")
            card.append(str(question.question), style=f"bold {THEME['text']}")
            card.append("\n")
            if getattr(question, "options", None):
                card.append("\n")
                for idx, option in enumerate(question.options, 1):
                    card.append(f"  [{idx}] ", style=f"bold {THEME['cyan']}")
                    card.append(str(option), style=THEME["text"])
                    card.append("\n")
            if getattr(question, "default", None):
                card.append("\n  default: ", style=THEME["muted"])
                card.append(str(question.default), style=f"bold {THEME['muted']}")
                card.append("\n")
            card.append("\n  type a number, or your own answer", style=THEME["muted"])
            card.append("  •  ", style=THEME["dim"])
            card.append(":cancel", style=f"bold {THEME['cyan']}")
            card.append(" to skip", style=THEME["muted"])

            log.write(
                Panel(
                    card,
                    border_style=THEME["warning"],
                    box=ROUNDED,
                    padding=(1, 2),
                )
            )

            try:
                input_widget = self.query_one("#prompt-input", SelectionAwareInput)
                input_widget.placeholder = "Answer the agent question..."
                input_widget.focus()
            except Exception:
                pass
            self._start_permission_pulse()

        try:
            self._call_ui(show_question)
        except RuntimeError as e:
            message = str(e).lower()
            if "different thread" in message or "app thread" in message:
                show_question()
            else:
                raise

        answer = await asyncio.wrap_future(future)
        return Answer(value=answer["value"], custom=answer.get("custom", False))

    def _direct_chat_status(self) -> tuple[bool, str, str]:
        """Return whether raw chat can talk to the active direct model session."""
        pure = getattr(self, "_pure_mode", None)
        pure_session = getattr(pure, "session", None)
        connected = bool(getattr(pure_session, "connected", False))
        provider = str(getattr(pure_session, "provider", "") or "").strip()
        model = str(getattr(pure_session, "model", "") or "").strip()

        execution_mode = str(self.__dict__.get("current_mode", "") or "").strip().lower()
        if not execution_mode:
            try:
                execution_mode = str(getattr(self, "current_mode", "") or "").strip().lower()
            except Exception:
                execution_mode = ""
        try:
            session_mode = str(getattr(get_session(), "execution_mode", "") or "").strip().lower()
        except Exception:
            session_mode = ""
        if execution_mode not in {"local", "byok", "pure", "acp"} and session_mode:
            execution_mode = session_mode

        direct_modes = {"local", "byok", "pure"}
        if connected and provider and model and execution_mode in direct_modes:
            return True, "", f"{provider}/{model}"

        if execution_mode == "acp" or getattr(self, "_acp_client", None) is not None:
            return (
                False,
                "Chat mode is only for Local/BYOK direct model sessions. "
                "ACP connections are full coding agents; use Build mode or Plan mode with them.",
                "",
            )

        return (
            False,
            "Chat mode needs a Local or BYOK direct model connection. "
            "Use :connect local or :connect byok first. ACP agents use Build/Plan mode.",
            "",
        )

    @work(exclusive=True)
    async def _chat_worker(self, text: str, log: ConversationLog):
        """Worker wrapper so chat streaming runs off the input handler."""
        await self._send_chat_message(text, log)

    def _use_jsonrpc_acp_client(self) -> bool:
        """Return True when the custom JSON-RPC ACP client is enabled."""
        import os

        mode = os.environ.get("SUPERQODE_ACP_CLIENT", "").strip().lower()
        return mode in {"custom", "jsonrpc", "rpc"}

    def _get_tool_signature(self, tool_name: str, tool_input: dict) -> str:
        """Generate a unique signature for a tool call to track approvals."""
        # Create a signature from tool name and key parameters
        file_path = tool_input.get("filePath", tool_input.get("path", tool_input.get("file", "")))
        command = tool_input.get("command", "")
        key = f"{tool_name}:{file_path or command}"
        return key

    def _reset_input_placeholder(self):
        """Reset input placeholder to default and stop any animations."""
        # Stop permission pulse animation
        self._stop_permission_pulse()

        # Reset approval notification flag
        self._approval_notification_shown = False

        # Reset input box border explicitly
        try:
            input_box = self.query_one("#input-box")
            input_box.styles.border = ("tall", "#1a1a1a")
        except Exception:
            pass

        try:
            input_widget = self.query_one("#prompt-input", SelectionAwareInput)
            input_widget.placeholder = SelectionAwareInput.DEFAULT_PLACEHOLDER
        except Exception:
            pass

    def _set_input_placeholder(self, text: str) -> None:
        """Best-effort prompt hint for inline decisions."""
        try:
            input_widget = self.query_one("#prompt-input", SelectionAwareInput)
            input_widget.placeholder = text
        except Exception:
            pass

    def _strip_ansi(self, text: str) -> str:
        """Remove ANSI escape codes from text."""
        import re

        ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        return ansi_escape.sub("", text)

    def _is_calm_output(self) -> bool:
        """True when we should present a calm, summarized view (not verbose)."""
        return getattr(self, "thinking_verbosity", "normal") != "verbose"

    def _looks_like_code(self, text: str) -> bool:
        """Check if a line looks like code (to be suppressed for local models).

        More aggressive detection to catch all code-like patterns.
        """
        text_stripped = text.strip()

        # Empty or whitespace-only lines
        if not text_stripped:
            return True

        # Very short lines that are likely code fragments
        if len(text_stripped) < 15:
            # But keep if it's a status message
            if any(
                word in text_stripped.lower()
                for word in ["ok", "done", "error", "fail", "complete"]
            ):
                return False
            # Likely code fragment if it has code characters
            if any(
                char in text_stripped
                for char in ["=", "(", ")", "[", "]", "{", "}", ":", "->", ".", ","]
            ):
                return True

        # Lines starting with common code keywords (more comprehensive)
        code_keywords = [
            "def ",
            "class ",
            "import ",
            "from ",
            "if ",
            "for ",
            "while ",
            "return ",
            "async ",
            "await ",
            "try:",
            "except",
            "finally:",
            "with ",
            "elif ",
            "else:",
            "pass",
            "break",
            "continue",
            "yield ",
            "const ",
            "let ",
            "var ",
            "function ",
            "export ",
            "require(",
            "public ",
            "private ",
            "protected ",
            "static ",
            "final ",
            "#",  # Comments
            "//",  # Comments
            "/*",  # Comments
        ]
        if any(text_stripped.startswith(keyword) for keyword in code_keywords):
            return True

        # Lines that are mostly code patterns
        code_patterns = [
            " = ",  # Assignment
            "()",  # Function call
            "[]",  # List access
            "{}",  # Dict access
            "->",  # Type hint
            "=>",  # Arrow function
            "::",  # Scope resolution
        ]
        pattern_count = sum(1 for pattern in code_patterns if pattern in text_stripped)

        # If multiple code patterns, likely code
        if pattern_count >= 2:
            return True

        # Lines ending with colon or semicolon (likely code)
        if text_stripped.endswith(":") or text_stripped.endswith(";"):
            if len(text_stripped) < 60:  # Reasonable length for code
                return True

        # Lines that are just variable assignments or function calls
        if " = " in text_stripped:
            # Check if it's a simple assignment (not a status message)
            parts = text_stripped.split(" = ", 1)
            if len(parts) == 2:
                # If left side looks like a variable name (short, alphanumeric/underscore)
                left = parts[0].strip()
                if len(left) < 40 and (
                    left.replace("_", "").replace(".", "").isalnum() or "[" in left or "." in left
                ):
                    return True

        # Lines with function call patterns
        if "(" in text_stripped and ")" in text_stripped:
            # Check if it looks like a function call (not just parentheses in text)
            if text_stripped.count("(") == text_stripped.count(")") and len(text_stripped) < 80:
                # Likely a function call
                return True

        # Lines with array/list access patterns
        if "[" in text_stripped and "]" in text_stripped:
            if len(text_stripped) < 60:
                return True

        # Lines that are just indentation (likely code structure)
        if text_stripped.startswith("    ") or text_stripped.startswith("\t"):
            if len(text_stripped.strip()) < 30:
                return True

        return False

    def _get_emoji_for_line(self, line: str) -> str:
        """Get appropriate emoji based on line content type with variety."""

        line_lower = line.lower()
        line_hash = abs(hash(line))  # For consistent selection per line

        # File operations - multiple emojis per category
        if any(keyword in line_lower for keyword in ["read", "reading", "opened", "file"]):
            emojis = ["📄", "📖", "📑", "📰", "📃", "📋", "🗂️", "📁"]
            return emojis[line_hash % len(emojis)]
        elif any(
            keyword in line_lower for keyword in ["write", "writing", "wrote", "saved", "created"]
        ):
            emojis = ["📝", "🖊️", "🖋️", "✏️", "📝", "💾", "💿"]
            return emojis[line_hash % len(emojis)]
        elif any(
            keyword in line_lower
            for keyword in ["edit", "editing", "modified", "updated", "changed"]
        ):
            emojis = ["✏️", "🔧", "🔄", "♻️", "🛠️", "📝", "✂️", "🔨"]
            return emojis[line_hash % len(emojis)]
        elif any(keyword in line_lower for keyword in ["delete", "deleted", "removed"]):
            emojis = ["🗑️", "❌", "🗑", "💥", "🔥", "⚡", "🗯️"]
            return emojis[line_hash % len(emojis)]

        # Code/compilation - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["compile", "compiling", "build", "building", "make"]
        ):
            emojis = ["🔨", "⚙️", "🛠️", "🔧", "🏗️", "📦", "🎯", "⚡"]
            return emojis[line_hash % len(emojis)]
        elif any(keyword in line_lower for keyword in ["code", "coding", "programming", "script"]):
            emojis = ["💻", "⌨️", "🖥️", "💾", "🔤", "📟", "🖱️", "⌨"]
            return emojis[line_hash % len(emojis)]
        elif any(keyword in line_lower for keyword in ["test", "testing", "tested", "spec"]):
            emojis = ["🧪", "🔬", "⚗️", "🧫", "🔍", "✅", "✔️", "🎯"]
            return emojis[line_hash % len(emojis)]
        elif any(
            keyword in line_lower for keyword in ["import", "importing", "require", "package"]
        ):
            emojis = ["📦", "📚", "📖", "📗", "📘", "📙", "📕", "🎁"]
            return emojis[line_hash % len(emojis)]

        # Search/query - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["search", "searching", "find", "finding", "grep", "query"]
        ):
            emojis = ["🔍", "🔎", "🔎", "👀", "🔭", "🔬", "🔦", "💡"]
            return emojis[line_hash % len(emojis)]
        elif any(keyword in line_lower for keyword in ["scan", "scanning", "analyze", "analyzing"]):
            emojis = ["🔎", "🔬", "🔍", "📊", "📈", "📉", "🔭", "👁️"]
            return emojis[line_hash % len(emojis)]

        # Network/web - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["http", "https", "url", "web", "api", "request", "fetch"]
        ):
            emojis = ["🌐", "🌍", "🌎", "🌏", "💻", "📡", "📶", "🔄"]
            return emojis[line_hash % len(emojis)]
        elif any(
            keyword in line_lower
            for keyword in ["connect", "connecting", "connected", "connection"]
        ):
            emojis = ["🔌", "🔗", "⛓️", "🔗", "📡", "📶", "🌐", "💫"]
            return emojis[line_hash % len(emojis)]
        elif any(
            keyword in line_lower for keyword in ["download", "downloading", "upload", "uploading"]
        ):
            emojis = ["⬇️", "⬆️", "📥", "📤", "💾", "📦", "🔄", "⚡"]
            return emojis[line_hash % len(emojis)]

        # Terminal/commands - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["run", "running", "execute", "executing", "command", "cmd"]
        ):
            emojis = ["🖥️", "💻", "⌨️", "⚡", "🚀", "▶️", "▶", "🎬"]
            return emojis[line_hash % len(emojis)]
        elif any(keyword in line_lower for keyword in ["terminal", "shell", "bash", "sh", "zsh"]):
            emojis = ["💻", "🖥️", "⌨️", "🖱️", "📟", "💾", "🔤", "⌨"]
            return emojis[line_hash % len(emojis)]
        elif any(
            keyword in line_lower
            for keyword in ["install", "installing", "installed", "setup", "setting up"]
        ):
            emojis = ["⚙️", "🔧", "🛠️", "📦", "📥", "✅", "🎯", "🔨"]
            return emojis[line_hash % len(emojis)]

        # Errors/warnings - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["error", "failed", "failure", "exception", "traceback"]
        ):
            emojis = ["❌", "🚫", "⚠️", "💥", "🔥", "⚡", "🚨", "⛔"]
            return emojis[line_hash % len(emojis)]
        elif any(keyword in line_lower for keyword in ["warn", "warning", "caution", "alert"]):
            emojis = ["⚠️", "🚨", "⚡", "💡", "🔔", "📢", "📣", "🔴"]
            return emojis[line_hash % len(emojis)]

        # Success/completion - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["success", "succeeded", "complete", "completed", "done", "finished"]
        ):
            emojis = ["✅", "✔️", "🎉", "🎊", "✨", "🌟", "💫", "🎯"]
            return emojis[line_hash % len(emojis)]
        elif any(
            keyword in line_lower for keyword in ["ready", "initialized", "started", "launch"]
        ):
            emojis = ["✨", "🚀", "⚡", "💫", "🌟", "🎯", "✅", "🎬"]
            return emojis[line_hash % len(emojis)]

        # Thinking/processing - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["think", "thinking", "process", "processing", "analyze"]
        ):
            emojis = ["🧠", "💭", "🤔", "💡", "🔍", "🔎", "🔬", "📊"]
            return emojis[line_hash % len(emojis)]
        elif any(keyword in line_lower for keyword in ["plan", "planning", "strategy"]):
            emojis = ["💭", "📋", "📝", "📄", "🗺️", "🧭", "🎯", "📊"]
            return emojis[line_hash % len(emojis)]
        elif any(keyword in line_lower for keyword in ["wait", "waiting", "pending"]):
            emojis = ["⏳", "⏰", "🕐", "🕑", "🕒", "⏱️", "⏲️", "💤"]
            return emojis[line_hash % len(emojis)]

        # Data/analysis - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["data", "result", "output", "response", "json", "xml"]
        ):
            emojis = ["📊", "📈", "📉", "📋", "📄", "📑", "📝", "💾"]
            return emojis[line_hash % len(emojis)]
        elif any(
            keyword in line_lower for keyword in ["model", "models", "ai", "llm", "gpt", "claude"]
        ):
            emojis = ["🤖", "👾", "🤖", "🧠", "💻", "🔮", "✨", "🌟"]
            return emojis[line_hash % len(emojis)]
        elif any(keyword in line_lower for keyword in ["token", "tokens", "cost", "usage"]):
            emojis = ["📈", "💰", "💵", "💴", "💶", "💷", "💸", "📊"]
            return emojis[line_hash % len(emojis)]

        # Configuration/setup - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["config", "configuration", "setting", "settings", "option"]
        ):
            emojis = ["⚙️", "🔧", "🛠️", "📋", "📝", "📄", "🗂️", "🔨"]
            return emojis[line_hash % len(emojis)]
        elif any(
            keyword in line_lower for keyword in ["init", "initialize", "initializing", "setup"]
        ):
            emojis = ["🔧", "⚙️", "🛠️", "🚀", "✨", "🎯", "📦", "🔨"]
            return emojis[line_hash % len(emojis)]

        # Git/version control - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["git", "commit", "push", "pull", "branch", "merge"]
        ):
            emojis = ["🌿", "🌳", "🌲", "🌱", "🍃", "🌾", "🔀", "📦"]
            return emojis[line_hash % len(emojis)]

        # Database - multiple emojis
        elif any(keyword in line_lower for keyword in ["database", "db", "sql", "query", "table"]):
            emojis = ["🗄️", "💾", "📊", "📈", "🗃️", "📦", "🗂️", "💿"]
            return emojis[line_hash % len(emojis)]

        # Security - multiple emojis
        elif any(
            keyword in line_lower
            for keyword in ["auth", "authentication", "login", "password", "key", "secret"]
        ):
            emojis = ["🔐", "🔒", "🔑", "🛡️", "🔰", "🛡", "🔓", "🗝️"]
            return emojis[line_hash % len(emojis)]

        # Default - expanded emoji pool with variety
        else:
            # Use different default emojis based on line characteristics
            if len(line) > 100:
                long_emojis = ["📋", "📄", "📑", "📰", "📃", "📊", "📈", "📉"]
                return long_emojis[line_hash % len(long_emojis)]
            elif any(char.isdigit() for char in line[:10]):
                number_emojis = ["🔢", "🔟", "1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "📊"]
                return number_emojis[line_hash % len(number_emojis)]
            elif ":" in line and "=" in line:
                config_emojis = ["📝", "⚙️", "🔧", "📋", "📄", "🗂️", "🔨", "🛠️"]
                return config_emojis[line_hash % len(config_emojis)]
            else:
                # Expanded pool of emojis for generic console output
                generic_emojis = [
                    "📋",
                    "📄",
                    "💬",
                    "📝",
                    "🔍",
                    "💡",
                    "📌",
                    "📍",
                    "✨",
                    "⭐",
                    "🌟",
                    "💫",
                    "🎯",
                    "🔮",
                    "🎪",
                    "🎨",
                    "🧩",
                    "🎲",
                    "🎭",
                    "🎬",
                    "🎸",
                    "🎵",
                    "🎶",
                    "🎤",
                    "🚀",
                    "⚡",
                    "🔥",
                    "💥",
                    "🎉",
                    "🎊",
                    "🎁",
                    "🎈",
                    "🌐",
                    "🌍",
                    "🌎",
                    "🌏",
                    "🌙",
                    "⭐",
                    "🌟",
                    "☀️",
                    "💻",
                    "⌨️",
                    "🖥️",
                    "🖱️",
                    "📱",
                    "📲",
                    "💾",
                    "💿",
                    "🔧",
                    "⚙️",
                    "🛠️",
                    "🔨",
                    "⚒️",
                    "🪓",
                    "🔩",
                    "⚡",
                    "🧠",
                    "💭",
                    "🤔",
                    "💡",
                    "🔍",
                    "🔎",
                    "🔬",
                    "📊",
                    "✅",
                    "✔️",
                    "🎯",
                    "🎪",
                    "🎨",
                    "🎭",
                    "🎬",
                    "🎸",
                ]
                # Use line hash for consistent emoji per line type
                return generic_emojis[line_hash % len(generic_emojis)]

    def _memory_status_state(self, status) -> str:
        if getattr(status, "available", False):
            return "ready"
        if not getattr(status, "enabled", True):
            return "disabled"
        if getattr(status, "installed", None) is False:
            return "missing"
        return "missing"

    async def _check_provider_health(self, log: ConversationLog):
        """Check provider health asynchronously."""
        from superqode.providers.health import get_health_checker, ProviderStatus

        log.add_info("Checking provider health...")

        checker = get_health_checker()
        results = await checker.check_all(force=True)

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Provider Health Status\n\n", style=f"bold {THEME['text']}")

        # Group by status
        ready = []
        not_configured = []
        errors = []

        for pid, result in sorted(results.items()):
            if result.status == ProviderStatus.READY:
                ready.append((pid, result))
            elif result.status == ProviderStatus.NOT_CONFIGURED:
                not_configured.append((pid, result))
            else:
                errors.append((pid, result))

        # Ready providers
        if ready:
            t.append(f"  ✓ Ready ({len(ready)})\n", style=f"bold {THEME['success']}")
            for pid, result in ready:
                t.append(f"    {result.status_icon} ", style=THEME["success"])
                t.append(f"{pid}", style=THEME["text"])
                if result.model_available:
                    t.append(f"  {result.model_available}", style=THEME["muted"])
                t.append("\n", style="")
            t.append("\n", style="")

        # Not configured
        if not_configured:
            t.append(f"  ○ Not Configured ({len(not_configured)})\n", style=f"{THEME['dim']}")
            for pid, result in not_configured[:5]:  # Show first 5
                t.append(f"    {result.status_icon} ", style=THEME["dim"])
                t.append(f"{pid}", style=THEME["muted"])
                t.append(f"  {result.message}\n", style=THEME["dim"])
            if len(not_configured) > 5:
                t.append(f"    ... and {len(not_configured) - 5} more\n", style=THEME["dim"])
            t.append("\n", style="")

        # Errors
        if errors:
            t.append(f"  ✗ Errors ({len(errors)})\n", style=f"bold {THEME['error']}")
            for pid, result in errors:
                t.append(f"    {result.status_icon} ", style=THEME["error"])
                t.append(f"{pid}", style=THEME["text"])
                t.append(f"  {result.message}\n", style=THEME["dim"])
            t.append("\n", style="")

        t.append(f"  💡 ", style=THEME["muted"])
        t.append(":connect <provider>", style=THEME["success"])
        t.append(" to connect to a ready provider\n", style=THEME["muted"])

        self._call_ui(log.write, t)

    @staticmethod
    def _parse_serve_args(subargs: str) -> tuple[str, dict]:
        """Parse ``<engine> [--model X] [--port N] [--ctx N] [--host H]``."""
        import shlex

        tokens = shlex.split(subargs)
        engine = tokens[0] if tokens else ""
        opts: dict = {}
        i = 1
        while i < len(tokens):
            tok = tokens[i]
            if tok in ("--model", "-m") and i + 1 < len(tokens):
                opts["model"] = tokens[i + 1]
                i += 2
            elif tok in ("--port", "-p") and i + 1 < len(tokens):
                opts["port"] = int(tokens[i + 1])
                i += 2
            elif tok == "--ctx" and i + 1 < len(tokens):
                opts["ctx"] = int(tokens[i + 1])
                i += 2
            elif tok == "--host" and i + 1 < len(tokens):
                opts["host"] = tokens[i + 1]
                i += 2
            elif tok == "--extra" and i + 1 < len(tokens):
                opts.setdefault("extra_args", []).append(tokens[i + 1])
                i += 2
            elif tok.startswith("--extra="):
                opts.setdefault("extra_args", []).append(tok.split("=", 1)[1])
                i += 1
            elif tok in ("--allow-download", "-y"):
                opts["allow_download"] = True
                i += 1
            else:
                i += 1
        return engine, opts

    @work(exclusive=True)
    async def _install_agent(self, agent_id: str, log: ConversationLog):
        agent = next((a for a in self._agents if a.short_name == agent_id), None)
        if not agent:
            log.add_error(f"Agent '{agent_id}' not found")
            return

        if agent.is_ready:
            log.add_success(f"{agent.icon} {agent.name} is already installed!")
            return

        try:
            from superqode.agents.discovery import get_agent_by_short_name_async

            full = await get_agent_by_short_name_async(agent_id)
            if full and "actions" in full:
                cmd = full.get("actions", {}).get("*", {}).get("install", {}).get("command", "")
                if cmd:
                    t = Text()
                    t.append(
                        f"\n  📦 Install {agent.icon} {agent.name}:\n\n",
                        style=f"bold {THEME['orange']}",
                    )
                    t.append(f"  $ {cmd}\n", style=THEME["success"])
                    log.write(t)
                    return
        except Exception:
            pass

        log.add_info(f"No install command found for {agent.name}")

    def _retry_last_message(self, log: ConversationLog):
        """Retry the last user prompt in the current session."""
        if not self._last_user_message:
            log.add_info("No previous prompt to retry")
            return
        if getattr(self, "is_busy", False):
            log.add_info("Agent is still running. Cancel or wait before retrying.")
            return

        prompt = self._last_user_message
        t = Text()
        t.append("\n  ↻ ", style=f"bold {THEME['cyan']}")
        t.append("Retrying last prompt\n", style=f"bold {THEME['text']}")
        preview = prompt.replace("\n", " ")
        if len(preview) > 120:
            preview = preview[:117] + "..."
        t.append(f"  {preview}\n", style=THEME["muted"])
        log.write(t)
        self._handle_message(prompt, log)
