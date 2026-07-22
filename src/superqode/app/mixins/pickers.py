"""Arrow-key navigation and selection across pickers."""

from __future__ import annotations
from textual import on
from rich.text import Text
from superqode.app.constants import (
    THEME,
)
from superqode.app.widgets import (
    ConversationLog,
)

# --- helpers extracted from app_main (A1) ---
from superqode.app.inputs import SelectionAwareInput


class PickerNavigationMixin:
    """navigate_*/select_highlighted_* actions and number-key selection."""

    @staticmethod
    def _picker_link_style(style: str, number: int) -> str:
        """Add a Textual/Rich link target to a picker style."""
        return f"{style} link superqode://pick/{number}"

    def _select_by_number_universal(self, num: int):
        """Universal number selection handler for all selection modes.

        Handles:
        - Connection type selection (1=ACP, 2=BYOK, 3=LOCAL)
        - BYOK provider selection
        - BYOK model selection
        - Local provider selection
        - Local model selection
        - ACP agent selection
        - OpenCode model selection
        """
        log = self.query_one("#log", ConversationLog)
        # While awaiting typed selection, inject digits into prompt instead of auto-selecting
        if (
            getattr(self, "_awaiting_acp_agent_selection", False)
            or getattr(self, "_awaiting_byok_model", False)
            or getattr(self, "_awaiting_local_model", False)
            or getattr(self, "_awaiting_byok_provider", False)
            or getattr(self, "_awaiting_local_provider", False)
            or getattr(self, "_awaiting_recommendation_selection", False)
            or getattr(self, "_awaiting_codex_model", False)
            or getattr(self, "_awaiting_codex_effort", False)
            or getattr(self, "_awaiting_session_resume", False)
            or getattr(self, "_awaiting_mode_selection", False)
            or getattr(self, "_awaiting_harness_wizard", False)
        ):
            try:
                prompt_input = self.query_one("#prompt-input", SelectionAwareInput)
                if not prompt_input.has_focus:
                    prompt_input.focus()
                cursor = prompt_input.cursor_position
                value = prompt_input.value
                digit = str(num)
                prompt_input.value = f"{value[:cursor]}{digit}{value[cursor:]}"
                prompt_input.cursor_position = cursor + 1
            except Exception:
                pass
            return True

        # 1. Handle connection type selection first (profile-driven)
        if getattr(self, "_awaiting_connect_type", False):
            from superqode.providers.connection_profiles import list_connection_profiles

            profiles = list_connection_profiles()
            if 1 <= num <= len(profiles):
                self._dispatch_connection_profile(profiles[num - 1], log)
                return True
            return False

        # 1b. Handle runtime selection
        if getattr(self, "_awaiting_runtime_selection", False):
            runtimes = getattr(self, "_runtime_selection_list", [])
            if runtimes and 1 <= num <= len(runtimes):
                info = runtimes[num - 1]
                if not info.installed:
                    log.add_error(self._runtime_install_message(info.name, info.install_hint))
                    return True
                if not info.implemented:
                    log.add_error(f"Runtime '{info.name}' is a stub and not yet usable.")
                    return True
                if not info.ready:
                    log.add_error(
                        f"Runtime '{info.name}' is not ready: {info.status_detail or 'check setup'}"
                    )
                    return True
                self._awaiting_runtime_selection = False
                self._runtime_cmd(info.name, log)
                if info.name not in self._SELF_CONTAINED_RUNTIMES:
                    self._show_byok_providers(log)
                return True
            return False

        # 1c. Handle session resume selection
        if getattr(self, "_awaiting_session_resume", False):
            sessions = getattr(self, "_session_resume_list", [])
            if sessions and 1 <= num <= len(sessions):
                self._handle_session_resume_selection(str(num), log)
                return True
            return False

        if getattr(self, "_awaiting_mode_selection", False):
            modes = self._mode_picker_items()
            if 1 <= num <= len(modes):
                self._apply_interaction_mode(modes[num - 1][0], log)
                return True
            return False

        if getattr(self, "_awaiting_harness_selection", False):
            entries = getattr(self, "_harness_selection_list", [])
            if entries and 1 <= num <= len(entries):
                self._harness_highlighted_index = num - 1
                self.action_select_highlighted_harness()
                return True
            return False

        # 2. Handle ACP agent selection
        if getattr(self, "_awaiting_acp_agent_selection", False):
            agent_list = getattr(self, "_acp_agent_list", [])
            if agent_list and 1 <= num <= len(agent_list):
                self._handle_acp_agent_selection(str(num), log)
                return True
            return False

        # 3. Handle BYOK provider selection
        if getattr(self, "_awaiting_byok_provider", False):
            if getattr(self, "_just_showed_byok_picker", False):
                return False
            provider_list = getattr(self, "_byok_connect_list", [])
            if provider_list and 1 <= num <= len(provider_list):
                self._handle_byok_provider_selection(str(num), log)
                return True
            return False

        # 4. Handle BYOK model selection
        if getattr(self, "_awaiting_byok_model", False):
            model_list = getattr(self, "_byok_model_list", [])
            if model_list and 1 <= num <= len(model_list):
                model = model_list[num - 1]
                provider_id = getattr(self, "_byok_selected_provider", None)
                if provider_id:
                    self._awaiting_byok_model = False
                    self._connect_byok_mode(provider_id, model, log)
                    return True
            return False

        # 5. Handle local provider selection
        if getattr(self, "_awaiting_local_provider", False):
            provider_list = getattr(self, "_local_provider_list", [])
            if provider_list and 1 <= num <= len(provider_list):
                self._handle_local_provider_selection(str(num), log)
                return True
            return False

        # 6. Handle local model selection
        if getattr(self, "_awaiting_local_model", False):
            model_list = getattr(self, "_local_model_list", [])
            if model_list and 1 <= num <= len(model_list):
                self._handle_local_model_selection(str(num), log)
                return True
            return False

        # 7. Handle OpenCode/other model selection (original behavior)
        if getattr(self, "_awaiting_codex_model", False):
            return self._handle_codex_model_selection(str(num), log)

        if getattr(self, "_awaiting_codex_effort", False):
            return self._handle_codex_effort_selection(str(num), log)

        if self._awaiting_model_selection:
            self._select_model_by_number(num)
            return True

        return False

    def _select_picker_number_direct(self, num: int) -> bool:
        """Select a picker item directly from a mouse click.

        Typed numeric keys are intentionally buffered for provider/model pickers so
        users can enter multi-digit indexes. Mouse clicks already carry the exact
        target number, so they should execute the selection immediately.
        """
        log = self.query_one("#log", ConversationLog)

        if getattr(self, "_awaiting_connect_type", False):
            return bool(self._select_by_number_universal(num))

        if getattr(self, "_awaiting_acp_agent_selection", False):
            agent_list = getattr(self, "_acp_agent_list", [])
            if agent_list and 1 <= num <= len(agent_list):
                self._handle_acp_agent_selection(str(num), log)
                return True
            return False

        if getattr(self, "_awaiting_byok_provider", False):
            provider_list = getattr(self, "_byok_connect_list", [])
            if provider_list and 1 <= num <= len(provider_list):
                self._just_showed_byok_picker = False
                self._handle_byok_provider_selection(str(num), log)
                return True
            return False

        if getattr(self, "_awaiting_byok_model", False):
            model_list = getattr(self, "_byok_model_list", [])
            if model_list and 1 <= num <= len(model_list):
                self._handle_byok_model_selection(str(num), log)
                return True
            return False

        if getattr(self, "_awaiting_local_provider", False):
            provider_list = getattr(self, "_local_provider_list", [])
            if provider_list and 1 <= num <= len(provider_list):
                self._just_showed_local_picker = False
                self._handle_local_provider_selection(str(num), log)
                return True
            return False

        if getattr(self, "_awaiting_local_model", False):
            model_list = getattr(self, "_local_model_list", [])
            if model_list and 1 <= num <= len(model_list):
                self._handle_local_model_selection(str(num), log)
                return True
            return False

        if getattr(self, "_awaiting_codex_model", False):
            return self._handle_codex_model_selection(str(num), log)

        if getattr(self, "_awaiting_codex_effort", False):
            return self._handle_codex_effort_selection(str(num), log)

        if getattr(self, "_awaiting_session_resume", False):
            sessions = getattr(self, "_session_resume_list", [])
            if sessions and 1 <= num <= len(sessions):
                self._handle_session_resume_selection(str(num), log)
                return True
            return False

        if getattr(self, "_awaiting_mode_selection", False):
            modes = self._mode_picker_items()
            if 1 <= num <= len(modes):
                self._apply_interaction_mode(modes[num - 1][0], log)
                return True
            return False

        if getattr(self, "_awaiting_harness_selection", False):
            entries = getattr(self, "_harness_selection_list", [])
            if entries and 1 <= num <= len(entries):
                self._harness_highlighted_index = num - 1
                self.action_select_highlighted_harness()
                return True
            return False

        if getattr(self, "_awaiting_model_selection", False):
            self._select_model_by_number(num)
            return True

        if getattr(self, "_awaiting_recommendation_selection", False):
            self._handle_recommendation_selection(str(num), log)
            return True

        return bool(self._select_by_number_universal(num))

    def _scroll_to_highlighted_item(
        self, log: ConversationLog, highlighted_idx: int, total_items: int
    ):
        """Scroll the log to keep the highlighted item visible.

        Prefer the actual rendered selection row so wrapped descriptions and a
        short terminal viewport cannot hide the item. The geometry fallback is
        retained for pickers that do not render a ``SELECTED`` marker.
        """
        if self._scroll_to_rendered_selected_block(log):
            self._schedule_picker_visibility(log, highlighted_idx, total_items)
            return

        try:
            # Disable follow-mode only around our own managed scroll, then
            # restore it: leaving it off made every later feedback write
            # (errors, setup guidance) land invisibly below the fold.
            log.auto_scroll = False
            visible_height = max(
                6,
                int(
                    getattr(getattr(log, "scrollable_content_region", None), "height", 0)
                    or getattr(getattr(log, "size", None), "height", 18)
                    or 18
                ),
            )
            lines_per_item = 3
            header_lines = 5
            highlighted_y = header_lines + highlighted_idx * lines_per_item
            target_y = max(0, highlighted_y - max(1, visible_height // 2))
            log.scroll_to(y=target_y, animate=False)
        except Exception:
            pass  # If scrolling fails, just continue
        finally:
            log.auto_scroll = True
        self._schedule_picker_visibility(log, highlighted_idx, total_items)

    def _schedule_picker_visibility(
        self, log: ConversationLog, highlighted_idx: int, total_items: int
    ) -> None:
        """Repeat managed scrolling after Textual has completed layout."""

        def reveal() -> None:
            if self._scroll_to_rendered_selected_block(log):
                return
            try:
                log.auto_scroll = False
                visible_height = max(
                    6,
                    int(getattr(getattr(log, "size", None), "height", 18) or 18),
                )
                selected_y = 5 + highlighted_idx * 3
                log.scroll_to(y=max(0, selected_y - max(1, visible_height // 2)), animate=False)
            except Exception:
                pass
            finally:
                log.auto_scroll = True

        try:
            self.call_after_refresh(reveal)
        except Exception:
            try:
                self.set_timer(0.01, reveal)
            except Exception:
                pass

    def action_navigate_provider_up(self):
        """Navigate to previous provider (arrow up)."""
        if not getattr(self, "_awaiting_byok_provider", False):
            return

        provider_list = getattr(self, "_byok_connect_list", [])
        if not provider_list:
            return

        current_idx = getattr(self, "_byok_highlighted_provider_index", 0)
        new_idx = max(0, current_idx - 1)
        if new_idx != current_idx:
            self._byok_highlighted_provider_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._show_byok_providers(log, clear_log=False)
            # Scroll to keep highlighted item visible
            self._scroll_to_highlighted_item(log, new_idx, len(provider_list))
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_provider_down(self):
        """Navigate to next provider (arrow down)."""
        if not getattr(self, "_awaiting_byok_provider", False):
            return

        provider_list = getattr(self, "_byok_connect_list", [])
        if not provider_list:
            return

        current_idx = getattr(self, "_byok_highlighted_provider_index", 0)
        new_idx = min(len(provider_list) - 1, current_idx + 1)
        if new_idx != current_idx:
            self._byok_highlighted_provider_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._show_byok_providers(log, clear_log=False)
            # Scroll to keep highlighted item visible
            self._scroll_to_highlighted_item(log, new_idx, len(provider_list))
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_select_highlighted_provider(self):
        """Select the currently highlighted provider (Enter key)."""
        if not getattr(self, "_awaiting_byok_provider", False):
            return

        provider_list = getattr(self, "_byok_connect_list", [])
        if not provider_list:
            return

        current_idx = getattr(self, "_byok_highlighted_provider_index", 0)
        if 0 <= current_idx < len(provider_list):
            provider_id, provider_def = provider_list[current_idx]
            log = self.query_one("#log", ConversationLog)
            self._awaiting_byok_provider = False
            # Reset model highlight index when entering a new provider
            self._byok_highlighted_model_index = 0
            self._show_provider_models(provider_id, log, use_picker=False)

    def _show_runtime_picker(self, log: ConversationLog, clear_log: bool = True):
        """Show interactive runtime picker with highlighting and status."""
        from superqode.runtime import list_runtimes, resolve_runtime_name

        self._awaiting_byok_provider = False
        self._awaiting_connect_type = False

        runtimes = list_runtimes()
        highlighted_idx = getattr(self, "_runtime_highlighted_index", 0)
        if not (0 <= highlighted_idx < len(runtimes)):
            highlighted_idx = 0

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Select Runtime\n\n", style=f"bold {THEME['text']}")

        current = resolve_runtime_name()
        for i, info in enumerate(runtimes):
            num = i + 1
            is_active = info.name == current
            is_highlighted = i == highlighted_idx

            if info.usable:
                status = "ready"
                status_color = THEME["success"]
            elif not info.installed:
                status = "needs setup"
                status_color = THEME["warning"]
            elif not info.ready:
                status = "not ready"
                status_color = THEME["warning"]
            else:
                status = "stub"
                status_color = THEME["warning"]

            line = Text()
            if is_highlighted:
                line.append("  ▶ ", style=f"bold {THEME['success']}")
                line.append(
                    f"[{num}] ",
                    style=self._picker_link_style(f"bold {THEME['success']}", num),
                )
                label_style = f"bold {THEME['success']}"
                line.append(info.name, style=label_style)
                if is_active:
                    line.append("  ◀ active\n", style=f"bold {THEME['success']}")
                else:
                    line.append("\n", style="")
            else:
                line.append(f"    [{num}] ", style=self._picker_link_style(THEME["dim"], num))
                line.append(info.name, style=f"bold {THEME['text']}")
                if is_active:
                    line.append("  ◀ active\n", style=THEME["muted"])
                else:
                    line.append("\n", style="")
            line.append(f"        {info.description}\n", style=THEME["muted"])
            line.append("        ", style="")
            line.append(status, style=status_color)
            line.append("\n\n", style="")
            t.append(line)

        t.append("  💡 ", style=THEME["muted"])
        t.append("↑↓", style=THEME["cyan"])
        t.append(" navigate  ", style=THEME["dim"])
        t.append("Enter", style=THEME["cyan"])
        t.append(" select  •  or type a number, e.g. ", style=THEME["dim"])
        t.append("2", style=THEME["cyan"])
        t.append("\n", style="")

        if clear_log:
            log.clear()
            log.auto_scroll = False
            log.write(t)
            log.scroll_home(animate=False)
            log.auto_scroll = True
        else:
            log.auto_scroll = False
            log.clear()
            log.write(t)
            log.auto_scroll = True

        self._awaiting_runtime_selection = True
        self._runtime_highlighted_index = highlighted_idx
        self._runtime_selection_list = runtimes
        self._scroll_to_highlighted_item(log, highlighted_idx, len(runtimes))
        self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_runtime_up(self):
        """Navigate to previous runtime (arrow up)."""
        if not getattr(self, "_awaiting_runtime_selection", False):
            return
        runtimes = getattr(self, "_runtime_selection_list", [])
        if not runtimes:
            return
        current_idx = getattr(self, "_runtime_highlighted_index", 0)
        new_idx = max(0, current_idx - 1)
        if new_idx != current_idx:
            self._runtime_highlighted_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._show_runtime_picker(log, clear_log=False)
            self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_runtime_down(self):
        """Navigate to next runtime (arrow down)."""
        if not getattr(self, "_awaiting_runtime_selection", False):
            return
        runtimes = getattr(self, "_runtime_selection_list", [])
        if not runtimes:
            return
        current_idx = getattr(self, "_runtime_highlighted_index", 0)
        new_idx = min(len(runtimes) - 1, current_idx + 1)
        if new_idx != current_idx:
            self._runtime_highlighted_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._show_runtime_picker(log, clear_log=False)
            self.set_timer(0.05, self._ensure_input_focus)

    def action_select_highlighted_runtime(self):
        """Select the currently highlighted runtime (Enter key)."""
        if not getattr(self, "_awaiting_runtime_selection", False):
            return
        runtimes = getattr(self, "_runtime_selection_list", [])
        if not runtimes:
            return
        idx = getattr(self, "_runtime_highlighted_index", 0)
        if not (0 <= idx < len(runtimes)):
            idx = 0
        info = runtimes[idx]
        if not info.installed:
            log = self.query_one("#log", ConversationLog)
            log.add_error(self._runtime_install_message(info.name, info.install_hint))
            return
        if not info.implemented:
            log = self.query_one("#log", ConversationLog)
            log.add_error(f"Runtime '{info.name}' is a stub and not yet usable.")
            return
        if not info.ready:
            log = self.query_one("#log", ConversationLog)
            log.add_error(
                f"Runtime '{info.name}' is not ready: {info.status_detail or 'check setup'}"
            )
            return
        self._awaiting_runtime_selection = False
        log = self.query_one("#log", ConversationLog)
        self._runtime_cmd(info.name, log)
        # Non-self-contained runtimes need a provider to connect; show the
        # BYOK provider picker so users can complete the connection.
        if info.name not in self._SELF_CONTAINED_RUNTIMES:
            self._show_byok_providers(log)

    def action_navigate_acp_agent_up(self):
        """Navigate to previous ACP agent (arrow up)."""
        if not getattr(self, "_awaiting_acp_agent_selection", False):
            return

        agent_list = getattr(self, "_acp_agent_list", [])
        if not agent_list:
            return

        current_idx = getattr(self, "_acp_highlighted_agent_index", 0)
        new_idx = max(0, current_idx - 1)
        if new_idx != current_idx:
            self._acp_highlighted_agent_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._show_agents(log, clear_log=False)
            self._scroll_to_highlighted_item(log, new_idx, len(agent_list))
            self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_acp_agent_down(self):
        """Navigate to next ACP agent (arrow down)."""
        if not getattr(self, "_awaiting_acp_agent_selection", False):
            return

        agent_list = getattr(self, "_acp_agent_list", [])
        if not agent_list:
            return

        current_idx = getattr(self, "_acp_highlighted_agent_index", 0)
        new_idx = min(len(agent_list) - 1, current_idx + 1)
        if new_idx != current_idx:
            self._acp_highlighted_agent_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._show_agents(log, clear_log=False)
            self._scroll_to_highlighted_item(log, new_idx, len(agent_list))
            self.set_timer(0.05, self._ensure_input_focus)

    def action_select_highlighted_acp_agent(self):
        """Select the currently highlighted ACP agent (Enter key)."""
        if not getattr(self, "_awaiting_acp_agent_selection", False):
            return

        agent_list = getattr(self, "_acp_agent_list", [])
        if not agent_list:
            return

        current_idx = getattr(self, "_acp_highlighted_agent_index", 0)
        if 0 <= current_idx < len(agent_list):
            agent_id, agent_data = agent_list[current_idx]
            log = self.query_one("#log", ConversationLog)
            self._awaiting_acp_agent_selection = False

            # Check if agent is installed
            from superqode.commands.acp import check_agent_installed

            is_installed = check_agent_installed(agent_data)

            if is_installed:
                # Connect to the agent
                self._announce_transition(
                    title="Connecting",
                    primary=agent_data["name"],
                    detail="Starting ACP session",
                    severity="information",
                    log=log,
                    persist=False,
                    timeout=2.5,
                    dedupe_key=f"agent-connecting:{agent_data['short_name']}",
                )
                self._connect_agent(agent_data["short_name"])
            else:
                from superqode.agents.registry import get_agent_installation_info

                install_info = get_agent_installation_info(agent_data)
                install_cmd = install_info.get("command", "")
                guidance = (
                    f"Install with: {install_cmd}"
                    if install_cmd
                    else f"Run :acp install {agent_data['short_name']}."
                )
                self._announce_transition(
                    title="Agent not installed",
                    primary=agent_data["name"],
                    detail="The ACP launcher is not available",
                    severity="warning",
                    log=log,
                    guidance=guidance,
                    dedupe_key=f"agent-missing:{agent_data['short_name']}",
                )

    def _show_session_resume_picker(self, log: ConversationLog, clear_log: bool = True) -> None:
        """Show a keyboard-navigable picker for resuming local sessions."""
        manager = self._get_session_manager()
        sessions = manager.list_all_sessions()[:12]

        self._awaiting_session_resume = bool(sessions)
        self._session_resume_list = sessions
        if not hasattr(self, "_session_resume_highlighted_index"):
            self._session_resume_highlighted_index = 0
        self._session_resume_highlighted_index = min(
            max(0, getattr(self, "_session_resume_highlighted_index", 0)),
            max(0, len(sessions) - 1),
        )

        t = Text()
        t.append("\n  📂 ", style=f"bold {THEME['purple']}")
        t.append("Switch Sessions\n", style=f"bold {THEME['text']}")
        t.append(
            "  Resuming a session restores its harness, model, and conversation history.\n\n",
            style=THEME["muted"],
        )

        if not sessions:
            t.append("  No sessions found yet.\n", style=THEME["muted"])
            t.append("  Start a conversation with ", style=THEME["muted"])
            t.append(":connect byok", style=THEME["cyan"])
            t.append(" or ", style=THEME["muted"])
            t.append(":connect local", style=THEME["cyan"])
            t.append(".\n", style=THEME["muted"])
            self._show_command_output(log, t, clear_log=clear_log)
            return

        for idx, session in enumerate(sessions, 1):
            highlighted = (idx - 1) == self._session_resume_highlighted_index
            display_id = session.session_id[:8]
            provider = session.provider or "-"
            model = session.model or "unknown"
            harness = session.harness_id or "workbench"
            route = f"{provider}/{model}"
            title = session.title or "(unnamed)"
            if highlighted:
                t.append("  ▶ ", style=f"bold {THEME['success']}")
                t.append(
                    f"[{idx:2}] ",
                    style=self._picker_link_style(f"bold {THEME['success']}", idx),
                )
                style = f"bold {THEME['success']}"
            else:
                t.append("    ", style="")
                t.append(f"[{idx:2}] ", style=self._picker_link_style(THEME["dim"], idx))
                style = THEME["text"]
            id_style = f"bold {THEME['cyan']}" if not highlighted else style
            count_style = THEME["muted"] if not highlighted else style
            title_style = THEME["dim"] if not highlighted else style
            t.append(f"{display_id:<10}", style=id_style)
            t.append(f"{harness[:17]:<19}", style=THEME["purple"] if not highlighted else style)
            t.append(f"{route[:27]:<29}", style=style)
            t.append(f"{session.message_count:>3} msgs  ", style=count_style)
            t.append(f"{title[:28]}\n", style=title_style)

        t.append("\n  ↑↓ navigate  Enter resume  or type ", style=THEME["muted"])
        t.append(":sessions switch <id>", style=THEME["cyan"])
        t.append("\n", style=THEME["muted"])
        self._show_command_output(log, t, clear_log=clear_log)
        self._scroll_to_highlighted_item(log, self._session_resume_highlighted_index, len(sessions))
        self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_session_resume_up(self) -> None:
        """Navigate to previous resumable session."""
        if not getattr(self, "_awaiting_session_resume", False):
            return
        sessions = getattr(self, "_session_resume_list", [])
        if not sessions:
            return
        current = getattr(self, "_session_resume_highlighted_index", 0)
        new_idx = max(0, current - 1)
        if new_idx != current:
            self._session_resume_highlighted_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._show_session_resume_picker(log, clear_log=False)

    def action_navigate_session_resume_down(self) -> None:
        """Navigate to next resumable session."""
        if not getattr(self, "_awaiting_session_resume", False):
            return
        sessions = getattr(self, "_session_resume_list", [])
        if not sessions:
            return
        current = getattr(self, "_session_resume_highlighted_index", 0)
        new_idx = min(len(sessions) - 1, current + 1)
        if new_idx != current:
            self._session_resume_highlighted_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._show_session_resume_picker(log, clear_log=False)

    def action_select_highlighted_session_resume(self) -> None:
        """Resume the highlighted session."""
        if not getattr(self, "_awaiting_session_resume", False):
            return
        sessions = getattr(self, "_session_resume_list", [])
        if not sessions:
            return
        idx = getattr(self, "_session_resume_highlighted_index", 0)
        if 0 <= idx < len(sessions):
            log = self.query_one("#log", ConversationLog)
            self._handle_resume_session(sessions[idx].session_id, log)

    def _mode_picker_items(self) -> list[tuple[str, str, str]]:
        return [
            ("chat", "Chat", "Local/BYOK direct model chat. ACP agents use Build/Plan."),
            ("build", "Build", "Repo-aware coding harness with tools."),
            ("plan", "Plan", "Reason first. No native tools until approved."),
        ]

    def _show_mode_picker(self, log: ConversationLog, clear_log: bool = True) -> None:
        """Show a keyboard-navigable Chat/Build/Plan switcher."""
        modes = self._mode_picker_items()
        current = self._current_interaction_mode_name()
        if not hasattr(self, "_mode_highlighted_index"):
            self._mode_highlighted_index = next(
                (idx for idx, item in enumerate(modes) if item[0] == current), 1
            )
        self._mode_highlighted_index = min(
            max(0, getattr(self, "_mode_highlighted_index", 0)), len(modes) - 1
        )

        t = Text()
        t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Mode Switcher\n\n", style=f"bold {THEME['text']}")
        for idx, (mode, label, description) in enumerate(modes, 1):
            selected = mode == current
            highlighted = idx - 1 == self._mode_highlighted_index
            marker = "▶ " if highlighted else "  "
            style = f"bold {THEME['success']}" if highlighted else f"bold {THEME['cyan']}"
            t.append(f"  {marker}", style=f"bold {THEME['success']}")
            t.append(f"[{idx}] ", style=self._picker_link_style(THEME["dim"], idx))
            t.append(label.upper(), style=style)
            if selected:
                t.append("  active", style=f"bold {THEME['success']}")
            t.append("\n      ", style="")
            t.append(description, style=THEME["muted"])
            t.append("\n", style="")
        t.append("\n  Use ", style=THEME["muted"])
        t.append("↑↓ Enter", style=f"bold {THEME['cyan']}")
        t.append(" or type ", style=THEME["muted"])
        t.append(":mode chat", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":mode build", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":mode plan", style=THEME["cyan"])
        t.append(".\n", style="")

        self._awaiting_mode_selection = True
        if clear_log:
            log.clear()
        log.write(t)
        self._scroll_to_highlighted_item(log, self._mode_highlighted_index, len(modes))
        self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_mode_up(self) -> None:
        if not getattr(self, "_awaiting_mode_selection", False):
            return
        self._mode_highlighted_index = max(0, getattr(self, "_mode_highlighted_index", 0) - 1)
        log = self.query_one("#log", ConversationLog)
        self._show_mode_picker(log, clear_log=True)

    def action_navigate_mode_down(self) -> None:
        if not getattr(self, "_awaiting_mode_selection", False):
            return
        modes = self._mode_picker_items()
        self._mode_highlighted_index = min(
            len(modes) - 1, getattr(self, "_mode_highlighted_index", 0) + 1
        )
        log = self.query_one("#log", ConversationLog)
        self._show_mode_picker(log, clear_log=True)

    def action_select_highlighted_mode(self) -> None:
        if not getattr(self, "_awaiting_mode_selection", False):
            return
        modes = self._mode_picker_items()
        idx = min(max(0, getattr(self, "_mode_highlighted_index", 0)), len(modes) - 1)
        log = self.query_one("#log", ConversationLog)
        self._apply_interaction_mode(modes[idx][0], log)

    def _setup_picker_handlers(self, picker, provider_id: str, log: ConversationLog):
        """Set up picker message handlers."""
        from superqode.widgets.model_picker import ModelPickerWidget

        @on(picker, ModelPickerWidget.ModelSelected)
        def on_model_selected(event: ModelPickerWidget.ModelSelected) -> None:
            """Handle model selection from picker."""
            self._awaiting_byok_model = False
            self._connect_byok_mode(provider_id, event.model_id, log)
            try:
                picker.remove()
            except Exception:
                pass

        @on(picker, ModelPickerWidget.Cancelled)
        def on_picker_cancelled(event: ModelPickerWidget.Cancelled) -> None:
            """Handle picker cancellation."""
            self._awaiting_byok_model = False
            try:
                picker.remove()
            except Exception:
                pass
