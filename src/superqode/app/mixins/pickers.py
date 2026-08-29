"""Arrow-key navigation and selection across pickers."""

from __future__ import annotations

import re
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
    def _picker_link_style(style: str, number: int, *, handle: bool = False) -> str:
        """Return a picker span style without an OSC-8 hyperlink.

        Terminals treat ``link superqode://pick/N`` as a real URL and pop a
        ⌘-click tooltip over the list. Clicks still select the row: they are
        resolved from the ``[n]`` header in ``_click_selects_picker_row``.
        The ↗ is the only “this is clickable” mark.
        """
        del number, handle
        return f"{style} not underline"

    def _append_picker_dot(self, target: Text, number: int, *, highlighted: bool) -> None:
        """Write the click dot that opens a row.

        Rows are clickable across their whole width, but a target you can aim
        at beats one you have to discover. The dot sits in a fixed column so
        the list reads as a column of buttons.
        """
        style = self._picker_link_style(
            f"bold {THEME['success']}" if highlighted else THEME["cyan"], number
        )
        target.append("● " if highlighted else "○ ", style=style)

    def _append_picker_arrow(self, target: Text, number: int) -> None:
        """Write the open-this-row arrow that closes a picker line.

        A dot in the left margin reads as a bullet, not a button. The arrow
        sits where the eye finishes the label, points away from the text, and
        is the one span coloured strongly enough to be found by a mouse user
        scanning for something to click.
        """
        target.append(" ↗", style=self._picker_link_style(f"bold {THEME['purple']}", number))

    @staticmethod
    def _picker_content_width(log: object) -> int:
        """Columns a picker row actually gets.

        The log is narrower than the terminal once a scrollbar or sidebar is in
        play. ``content_size`` excludes padding, border and scrollbar; the
        terminal is the fallback before layout.
        """
        for attr in ("content_size", "size"):
            width = getattr(getattr(log, attr, None), "width", 0) or 0
            if width > 0:
                return int(width)
        import shutil

        return shutil.get_terminal_size().columns

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
        # While awaiting typed selection, inject digits into prompt instead of
        # auto-selecting. A mouse click is exempt: it names the row outright.
        if not getattr(self, "_direct_pick", False) and (
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
            profiles = self._connect_menu_profiles()
            if 1 <= num <= len(profiles):
                self._dispatch_connection_profile(profiles[num - 1], log)
                return True
            return False

        # 1a-i. The build-your-own pickers, driven by number like the rest.
        if getattr(self, "_awaiting_harness_preset", False):
            presets = getattr(self, "_harness_preset_list", [])
            if presets and 1 <= num <= len(presets):
                log.clear()
                self._clone_harness_preset(num - 1, log)
                return True
            return False

        if getattr(self, "_awaiting_harness_import", False):
            found = getattr(self, "_harness_import_list", [])
            if found and 1 <= num <= len(found):
                log.clear()
                self._import_harness_selection(num - 1, log)
                return True
            return False

        if getattr(self, "_awaiting_explore", False):
            capabilities = getattr(self, "_explore_capabilities", [])
            if capabilities and 1 <= num <= len(capabilities):
                self._explore_index = num - 1
                self.action_toggle_explore_row()
                return True
            return False

        # 1a. A registry-driven prompt sits on top of whatever opened it, so it
        # claims the number keys. Handled generically: every prompt registered
        # in the stack gets number selection without another branch here.
        if self._prompts.active is not None:
            if self._prompts.select_index(num - 1):
                return True
            return False

        # 1b. Handle runtime selection
        if getattr(self, "_awaiting_runtime_selection", False):
            runtimes = getattr(self, "_runtime_selection_list", [])
            if runtimes and 1 <= num <= len(runtimes):
                info = runtimes[num - 1]
                if not info.installed:
                    if not self._show_dependency_install_picker(info.name, log):
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

    #: Every flag that means "a numbered list is on screen awaiting a choice".
    _PICKER_AWAITING_FLAGS = (
        "_awaiting_connect_type",
        "_awaiting_acp_agent_selection",
        "_awaiting_byok_provider",
        "_awaiting_byok_model",
        "_awaiting_local_provider",
        "_awaiting_local_model",
        "_awaiting_codex_model",
        "_awaiting_codex_effort",
        "_awaiting_session_resume",
        "_awaiting_mode_selection",
        "_awaiting_harness_selection",
        "_awaiting_runtime_selection",
        "_awaiting_recommendation_selection",
        "_awaiting_harness_wizard",
    )

    #: A row opens with an optional marker, then its bracketed number.
    _PICKER_ROW = re.compile(r"^\s*[▶●○]?\s*\[\s*(\d+)\s*\]")

    #: How far above a clicked line to look for the row it belongs to. A
    #: description wraps to a handful of lines at most; scanning further would
    #: start claiming clicks on unrelated chrome.
    _PICKER_ROW_LOOKBACK = 8

    def _click_selects_picker_row(self, event) -> bool:
        """Resolve a click anywhere on a row to that row's number.

        Only the header line carries a link, so a click on the description
        beneath it resolves by walking up to the nearest ``[n]`` line. That
        keeps the whole row clickable without painting link styling across the
        prose, which terminals underline and recolour.
        """
        if not any(getattr(self, flag, False) for flag in self._PICKER_AWAITING_FLAGS):
            return False
        try:
            log = self.query_one("#log", ConversationLog)
            offset = event.screen_offset - log.region.offset
            index = offset.y + int(log.scroll_offset.y)
            lines = log.lines
            if not (0 <= index < len(lines)):
                return False
        except Exception:  # noqa: BLE001 - a stray click must never raise
            return False

        if getattr(self, "_awaiting_connect_type", False):
            try:
                header = "".join(segment.text for segment in lines[index])
            except Exception:  # noqa: BLE001
                header = ""
            if "Detected" in header:
                activate = getattr(self, "_activate_detected_chip", None)
                hits = getattr(self, "_connect_chip_hits", None) or []
                if callable(activate) and hits:
                    column = int(getattr(offset, "x", -1))
                    for start, end, chip in hits:
                        if start <= column < end:
                            return bool(activate(chip))
                    if len(hits) == 1:
                        return bool(activate(hits[0][2]))
                return False

        for cursor in range(index, max(-1, index - self._PICKER_ROW_LOOKBACK), -1):
            try:
                text = "".join(segment.text for segment in lines[cursor])
            except Exception:  # noqa: BLE001 - a stray click must never raise
                return False
            match = self._PICKER_ROW.match(text)
            if match:
                return self._select_picker_number_direct(int(match.group(1)))
            if cursor != index and not text.strip():
                # A blank line ends the row: past it lies a different one.
                return False
        return False

    def _select_picker_number_direct(self, num: int) -> bool:
        """Select a picker item directly from a mouse click.

        Typed numeric keys are intentionally buffered for provider/model pickers so
        users can enter multi-digit indexes. Mouse clicks already carry the exact
        target number, so they should execute the selection immediately.
        """
        log = self.query_one("#log", ConversationLog)

        # Screens without an explicit branch below fall through to
        # _select_by_number_universal, whose first branch buffers digits into
        # the prompt so multi-digit indexes can be typed. A click is not
        # typing: it carries the exact target already, and buffering it put
        # "1" and "2" in the prompt box instead of selecting anything.
        self._direct_pick = True
        try:
            return self._select_picker_number_resolved(num, log)
        finally:
            self._direct_pick = False

    def _select_picker_number_resolved(self, num: int, log) -> bool:
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

    def _show_agent_install_picker(
        self,
        agent_data: dict,
        log: ConversationLog,
        *,
        reset_highlight: bool = True,
    ) -> bool:
        """Show manual setup for a missing external ACP agent.

        This connection flow never runs vendor package-manager or shell
        installers. Its automatic install picker is reserved for allow-listed
        ``superqode[...]`` Python extras required by SuperQode's own runtimes.
        """
        from superqode.agents.install_commands import classify_install_command
        from superqode.agents.registry import get_agent_installation_info
        from superqode.app.prompt_stack import PromptSpec

        raw = str((get_agent_installation_info(agent_data) or {}).get("command", "") or "")
        install = classify_install_command(raw)
        if not install.raw:
            return False

        short_name = str(agent_data.get("short_name") or "")
        name = str(agent_data.get("name") or short_name)

        options: list[tuple[str, str, str]] = [
            ("manual", "I will install it myself", "show the vendor command and go back"),
            ("cancel", "Cancel", "return to the connection screen"),
        ]

        if reset_highlight and not self._prompts.is_active("agent_install"):
            self._prompts.push(
                PromptSpec(
                    name="agent_install",
                    kind="picker",
                    options=lambda: list(options),
                    on_select=lambda option: self._apply_agent_install_choice(
                        option[0], agent_data=agent_data, install=install
                    ),
                    on_cancel=lambda: self._show_connect_type_picker(
                        self.query_one("#log", ConversationLog)
                    ),
                    render=self._rerender_agent_install_picker,
                    data={"agent": agent_data, "install": install, "options": options},
                )
            )

        highlighted = self._prompts.index
        t = Text()
        t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append(f"{name} is not installed\n\n", style=f"bold {THEME['text']}")
        t.append(f"    {install.raw}\n\n", style=THEME["cyan"])
        if install.reason:
            t.append(f"    {install.reason}\n\n", style=THEME["warning"])
        elif install.runnable:
            t.append(
                "    External agent installers are manual-only in this flow; "
                "SuperQode only auto-installs its own optional Python extras.\n\n",
                style=THEME["warning"],
            )

        for index, (_key, label, description) in enumerate(options):
            num = index + 1
            if index == highlighted:
                t.append("  ▶ ", style=f"bold {THEME['success']}")
                t.append(
                    f"[{num}] ", style=self._picker_link_style(f"bold {THEME['success']}", num)
                )
                t.append(label, style=f"bold {THEME['success']}")
            else:
                t.append(f"    [{num}] ", style=self._picker_link_style(THEME["dim"], num))
                t.append(label, style=f"bold {THEME['text']}")
            t.append("\n", style="")
            t.append(f"        {description}\n", style=THEME["muted"])

        t.append("\n  💡 ", style=THEME["muted"])
        t.append("↑↓", style=THEME["cyan"])
        t.append(" navigate  ", style=THEME["dim"])
        t.append("Enter", style=THEME["cyan"])
        t.append(" select  •  or type a number\n", style=THEME["dim"])

        log.auto_scroll = False
        log.clear()
        log.write(t)
        log.auto_scroll = True
        self.set_timer(0.05, self._ensure_input_focus)
        return True

    def _rerender_agent_install_picker(self) -> None:
        """Redraw the agent install prompt after a navigation key."""
        spec = self._prompts.active
        if spec is None or spec.name != "agent_install":
            return
        log = self.query_one("#log", ConversationLog)
        self._show_agent_install_picker(
            dict(spec.data.get("agent") or {}), log, reset_highlight=False
        )

    def _show_vendor_model_picker(
        self,
        log: ConversationLog,
        *,
        title: str,
        entries: list[tuple[str, str]],
        on_choose,
        current: str = "",
        retry_hint: str = "",
        reset_highlight: bool = True,
    ) -> bool:
        """Make a vendor's model list selectable with the keyboard.

        Every vendor runtime listed its models as plain text, leaving the user
        to retype an id. ``entries`` are ``(model_id, label)`` pairs; the id is
        what gets chosen, the label is what is shown.

        Returns False when there is nothing to offer, so callers can fall back
        to their previous output rather than showing an empty picker.
        """
        from superqode.app.prompt_stack import PromptSpec

        entries = [(str(mid), str(label or mid)) for mid, label in entries if str(mid or label)]
        if not entries:
            return False

        if reset_highlight and not self._prompts.is_active("vendor_model"):
            self._prompts.push(
                PromptSpec(
                    name="vendor_model",
                    kind="picker",
                    options=lambda: list(entries),
                    on_select=lambda entry: on_choose(entry[0]),
                    on_cancel=lambda: log.add_info(
                        f"Model selection cancelled.{' ' + retry_hint if retry_hint else ''}"
                    ),
                    render=self._rerender_vendor_model_picker,
                    data={
                        "title": title,
                        "entries": entries,
                        "on_choose": on_choose,
                        "current": current,
                        "retry_hint": retry_hint,
                    },
                )
            )

        highlighted = self._prompts.index
        # Vendors with a handful of models fit on one screen; a catalog like
        # Prime Agent's does not. Numbers are right-aligned so the rows stay a
        # column, and the highlighted row is scrolled back into view below.
        number_width = len(str(len(entries)))
        t = Text()
        t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append(f"{title}", style=f"bold {THEME['text']}")
        t.append(f"   {len(entries)} models\n\n", style=THEME["muted"])
        for index, (model_id, label) in enumerate(entries):
            num = index + 1
            is_highlighted = index == highlighted
            # The whole row is the click target, not just the number. A mouse
            # user aims at the name they are reading.
            style = f"bold {THEME['success']}" if is_highlighted else THEME["dim"]
            link = self._picker_link_style(style, num)
            handle = self._picker_link_style(
                f"bold {THEME['success']}" if is_highlighted else f"bold {THEME['text']}",
                num,
                handle=True,
            )
            t.append("  ", style="")
            self._append_picker_dot(t, num, highlighted=is_highlighted)
            t.append(f"[{num:>{number_width}}] ", style=link)
            t.append(label, style=handle)
            # Show the id only when it adds information beyond the label.
            if model_id and model_id != label and model_id not in label:
                t.append(f"  {model_id}", style=THEME["muted"])
            if current and model_id == current:
                t.append("  ◀ active", style=THEME["muted"])
            if is_highlighted:
                self._append_picker_arrow(t, num)
            t.append("\n", style="")
        t.append("\n  💡 ", style=THEME["muted"])
        t.append("↑↓", style=THEME["cyan"])
        t.append(" navigate  ", style=THEME["dim"])
        t.append("Enter", style=THEME["cyan"])
        t.append(" select  •  click a row  •  or type a number\n", style=THEME["dim"])

        log.auto_scroll = False
        log.clear()
        log.write(t)
        log.auto_scroll = True
        # Without this the highlight walks off the bottom of a long catalog and
        # the user cannot see what is selected.
        self._scroll_to_highlighted_item(log, highlighted, len(entries))
        self.set_timer(0.05, self._ensure_input_focus)
        return True

    def _rerender_vendor_model_picker(self) -> None:
        """Redraw the vendor model list after a navigation key."""
        spec = self._prompts.active
        if spec is None or spec.name != "vendor_model":
            return
        log = self.query_one("#log", ConversationLog)
        self._show_vendor_model_picker(
            log,
            title=str(spec.data.get("title") or "Select Model"),
            entries=list(spec.data.get("entries") or []),
            on_choose=spec.data.get("on_choose"),
            current=str(spec.data.get("current") or ""),
            retry_hint=str(spec.data.get("retry_hint") or ""),
            reset_highlight=False,
        )

    def _show_antigravity_model_picker(
        self,
        models: list[str],
        log: ConversationLog,
        *,
        reset_highlight: bool = True,
    ) -> bool:
        """Pick an Antigravity model from the ``agy models`` list."""
        runtime = self._active_antigravity_runtime()
        return self._show_vendor_model_picker(
            log,
            title="Select Antigravity Model",
            entries=[(model, model) for model in models if model],
            on_choose=lambda model: self._antigravity_model_cmd(model, log),
            current=str(getattr(getattr(runtime, "config", None), "model", "") or ""),
            retry_hint="Run :agy models to choose again.",
            reset_highlight=reset_highlight,
        )

    @property
    def _awaiting_dependency_install(self) -> dict | None:
        """Compatibility view of the prompt stack for truthiness checks.

        Existing dispatch sites test this flag; backing it with the stack keeps
        them working while the prompt itself is fully registry-driven.
        """
        spec = self._prompts.active
        if spec is not None and spec.name == "dependency_install":
            return spec.data
        return None

    @_awaiting_dependency_install.setter
    def _awaiting_dependency_install(self, value) -> None:
        # Only clearing is meaningful; the prompt is opened by pushing a spec.
        if value is None and self._prompts.is_active("dependency_install"):
            self._prompts.pop()

    def _cancel_dependency_install(self) -> None:
        """Esc on the install prompt goes back to the connection screen.

        Matches the prompt's own Cancel option: the runtime picker would only
        re-offer the runtime that was just declined.
        """
        log = self.query_one("#log", ConversationLog)
        self._show_connect_type_picker(log)

    def _dependency_install_text_answer(self, text: str) -> bool:
        """Accept a typed answer to the install prompt."""
        log = self.query_one("#log", ConversationLog)
        return self._handle_dependency_install_input(text, log)

    #: Choices offered when a runtime's Python extra is missing.
    _DEPENDENCY_INSTALL_OPTIONS = (
        ("install", "Install it for me", "SuperQode runs the command and connects"),
        ("manual", "I will install it myself", "show the command and go back"),
        ("cancel", "Cancel", "return to the runtime picker"),
    )

    def _show_dependency_install_picker(
        self,
        runtime_name: str,
        log: ConversationLog,
        clear_log: bool = True,
        *,
        reset_highlight: bool = True,
    ) -> bool:
        """Offer an in-TUI install for a runtime's missing extra.

        Returns False when the runtime is not backed by a SuperQode extra (an
        external CLI, say), so callers can fall back to printed guidance.

        ``reset_highlight`` is False when redrawing after a navigation key, which
        must keep the selection the user just moved to.
        """
        from superqode.providers.env_introspect import environment_info, extra_install_command
        from superqode.runtime import runtime_extra

        extra = runtime_extra(runtime_name)
        if not extra:
            return False

        from superqode.app.prompt_stack import PromptSpec

        command = extra_install_command(extra)
        env = environment_info()
        # The runtime picker's Enter must not race this prompt's Enter.
        self._awaiting_runtime_selection = False
        if reset_highlight and not self._prompts.is_active("dependency_install"):
            # Declared once: Enter, typed answers, Esc, arrows, and number keys
            # are all routed from this single registration.
            pending = {"runtime": runtime_name, "extra": extra, "command": command}
            self._prompts.push(
                PromptSpec(
                    name="dependency_install",
                    kind="picker",
                    options=lambda: list(self._DEPENDENCY_INSTALL_OPTIONS),
                    # The stack closes the prompt before dispatching, so the
                    # choice data is captured here rather than read back off it.
                    on_select=lambda option: self._apply_dependency_install_choice(
                        option[0], pending=pending
                    ),
                    on_text=self._dependency_install_text_answer,
                    on_cancel=self._cancel_dependency_install,
                    render=self._rerender_dependency_install_picker,
                    data=pending,
                )
            )

        t = Text()
        t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append(f"{runtime_name} is not installed\n\n", style=f"bold {THEME['text']}")
        t.append("    It needs the ", style=THEME["muted"])
        t.append(f"superqode[{extra}]", style=f"bold {THEME['cyan']}")
        t.append(" extra.\n\n", style=THEME["muted"])
        t.append("    Running from  ", style=THEME["muted"])
        t.append(f"{env.label}\n", style=THEME["text"])
        t.append("    Install into  ", style=THEME["muted"])
        t.append(f"{env.target}\n\n", style=THEME["text"])
        t.append(f"    {command}\n\n", style=THEME["cyan"])
        t.append(self._dependency_install_option_lines())
        t.append("  💡 ", style=THEME["muted"])
        t.append("↑↓", style=THEME["cyan"])
        t.append(" navigate  ", style=THEME["dim"])
        t.append("Enter", style=THEME["cyan"])
        t.append(" select  •  or type a number, e.g. ", style=THEME["dim"])
        t.append("2", style=THEME["cyan"])
        t.append("\n", style="")

        log.auto_scroll = False
        if clear_log:
            log.clear()
        log.write(t)
        log.auto_scroll = True
        self.set_timer(0.05, self._ensure_input_focus)
        return True

    def _dependency_install_option_lines(self) -> Text:
        """Render the highlighted option list for the dependency prompt."""
        highlighted = self._prompts.index
        options = self._DEPENDENCY_INSTALL_OPTIONS
        if not (0 <= highlighted < len(options)):
            highlighted = 0

        t = Text()
        for index, (_key, label, description) in enumerate(options):
            num = index + 1
            if index == highlighted:
                t.append("  ▶ ", style=f"bold {THEME['success']}")
                t.append(
                    f"[{num}] ", style=self._picker_link_style(f"bold {THEME['success']}", num)
                )
                t.append(label, style=f"bold {THEME['success']}")
            else:
                t.append(f"    [{num}] ", style=self._picker_link_style(THEME["dim"], num))
                t.append(label, style=f"bold {THEME['text']}")
            t.append("\n", style="")
            t.append(f"        {description}\n", style=THEME["muted"])
        t.append("\n", style="")
        return t

    def _rerender_dependency_install_picker(self) -> None:
        """Redraw the prompt in place after a navigation key."""
        pending = self._awaiting_dependency_install
        if not isinstance(pending, dict):
            return
        log = self.query_one("#log", ConversationLog)
        self._show_dependency_install_picker(
            str(pending.get("runtime") or ""), log, reset_highlight=False
        )

    def action_navigate_dependency_install_up(self):
        """Highlight the previous dependency choice (arrow up)."""
        if self._prompts.is_active("dependency_install"):
            self._prompts.navigate(-1)

    def action_navigate_dependency_install_down(self):
        """Highlight the next dependency choice (arrow down)."""
        if self._prompts.is_active("dependency_install"):
            self._prompts.navigate(1)

    def action_select_highlighted_dependency_install(self):
        """Act on the highlighted dependency choice (Enter key)."""
        if self._prompts.is_active("dependency_install"):
            self._prompts.select()

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
            if not self._show_dependency_install_picker(info.name, log):
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
            self._reshow_acp_agents(log)
            self._scroll_to_highlighted_item(log, new_idx, len(agent_list))
            self.set_timer(0.05, self._ensure_input_focus)

    def _reshow_acp_agents(self, log: ConversationLog) -> None:
        """Redraw the ACP picker in the view the user is actually looking at.

        Redrawing with the default arguments silently switched a filtered view
        back to the full catalogue on the first arrow key.
        """
        view = getattr(self, "_acp_catalog_view", "all")
        self._show_agents(
            log,
            clear_log=False,
            include_all=view == "all",
            catalog_tier=view,
        )

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
            self._reshow_acp_agents(log)
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
            # Enter is its own path, so it needs the same mark the numbered and
            # clicked routes set: what follows is a result, and back belongs on
            # this listing rather than the category screen above it.
            try:
                self._history.detach()
                self._sync_navigation_controls()
            except Exception:  # noqa: BLE001 - chrome must never block a connect
                pass

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
            elif not self._show_agent_install_picker(agent_data, log):
                # No install command is registered for this agent at all.
                self._announce_transition(
                    title="Agent not installed",
                    primary=agent_data["name"],
                    detail="The ACP launcher is not available",
                    severity="warning",
                    log=log,
                    guidance=f"Run :acp install {agent_data['short_name']}.",
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
