"""Connection wizard: local / BYOK / ACP connect flows."""

from __future__ import annotations
import asyncio
import shutil
from textual import work
from rich.text import Text
from rich.panel import Panel
from rich.box import ROUNDED
from superqode.providers.model_specs import (
    normalize_model_for_provider,
    normalize_provider_id,
    split_provider_model_ref,
)
from superqode.app.constants import (
    THEME,
)
from superqode.app.widgets import (
    ColorfulStatusBar,
    ModeBadge,
    ConversationLog,
)

# --- helpers extracted from app_main (A1) ---
from superqode.app.recipes import PromptCompletionCandidate
from superqode.app.session_state import get_session


class ConnectMixin:
    """Local/BYOK/ACP connection flows and catalog refresh."""

    def action_refresh_byok_models(self):
        """Refresh BYOK providers/models from models.dev API."""
        if not (
            getattr(self, "_awaiting_byok_provider", False)
            or getattr(self, "_awaiting_byok_model", False)
        ):
            return

        try:
            from superqode.providers.models_dev import get_models_dev

            client = get_models_dev()

            t = Text()
            t.append("\n  🔄 ", style=THEME["success"])
            t.append("Refreshing models from models.dev...", style=THEME["text"])

            log = self.query_one("#log", ConversationLog)
            log.write(t)

            def on_refresh_complete(success: bool):
                log = self.query_one("#log", ConversationLog)
                if success:
                    t = Text()
                    t.append("  ✓ ", style=THEME["success"])
                    t.append("Models refreshed successfully!", style=THEME["text"])
                    log.write(t)
                else:
                    t = Text()
                    t.append("  ⚠️ ", style=THEME["error"])
                    t.append("Failed to refresh. Using cached models.", style=THEME["muted"])
                    log.write(t)

                # Re-show the provider picker
                self.set_timer(0.3, lambda: self._show_connect_picker(log, clear_log=True))

            # Trigger async refresh - it will call on_refresh_complete when done
            import asyncio

            async def do_refresh():
                success = await client.refresh(force=True)
                if success:
                    self._apply_live_models(client)
                self.call_later(lambda: on_refresh_complete(success))

            asyncio.create_task(do_refresh())

        except Exception as e:
            log = self.query_one("#log", ConversationLog)
            t = Text()
            t.append(f"\n  ⚠️  Error refreshing: {str(e)}", style=THEME["error"])
            log.write(t)

    def action_navigate_connect_type_up(self):
        """Navigate to previous connection type (arrow up)."""
        if not getattr(self, "_awaiting_connect_type", False):
            return

        current_idx = getattr(self, "_byok_highlighted_connect_type_index", 0)
        new_idx = max(0, current_idx - 1)
        if new_idx != current_idx:
            self._byok_highlighted_connect_type_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._show_connect_type_picker(log, clear_log=False)
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_connect_type_down(self):
        """Navigate to next connection type (arrow down)."""
        if not getattr(self, "_awaiting_connect_type", False):
            return

        from superqode.providers.connection_profiles import list_connection_profiles

        current_idx = getattr(self, "_byok_highlighted_connect_type_index", 0)
        new_idx = min(len(list_connection_profiles()) - 1, current_idx + 1)
        if new_idx != current_idx:
            self._byok_highlighted_connect_type_index = new_idx
            log = self.query_one("#log", ConversationLog)
            self._show_connect_type_picker(log, clear_log=False)
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_select_highlighted_connect_type(self):
        """Select the currently highlighted connection type (Enter key)."""
        if not getattr(self, "_awaiting_connect_type", False):
            return

        from superqode.providers.connection_profiles import list_connection_profiles

        profiles = list_connection_profiles()
        idx = getattr(self, "_byok_highlighted_connect_type_index", 0)
        if not (0 <= idx < len(profiles)):
            idx = 0
        log = self.query_one("#log", ConversationLog)
        # A selection result replaces the picker. Appending below a long picker
        # can leave the requested content outside the viewport.
        log.clear()
        log.scroll_home(animate=False)
        log.auto_scroll = True
        self._dispatch_connection_profile(profiles[idx], log)

    def _reset_connect_selection_states(self) -> None:
        """Clear transient connect-flow selection state so flows don't interfere."""
        self._awaiting_connect_type = False
        self._awaiting_runtime_selection = False
        self._awaiting_byok_provider = False
        self._awaiting_byok_model = False
        self._awaiting_acp_agent_selection = False
        self._awaiting_local_provider = False
        self._awaiting_local_model = False
        self._awaiting_codex_model = False
        self._awaiting_codex_effort = False
        for attr in (
            "_byok_selected_provider",
            "_byok_connect_list",
            "_byok_model_list",
            "_local_selected_provider",
            "_local_provider_list",
            "_local_model_list",
            "_local_cached_models",
        ):
            if hasattr(self, attr):
                delattr(self, attr)

    def _dispatch_connection_profile(self, profile, log: ConversationLog) -> None:
        """Route a chosen connection profile to its connector.

        See ``providers/connection_profiles.py`` for the connector semantics.
        Reuses the existing per-connector handlers so the BYOK/local/ACP flows
        are unchanged.
        """
        self._reset_connect_selection_states()
        conn = profile.connector
        if conn == "runtime":
            # Self-contained runtime (e.g. Codex) — auto-connects in _runtime_cmd.
            self._runtime_cmd(profile.runtime or "", log)
        elif conn == "acp":
            # A specific ACP agent by short_name (Claude, Grok Build, …).
            self._connect_acp_cmd(profile.acp_agent or "", log)
        elif conn == "byok":
            provider = getattr(profile, "byok_provider", None)
            if provider:
                self._connect_byok_cmd(provider, log)
                return
            self._byok_highlighted_provider_index = 0
            self._byok_highlighted_model_index = 0
            self._just_showed_byok_picker = True
            self._show_byok_providers(log)
            self.set_timer(0.3, lambda: setattr(self, "_just_showed_byok_picker", False))
        elif conn == "local":
            self._local_highlighted_provider_index = 0
            self._local_highlighted_model_index = 0
            self._show_local_provider_picker(log)
        elif conn == "acp-picker":
            self._show_agents(log)
        elif conn == "external-cli":
            if getattr(profile, "id", "") == "antigravity":
                self._antigravity_cmd("connect", log)
            else:
                log.add_error(
                    f"Unsupported external CLI profile: {getattr(profile, 'id', profile)}"
                )
        else:
            log.add_error(f"Unknown connection type: {getattr(profile, 'id', profile)}")

    def _select_byok_model_by_number(self, num: int):
        """Select a BYOK model by number."""
        if not getattr(self, "_awaiting_byok_model", False):
            return

        model_list = getattr(self, "_byok_model_list", [])
        if not model_list:
            return

        if 1 <= num <= len(model_list):
            model = model_list[num - 1]
            provider_id = getattr(self, "_byok_selected_provider", None)
            if provider_id:
                log = self.query_one("#log", ConversationLog)
                self._awaiting_byok_model = False
                self._connect_byok_mode(provider_id, model, log)

    def _track_byok_usage(
        self,
        input_text: str,
        response: str,
        tool_calls: int = 0,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        total_cost: float | None = None,
    ):
        """Track BYOK usage, preferring exact provider totals when available."""
        from superqode.providers.usage import get_usage_tracker

        input_tokens = max(0, int(prompt_tokens or 0))
        output_tokens = max(0, int(completion_tokens or 0))
        reported_total = max(0, int(total_tokens or 0))

        if reported_total > 0:
            # Some providers include reasoning/cache tokens in total_tokens.
            # Preserve the authoritative total even when the input/output
            # breakdown does not add up to it exactly.
            if input_tokens > reported_total:
                input_tokens = 0
            output_tokens = reported_total - input_tokens
        elif input_tokens + output_tokens == 0:
            # Older/non-reporting gateways still get a clearly documented
            # fallback rather than losing usage tracking entirely.
            input_tokens = len(input_text) // 4
            output_tokens = len(response) // 4

        tracker = get_usage_tracker()
        tracker.add_usage(input_tokens, output_tokens, cost=total_cost)

        for _ in range(tool_calls):
            tracker.add_tool_call()

        # Update status bar
        self._update_byok_status_bar()

    def _update_byok_status_bar(self):
        """Update status bar with current BYOK usage."""
        from superqode.providers.usage import get_usage_tracker

        try:
            status_bar = self.query_one("#status-bar", ColorfulStatusBar)
            tracker = get_usage_tracker()
            summary = tracker.get_summary()

            if summary["connected"]:
                status_bar.update_byok_status(
                    provider=summary["provider"],
                    model=summary["model"],
                    tokens=summary["tokens"],
                    cost=summary["cost"],
                    context_window=self._resolve_context_window(
                        summary.get("provider", ""), summary.get("model", "")
                    ),
                )
        except Exception:
            pass

    @staticmethod
    def _connect_profile_completion_candidates() -> list[PromptCompletionCandidate]:
        """Connection sources for `:connect <profile>` completion, with status."""
        from superqode.providers.connection_profiles import list_connection_profiles

        candidates: list[PromptCompletionCandidate] = []
        for profile in list_connection_profiles():
            desc = profile.description
            if not profile.available and profile.unavailable_hint:
                desc = f"needs setup — {profile.unavailable_hint}"
            candidates.append(
                PromptCompletionCandidate(
                    value=profile.id,
                    label=profile.id,
                    description=desc,
                    kind="connect",
                )
            )
        return candidates

    @staticmethod
    def _byok_provider_completion_candidates() -> list[PromptCompletionCandidate]:
        from superqode.app_main import SuperQodeApp

        return SuperQodeApp._provider_completion_candidates(local=False)

    @staticmethod
    def _byok_provider_ids() -> list[str]:
        try:
            from superqode.providers.registry import ProviderCategory
            from superqode.providers.dynamic import all_provider_ids, resolve_provider_def

            return [
                provider_id
                for provider_id in all_provider_ids()
                if (provider := resolve_provider_def(provider_id)) is not None
                and provider.category != ProviderCategory.LOCAL
            ]
        except Exception:
            return []

    def _announce_self_contained_connection(self, runtime_name: str, log: ConversationLog) -> None:
        """Write a clear 'connected' panel for a self-contained runtime and
        resolve its active model in the background (so the user can see which
        model is live and what to do next)."""
        from superqode.providers.connection_profiles import list_connection_profiles

        label = next(
            (
                p.label
                for p in list_connection_profiles()
                if p.connector == "runtime" and p.runtime == runtime_name
            ),
            runtime_name,
        )
        connection_details = {
            "codex-sdk": {
                "auth": "your local Codex login (~/.codex)",
                "model": "resolving...",
                "commands": (
                    (":codex model", "to switch model"),
                    (":codex status", "for diagnostics"),
                ),
            },
            "copilot-sdk": {
                "auth": "GitHub Copilot login or COPILOT_GITHUB_TOKEN",
                "model": "Copilot account default",
                "commands": (
                    (":copilot models", "to list models available to this account"),
                    (":copilot model <id>", "to switch model"),
                    (":copilot acp", "to use the official ACP path instead"),
                ),
            },
            "claude-agent-sdk": {
                "auth": "Anthropic API key (ANTHROPIC_API_KEY)",
                "model": "Claude SDK default",
                "commands": (
                    (":claude model", "to switch model"),
                    (":claude status", "for diagnostics"),
                ),
            },
            "antigravity-cli": {
                "auth": "Google Sign-In managed by agy and the OS keyring",
                "model": "managed by Antigravity CLI",
                "commands": (
                    (":antigravity status", "for diagnostics"),
                    (":antigravity help", "for route details"),
                ),
            },
            "antigravity-sdk": {
                "auth": "Gemini API key (GEMINI_API_KEY or GOOGLE_API_KEY)",
                "model": "Antigravity SDK default",
                "commands": (
                    (":antigravity status", "for diagnostics"),
                    (":antigravity help", "for route details"),
                ),
            },
            "antigravity-managed": {
                "auth": "Gemini API key (GEMINI_API_KEY or GOOGLE_API_KEY)",
                "model": "Google-hosted Antigravity managed agent",
                "commands": (
                    (":antigravity help", "for route details"),
                    (":runtime list", "to compare available runtime routes"),
                ),
            },
        }
        details = connection_details.get(
            runtime_name,
            {"auth": "managed by runtime", "model": "runtime default", "commands": ()},
        )
        t = Text()
        t.append("\n  ✓ ", style=f"bold {THEME['success']}")
        t.append("Connected: ", style=f"bold {THEME['text']}")
        t.append(f"{label}\n\n", style=f"bold {THEME['success']}")
        t.append("    Runtime   ", style=THEME["muted"])
        t.append(f"{runtime_name}\n", style=THEME["text"])
        t.append("    Auth      ", style=THEME["muted"])
        t.append(f"{details['auth']}\n", style=THEME["text"])
        t.append("    Model     ", style=THEME["muted"])
        t.append(f"{details['model']}\n", style=THEME["dim"])
        t.append("\n  Next:\n", style=THEME["muted"])
        t.append("    • ", style=THEME["dim"])
        t.append("type a message", style=THEME["cyan"])
        t.append(" to start coding\n", style=THEME["muted"])
        for command, description in details["commands"]:
            t.append("    • ", style=THEME["dim"])
            t.append(command, style=THEME["cyan"])
            t.append(f" {description}\n", style=THEME["muted"])
        log.write(t)
        announce = getattr(self, "_announce_transition", None)
        if announce is not None:
            announce(
                title="Connected",
                primary=label,
                detail=f"{runtime_name} · {details['model']}",
                severity="success",
                log=log,
                persist=False,
                dedupe_key=f"runtime:{runtime_name}",
            )
        self._sync_self_contained_status(runtime_name)
        if runtime_name == "codex-sdk":
            self.run_worker(self._resolve_codex_active_model(log), exclusive=False)

    def _show_antigravity_connect(self, log) -> None:
        agy_path = shutil.which("agy")
        command = self._antigravity_command_line()
        status_style = THEME["success"] if agy_path else THEME["warning"]
        t = Text()
        t.append("\n  ")
        t.append("✓" if agy_path else "⚠", style=f"bold {status_style}")
        t.append(" Antigravity CLI\n\n", style=f"bold {THEME['text']}")
        t.append("    Mode      ", style=THEME["muted"])
        t.append("local agy CLI handoff\n", style=THEME["text"])
        t.append("    Auth      ", style=THEME["muted"])
        t.append("Google sign-in/keyring managed by agy\n", style=THEME["text"])
        t.append("    Status    ", style=THEME["muted"])
        if agy_path:
            t.append(f"installed at {agy_path}\n", style=THEME["success"])
        else:
            t.append("agy not found on PATH\n", style=THEME["warning"])
        t.append("\n  Run in a terminal:\n", style=THEME["muted"])
        t.append(f"    {command}\n", style=THEME["cyan"])
        t.append("\n  Notes:\n", style=THEME["muted"])
        t.append(
            "    - agy has headless print mode, but does not expose a documented ACP event stream.\n",
            style=THEME["muted"],
        )
        t.append("    - Use ", style=THEME["muted"])
        t.append(":antigravity migrate", style=THEME["cyan"])
        t.append(" to import Gemini CLI config/plugins.\n", style=THEME["muted"])
        if not agy_path:
            t.append("\n  Install:\n", style=THEME["muted"])
            t.append(
                "    curl -fsSL https://antigravity.google/cli/install.sh | bash\n",
                style=THEME["cyan"],
            )
        log.write(
            Panel(
                t,
                title=f"[bold {THEME['cyan']}]Google Antigravity[/]",
                border_style=THEME["cyan"],
                box=ROUNDED,
                padding=(1, 2),
            )
        )
        self._announce_transition(
            title="Antigravity ready" if agy_path else "Antigravity setup required",
            primary="Google Antigravity CLI",
            detail="Installed" if agy_path else "agy was not found on PATH",
            severity="success" if agy_path else "warning",
            log=log,
            persist=False,
            guidance="Install agy, then run :connect antigravity." if not agy_path else "",
            dedupe_key=f"antigravity:{bool(agy_path)}",
        )

    def _claude_runtime_or_connect(self, log):
        pure = getattr(self, "_pure_mode", None)
        runtime = getattr(pure, "_runtime", None) if pure is not None else None
        if (
            runtime is not None
            and getattr(pure, "runtime_name", "") == "claude-agent-sdk"
            and getattr(getattr(pure, "session", None), "connected", False)
        ):
            return runtime
        self._runtime_cmd("claude-agent-sdk", log)
        pure = getattr(self, "_pure_mode", None)
        runtime = getattr(pure, "_runtime", None) if pure is not None else None
        if runtime is None or getattr(pure, "runtime_name", "") != "claude-agent-sdk":
            raise RuntimeError("Claude Agent SDK runtime is not connected")
        return runtime

    def _connect_pure_mode(self, provider: str, model: str, level, log: ConversationLog):
        """Connect to provider session with specified provider/model."""
        from superqode.pure_mode import PureMode
        from superqode.tools.base import ToolResult

        if not hasattr(self, "_pure_mode"):
            self._pure_mode = PureMode()

        # Set up callbacks for tool calls
        def on_tool_call(name: str, args: dict):
            self._call_ui(self._show_pure_tool_call, name, args, log)

        def on_tool_result(name: str, result: ToolResult):
            self._call_ui(self._show_pure_tool_result, name, result, log)

        self._pure_mode.on_tool_call = on_tool_call
        self._pure_mode.on_tool_result = on_tool_result
        self._install_pure_permission_bridge(self._pure_mode, log)

        # Connect
        self._pure_mode.connect(provider, model, level)

        # Update state
        session = get_session()
        session.execution_mode = "pure"

        self.current_mode = "pure"
        self.current_agent = "pure"
        self.current_model = model
        self.current_provider = provider

        # Update badge
        badge = self.query_one("#mode-badge", ModeBadge)
        badge.mode = "pure"
        badge.agent = ""
        badge.model = model
        badge.provider = provider
        badge.execution_mode = "pure"

        # Clear screen and show fresh workspace
        self._clear_for_workspace(log, f"PURE • {provider}")

    def _show_byok_thinking_line(self, text: str, log: ConversationLog):
        """Show thinking line for BYOK - handles threading correctly.

        The agent loop runs in an async context which might be in the same thread
        as the Textual app. This method safely handles both cases.
        """
        # Use call_from_thread, but catch the error if we're already in UI thread
        try:
            self._call_ui(self._show_thinking_line, text, log)
        except RuntimeError as e:
            # If we get "must run in a different thread" error, we're already in UI thread
            # Call directly
            if "different thread" in str(e).lower():
                self._show_thinking_line(text, log)
            else:
                # Re-raise other errors
                raise

    def _handle_byok_provider_selection(self, selection: str, log: ConversationLog):
        """Handle provider selection from :connect picker."""
        # Only process if we're actually awaiting provider selection
        if not getattr(self, "_awaiting_byok_provider", False):
            return False

        # Check for _byok_connect_list (from :connect command)
        if hasattr(self, "_byok_connect_list") and self._byok_connect_list:
            selection = selection.strip()
            provider_id = None
            provider_def = None

            # Try numeric selection first
            try:
                idx = int(selection) - 1
                if 0 <= idx < len(self._byok_connect_list):
                    provider_id, provider_def = self._byok_connect_list[idx]
            except ValueError:
                # Not a number - try to match by provider name/ID
                selection_lower = selection.lower()
                for pid, pdef in self._byok_connect_list:
                    if selection_lower == pid.lower() or selection_lower in pdef.name.lower():
                        provider_id, provider_def = pid, pdef
                        break

            if provider_id:
                self._awaiting_byok_provider = False
                # CRITICAL: Clear _awaiting_byok_model to prevent any auto-connection
                # The model list must be shown first, and user must explicitly select a model
                self._awaiting_byok_model = False
                # CRITICAL: Store the selection that was used to select the provider
                # This prevents the same input from being processed as a model selection
                self._last_provider_selection = selection.strip()
                # CRITICAL: Prevent _show_provider_models from setting _awaiting_byok_model immediately
                # This prevents the same input from being processed as a model selection
                self._skip_set_awaiting_model = True
                # Reset model highlight index when entering a new provider
                self._byok_highlighted_model_index = 0
                # Always use numbered list (not picker) to ensure model list is shown
                # Disable picker mode to prevent any auto-selection issues
                self._show_provider_models(provider_id, log, use_picker=False)
                # The provider input event has already been consumed, so it is safe
                # to enable model navigation immediately. Delaying this made
                # arrow/Enter feel broken when users acted quickly after the list appeared.
                self._awaiting_byok_model = True
                self.set_timer(0.1, lambda: setattr(self, "_last_provider_selection", None))
                return True
            else:
                # Invalid selection
                log.add_error(f"Unknown provider: {selection}")
                log.add_info("Enter a number or provider name (e.g., 'openai', 'anthropic')")
                return True

        return False

    def _handle_byok_model_selection(self, selection: str, log: ConversationLog):
        """Handle model selection from :connect picker with search support."""
        if not hasattr(self, "_byok_selected_provider"):
            return False

        # CRITICAL: Only process model selection if we're actually awaiting it
        # and the model list has been displayed (not immediately after provider selection)
        if not getattr(self, "_awaiting_byok_model", False):
            return False

        # CRITICAL: Prevent the same input that selected the provider from being
        # processed as a model selection
        last_provider_selection = getattr(self, "_last_provider_selection", None)
        if last_provider_selection and selection.strip() == last_provider_selection:
            # This is the same input that selected the provider - ignore it
            return False

        provider_id = self._byok_selected_provider
        model_list = getattr(self, "_byok_model_list", [])
        searchable_model_list = getattr(self, "_byok_all_model_list", model_list)

        # CRITICAL: Ensure model list is populated before allowing selection
        if not model_list:
            return False

        model = None

        if selection.isdigit():
            # Number selection
            idx = int(selection)
            if model_list and 1 <= idx <= len(model_list):
                model = model_list[idx - 1]
            else:
                log.add_error(f"Invalid selection. Choose 1-{len(model_list)}")
                return True
        else:
            # Search by model name/ID
            selection_lower = selection.lower().strip()

            # CRITICAL: Prevent provider names from matching models
            # If the selection matches the provider name, don't auto-select
            if selection_lower == provider_id.lower() or selection_lower in provider_id.lower():
                log.add_error(
                    f"'{selection}' is the provider name. Please enter a model number (1-{len(model_list)}) or model name."
                )
                return True

            # Try exact match first
            for m in searchable_model_list:
                if selection_lower == m.lower():
                    model = m
                    break
                # Try partial match (contains)
                if selection_lower in m.lower():
                    if model is None:  # First match
                        model = m
                    else:
                        # Multiple matches - be more specific
                        if selection_lower in m.lower() and len(m) < len(model):
                            model = m  # Prefer shorter match

            if not model:
                log.add_error(f"Model '{selection}' not found for {provider_id}")
                log.add_info(f"Available models: {', '.join(searchable_model_list[:5])}")
                if len(searchable_model_list) > 5:
                    log.add_info(f"... and {len(searchable_model_list) - 5} more")
                return True

        self._awaiting_byok_model = False
        self._connect_byok_mode(provider_id, model, log)
        return True

    async def _refresh_catalog_then_connect_byok(
        self,
        provider: str,
        model: str,
        log: ConversationLog,
        resolved_role=None,
        *,
        session_id: str | None = None,
    ) -> None:
        """Fetch a models.dev-only provider before retrying a direct connection."""
        try:
            from superqode.providers.models_dev import get_models_dev

            client = get_models_dev()
            await client.ensure_loaded()
            if client.get_provider(provider) is None:
                await client.refresh(force=True)
            self._apply_live_models(client)
        except Exception:
            pass
        self.call_later(
            lambda: self._connect_byok_mode(
                provider,
                model,
                log,
                resolved_role,
                _catalog_refresh_attempted=True,
                session_id=session_id,
            )
        )

    def _connect_byok_mode(
        self,
        provider: str,
        model: str,
        log: ConversationLog,
        resolved_role=None,
        *,
        _catalog_refresh_attempted: bool = False,
        session_id: str | None = None,
    ):
        """Connect to BYOK mode with specified provider/model.

        Args:
            provider: Provider ID (e.g., "ollama", "anthropic")
            model: Model name (e.g., "qwen3.6:35b-a3b", "claude-opus-4-8")
            log: Conversation log for output
            resolved_role: Optional ResolvedRole object for role-based connections
                          (used to inject job description into system prompt)
        """
        from superqode.providers.dynamic import resolve_provider_def

        provider = normalize_provider_id(provider)
        model = normalize_model_for_provider(provider, model)
        provider_def = resolve_provider_def(provider)
        if provider_def is None:
            if not _catalog_refresh_attempted:
                self.run_worker(
                    self._refresh_catalog_then_connect_byok(
                        provider,
                        model,
                        log,
                        resolved_role,
                        session_id=session_id,
                    )
                )
                return
            log.add_error(
                f"Provider '{provider}' is not available from the current models.dev catalog."
            )
            return

        # Clear any existing ACP connection when switching to BYOK
        if hasattr(self, "_acp_client") and self._acp_client:
            # Disconnect ACP client if switching from ACP to BYOK
            try:
                if self._acp_loop_runner is not None:
                    self._acp_loop_runner.run(self._acp_client.stop())
                else:
                    asyncio.create_task(self._acp_client.stop())
            except Exception:
                pass
            self._acp_client = None
            self._acp_client_key = None

        # Clear session state
        session = get_session()
        if hasattr(session, "connected_agent"):
            session.connected_agent = None
        if hasattr(session, "acp_manager"):
            session.acp_manager = None
        from superqode.providers.registry import ProviderCategory
        from superqode.pure_mode import PureMode
        from superqode.agent.system_prompts import SystemPromptLevel
        from superqode.providers.usage import get_usage_tracker
        import os

        provider_name = provider_def.name if provider_def else provider.upper()

        # Show experimental warning for vLLM and SGLang
        if provider in ("vllm", "sglang"):
            t = Text()
            t.append(f"\n  ⚠️  ", style=THEME["warning"])
            t.append(f"Experimental Provider Warning\n\n", style=f"bold {THEME['warning']}")
            t.append(f"  {provider_name} support is ", style=THEME["text"])
            t.append(f"EXPERIMENTAL", style=f"bold {THEME['warning']}")
            t.append(f". Features may be unstable and behavior may change.\n", style=THEME["text"])
            t.append(f"  Please report any issues you encounter.\n\n", style=THEME["dim"])
            log.write_feedback(t)

        # Check API key before connecting (except for local providers)
        if (
            provider_def
            and provider_def.category != ProviderCategory.LOCAL
            and provider_def.env_vars
        ):
            from superqode.providers.credentials import provider_api_key

            has_key = bool(provider_api_key(provider_def))

            if not has_key:
                t = Text()
                t.append(f"\n  ⚠️  ", style=THEME["warning"])
                t.append("API Key Required\n\n", style=f"bold {THEME['warning']}")
                t.append(f"  Provider: ", style=THEME["muted"])
                t.append(f"{provider_name}\n", style=THEME["text"])
                t.append(f"  Required: ", style=THEME["muted"])
                t.append(f"{' or '.join(provider_def.env_vars)}\n\n", style=THEME["yellow"])
                t.append(f"  Setup:\n", style=THEME["muted"])
                t.append(f"    1. Get API key from: ", style=THEME["dim"])
                if provider_def.docs_url:
                    t.append(f"{provider_def.docs_url}\n", style=THEME["cyan"])
                else:
                    t.append(f"{provider_name} website\n", style=THEME["cyan"])
                t.append(f"    2. Export key:\n", style=THEME["dim"])
                for env_var in provider_def.env_vars[:1]:  # Show first option
                    t.append(f"       export {env_var}='your-api-key'\n", style=THEME["cyan"])
                t.append(
                    f"    3. Add to ~/.zshrc or ~/.bashrc for persistence\n\n", style=THEME["dim"]
                )
                t.append(
                    "  Or store it in SuperQode's local auth store (no shell config):\n",
                    style=THEME["muted"],
                )
                t.append(f"    superqode auth login {provider}\n\n", style=THEME["cyan"])
                t.append(f"  Then run: ", style=THEME["muted"])
                t.append(f":connect {provider}/{model}\n", style=THEME["success"])
                log.write_feedback(t)
                return

        # Store previous provider for quick switching
        if hasattr(self, "current_provider") and self.current_provider:
            self._previous_provider = (self.current_provider, self.current_model)

        # For BYOK, we use the provider session infrastructure with STANDARD system prompt
        # (includes role context) instead of MINIMAL
        if not hasattr(self, "_pure_mode"):
            self._pure_mode = PureMode()

        # Set up callbacks
        # Note: BYOK runs in the same event loop as Textual, but callbacks are invoked from async code
        # Use call_later to ensure UI updates happen on the next event loop tick
        # (ACP uses call_from_thread() because it runs in a separate subprocess)
        def on_tool_call(name: str, args: dict):
            # Schedule UI update on the next event loop tick
            self.call_later(self._show_pure_tool_call, name, args, log)

        def on_tool_result(name: str, result):
            # Schedule UI update on the next event loop tick
            self.call_later(self._show_pure_tool_result, name, result, log)

        is_local_provider = bool(provider_def and provider_def.category == ProviderCategory.LOCAL)

        async def on_thinking_async(text: str):
            """Handle thinking logs from AgentLoop - honors the :thinking toggle.

            OFF  -> nothing. NORMAL -> loop bookkeeping folds into the live
            throbber ("Working… step N"); for local models the raw reasoning is
            kept quiet so the screen stays clean. VERBOSE -> show everything,
            so users can see exactly what a local/ACP/BYOK model is doing.
            """
            if not (text and text.strip()):
                return
            if not self.show_thinking_logs:
                return  # OFF
            loop_status = self._thinking_loop_status(text)
            if loop_status is not None and self.thinking_verbosity != "verbose":
                self.call_later(self._set_thinking_status, loop_status)
                return
            # Calm mode stays quiet beyond the throbber to avoid flooding; flip
            # to :thinking verbose (or Ctrl+T) to see the full reasoning.
            if self.thinking_verbosity != "verbose":
                self.call_later(self._set_thinking_status, "💭 Thinking…")
                self.call_later(self._maybe_show_thinking_hint, log)
                return
            # Schedule UI update on the next event loop tick
            # ACP uses call_from_thread() because it runs in a separate subprocess
            self.call_later(self._show_thinking_line, text, log)

        # Thinking is always wired now; the handler above gates by verbosity so
        # the :thinking / Ctrl+T toggle works for local, BYOK, and ACP alike.
        self._pure_mode.on_tool_call = on_tool_call
        self._pure_mode.on_tool_result = on_tool_result
        self._pure_mode.on_thinking = on_thinking_async
        self._install_pure_permission_bridge(self._pure_mode, log)

        # Use STANDARD for cloud providers, MINIMAL for local to avoid confusion
        from superqode.providers.registry import ProviderCategory
        from superqode.agent.system_prompts import get_job_description_prompt
        from superqode.config import find_config_file
        from pathlib import Path

        system_level = (
            SystemPromptLevel.STANDARD
            if provider == "ds4"
            or not (provider_def and provider_def.category == ProviderCategory.LOCAL)
            else SystemPromptLevel.MINIMAL
        )

        # Determine project root (where superqode.yaml is located)
        # For local models, restrict to project root to prevent filesystem traversal
        config_file = find_config_file()
        if config_file:
            project_root = config_file.parent.resolve()
        else:
            # If no config file found, use current directory
            project_root = Path.cwd().resolve()

        # For local providers, use project root as working directory
        # For cloud providers, use current directory (existing behavior)
        working_dir = (
            project_root
            if (provider_def and provider_def.category == ProviderCategory.LOCAL)
            else None
        )

        # Extract job description from resolved role if available
        job_description = None
        if resolved_role:
            base_job_description = getattr(resolved_role, "job_description", None) or ""
            if base_job_description:
                # Build job description prompt for the role
                job_description = get_job_description_prompt(
                    base_job_description, role_config=resolved_role
                )

        # Connect with job description and working directory for role-based connections
        self._pure_mode.connect(
            provider,
            model,
            system_level,
            working_directory=working_dir,
            job_description=job_description,
            role_config=resolved_role,
            session_id=session_id,
        )

        # Update state
        session = get_session()
        # Determine execution mode: "local" for local providers, "byok" for cloud
        is_local = provider_def and provider_def.category == ProviderCategory.LOCAL
        # Check if session already has execution_mode set (from role)
        if hasattr(session, "execution_mode") and session.execution_mode == "local":
            exec_mode = "local"
        elif is_local:
            exec_mode = "local"
        else:
            exec_mode = "byok"

        session.execution_mode = exec_mode

        self.current_mode = exec_mode
        self.current_agent = ""
        self.current_model = model
        self.current_provider = provider

        # Start usage tracking
        tracker = get_usage_tracker()
        tracker.set_provider(provider, model)

        # Save to persistent config
        self._save_byok_config(provider, model)

        # Update badge
        badge = self.query_one("#mode-badge", ModeBadge)
        badge.mode = exec_mode
        badge.agent = ""
        badge.model = model
        badge.provider = provider
        badge.execution_mode = exec_mode

        # Clear screen and show fresh workspace
        mode_label = "LOCAL" if exec_mode == "local" else "BYOK"
        self._clear_for_workspace(log, f"{mode_label} • {provider_name}")

        try:
            status_bar = self.query_one("#status-bar", ColorfulStatusBar)
            status_bar.update_byok_status(provider, model)
        except Exception:
            pass

        local_host = self._local_provider_host(provider) if is_local else ""
        self._show_connection_summary(
            log,
            mode=exec_mode,
            provider=provider,
            provider_name=provider_name,
            model=model,
            host=local_host,
        )

        if is_local:
            self.run_worker(self._test_local_connection(provider, model, log, quiet=True))
        else:
            log.add_meta(f"Ready · {provider}/{model}")

    def _show_connection_summary(
        self,
        log: ConversationLog,
        *,
        mode: str,
        provider: str,
        provider_name: str,
        model: str,
        host: str = "",
    ) -> None:
        t = Text()
        local = mode == "local"
        title = "Local Model Selected" if local else "Provider Connected"
        icon = "✓"
        color = THEME["success"]
        t.append(f"\n  {icon} ", style=f"bold {color}")
        t.append(f"{title}\n\n", style=f"bold {THEME['text']}")
        t.append("    Method   ", style=THEME["muted"])
        t.append("Local" if local else "BYOK", style=THEME["text"])
        t.append("\n")
        t.append("    Provider ", style=THEME["muted"])
        t.append(provider_name or provider, style=THEME["text"])
        t.append("\n")
        t.append("    Model    ", style=THEME["muted"])
        t.append(model, style=f"bold {THEME['cyan']}")
        t.append("\n")
        if host:
            t.append("    Host     ", style=THEME["muted"])
            t.append(host, style=THEME["dim"])
            t.append("\n")
        t.append(
            "\n  Validating the local server..."
            if local
            else "\n  Ready. Type a message to start.",
            style=THEME["muted"],
        )
        if local:
            t.append(" Use ", style=THEME["muted"])
            t.append(":local test", style=THEME["cyan"])
            t.append(" for a manual smoke check.", style=THEME["muted"])

        log.write(
            Panel(
                t,
                title=f"[bold {THEME['cyan']}]Connection[/]",
                border_style=color,
                box=ROUNDED,
                padding=(1, 2),
            )
        )
        self._announce_transition(
            title=title,
            primary=f"{provider_name or provider} · {model}",
            detail="Local" if local else "BYOK",
            severity="information" if local else "success",
            log=log,
            persist=False,
            dedupe_key=f"connection:{mode}:{provider}:{model}",
        )

    def _connect_byok_cmd(self, args: str, log: ConversationLog):
        """Handle :connect byok command - Interactive provider/model picker."""
        args = args.strip()

        # If no args provided, show the provider picker
        # This is the main entry point for :connect byok
        if not args:
            # Clear any existing state that might interfere
            self._awaiting_byok_model = False
            self._awaiting_byok_provider = False
            if hasattr(self, "_byok_selected_provider"):
                delattr(self, "_byok_selected_provider")
            if hasattr(self, "_byok_model_list"):
                delattr(self, "_byok_model_list")
            # Show the provider list
            self._show_connect_picker(log)
            return

        # :connect - (switch to previous)
        if args == "-":
            self._connect_previous(log)
            return

        # :connect ! (show history)
        if args == "!":
            self._connect_history(log)
            return

        # :connect last (reconnect to last used)
        if args == "last":
            self._connect_last(log)
            return

        # :connect <provider>[/<model>] (direct connect with / separator)
        if args:
            # Prevent "byok", "acp", "local" from being treated as provider names
            # These are subcommands, not providers
            if args.lower().strip() in ("byok", "acp", "local"):
                # This shouldn't happen if parsing is correct, but be defensive
                self._show_connect_picker(log)
                return

            parsed = split_provider_model_ref(args)
            if parsed.provider and parsed.model:
                self._connect_byok_mode(parsed.provider, parsed.model, log)
                return

            # Support provider/model syntax
            if "/" in args:
                parts = args.split("/", 1)
                provider = parts[0].strip()
                model = parts[1].strip() if len(parts) > 1 else None
                if provider and model:
                    self._connect_byok_mode(provider, model, log)
                    return

            # Support space-separated syntax
            parts = args.split(maxsplit=1)
            provider = parts[0].strip()
            model = parts[1].strip() if len(parts) > 1 else None

            # Double-check provider is not a subcommand
            if provider.lower() in ("byok", "acp", "local"):
                self._show_connect_picker(log)
                return

            if model:
                # Direct connect with provider and model
                self._connect_byok_mode(provider, model, log)
            else:
                # A bare token that is not a provider may be a model id
                # (":connect gpt-5.6-sol") — resolve the provider from the
                # catalog so users do not need to know who hosts a model.
                from superqode.providers.dynamic import is_curated_provider, resolve_provider_def
                from superqode.providers.models import find_providers_for_model

                if resolve_provider_def(provider) is None:
                    candidates = find_providers_for_model(provider)
                    if len(candidates) > 1:
                        # Gateways mirror popular models; prefer first-party /
                        # curated providers so ":connect gpt-5.6" goes to
                        # OpenAI, not a reseller. Multiple curated matches
                        # (e.g. grok-4.5 via xai API or grok-cli subscription)
                        # remain a genuine user choice.
                        curated = [pid for pid in candidates if is_curated_provider(pid)]
                        if curated:
                            candidates = curated
                    if len(candidates) == 1:
                        log.add_info(f"Resolved '{provider}' to {candidates[0]}/{provider}.")
                        self._connect_byok_mode(candidates[0], provider, log)
                        return
                    if len(candidates) > 1:
                        log.add_info(f"'{provider}' is available from several providers:")
                        for pid in candidates:
                            log.add_info(f"  :connect {pid}/{provider}")
                        return
                # Show models for this provider - always use numbered list
                self._show_provider_models(provider, log, use_picker=False)
            return

    def _connect_previous(self, log: ConversationLog):
        """Switch to previous provider/model."""
        if hasattr(self, "_previous_provider") and self._previous_provider:
            provider, model = self._previous_provider
            self._connect_byok_mode(provider, model, log)
        else:
            log.add_info("No previous provider to switch to")
            log.add_system("Use :connect to select a provider")

    def _connect_history(self, log: ConversationLog):
        """Show connection history."""
        history = self._load_byok_history()

        if not history:
            log.add_info("No connection history yet")
            log.add_system("Use :connect to connect to a provider")
            return

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Connection History\n\n", style=f"bold {THEME['text']}")

        for i, entry in enumerate(history[:10], 1):
            provider, model = entry.split("/", 1) if "/" in entry else (entry, "")
            t.append(f"  [{i}] ", style=THEME["dim"])
            t.append(f"{provider}", style=f"bold {THEME['success']}")
            if model:
                t.append(f"/{model}", style=THEME["muted"])
            t.append("\n", style="")

        t.append(f"\n  💡 ", style=THEME["muted"])
        t.append(":connect <number>", style=THEME["success"])
        t.append(" to reconnect\n", style=THEME["muted"])

        log.write(t)

    def _connect_last(self, log: ConversationLog):
        """Connect to the last used provider/model."""
        config = self._load_byok_config()

        if config.get("last_provider") and config.get("last_model"):
            self._connect_byok_mode(config["last_provider"], config["last_model"], log)
        else:
            log.add_info("No previous connection saved")
            log.add_system("Use :connect to select a provider")

    def _show_connect_type_picker(self, log: ConversationLog, clear_log: bool = True):
        """Show picker to choose between ACP, BYOK, and LOCAL connection types.

        Args:
            log: The conversation log widget
            clear_log: If True, clear the log before writing (default: True).
                      Set to False when updating during navigation to reduce flickering.
        """
        # Clear any other primary picker state to prevent interference.
        self._awaiting_harness_selection = False
        self._awaiting_harness_confirmation = False
        if hasattr(self, "_harness_selection_list"):
            delattr(self, "_harness_selection_list")

        # Clear any BYOK state to prevent interference
        self._awaiting_byok_provider = False
        self._awaiting_byok_model = False
        if hasattr(self, "_byok_selected_provider"):
            delattr(self, "_byok_selected_provider")
        if hasattr(self, "_byok_connect_list"):
            delattr(self, "_byok_connect_list")

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Select Connection Type\n\n", style=f"bold {THEME['text']}")

        # Show connection sources (profile-driven) with highlighting + status
        from superqode.providers.connection_profiles import list_connection_profiles

        profiles = list_connection_profiles()
        highlighted_idx = getattr(self, "_byok_highlighted_connect_type_index", 0)
        if not (0 <= highlighted_idx < len(profiles)):
            highlighted_idx = 0

        for i, profile in enumerate(profiles):
            num = i + 1
            available = profile.available
            status = "ready" if available else "needs setup"
            status_color = THEME["success"] if available else THEME["warning"]
            is_highlighted = i == highlighted_idx
            if is_highlighted:
                t.append("  ▶ ", style=f"bold {THEME['success']}")
                t.append(
                    f"[{num}] ",
                    style=self._picker_link_style(f"bold {THEME['success']}", num),
                )
                t.append(profile.label, style=f"bold {THEME['success']}")
                t.append("  ← SELECTED\n", style=f"bold {THEME['success']}")
            else:
                t.append(f"    [{num}] ", style=self._picker_link_style(THEME["dim"], num))
                t.append(profile.label, style=f"bold {THEME['text']}")
                t.append("\n", style="")
            t.append(f"        {profile.description}\n", style=THEME["muted"])
            t.append("        ", style="")
            t.append(status, style=status_color)
            if not available and profile.unavailable_hint:
                t.append(f" — {profile.unavailable_hint}", style=THEME["dim"])
            t.append("\n\n", style="")

        t.append("  💡 ", style=THEME["muted"])
        t.append("↑↓", style=THEME["cyan"])
        t.append(" navigate  ", style=THEME["dim"])
        t.append("Enter", style=THEME["cyan"])
        t.append(" select  •  or type a number or name, e.g. ", style=THEME["dim"])
        t.append(":connect codex", style=THEME["cyan"])
        t.append("\n", style="")

        if clear_log:
            log.clear()
            log.auto_scroll = False
            log.write(t)
            log.scroll_home(animate=False)
            log.auto_scroll = True  # set synchronously; avoids per-keystroke scroll-jump flicker
        else:
            # Update during navigation - clear and write but don't scroll to home
            log.auto_scroll = False
            log.clear()
            log.write(t)
            # Don't scroll to home on navigation updates to reduce flickering
            log.auto_scroll = True  # set synchronously; avoids per-keystroke scroll-jump flicker

        self._scroll_to_highlighted_item(log, highlighted_idx, len(profiles))

        # Set up selection handler
        self._awaiting_connect_type = True
        self._byok_highlighted_connect_type_index = highlighted_idx  # Preserve current highlight

        # Ensure input stays focused for keyboard navigation
        self.set_timer(0.05, self._ensure_input_focus)

    def _show_byok_providers(self, log: ConversationLog, clear_log: bool = True):
        """Show BYOK provider picker - alias for _show_connect_picker."""
        # CRITICAL: Explicitly clear ALL state that might cause it to skip to models
        # This must be done BEFORE calling _show_connect_picker
        # BUT: During navigation (clear_log=False), preserve the connect list
        self._awaiting_byok_model = False
        self._awaiting_byok_provider = False  # Set to False first
        if hasattr(self, "_byok_selected_provider"):
            delattr(self, "_byok_selected_provider")
        if hasattr(self, "_byok_model_list"):
            delattr(self, "_byok_model_list")
        if hasattr(self, "_byok_all_model_list"):
            delattr(self, "_byok_all_model_list")
        # Only clear connect list on initial display, not during navigation
        if clear_log and hasattr(self, "_byok_connect_list"):
            delattr(self, "_byok_connect_list")
        # Set flag to prevent any immediate model display (only on initial display)
        if clear_log:
            self._just_showed_byok_picker = True
            # Clear the flag after a delay
            self.set_timer(0.5, lambda: setattr(self, "_just_showed_byok_picker", False))
        # Now show the provider picker - it will set _awaiting_byok_provider = True
        self._show_connect_picker(log, clear_log=clear_log)

    def _show_connect_picker(self, log: ConversationLog, clear_log: bool = True):
        """Show interactive provider picker with model counts and API key guidance."""
        from superqode.providers.registry import PROVIDERS, ProviderCategory, get_free_providers
        from superqode.providers.dynamic import all_provider_ids, resolve_provider_def
        from superqode.providers.models import get_models_for_provider, get_data_source
        import os

        # CRITICAL: Clear any model selection state to ensure we show provider list, not models
        # This must be done FIRST before any other logic
        # Force clear ALL BYOK-related state to prevent any auto-selection
        # BUT: During navigation (clear_log=False), preserve the connect list
        self._awaiting_byok_model = False
        self._awaiting_byok_provider = (
            False  # Set to False first, then True after we build the list
        )
        if hasattr(self, "_byok_selected_provider"):
            delattr(self, "_byok_selected_provider")
        if hasattr(self, "_byok_model_list"):
            delattr(self, "_byok_model_list")
        if hasattr(self, "_byok_all_model_list"):
            delattr(self, "_byok_all_model_list")
        # Only clear the connect list on initial display, not during navigation
        if clear_log and hasattr(self, "_byok_connect_list"):
            delattr(self, "_byok_connect_list")

        # Reset provider highlight index only on initial display, preserve during navigation
        if clear_log:
            # On initial display, reset to 0
            if not hasattr(self, "_byok_highlighted_provider_index"):
                self._byok_highlighted_provider_index = 0
            else:
                self._byok_highlighted_provider_index = 0
        else:
            # During navigation, preserve the current index (don't reset)
            if not hasattr(self, "_byok_highlighted_provider_index"):
                self._byok_highlighted_provider_index = 0

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Select Provider\n\n", style=f"bold {THEME['text']}")

        # Show data source info
        data_source = get_data_source()
        t.append(f"  📊 Source: {data_source}\n\n", style=THEME["dim"])

        # Get providers with free models
        free_providers = get_free_providers()
        free_provider_ids = set(free_providers.keys())

        # Helper function to get provider info
        def get_provider_info(pid, pdef):
            configured = False
            missing_keys = []
            if not pdef.env_vars:
                configured = True
            else:
                for env_var in pdef.env_vars:
                    if os.environ.get(env_var):
                        configured = True
                        break
                    else:
                        missing_keys.append(env_var)

            try:
                models = get_models_for_provider(pid)
                model_count = len(models)
            except Exception:
                model_count = len(pdef.example_models) if pdef.example_models else 0

            return (pid, pdef, configured, missing_keys, model_count)

        # Group by category
        category_order = {
            ProviderCategory.US_LABS: ("🇺🇸 US Labs", THEME["cyan"]),
            ProviderCategory.CHINA_LABS: ("🇨🇳 China Labs", THEME["error"]),
            ProviderCategory.OTHER_LABS: ("🌍 Other Labs", THEME["success"]),
            ProviderCategory.MODEL_HOSTS: ("🌐 Model Hosts", THEME["purple"]),
            ProviderCategory.LOCAL: ("🏠 Local / Self-Hosted", THEME["muted"]),
        }

        providers_by_category = {}
        for pid in all_provider_ids():
            pdef = resolve_provider_def(pid)
            if pdef is None:
                continue
            category = pdef.category
            if category not in providers_by_category:
                providers_by_category[category] = []

            providers_by_category[category].append(get_provider_info(pid, pdef))

        idx = 1
        provider_list = []

        # Show Free Models section first if there are any
        if free_provider_ids:
            t.append(f"  🆓 Free Models\n", style=f"bold {THEME['success']}")
            free_providers_list = []
            for pid in free_provider_ids:
                pdef = PROVIDERS.get(pid)
                if not pdef:
                    continue
                free_providers_list.append(get_provider_info(pid, pdef))

            # Sort free providers by name
            free_providers_list.sort(key=lambda x: x[1].name)

            for pid, pdef, configured, missing_keys, model_count in free_providers_list:
                status = "✓" if configured else "○"
                status_style = THEME["success"] if configured else THEME["warning"]

                # Highlight current selection
                is_highlighted = (idx - 1) == getattr(self, "_byok_highlighted_provider_index", 0)
                if is_highlighted:
                    t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                    t.append(
                        f"[{idx:2}] ",
                        style=self._picker_link_style(f"bold {THEME['success']}", idx),
                    )
                    t.append(f"{status} ", style=status_style)
                    t.append(f"{pid:<15}", style=f"bold {THEME['success']}")
                    t.append(f"{pdef.name}", style=f"bold {THEME['success']}")
                    t.append(f" 🆓", style=f"bold {THEME['success']}")
                    if model_count > 0:
                        t.append(
                            f" ({model_count} model{'s' if model_count > 1 else ''})",
                            style=f"bold {THEME['success']}",
                        )
                    if not configured and pdef.env_vars:
                        t.append(
                            f" • Needs: {', '.join(missing_keys)}", style=f"bold {THEME['success']}"
                        )
                    t.append(f"  ← SELECTED\n", style=f"bold {THEME['success']}")
                else:
                    t.append(f"    [{idx:2}] ", style=self._picker_link_style(THEME["dim"], idx))
                    t.append(f"{status} ", style=status_style)
                    t.append(f"{pid:<15}", style=THEME["text"])
                    t.append(f"{pdef.name}", style=THEME["muted"])
                    t.append(f" 🆓", style=THEME["success"])

                    # Show model count
                    if model_count > 0:
                        t.append(f" ({model_count} model", style=THEME["dim"])
                        if model_count > 1:
                            t.append("s", style=THEME["dim"])
                        t.append(")", style=THEME["dim"])

                    # Show API key requirement if not configured
                    if not configured and pdef.env_vars:
                        t.append(f" • Needs: {', '.join(missing_keys)}", style=THEME["yellow"])

                    t.append("\n", style="")

                provider_list.append((pid, pdef))
                idx += 1

            t.append("\n", style="")

        # Show providers grouped by category. LOCAL/self-hosted providers are
        # intentionally excluded here — they have their own picker via
        # `:connect local` and shouldn't clutter the BYOK (cloud key) list.
        for category in [
            ProviderCategory.US_LABS,
            ProviderCategory.CHINA_LABS,
            ProviderCategory.OTHER_LABS,
            ProviderCategory.MODEL_HOSTS,
        ]:
            if category not in providers_by_category:
                continue

            label, color = category_order[category]

            # Sort providers by name within category
            category_providers = sorted(providers_by_category[category], key=lambda x: x[1].name)

            # Count non-free providers in this category
            non_free_providers = [p for p in category_providers if p[0] not in free_provider_ids]

            # Show category header if there are any providers (even if all are free, show the header)
            if category_providers:
                t.append(f"  {label}\n", style=f"bold {color}")

            for pid, pdef, configured, missing_keys, model_count in category_providers:
                # Skip if already shown in Free Models section
                if pid in free_provider_ids:
                    continue

                status = "✓" if configured else "○"
                status_style = THEME["success"] if configured else THEME["warning"]

                # Highlight current selection
                is_highlighted = (idx - 1) == getattr(self, "_byok_highlighted_provider_index", 0)
                if is_highlighted:
                    t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                    t.append(
                        f"[{idx:2}] ",
                        style=self._picker_link_style(f"bold {THEME['success']}", idx),
                    )
                    t.append(f"{status} ", style=status_style)
                    t.append(f"{pid:<15}", style=f"bold {THEME['success']}")
                    t.append(f"{pdef.name}", style=f"bold {THEME['success']}")
                    if model_count > 0:
                        t.append(
                            f" ({model_count} model{'s' if model_count > 1 else ''})",
                            style=f"bold {THEME['success']}",
                        )
                    if not configured and pdef.env_vars:
                        t.append(
                            f" • Needs: {', '.join(missing_keys)}", style=f"bold {THEME['success']}"
                        )
                    t.append(f"  ← SELECTED\n", style=f"bold {THEME['success']}")
                else:
                    t.append(f"    [{idx:2}] ", style=self._picker_link_style(THEME["dim"], idx))
                    t.append(f"{status} ", style=status_style)
                    t.append(f"{pid:<15}", style=THEME["text"])
                    t.append(f"{pdef.name}", style=THEME["muted"])

                # Show free badge if provider offers free models
                if pid in free_provider_ids:
                    t.append(f" 🆓", style=THEME["success"])

                # Show model count
                if model_count > 0:
                    t.append(f" ({model_count} model", style=THEME["dim"])
                    if model_count > 1:
                        t.append("s", style=THEME["dim"])
                    t.append(")", style=THEME["dim"])

                # Show API key requirement if not configured
                if not configured and pdef.env_vars:
                    t.append(f" • Needs: {', '.join(missing_keys)}", style=THEME["yellow"])

                t.append("\n", style="")

                provider_list.append((pid, pdef))
                idx += 1

            t.append("\n", style="")

        # Add arrow key navigation instructions
        t.append(f"  💡 Quick Connect:\n", style=THEME["muted"])
        t.append(f"    ⌨️  ", style=THEME["dim"])
        t.append(f"↑↓", style=THEME["cyan"])
        t.append(" Arrow keys to navigate  ", style=THEME["dim"])
        t.append(f"Enter", style=THEME["cyan"])
        t.append(" to select highlighted provider\n", style=THEME["dim"])
        t.append(f"    Or enter number (1-{len(provider_list)})  ", style=THEME["dim"])
        t.append("to select provider\n", style=THEME["text"])
        t.append(f"    Or: ", style=THEME["dim"])
        t.append(f":connect byok <provider>/<model>", style=THEME["success"])
        t.append(" for direct connect\n", style=THEME["text"])
        t.append(f"    Local models? Use ", style=THEME["dim"])
        t.append(f":connect local", style=THEME["cyan"])
        t.append(" (Ollama, LM Studio, vLLM, …)\n", style=THEME["dim"])
        t.append(f"    ", style=THEME["dim"])
        t.append(f"R", style=f"bold {THEME['success']}")
        t.append(" to refresh models from API\n", style=THEME["dim"])
        t.append(f"    Use ", style=THEME["dim"])
        t.append(f":back", style=THEME["cyan"])
        t.append(" or ", style=THEME["dim"])
        t.append(f":home", style=THEME["cyan"])
        t.append(" to cancel\n", style=THEME["text"])
        t.append(f"\n  💡 API Key Setup:\n", style=THEME["muted"])
        t.append(f"    Export API key: ", style=THEME["dim"])
        t.append("export ANTHROPIC_API_KEY='your-key'\n", style=THEME["cyan"])
        t.append(f"    Or in ~/.zshrc: ", style=THEME["dim"])
        t.append("export ANTHROPIC_API_KEY='your-key'\n", style=THEME["cyan"])
        t.append(f"    See provider docs: ", style=THEME["dim"])
        t.append("https://docs.superqode.ai/providers\n\n", style=THEME["cyan"])

        # Ensure we have providers to show
        if not provider_list:
            log.add_error("No providers available. Please check your provider configuration.")
            return

        # Clear log and show content from top (like agent finish work)
        if clear_log:
            log.clear()
            log.auto_scroll = False
            log.write(t)
            log.scroll_home(animate=False)
            # Re-enable auto-scroll after a short delay
            log.auto_scroll = True  # set synchronously; avoids per-keystroke scroll-jump flicker
        else:
            # Update during navigation - clear and write but don't scroll to home
            log.auto_scroll = False
            log.clear()
            log.write(t)
            # Don't scroll to home on navigation updates to reduce flickering
            log.auto_scroll = True  # set synchronously; avoids per-keystroke scroll-jump flicker

        # Store for selection handling
        self._byok_connect_list = provider_list
        # CRITICAL: Set provider selection mode and clear model selection mode
        # This must be set AFTER building the list to ensure we show providers, not models
        self._awaiting_byok_provider = True
        self._awaiting_byok_model = False
        # Clear any selected provider to prevent auto-showing models
        if hasattr(self, "_byok_selected_provider"):
            delattr(self, "_byok_selected_provider")
        # Preserve current highlight if already set, otherwise start with first
        # Only reset on initial display, preserve during navigation
        if clear_log:
            if not hasattr(self, "_byok_highlighted_provider_index"):
                self._byok_highlighted_provider_index = 0
        else:
            # During navigation, preserve the index (it's already set by navigation methods)
            if not hasattr(self, "_byok_highlighted_provider_index"):
                self._byok_highlighted_provider_index = 0

        # Set flag to prevent immediate provider selection from any pending input (only on initial display)
        if clear_log:
            self._just_showed_byok_picker = True
            # Clear the flag after a short delay to allow normal selection
            self.set_timer(0.2, lambda: setattr(self, "_just_showed_byok_picker", False))

        # Ensure input stays focused for keyboard navigation
        self.set_timer(0.05, self._ensure_input_focus)

    def _set_byok_model(self, model: str, log: ConversationLog):
        """Switch model without reconnecting."""
        session = get_session()
        if session.execution_mode not in ("byok", "local") or not hasattr(self, "_pure_mode"):
            log.add_error("Not connected to BYOK provider")
            return

        provider = getattr(self._pure_mode, "_provider", None)
        if not provider:
            log.add_error("No provider selected")
            return

        # Reconnect with new model
        self._connect_byok_mode(provider, model, log)

    def _load_byok_config(self) -> dict:
        """Load BYOK config from file."""
        import json
        from pathlib import Path

        config_path = Path.home() / ".superqode" / "config.json"
        try:
            if config_path.exists():
                data = json.loads(config_path.read_text())
                return data.get("byok", {})
        except Exception:
            pass
        return {}

    def _save_byok_config(self, provider: str, model: str):
        """Save BYOK config to file."""
        import json
        from pathlib import Path

        config_path = Path.home() / ".superqode" / "config.json"
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)

            # Load existing config
            data = {}
            if config_path.exists():
                data = json.loads(config_path.read_text())

            # Update BYOK section
            if "byok" not in data:
                data["byok"] = {}

            data["byok"]["last_provider"] = provider
            data["byok"]["last_model"] = model

            # Update history
            history = data["byok"].get("history", [])
            entry = f"{provider}/{model}"
            if entry in history:
                history.remove(entry)
            history.insert(0, entry)
            data["byok"]["history"] = history[:20]  # Keep last 20

            config_path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def _load_byok_history(self) -> list:
        """Load BYOK connection history."""
        config = self._load_byok_config()
        return config.get("history", [])

    def _connect_acp_cmd(self, args: str, log: ConversationLog):
        """Handle :connect acp command - Connect to ACP agent."""
        if not args:
            # The default picker is curated. Installed agents are always shown.
            self._show_agents(log)
            return

        command = args.strip().lower()
        if command in {"all", "--all"}:
            self._show_agents(log, include_all=True)
            return
        if command in {"enterprise", "--enterprise"}:
            self._show_agents(log, catalog_tier="enterprise")
            return
        if command in {"refresh", "sync"}:
            self._refresh_acp_registry(log)
            return

        # Clear any existing BYOK connection when switching to ACP
        if hasattr(self, "_pure_mode") and self._pure_mode:
            # Disconnect provider session if switching from BYOK to ACP
            self._pure_mode.disconnect()

        # Clear session state
        session = get_session()
        if hasattr(session, "execution_mode"):
            session.execution_mode = "acp"
        if hasattr(session, "connected_agent"):
            # Will be set by _connect_agent
            pass

        # Parse: acp <agent> [model]
        parts = args.split(maxsplit=1)
        agent_name = parts[0]
        model_hint = parts[1] if len(parts) > 1 else None
        self._connect_agent(agent_name, model_hint)

    @work(exclusive=True)
    async def _refresh_acp_registry(self, log: ConversationLog):
        """Refresh the cached official ACP Registry and reopen the picker."""
        from superqode.providers.acp_registry import get_acp_registry_agents

        agents = await get_acp_registry_agents(force_refresh=True)
        self._announce_transition(
            title="ACP Registry refreshed",
            primary=f"{len(agents)} agents available",
            detail="Featured, Enterprise, and All catalogs updated",
            severity="success",
            log=log,
            dedupe_key="acp-registry-refresh",
        )
        self._show_agents_async(log, clear_log=False)

    @work(exclusive=True)
    async def _connect_agent(self, agent_id: str, model_hint: str = None):
        log = self.query_one("#log", ConversationLog)

        try:
            from superqode.agents.discovery import get_agent_by_short_name_async

            agent = await get_agent_by_short_name_async(agent_id)

            if agent:
                session = get_session()
                session.connect_to_agent(agent)

                self.current_agent = agent.get("short_name", agent_id)
                self.current_mode = "agent"
                self.current_role = ""

                # Reset session for new agent connection
                self._is_first_message = True
                self._opencode_session_id = ""

                # Clear screen for fresh workspace
                self._clear_for_workspace(log, self.current_agent.upper())

                # For OpenCode, handle model selection
                if self.current_agent == "opencode":
                    # If model hint provided, try to auto-select it
                    if model_hint:
                        self._auto_select_opencode_model(model_hint, agent, log)
                    else:
                        self._show_opencode_models_selection(agent, log)
                elif self.current_agent == "gemini":
                    # For Gemini, handle model selection
                    if model_hint:
                        self._auto_select_gemini_model(model_hint, agent, log)
                    else:
                        self._show_gemini_models_selection(agent, log)
                elif self.current_agent == "claude":
                    # For Claude Code, handle model selection
                    if model_hint:
                        self._auto_select_claude_model(model_hint, agent, log)
                    else:
                        self._show_claude_models_selection(agent, log)
                elif self.current_agent == "codex":
                    # For Codex CLI, handle model selection
                    if model_hint:
                        self._auto_select_codex_model(model_hint, agent, log)
                    else:
                        self._show_codex_models_selection(agent, log)
                elif self.current_agent == "grok":
                    # Grok Build owns the subscription and model catalog. Keep
                    # the default unset so its signed-in account decides; an
                    # explicit model hint is forwarded through ACP.
                    self.current_model = (model_hint or "").strip()
                    self.current_provider = "xai"
                    self._awaiting_model_selection = False

                    badge = self.query_one("#mode-badge", ModeBadge)
                    badge.agent = self.current_agent
                    badge.mode = ""
                    badge.role = ""
                    badge.model = self.current_model or "grok-build"
                    badge.provider = self.current_provider
                    badge.execution_mode = "acp"

                    self._announce_transition(
                        title="Agent connected",
                        primary="Grok Build",
                        detail=(
                            f"{self.current_model} via ACP"
                            if self.current_model
                            else "Signed-in account default via ACP"
                        ),
                        severity="success",
                        log=log,
                        dedupe_key=f"agent:grok:{self.current_model or 'default'}",
                    )
                elif self.current_agent == "openhands":
                    # For OpenHands, handle model selection
                    if model_hint:
                        self._auto_select_openhands_model(model_hint, agent, log)
                    else:
                        self._show_openhands_models_selection(agent, log)
                else:
                    # For other agents, just connect
                    self.current_model = agent.get("model", "")
                    self.current_provider = agent.get("provider", "")

                    badge = self.query_one("#mode-badge", ModeBadge)
                    badge.agent = self.current_agent
                    badge.mode = ""
                    badge.role = ""
                    badge.model = self.current_model
                    badge.provider = self.current_provider

                # The legacy mode badge and the mounted top status bar are
                # separate widgets. Keep both synchronized for every ACP
                # connection, including the model-selection state.
                self._set_acp_status(self.current_model)

                model_picker_agents = {"opencode", "gemini", "claude", "codex", "openhands"}
                if self.current_agent in model_picker_agents and self._awaiting_model_selection:
                    self._announce_transition(
                        title="Agent connected",
                        primary=agent.get("name", self.current_agent),
                        detail="Choose a model to continue",
                        severity="information",
                        log=log,
                        persist=False,
                        dedupe_key=f"agent-picker:{self.current_agent}",
                    )
                elif self.current_agent not in model_picker_agents and self.current_agent != "grok":
                    self._announce_transition(
                        title="Agent connected",
                        primary=agent.get("name", self.current_agent),
                        detail=(
                            f"{self.current_model} via ACP"
                            if self.current_model
                            else "ACP session ready"
                        ),
                        severity="success",
                        log=log,
                        dedupe_key=f"agent:{self.current_agent}:{self.current_model}",
                    )
            else:
                self._announce_transition(
                    title="Agent not found",
                    primary=agent_id,
                    detail="No matching ACP agent is available",
                    severity="error",
                    log=log,
                    guidance="Run :connect acp all to review available agents.",
                )
        except Exception as e:
            self._announce_transition(
                title="Connection failed",
                primary=agent_id,
                detail=str(e),
                severity="error",
                log=log,
                guidance="Run :log verbose for startup details.",
            )
