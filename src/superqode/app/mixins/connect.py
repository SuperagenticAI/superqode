"""Connection wizard: local / BYOK / ACP connect flows."""

from __future__ import annotations
import asyncio
import json
import logging
import os
import shutil
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from textual import work

from superqode.widgets.a2a_connect import A2AConnectScreen
from superqode.widgets.uhp_connect import UHPConnectScreen
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
from superqode.providers.harness_catalog import HarnessAuthSpec

_CONNECT_LOG = logging.getLogger("superqode.connect")
_CONNECTION_KEYS = (
    "category",
    "auth_mode",
    "harness_id",
    "profile_id",
    "acp_agent",
    "openness",
    "provider",
    "model",
    "transport",
    "after_auth",
)


@dataclass
class KeyHarnessSession:
    """In-flight Open/Closed key path. Survives ``_reset_connect_selection_states``."""

    entry_id: str
    openness: str
    auth_spec: HarnessAuthSpec
    return_menu: str
    after_auth: str
    # The switch target, which is a HarnessDefinition id and need not equal
    # ``entry_id``. The harness switch reports back in this namespace, so
    # matching on the catalog id alone would drop the session for any row
    # whose ``harness_id`` differs.
    harness_id: str = ""


def _menu_history_label(menu: str) -> str:
    """Title of a connect screen, for the back control's tooltip."""
    from superqode.providers.connection_profiles import connect_menu_titles

    entry = connect_menu_titles().get(menu)
    if isinstance(entry, (tuple, list)) and entry:
        return str(entry[0])
    return str(entry or "Connect")


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

    def _connect_menu_profiles(self):
        """Profiles on the current connect screen, in the order they are drawn.

        Selection and navigation both index this list, so it has to match the
        screen rather than the registry.
        """
        from superqode.providers.connection_profiles import (
            CONNECT_MENU_KEY_MODELS,
            CONNECT_MENU_ROOT,
            display_ordered_profiles,
        )

        menu = getattr(self, "_connect_menu", CONNECT_MENU_ROOT)
        profiles = display_ordered_profiles(menu)
        if menu != CONNECT_MENU_KEY_MODELS:
            return profiles
        # A harness that allows no providers for a mode must not offer the row:
        # selecting it would open a picker with nothing in it.
        offered = [row for row in profiles if self._key_models_row_offered(row.id)]
        return offered or profiles

    def _key_models_row_offered(self, row_id: str) -> bool:
        """False when the active key-harness allows no provider for this row."""
        if row_id not in {"local", "byok"}:
            return True
        allowed = self._key_harness_allowlist(row_id)
        return allowed is None or bool(allowed)

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

        current_idx = getattr(self, "_byok_highlighted_connect_type_index", 0)
        new_idx = min(len(self._connect_menu_profiles()) - 1, current_idx + 1)
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

        profiles = self._connect_menu_profiles()
        if not profiles:
            return
        idx = getattr(self, "_byok_highlighted_connect_type_index", 0)
        if not (0 <= idx < len(profiles)):
            idx = 0
        log = self.query_one("#log", ConversationLog)
        # A selection result replaces the picker. Appending below a long picker
        # can leave the requested content outside the viewport. Cleared here as
        # well as in the dispatcher so the picker is gone before any connector
        # runs, including one that returns early without rendering anything.
        self._open_connect_screen(log)
        self._dispatch_connection_profile(profiles[idx], log)

    def action_connect_menu_back(self) -> bool:
        """Step one screen back, or let Esc cancel the picker at the root.

        Returns True when it handled the request, so Esc/`:back` can fall
        through to cancelling the picker on the root screen.
        """
        from superqode.providers.connection_profiles import (
            CONNECT_MENU_AGENTS,
            CONNECT_MENU_KEY_MODELS,
            CONNECT_MENU_ROOT,
            parent_menu,
        )

        if not getattr(self, "_awaiting_connect_type", False):
            return False

        current = getattr(self, "_connect_menu", CONNECT_MENU_ROOT)
        if current == CONNECT_MENU_ROOT:
            self._clear_key_harness_session()
            return False
        # Each screen declares its parent, so Esc walks the path the user
        # actually took instead of jumping back to the start.
        session = getattr(self, "_key_harness_session", None)
        dest = parent_menu(
            current,
            return_menu=getattr(session, "return_menu", None),
        )
        # Esc to the existing-harness screen ends the Open/Closed key flow.
        if dest == CONNECT_MENU_AGENTS or current == CONNECT_MENU_AGENTS:
            self._clear_key_harness_session()
        elif current != CONNECT_MENU_KEY_MODELS and dest == CONNECT_MENU_ROOT:
            self._clear_key_harness_session()
        log = self.query_one("#log", ConversationLog)
        self._show_connect_type_picker(log, menu=dest)
        return True

    def _show_own_harness_catalog(self, log: ConversationLog, profile_id: str = "") -> None:
        """List built-in and repository harnesses only.

        Excludes vendor and ACP agents, which belong to the other branch of
        ``:connect``.
        """
        from pathlib import Path

        from superqode.harness import list_harnesses

        try:
            entries = list_harnesses(Path.cwd())
        except Exception:  # noqa: BLE001 - fall back to the full switcher
            self._harness_cmd("", log)
            return

        if profile_id == "harness-repo":
            project = [entry for entry in entries if entry.source not in {"built-in"}]
            entries = project or entries
        self._show_harness_picker(
            log,
            catalog_entries=entries,
            subtitle="Harnesses we ship, plus any this repository defines",
        )

    def _return_to_model_step(self) -> None:
        """Reopen the model screen after backing out of a provider list."""
        from superqode.providers.connection_profiles import (
            CONNECT_MENU_KEY_MODELS,
            CONNECT_MENU_MODELS,
        )

        log = self.query_one("#log", ConversationLog)
        log.clear()
        menu = (
            CONNECT_MENU_KEY_MODELS
            if getattr(self, "_key_harness_session", None) is not None
            else CONNECT_MENU_MODELS
        )
        self._show_connect_type_picker(log, menu=menu)

    def action_browse_harnesses_from_connect(self) -> None:
        """H / typed harness: Other picker in v1, Open list in v2."""
        if not getattr(self, "_awaiting_connect_type", False):
            return
        from superqode.providers.connection_profiles import (
            CONNECT_MENU_OPEN,
            connect_menu_version,
        )

        log = self.query_one("#log", ConversationLog)
        if connect_menu_version() == "v2":
            self._show_connect_type_picker(log, menu=CONNECT_MENU_OPEN)
            return
        self._awaiting_connect_type = False
        log.clear()
        self._show_other_harnesses(log, clear_log=False)

    def _show_other_harnesses(self, log: ConversationLog, *, clear_log: bool = True) -> None:
        """Open the focused picker for harness integrations outside ACP."""
        from pathlib import Path

        from superqode.harness import optional_harnesses

        entries = optional_harnesses(Path.cwd())
        if not entries:
            log.add_error("No optional non-ACP harness integrations are available.")
            return
        self._show_harness_picker(
            log,
            include_all=False,
            clear_log=clear_log,
            catalog_entries=entries,
            subtitle="Optional non-ACP harness integrations",
        )

    def _show_uhp_harnesses(self, log: ConversationLog, args: str = "") -> None:
        """Open the UHP connect screen, or run a fully specified connect.

        A UHP server is remote, so the address comes first and the catalog is
        fetched. With no arguments this opens a picker; with arguments it runs
        the same command the shell would, so every flag keeps working.
        """
        import shlex

        from superqode.providers.uhp import DEFAULT_BASE_URL, resolve_settings

        try:
            tokens = shlex.split(args or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :connect uhp arguments: {exc}")
            return
        # `:connect uhp <url>` is the form people reach for; the flag form
        # stays available so every CLI option works here too.
        if tokens and not tokens[0].startswith("-"):
            tokens = ["--base-url", *tokens]
        if tokens:
            log.add_info("Connecting to the UHP server ...")
            self._run_cli_passthrough(["connect", "uhp", *tokens], log, "UHP harnesses")
            return

        settings = resolve_settings()
        self.push_screen(
            UHPConnectScreen(
                base_url=settings.base_url,
                default_url=DEFAULT_BASE_URL,
                max_output_tokens=settings.max_output_tokens,
            ),
            callback=lambda result: self._apply_uhp_selection(result, log),
        )

    def _apply_uhp_selection(self, result, log: ConversationLog) -> None:
        """Save the chosen server and harness, then make it the active one."""
        if result is None:
            self._ensure_input_focus()
            return
        from superqode.providers.uhp import UHPSettings, resolve_settings, save_connection

        previous = resolve_settings()
        save_connection(
            UHPSettings(
                base_url=result.base_url,
                api_key=previous.api_key,
                harness_id=result.harness_id,
                max_output_tokens=result.max_output_tokens,
            )
        )
        selected = result.harness_name or result.harness_id
        if result.max_output_tokens:
            log.add_success(
                f"UHP harness selected: {selected} · {result.max_output_tokens} token cap"
            )
        else:
            log.add_success(f"UHP harness selected: {selected}")
        # The catalog reads the saved connection, so the entry is only
        # available once the selection above has been written.
        self._harness_cmd("switch uhp", log)

    def _show_a2a_agent(self, log: ConversationLog, args: str = "") -> None:
        """Open the A2A connect screen, or run a fully specified connect.

        An A2A agent is remote, so the origin comes first and the card is
        fetched. With no arguments this opens a picker; with arguments it runs
        the same command the shell would, so every flag keeps working.
        """
        import shlex

        from superqode.a2a.connection import DEFAULT_URL, resolve_settings

        try:
            tokens = shlex.split(args or "")
        except ValueError as exc:
            log.add_error(f"Could not parse :connect a2a arguments: {exc}")
            return
        # `:connect a2a <url>` is the form people reach for; the flag form
        # stays available so every CLI option works here too.
        if tokens and not tokens[0].startswith("-"):
            tokens = ["--url", *tokens]
        if tokens:
            log.add_info("Connecting to the A2A agent ...")
            self._run_cli_passthrough(["connect", "a2a", *tokens], log, "A2A agent")
            return

        settings = resolve_settings()
        self.push_screen(
            A2AConnectScreen(
                url=settings.url,
                default_url=DEFAULT_URL,
                token=settings.token,
            ),
            callback=lambda result: self._apply_a2a_selection(result, log),
        )

    def _apply_a2a_selection(self, result, log: ConversationLog) -> None:
        """Save the chosen Agent Card origin and optional Bearer."""
        if result is None:
            self._ensure_input_focus()
            return
        from superqode.a2a.connection import A2ASettings, save_connection

        save_connection(A2ASettings(url=result.url, token=result.token))
        selected = result.name or result.url
        if result.binding:
            detail = f"{result.binding} {result.protocol_version}".rstrip()
            log.add_success(f"A2A agent connected: {selected} · {detail}")
        else:
            log.add_success(f"A2A agent connected: {selected}")
        if result.task_text:
            log.add_info(result.task_text[:2000])
        self._ensure_input_focus()

    def _begin_key_harness(
        self, profile, log: ConversationLog, *, apply_route: tuple | None = None
    ) -> None:
        """Connect an Open/Closed catalog row.

        ``switch-and-model`` (Tau, DSH, DeepAgents SDK) switches the hosted
        adapter then opens ``CONNECT_MENU_KEY_MODELS``. ``acp-attach`` opens the
        same model step without switching, because the agent keeps its own loop
        and only needs the credentials the picker resolves. The session is set
        before the extra check so a first-run install resume still opens
        KEY_MODELS, not native Plan.
        """
        from superqode.providers.connection_profiles import (
            CONNECT_MENU_CLOSED,
            CONNECT_MENU_KEY_MODELS,
            CONNECT_MENU_OPEN,
        )
        from superqode.providers.harness_catalog import get_entry

        def _drop_pending() -> None:
            self._pending_key_harness_route = None

        entry = get_entry(getattr(profile, "id", ""))
        if entry is None:
            _drop_pending()
            log.add_error("This open harness has no catalog entry.")
            return
        key_spec = next((spec for spec in entry.auth if spec.mode in {"byok", "local"}), None)
        after_auth = key_spec.after_auth if key_spec is not None else ""
        if after_auth in {"vendor-key-acp", "vendor-key-cli"}:
            _drop_pending()
            self._begin_vendor_key(profile, log)
            return
        # Both hand the loop to someone else after the model step: one over ACP,
        # one over Prime's Python RPC. Neither switches a SuperQode harness.
        attaches = (after_auth == "acp-attach" and bool(entry.acp_agent)) or (
            after_auth == "vendor-key-rpc"
        )
        if after_auth != "switch-and-model" and not attaches:
            _drop_pending()
            self._write_harness_setup_card(log, entry, key_spec)
            return
        harness_id = entry.harness_id or getattr(profile, "runtime", None) or entry.id
        if not harness_id and not attaches:
            _drop_pending()
            log.add_error("This open harness has no switch target.")
            return
        return_menu = getattr(profile, "menu", "") or CONNECT_MENU_OPEN
        if return_menu not in {CONNECT_MENU_OPEN, CONNECT_MENU_CLOSED}:
            return_menu = CONNECT_MENU_OPEN
        self._key_harness_session = KeyHarnessSession(
            entry_id=entry.id,
            openness=entry.openness,
            auth_spec=key_spec,
            return_menu=return_menu,
            after_auth=after_auth,
            harness_id=str(harness_id or ""),
        )
        self._pending_key_harness_route = apply_route
        if attaches:
            # No harness switch: the agent already owns its loop, so the only
            # question left is which credentials it is handed.
            if apply_route:
                self._pending_key_harness_route = None
                mode, provider, model = apply_route
                if mode == "local":
                    self._connect_local_mode(provider, model, log)
                else:
                    self._connect_byok_mode(provider, model, log)
                return
            if self._attach_key_harness_from_env(entry, key_spec, log):
                return
            self._connect_context_note = f"{entry.label} runs its own loop. Choose its model."
            self._show_connect_type_picker(log, menu=CONNECT_MENU_KEY_MODELS)
            return
        self._harness_cmd(f"switch {harness_id}", log)

    def _clear_key_harness_session(self) -> None:
        """Drop the Open/Closed key flow. Safe to call when none is active."""
        self._key_harness_session = None
        self._pending_key_harness_route = None

    def _key_harness_session_matches(self, harness_id: str = "") -> bool:
        """True when the in-flight key session is for this (or the active) harness.

        The caller reports a harness id or a spec path, so both the file name
        and its stem count as the same harness. ``harness_id`` is compared as
        well as ``entry_id`` because a switch answers in the harness namespace.
        """
        session = getattr(self, "_key_harness_session", None)
        if session is None:
            return False
        target = str(harness_id or "").strip()
        if not target:
            getter = getattr(self, "_active_harness_reference", None)
            if callable(getter):
                try:
                    target = str(getter() or "").strip()
                except Exception:  # noqa: BLE001 - matching must never break connect
                    target = ""
        if not target:
            return True
        path = Path(target)
        # Never a suffix test: `endswith` made a `my-tau` harness match `tau`.
        candidates = {target, path.name, path.stem}
        return bool(candidates & {session.entry_id, session.harness_id or session.entry_id})

    def _key_harness_allowlist(self, mode: str) -> frozenset[str] | None:
        """Picker filter for the active key-harness. ``None`` means all native."""
        session = getattr(self, "_key_harness_session", None)
        if session is None:
            return None
        from superqode.providers.harness_catalog import auth_allowlist, get_entry

        entry = get_entry(session.entry_id)
        if entry is None:
            return None
        allowed = auth_allowlist(entry, mode)
        if allowed is None:
            return None
        return frozenset(allowed)

    def _write_harness_setup_card(self, log: ConversationLog, entry, spec) -> None:
        """Honest card for a listed harness SuperQode cannot launch yet."""
        t = Text()
        t.append("\n  ", style=THEME["muted"])
        t.append(entry.label, style=f"bold {THEME['purple']}")
        t.append("\n\n", style=THEME["muted"])
        t.append(
            "  This harness is on the Open/Closed list so you can find it.\n", style=THEME["text"]
        )
        if (
            getattr(entry, "id", "") == "zcode"
            or getattr(entry, "readiness", "") == "not-supported"
        ):
            t.append(
                "  SuperQode cannot launch it yet — there is no ACP, CLI, or key API.\n\n",
                style=THEME["text"],
            )
        else:
            t.append(
                "  SuperQode does not start its loop from this row yet.\n\n", style=THEME["text"]
            )
        note = str(getattr(entry, "support_note", "") or "")
        if note:
            t.append(f"  {note}\n\n", style=THEME["muted"])
        if getattr(entry, "repository", ""):
            t.append("  Source:  ", style=THEME["muted"])
            t.append(f"{entry.repository}\n", style=THEME["cyan"])
        agent = getattr(entry, "acp_agent", "") or ""
        env_vars = tuple(getattr(spec, "env_vars", ()) or ()) if spec is not None else ()
        if env_vars:
            t.append("  Key:     ", style=THEME["muted"])
            t.append(f"{' or '.join(env_vars)}\n", style=THEME["yellow"])
            if agent:
                t.append(
                    "  Set that in the harness itself, then attach over ACP if it is installed.\n",
                    style=THEME["text"],
                )
            else:
                # No ACP server to hand a child env to: the vendor CLI is the
                # only thing that reads this key, so say where to put it.
                t.append(
                    "  Export it in the shell you run the harness from; it reads the key itself.\n",
                    style=THEME["text"],
                )
        else:
            t.append(
                "  Configure a provider key or local model in the harness, then return.\n",
                style=THEME["text"],
            )
        if agent:
            t.append("  ACP:     ", style=THEME["muted"])
            t.append(f":connect acp {agent}\n", style=THEME["cyan"])
        writer = getattr(log, "write_feedback", None) or getattr(log, "write", None)
        if writer is not None:
            writer(t)
        elif log is not None:
            log.add_info(
                f"Set up {entry.label} in the harness, then :connect acp {agent or entry.id}."
            )

    def _write_api_key_required_panel(
        self,
        log: ConversationLog,
        *,
        provider_name: str,
        env_vars: list[str] | tuple[str, ...],
        login_id: str,
        docs_url: str = "",
        retry: str = "",
    ) -> None:
        """Reuse the BYOK API Key Required card for a vendor harness key."""
        names = [name for name in env_vars if name]
        t = Text()
        t.append("\n  ⚠️  ", style=THEME["warning"])
        t.append("API Key Required\n\n", style=f"bold {THEME['warning']}")
        t.append("  Provider: ", style=THEME["muted"])
        t.append(f"{provider_name}\n", style=THEME["text"])
        t.append("  Required: ", style=THEME["muted"])
        t.append(f"{' or '.join(names)}\n", style=THEME["yellow"])
        # `superqode auth login` only accepts a real ProviderDef id. Naming a
        # vendor SuperQode has no provider for (jetbrains, qoder) prints a
        # command that answers "Unknown provider", so export leads instead.
        if login_id:
            t.append("  Recommended: ", style=THEME["muted"])
            t.append(f"superqode auth login {login_id}\n", style=THEME["cyan"])
        if names:
            t.append("  Or export:   " if login_id else "  Set it with: ", style=THEME["muted"])
            t.append(f"export {names[0]}='your-api-key'\n", style=THEME["cyan"])
        if docs_url:
            t.append("  Get a key:   ", style=THEME["muted"])
            t.append(f"{docs_url}\n", style=THEME["cyan"])
        if retry:
            t.append("  Retry:       ", style=THEME["muted"])
            t.append(f"{retry}\n", style=THEME["success"])
        writer = getattr(log, "write_feedback", None) or getattr(log, "write", None)
        if writer is not None:
            writer(t)

    def _clear_acp_extra_env(self) -> None:
        """Drop a Closed-key inject. Safe to call when none is set."""
        self._acp_extra_env = None
        self._acp_extra_env_agent = None
        self._pending_vendor_key = None

    def _set_acp_extra_env(self, extra_env: dict[str, str], agent: str) -> None:
        """Pin child-only extra env to one ACP agent short_name."""
        self._acp_extra_env = dict(extra_env)
        self._acp_extra_env_agent = (agent or "").strip().lower() or None

    def _retain_acp_extra_env_for(self, agent_id: str) -> None:
        """Keep extra env only when attaching the agent it was resolved for."""
        owned = (getattr(self, "_acp_extra_env_agent", None) or "").strip().lower()
        requested = (agent_id or "").strip().lower()
        if owned and owned != requested:
            self._clear_acp_extra_env()

    def _merge_acp_session_extra_env(
        self, agent_type: str, acp_extra_env: dict[str, str] | None = None
    ) -> dict[str, str]:
        """Merge session extra env into the child env if it belongs to this agent."""
        merged = dict(acp_extra_env or {})
        extra = getattr(self, "_acp_extra_env", None) or {}
        owned = (getattr(self, "_acp_extra_env_agent", None) or "").strip().lower()
        current = (agent_type or "").strip().lower()
        if extra and owned and owned == current:
            merged.update(dict(extra))
        return merged

    def _finish_vendor_key_or_teach(self, log: ConversationLog, agent: dict) -> None:
        """Teach after ACP attach; record Closed milestones only on success."""
        pending = getattr(self, "_pending_vendor_key", None)
        current = (getattr(self, "current_agent", None) or "").strip().lower()
        if isinstance(pending, dict) and (pending.get("agent") or "") == current:
            self._teach(
                "_write_connection_teaching_card",
                log,
                label=str(pending.get("label") or agent.get("name") or current),
                vendor_owned=bool(pending.get("vendor_owned", True)),
                harness=str(pending.get("harness") or current),
                model=getattr(self, "current_model", "") or "chosen by the agent",
                note=str(pending.get("note") or ""),
            )
            try:
                from superqode.app.progress import record_milestone

                record_milestone("connected_closed_harness")
                record_milestone("connected")
            except Exception:  # noqa: BLE001 - progress must never block connect
                pass
            self._pending_vendor_key = None
            return
        self._teach(
            "_write_connection_teaching_card",
            log,
            label=str(agent.get("name") or current),
            vendor_owned=True,
            harness=str(agent.get("name") or current),
            model=getattr(self, "current_model", "") or "chosen by the agent",
        )

    def _abandon_vendor_key_attach(self, agent_id: str) -> None:
        """Drop a pending Closed-key attach that never landed.

        An exclusive worker that fails for a *different* agent must not
        touch a newer droid-key staging that was queued after it.
        """
        pending = getattr(self, "_pending_vendor_key", None)
        requested = (agent_id or "").strip().lower()
        if isinstance(pending, dict) and (pending.get("agent") or "") == requested:
            self._clear_acp_extra_env()

    def _redirect_harness_only_provider(self, provider: str, log: ConversationLog) -> bool:
        """Reject SuperQode-loop BYOK for harness-only credential slots."""
        from superqode.providers.dynamic import resolve_provider_def

        provider_id = normalize_provider_id(provider)
        provider_def = resolve_provider_def(provider_id)
        if provider_def is None or not getattr(provider_def, "harness_only", False):
            return False
        if log is not None:
            log.add_info(
                f"{provider_def.name} is not a SuperQode BYOK provider. "
                "Use :connect droid-key to attach Factory Droid with FACTORY_API_KEY."
            )
        return True

    def _resolve_vendor_key(self, spec) -> tuple[str, object, str]:
        """Resolve a vendor harness key. Returns ``(key, provider_def, login_id)``.

        A stored credential wins over the environment, so a key put there with
        ``superqode auth login`` is found. ``login_id`` stays empty unless a
        real ProviderDef backs it: guessing one from the variable name
        (JETBRAINS_API_KEY -> jetbrains) names a provider that does not exist.
        """
        from superqode.providers.credentials import provider_api_key
        from superqode.providers.registry import PROVIDERS

        provider_id = (getattr(spec, "byok_provider", "") or "") if spec is not None else ""
        provider_def = PROVIDERS.get(provider_id) if provider_id else None
        resolved = provider_api_key(provider_def) if provider_def is not None else None
        if not resolved:
            for name in getattr(spec, "env_vars", ()) or ():
                value = os.environ.get(name)
                if value:
                    resolved = value
                    break
        return (resolved or ""), provider_def, (provider_id if provider_def is not None else "")

    def _write_vendor_key_required(self, log: ConversationLog, profile, entry, spec) -> None:
        """API Key Required for a vendor harness, named the way the user found it."""
        _resolved, provider_def, login_id = self._resolve_vendor_key(spec)
        if provider_def is not None:
            provider_name = provider_def.name
        elif entry is not None:
            provider_name = entry.label
        else:
            provider_name = profile.label
        docs_url = str(getattr(provider_def, "docs_url", "") or "")
        if not docs_url and entry is not None:
            docs_url = entry.homepage or entry.repository or ""
        self._write_api_key_required_panel(
            log,
            provider_name=provider_name,
            env_vars=spec.env_vars,
            login_id=login_id,
            docs_url=docs_url,
            retry=f":connect {getattr(profile, 'id', '')}",
        )

    def _require_vendor_key(self, profile, log: ConversationLog, after_auth: str) -> bool:
        """True when this row's vendor key is present; otherwise write the panel.

        Shared by the ACP and CLI closed-key paths so both gate on the same
        credential lookup and print the same card when it is missing.
        """
        from superqode.providers.harness_catalog import get_entry

        entry = get_entry(getattr(profile, "id", ""))
        spec = None
        if entry is not None:
            spec = next((item for item in entry.auth if item.after_auth == after_auth), None)
        if spec is None:
            if log is not None:
                log.add_error("This harness has no API-key path.")
            return False
        resolved, _provider_def, _login_id = self._resolve_vendor_key(spec)
        if not resolved:
            if log is not None:
                self._write_vendor_key_required(log, profile, entry, spec)
            return False
        return True

    def _key_harness_child_env(self, spec, provider_def, model: str) -> dict[str, str]:
        """Credentials for an Open row's ACP child, named from declared data only.

        Two shapes, both stated by the catalog rather than guessed here:

        * the harness reads its own variable (``GROK_CODE_XAI_API_KEY``), so
          ``spec.env_vars`` names every slot the key is written to;
        * the harness is model-agnostic and reads the provider's documented
          variable, so ``ProviderDef.env_vars`` names it instead.

        A base URL is only passed under ``spec.base_url_env``, which is the
        catalog stating that this harness reads that variable. The provider's
        own ``base_url_env`` is deliberately not a fallback: ``OLLAMA_HOST``
        describes Ollama's client, not what a third-party agent reads, and an
        endpoint under a name the agent ignores fails silently instead of
        saying the model choice did not reach it.
        """
        from superqode.providers.credentials import provider_api_key
        from superqode.providers.dynamic import resolve_base_url

        extra: dict[str, str] = {}
        key = provider_api_key(provider_def) or ""
        names = tuple(getattr(spec, "env_vars", ()) or ()) or tuple(
            getattr(provider_def, "env_vars", ()) or ()
        )
        if key:
            for name in names:
                extra[name] = key
        base_url_env = getattr(spec, "base_url_env", "") or ""
        base_url = resolve_base_url(provider_def) if base_url_env else ""
        if base_url and base_url_env:
            extra[base_url_env] = base_url
        return extra

    def _attach_key_harness_over_acp(
        self, provider: str, model: str, provider_def, log: ConversationLog
    ) -> bool:
        """Hand the chosen model to an Open row's own agent over ACP.

        Returns True when the attach owns this selection, so the caller stops
        before starting SuperQode's own loop. The agent runs the loop here; the
        model picker only decided which credentials it is given.
        """
        from superqode.providers.harness_catalog import get_entry
        from superqode.providers.registry import ProviderCategory

        session = getattr(self, "_key_harness_session", None)
        if session is None or session.after_auth != "acp-attach":
            return False
        entry = get_entry(session.entry_id)
        agent = (entry.acp_agent if entry is not None else "") or ""
        if entry is None or not agent:
            # Nothing to attach to. Fall through so the picker still connects
            # SuperQode's own loop rather than dead-ending on the selection.
            return False
        spec = next((item for item in entry.auth if item.mode in {"byok", "local"}), None)
        is_local = bool(provider_def and provider_def.category == ProviderCategory.LOCAL)

        extra_env = self._key_harness_child_env(spec, provider_def, model)
        if not extra_env and not is_local:
            # A cloud provider with no resolvable key would attach an agent that
            # fails on its first model call, so ask for the key instead.
            if log is not None:
                self._write_api_key_required_panel(
                    log,
                    provider_name=(provider_def.name if provider_def else provider),
                    env_vars=(
                        tuple(getattr(spec, "env_vars", ()) or ())
                        or tuple(getattr(provider_def, "env_vars", ()) or ())
                    ),
                    login_id=provider,
                    docs_url=str(getattr(provider_def, "docs_url", "") or ""),
                    retry=f":connect {entry.id}",
                )
            return True

        if not extra_env and log is not None:
            # A local endpoint neither the catalog nor the provider names a
            # variable for. Attaching is still right, but saying nothing would
            # imply the picked model reached the agent.
            log.add_info(
                f"{entry.label} keeps its own model configuration: SuperQode knows no "
                f"environment variable it reads for {provider}. Set {model or 'the model'} "
                "inside the agent if it does not already use it."
            )
        self._finish_key_harness_attach(
            entry,
            agent,
            extra_env,
            log,
            provider=provider,
            model=model,
            auth_mode="local" if is_local else "byok",
        )
        return True

    def _attach_key_harness_over_rpc(
        self, provider: str, model: str, provider_def, log: ConversationLog
    ) -> bool:
        """Run Prime Agent on the chosen model through its Python RPC backend.

        Prime owns the loop here as much as an ACP agent does, but it is not an
        ACP process: a cloud provider is handed its key in the child env, and a
        local endpoint is registered in Prime's own ``models.json``, which is
        the mechanism Prime documents for custom OpenAI-compatible servers.
        """
        from superqode.providers import prime_agent as prime
        from superqode.providers.credentials import provider_api_key
        from superqode.providers.dynamic import resolve_base_url
        from superqode.providers.harness_catalog import get_entry
        from superqode.providers.registry import ProviderCategory

        session = getattr(self, "_key_harness_session", None)
        if session is None or session.after_auth != "vendor-key-rpc":
            return False
        entry = get_entry(session.entry_id)
        if entry is None:
            return False
        if not prime.is_installed():
            if log is not None:
                log.add_error("Prime Agent is not installed.")
                log.add_info(f"Install: {prime.INSTALL_HINT}")
            return True

        is_local = bool(provider_def and provider_def.category == ProviderCategory.LOCAL)
        extra_env: dict[str, str] = {}
        if is_local:
            base_url = resolve_base_url(provider_def) or ""
            if not base_url:
                if log is not None:
                    log.add_error(
                        f"SuperQode does not know a base URL for {provider}, "
                        "so Prime cannot be pointed at it."
                    )
                return True
            # Prime reads custom providers as OpenAI-compatible endpoints.
            endpoint = base_url.rstrip("/")
            if not endpoint.endswith("/v1"):
                endpoint = f"{endpoint}/v1"
            try:
                _providers, _models, path = prime.merge_local_models(
                    {provider: (endpoint, [model])}
                )
            except Exception as exc:  # noqa: BLE001 - report, never half-connect
                if log is not None:
                    log.add_error(f"Could not register {provider} with Prime Agent: {exc}")
                return True
            if log is not None:
                log.add_info(f"Registered {provider}/{model} at {endpoint} in {path}.")
        else:
            key = provider_api_key(provider_def) or ""
            names = tuple(getattr(provider_def, "env_vars", ()) or ())
            if not key or not names:
                if log is not None:
                    self._write_api_key_required_panel(
                        log,
                        provider_name=(provider_def.name if provider_def else provider),
                        env_vars=names,
                        login_id=provider,
                        docs_url=str(getattr(provider_def, "docs_url", "") or ""),
                        retry=f":connect {entry.id}",
                    )
                return True
            for name in names:
                extra_env[name] = key

        connected = self._connect_prime_rpc(
            f"{provider}/{model}" if provider and model else model,
            log,
            extra_env=extra_env,
        )
        if not connected:
            return True
        self._save_connection_config(
            category=session.return_menu,
            auth_mode="local" if is_local else "byok",
            harness_id=session.harness_id or session.entry_id,
            profile_id=session.entry_id,
            acp_agent="",
            openness=session.openness,
            provider=provider,
            model=model,
            transport="Python RPC",
            after_auth=session.after_auth,
        )
        _CONNECT_LOG.info(
            "connect.completed category=%s auth_mode=%s harness_id=%s provider=%s after_auth=%s",
            session.return_menu,
            "local" if is_local else "byok",
            session.entry_id,
            provider,
            session.after_auth,
        )
        if session.openness == "open":
            record = getattr(self, "_record_milestone", None)
            if callable(record):
                record("connected_open_harness")
        self._clear_key_harness_session()
        return True

    def _attach_key_harness_from_env(self, entry, spec, log: ConversationLog) -> bool:
        """Attach straight away when the harness's own key is already exported.

        Rows like Grok Build hide the provider picker (``byok_providers=()``)
        because the key is the vendor's, not a provider choice. Asking such a
        user to pick a model would be a step with one wrong answer, so an
        exported ``GROK_CODE_XAI_API_KEY`` connects directly.
        """
        agent = (getattr(entry, "acp_agent", "") or "") if entry is not None else ""
        if not agent or spec is None:
            return False
        names = (*(spec.env_vars or ()), *(spec.optional_env or ()))
        extra_env = {}
        for name in names:
            value = os.environ.get(name, "").strip()
            if value:
                extra_env[name] = value
                break
        if not extra_env:
            return False
        base_url_env = getattr(spec, "base_url_env", "") or ""
        if base_url_env:
            base_url = os.environ.get(base_url_env, "").strip()
            if base_url:
                extra_env[base_url_env] = base_url
        self._finish_key_harness_attach(
            entry,
            agent,
            extra_env,
            log,
            provider="",
            model="",
            auth_mode="byok",
        )
        return True

    def _finish_key_harness_attach(
        self,
        entry,
        agent: str,
        extra_env: dict[str, str],
        log: ConversationLog,
        *,
        provider: str,
        model: str,
        auth_mode: str,
    ) -> None:
        """Attach the agent, pin its child env, then record and end the session."""
        session = getattr(self, "_key_harness_session", None)
        return_menu = getattr(session, "return_menu", "") or ""
        openness = getattr(session, "openness", "") or ""
        after_auth = getattr(session, "after_auth", "") or "acp-attach"

        # Not a subscription: nothing to strip, and no vendor pin to inherit.
        self._acp_subscription_vendor = None
        self._connecting_profile_id = entry.id
        # A named attach clears leftover extra env, so pin ours after it returns.
        self._connect_acp_cmd(agent, log)
        if provider and model:
            note = f"{provider}/{model} through the agent's own loop."
        elif provider:
            note = f"{provider} through the agent's own loop."
        else:
            note = "API key path, through the agent's own loop."
        self._pending_vendor_key = {
            "agent": agent.strip().lower(),
            "label": entry.label,
            "vendor_owned": bool(entry.vendor_owned),
            "harness": agent,
            "note": note,
        }
        if extra_env:
            self._set_acp_extra_env(extra_env, agent)
        self._save_connection_config(
            category=return_menu,
            auth_mode=auth_mode,
            harness_id=entry.id,
            profile_id=entry.id,
            acp_agent=agent,
            openness=openness,
            provider=provider,
            model=model,
            transport="ACP",
            after_auth=after_auth,
        )
        _CONNECT_LOG.info(
            "connect.completed category=%s auth_mode=%s harness_id=%s provider=%s after_auth=%s",
            return_menu,
            auth_mode,
            entry.id,
            provider,
            after_auth,
        )
        if openness == "open":
            record = getattr(self, "_record_milestone", None)
            if callable(record):
                record("connected_open_harness")
        self._clear_key_harness_session()

    def _begin_vendor_key_cli(self, profile, log: ConversationLog) -> None:
        """Closed key path for a harness SuperQode cannot drive over ACP.

        Muse Code has no ACP server and no headless mode SuperQode consumes, so
        the key cannot be handed to a child process here. Gate on the key, then
        state plainly that the user runs the vendor CLI and it reads that key.
        """
        from superqode.providers.harness_catalog import get_entry

        if not self._require_vendor_key(profile, log, "vendor-key-cli"):
            return
        entry = get_entry(getattr(profile, "id", ""))
        spec = None
        if entry is not None:
            spec = next(
                (item for item in entry.auth if item.after_auth == "vendor-key-cli"),
                None,
            )
        self._write_harness_setup_card(log, entry, spec)

    def _begin_vendor_key(self, profile, log: ConversationLog) -> None:
        """Vendor key path: API Key Required, then vendor ACP with child-only env.

        Used by Closed rows and by Open rows that have a locked vendor key
        (no SuperQode model picker). Resolves a stored credential then env.
        Never setdefault into the SuperQode process — that would make a later
        subscription connect see and strip the key.
        """
        from superqode.providers.harness_catalog import get_entry

        entry = get_entry(getattr(profile, "id", ""))
        spec = None
        if entry is not None:
            spec = next(
                (item for item in entry.auth if item.after_auth == "vendor-key-acp"),
                None,
            )
            if spec is None:
                spec = next((item for item in entry.auth if item.mode == "byok"), None)
        if spec is None:
            if log is not None:
                log.add_error("This harness has no API-key path.")
            return

        resolved, _provider_def, _login_id = self._resolve_vendor_key(spec)
        if not resolved:
            if log is not None:
                self._write_vendor_key_required(log, profile, entry, spec)
            return

        extra_env: dict[str, str] = {}
        if spec.inject_env:
            for name in spec.env_vars:
                extra_env[name] = resolved
                break

        # Key path is never a subscription: do not strip, do not inherit a
        # previous vendor pin. `_connect_acp_cmd` clears leftover extra_env;
        # we re-set it after, because ACPClient is built on the first prompt.
        # Teaching and milestones wait until `_connect_agent` actually succeeds.
        self._acp_subscription_vendor = None
        agent = (entry.acp_agent if entry is not None else None) or getattr(
            profile, "acp_agent", ""
        )
        # Named ACP attach clears leftover extra env; re-pin after it returns.
        self._connect_acp_cmd(agent or "", log)
        self._pending_vendor_key = {
            "agent": (agent or "").strip().lower(),
            "label": entry.label if entry is not None else profile.label,
            "vendor_owned": bool(entry.vendor_owned) if entry is not None else True,
            "harness": agent or "",
            "note": (
                "API key path — not your Droid CLI login."
                if entry is not None and entry.id == "droid-key"
                else "API key path — not your subscription login."
            ),
        }
        self._set_acp_extra_env(extra_env, agent or "")

    #: Vendor-specific controls available after connecting, as
    #: (name matchers, command, description).
    _VENDOR_COMMANDS: tuple[tuple[tuple[str, ...], str, str], ...] = (
        (("antigravity", "agy"), ":agy", "profiles, models and Google sign-in"),
        (("antigravity", "agy"), ":antigravity status", "which Antigravity route is live"),
        (("copilot",), ":copilot", "switch Copilot models and check your plan"),
        (("codex",), ":codex model", "pick the Codex model"),
        (("codex",), ":codex effort", "set reasoning effort"),
        (("grok", "xai"), ":grok", "Grok routes, models and sign-in"),
        (("claude",), ":claude", "Claude Agent SDK options"),
        (("devin",), ":acp devin", "Devin session controls"),
        (("droid", "factory"), ":acp droid", "Droid model and session controls"),
        (("fx",), ":fx", "fx status, Vercel login, and connect"),
    )

    def _vendor_command_hints(self, *names: str) -> list[tuple[str, str]]:
        """Commands worth knowing for the product that was just connected."""
        haystack = " ".join(name.lower() for name in names if name)
        seen: set[str] = set()
        hints: list[tuple[str, str]] = []
        for matchers, command, description in self._VENDOR_COMMANDS:
            if command in seen:
                continue
            if any(matcher in haystack for matcher in matchers):
                seen.add(command)
                hints.append((command, description))
        return hints

    def _teach(self, method: str, *args, **kwargs) -> None:
        """Call an informational renderer, ignoring any failure.

        These cards describe a connection that already succeeded, so a
        rendering error must not surface as a connection error.
        """
        try:
            renderer = getattr(self, method, None)
            if renderer is not None:
                renderer(*args, **kwargs)
        except Exception:  # noqa: BLE001 - teaching is never load-bearing
            pass

    def _write_connection_teaching_card(
        self,
        log: ConversationLog,
        *,
        label: str,
        vendor_owned: bool,
        harness: str = "",
        model: str = "",
        note: str = "",
    ) -> None:
        """Summarise the connection and the commands now available."""
        if log is None:
            return

        t = Text()
        t.append("\n  ✓ ", style=f"bold {THEME['success']}")
        t.append(f"Connected — {label}\n\n", style=f"bold {THEME['text']}")
        if note:
            t.append(f"    {note}\n\n", style=THEME["muted"])

        t.append("    Harness   ", style=THEME["dim"])
        if vendor_owned:
            t.append(f"{harness or label} ", style=THEME["text"])
            t.append("(vendor-owned)\n", style=THEME["muted"])
            t.append("    Model     ", style=THEME["dim"])
            t.append(f"{model or 'chosen by the agent'}\n", style=THEME["muted"])
        else:
            t.append(f"{harness or 'core'} ", style=THEME["text"])
            t.append("(SuperQode, yours to inspect and change)\n", style=THEME["muted"])
            t.append("    Model     ", style=THEME["dim"])
            t.append(f"{model or 'not set'}\n", style=THEME["text"])
        t.append("    Session   ", style=THEME["dim"])
        t.append("durable — survives switching to any other harness\n\n", style=THEME["text"])

        t.append("    You now also have  ", style=THEME["dim"])
        t.append(
            ":memory  :share  :tree  :plan  :eval  :trust\n\n",
            style=THEME["cyan"],
        )

        # Surface the product's own model and profile controls.
        hints = self._vendor_command_hints(label, harness)
        if hints:
            product = label.replace(" subscription", "").split(" · ")[0].strip()
            t.append(f"    {product} commands\n", style=f"bold {THEME['text']}")
            width = max(len(command) for command, _ in hints)
            for command, description in hints:
                t.append(f"      {command:<{width}}  ", style=f"bold {THEME['cyan']}")
                t.append(f"{description}\n", style=THEME["muted"])
            t.append("\n", style="")

        t.append("    When you're ready\n", style=f"bold {THEME['text']}")
        rows = [
            (
                ":harness switch workbench" if vendor_owned else ":harness",
                "same session, our harness" if vendor_owned else "swap the tool loop, keep context",
            ),
            (":explore", "everything else available here"),
        ]
        width = max(len(command) for command, _ in rows)
        for command, description in rows:
            t.append(f"      {command:<{width}}  ", style=f"bold {THEME['cyan']}")
            t.append(f"{description}\n", style=THEME["muted"])
        log.write(t)

    def _reset_connect_selection_states(self) -> None:
        """Clear transient connect-flow selection state so flows don't interfere.

        Must not clear ``_key_harness_session``. That object lives until a
        successful connect, an explicit cancel, or Esc back to the agents menu.
        """
        from superqode.providers.connection_profiles import CONNECT_MENU_ROOT

        self._awaiting_connect_type = False
        self._connect_menu = CONNECT_MENU_ROOT
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

    def _open_connect_screen(self, log: ConversationLog) -> None:
        """Start a connect step on a clean screen.

        Each step replaces the one before it. Appending under the list the user
        just chose from leaves the previous rows above the result, so a new
        screen reads as more of the same page and it is not obvious the choice
        landed or that the prompt is ready.
        """
        if log is None:
            return
        try:
            log.clear()
            log.scroll_home(animate=False)
            log.auto_scroll = True
        except Exception:  # noqa: BLE001 - a log that cannot reset still renders
            pass
        # What lands here is a result, not a step. Marking it keeps back
        # pointing at the list it was chosen from instead of the screen above.
        try:
            self._history.detach()
            self._sync_navigation_controls()
        except Exception:  # noqa: BLE001 - navigation chrome must never block a connect
            pass

    def _dispatch_connection_profile(self, profile, log: ConversationLog) -> None:
        """Route a chosen connection profile to its connector.

        See ``providers/connection_profiles.py`` for the connector semantics.
        Reuses the existing per-connector handlers so the BYOK/local/ACP flows
        are unchanged.

        The screen is cleared here rather than at each call site: selecting by
        Enter used to clear while a click or typed number did not, so the same
        choice landed on a clean screen or under the old list depending on how
        it was made.

        ``KeyHarnessSession`` survives the reset so Local/BYOK from KEY_MODELS
        still know which harness they belong to. Any other connector ends that
        flow so a later Core switch does not inherit KEY_MODELS / persist.
        """
        self._reset_connect_selection_states()
        self._open_connect_screen(log)
        conn = profile.connector
        if conn not in {"byok", "local", "key-harness"}:
            self._clear_key_harness_session()
        if getattr(profile, "id", "") == "copilot-acp" and log is not None:
            log.add_info(
                "`:connect copilot-acp` now points at `:connect copilot-cli`. "
                "Both drive the Copilot CLI over ACP; `:connect copilot` uses the SDK."
            )
        if not profile.available and log is not None:
            # Grok exposes a device-auth flow that SuperQode can safely relay
            # while the vendor CLI remains the credential owner.
            if conn == "acp" and getattr(profile, "id", "") == "grok":
                self._begin_subscription_login(
                    "grok",
                    log,
                    on_success=lambda: self._connect_acp_cmd("grok", log),
                    reason="A local Grok subscription login is required.",
                )
                return
            # Prime Agent has no login subcommand, so the handoff runs the
            # binary bare and the user signs in with its own `/login`.
            if getattr(profile, "id", "") == "prime-agent":
                from superqode.providers import prime_agent as prime

                if prime.is_installed():
                    self._begin_subscription_login(
                        "prime-agent",
                        log,
                        on_success=lambda: self._connect_prime_rpc("", log),
                        reason=(
                            "Prime Agent needs a provider before it can call a model. "
                            "SuperQode will hand over the terminal; run /login there, "
                            "then quit."
                        ),
                    )
                    return
            # Only the ACP channel has no setup path of its own. Every other
            # connector's handler reports what is missing and what to do about
            # it: the dependency install picker (copilot, runtime), an API key
            # panel (byok, grok-api), a readiness report (external-cli), or the
            # vendor's install hint (prime-rpc). Answering here on their behalf
            # replaces guidance the user can act on with a dead end, and the
            # picker connectors are menus that must always open.
            if conn == "acp":
                log.add_info(f"{profile.label} needs setup: {profile.unavailable_hint}")
                return
        if conn == "copilot":
            self._connect_copilot_subscription(profile, log)
        elif conn == "prime-rpc":
            self._connect_prime_rpc("", log)
        elif conn == "runtime":
            # Self-contained runtime (e.g. Codex) — auto-connects in _runtime_cmd.
            self._runtime_cmd(profile.runtime or "", log)
        elif conn == "acp":
            # A specific ACP agent by short_name (Claude, Grok Build, …).
            self._apply_subscription_billing_policy(profile, log)
            self._connecting_profile_id = getattr(profile, "id", "") or ""
            self._connect_acp_cmd(profile.acp_agent or "", log)
        elif conn == "byok":
            # An acp-attach session keeps this picker: the selection is diverted
            # to the agent in _connect_byok_mode rather than at the menu.
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
        elif conn == "protocols-menu":
            from superqode.providers.connection_profiles import CONNECT_MENU_PROTOCOLS

            self._show_connect_type_picker(log, menu=CONNECT_MENU_PROTOCOLS)
        elif conn == "a2a-picker":
            self._show_a2a_agent(log)
        elif conn == "uhp-picker":
            self._show_uhp_harnesses(log)
        elif conn == "harness-picker":
            self._show_other_harnesses(log)
        elif conn == "open-harness-picker":
            from superqode.providers.connection_profiles import CONNECT_MENU_OPEN

            if getattr(profile, "id", "") == "other-harnesses":
                self._connect_context_note = "Other harnesses now live under Open harnesses."
            self._show_connect_type_picker(log, menu=CONNECT_MENU_OPEN)
        elif conn == "closed-harness-picker":
            from superqode.providers.connection_profiles import CONNECT_MENU_CLOSED

            self._show_connect_type_picker(log, menu=CONNECT_MENU_CLOSED)
        elif conn == "key-harness":
            self._begin_key_harness(profile, log)
        elif conn == "vendor-key":
            self._begin_vendor_key(profile, log)
        elif conn in {"agent-picker", "subscription-picker"}:
            from superqode.providers.connection_profiles import CONNECT_MENU_AGENTS

            self._show_connect_type_picker(log, menu=CONNECT_MENU_AGENTS)
        elif conn == "model-picker":
            from superqode.providers.connection_profiles import CONNECT_MENU_MODELS

            self._show_connect_type_picker(log, menu=CONNECT_MENU_MODELS)
        elif conn == "build-picker":
            from superqode.providers.connection_profiles import CONNECT_MENU_BUILD

            self._show_connect_type_picker(log, menu=CONNECT_MENU_BUILD)
        elif conn == "plan-picker":
            from superqode.providers.connection_profiles import CONNECT_MENU_PLAN

            self._show_connect_type_picker(log, menu=CONNECT_MENU_PLAN)
        elif conn == "vendor-picker":
            from superqode.providers.connection_profiles import CONNECT_MENU_VENDORS

            self._show_connect_type_picker(log, menu=CONNECT_MENU_VENDORS)
        elif conn == "grok-api":
            # Plan route runs our harness on xAI models, as `:grok api` does.
            self._grok_api_cmd("", log)
        elif conn == "harness-picker-menu":
            from superqode.providers.connection_profiles import CONNECT_MENU_HARNESS

            self._show_connect_type_picker(log, menu=CONNECT_MENU_HARNESS)
        elif conn == "harness-use":
            # Switching confirms the harness, then prompts for the model.
            self._harness_cmd(f"switch {profile.runtime or 'core'}", log)
        elif conn == "harness-catalog":
            # Remember the entry point so Esc returns to the harness step.
            self._harness_picker_from_connect = True
            self._show_own_harness_catalog(log, profile.id)
        elif conn == "harness-import":
            self._harness_import_picker(log)
        elif conn == "harness-preset":
            self._show_harness_preset_picker(log)
        elif conn == "harness-wizard":
            self._start_harness_wizard_flow(log)
        elif conn == "harness-blank":
            self._scaffold_blank_harness(log)
        elif conn == "external-cli":
            profile_id = getattr(profile, "id", "")
            if profile_id == "antigravity":
                self._antigravity_cmd("connect", log)
            elif profile_id == "muse":
                self._show_muse_connect(log)
            elif profile_id == "muse-key":
                # Closed key row, not the account row: gate on META_API_KEY,
                # then say what SuperQode can and cannot do with it.
                self._begin_vendor_key_cli(profile, log)
            else:
                log.add_error(
                    f"Unsupported external CLI profile: {getattr(profile, 'id', profile)}"
                )
        else:
            log.add_error(f"Unknown connection type: {getattr(profile, 'id', profile)}")

    def _connect_prime_rpc(
        self,
        selector: str,
        log: ConversationLog,
        *,
        pure=None,
        select_default: bool = True,
        session_id: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> bool:
        """Connect Prime Agent through the native Python RPC HarnessSpec backend.

        ``extra_env`` reaches the Prime process only, which is how the Open
        key row hands over a provider key without exporting it here.
        """
        from pathlib import Path

        from superqode.providers import prime_agent as prime

        if not prime.is_installed():
            log.add_error("Prime Agent is not installed.")
            log.add_info(f"Install: {prime.INSTALL_HINT}")
            return False

        chosen = (selector or "").strip()
        if chosen and hasattr(self, "_prime_set_opts"):
            self._prime_set_opts(model=chosen)
        elif not chosen and hasattr(self, "_prime_opts"):
            chosen = self._prime_opts().model

        pure = pure or self._ensure_pure_mode()
        if select_default:
            import dataclasses

            from superqode.harness import get_harness_template

            spec = get_harness_template("prime-agent-python")
            opts = self._prime_opts() if hasattr(self, "_prime_opts") else None
            args: list[str] = []
            environment: dict[str, str] = {}
            if opts is not None:
                if opts.goal:
                    args.extend(("--goal", opts.goal))
                    if opts.goal_token_budget and opts.goal_token_budget > 0:
                        args.extend(("--goal-token-budget", str(opts.goal_token_budget)))
                if opts.autonomous:
                    args.append("--autonomous")
                    for gate in opts.gates:
                        if str(gate).strip():
                            args.extend(("--autonomous-gate", str(gate).strip()))
                environment.update(opts.env())
            # Last, so a key resolved for this connection wins over a pinned
            # launch option that happens to use the same name.
            environment.update(dict(extra_env or {}))
            runtime = dataclasses.replace(
                spec.runtime,
                config={"prime_agent": {"args": args, "env": environment}},
            )
            pure.set_harness(dataclasses.replace(spec, runtime=runtime))
            os.environ["SUPERQODE_HARNESS"] = "prime-agent-python"

        # The subscription and ACP routes are alternatives. Stop an existing
        # ACP process before making Python RPC authoritative for input routing.
        if getattr(self, "_acp_client", None):
            try:
                if getattr(self, "_acp_loop_runner", None) is not None:
                    self._acp_loop_runner.run(self._acp_client.stop())
                else:
                    asyncio.create_task(self._acp_client.stop())
            except Exception:  # noqa: BLE001 - stale ACP teardown is best effort
                pass
            self._acp_client = None
            self._acp_client_key = None

        provider, model = prime.split_selector(chosen)
        if not provider and not model:
            provider, model = pure._resolve_harness_route()
        pure.connect(
            provider=provider,
            model=model,
            working_directory=Path.cwd(),
            session_id=session_id,
        )
        self._install_pure_permission_bridge(pure, log)

        session = get_session()
        session.execution_mode = "prime-rpc"
        self.current_mode = "agent"
        self.current_agent = "prime-agent"
        self.current_provider = provider or "prime"
        self.current_model = model

        try:
            badge = self.query_one("#mode-badge", ModeBadge)
            badge.mode = ""
            badge.role = ""
            badge.agent = "prime-agent"
            badge.model = model or "Prime default"
            badge.provider = provider or "prime"
            badge.execution_mode = "prime-rpc"
        except Exception:  # noqa: BLE001 - connection works without mounted chrome
            pass

        log.add_success(
            "Prime Agent connected through prime-agent-python-client (native Python RPC)."
        )
        route = f"{provider}/{model}" if provider and model else model or "Prime configured default"
        log.add_info(f"Model route: {route} · ACP alternative: :connect acp prime-agent")
        return True

    def _muse_cmd(self, args: str, log: ConversationLog) -> None:
        """Handle `:muse` subcommands.

        Sign-in runs Meta's own `muse login` through the shared subscription
        login flow, so SuperQode never implements Meta's OAuth and never copies
        the resulting token.
        """
        sub = (args or "").strip().split(maxsplit=1)
        action = sub[0].lower() if sub and sub[0].strip() else "connect"

        if action in {"login", "auth", "signin", "sign-in"}:
            # Detection first: an existing session is never disturbed, and the
            # browser is only ever launched after an explicit confirmation.
            started = self._begin_subscription_login(
                "muse",
                log,
                on_success=lambda: self._show_muse_connect(log),
                reason="Muse Code needs a Meta account before it can call the model.",
            )
            if not started:
                log.add_info("Muse Code already has a credential.")
                self._show_muse_connect(log)
        elif action in {"connect", "status", "doctor"}:
            self._show_muse_connect(log)
        elif action in {"help", "?"}:
            log.add_info("Usage: :muse [connect|login|status|help]")
        else:
            log.add_error(f"Unknown muse command: {action}")
            log.add_info("Usage: :muse [connect|login|status|help]")

    def _fx_cmd(self, args: str, log: ConversationLog) -> None:
        """Handle `:fx` subcommands.

        Sign-in runs Vercel's own `fx login` through the shared subscription
        login flow. SuperQode never copies `~/.fx/auth.json`.
        """
        sub = (args or "").strip().split(maxsplit=1)
        action = sub[0].lower() if sub and sub[0].strip() else "status"

        if action in {"login", "auth", "signin", "sign-in"}:
            started = self._begin_subscription_login(
                "fx",
                log,
                on_success=lambda: self._connect_fx(log),
                reason="fx needs a Vercel login before it can spend AI Gateway credits.",
            )
            if not started:
                log.add_info("fx already has a Vercel login.")
                self._connect_fx(log)
        elif action == "connect":
            self._connect_fx(log)
        elif action in {"status", "doctor"}:
            self._show_fx_status(log)
        elif action in {"help", "?"}:
            log.add_info("Usage: :fx [connect|login|status|help]")
        else:
            log.add_error(f"Unknown fx command: {action}")
            log.add_info("Usage: :fx [connect|login|status|help]")

    def _connect_fx(self, log: ConversationLog) -> None:
        """Attach fx over ACP through the Subscriptions profile."""
        from superqode.providers.connection_profiles import get_connection_profile

        self._dispatch_connection_profile(get_connection_profile("fx"), log)

    def _show_fx_status(self, log: ConversationLog) -> None:
        """Report fx install, Vercel login, and leftover Gateway-key state."""
        from superqode.providers.subscription_env import diverting_api_keys

        installed = shutil.which("fx") is not None
        signed_in = installed and (Path.home() / ".fx" / "auth.json").exists()
        leftover_key = bool(diverting_api_keys("fx"))
        auth_path = Path.home() / ".fx" / "auth.json"

        t = Text()
        t.append("\n  fx\n\n", style=f"bold {THEME['text']}")
        t.append("    Status    ", style=THEME["muted"])
        if not installed:
            t.append("not installed\n", style=THEME["warning"])
        elif signed_in:
            t.append("installed, Vercel login found\n", style=THEME["success"])
        else:
            t.append("installed, no Vercel login detected\n", style=THEME["warning"])
        t.append("    Harness   ", style=THEME["muted"])
        t.append("fx owns the loop (Apache-2.0, experimental)\n", style=THEME["text"])
        t.append("    Models    ", style=THEME["muted"])
        t.append("Vercel AI Gateway credits\n", style=THEME["dim"])

        if leftover_key:
            t.append("\n  AI_GATEWAY_API_KEY is set in this environment.\n", style=THEME["warning"])
            t.append("  :connect fx ignores it so the session stays on ", style=THEME["muted"])
            t.append("fx login", style=THEME["cyan"])
            t.append(".\n", style=THEME["muted"])
            t.append("  Spend that key with ", style=THEME["muted"])
            t.append(":connect fx-key", style=THEME["cyan"])
            t.append(".\n", style=THEME["muted"])

        if not installed:
            t.append("\n  Install:\n", style=THEME["muted"])
            t.append("    curl -fsSL https://fx.sh/setup.sh | bash\n", style=THEME["cyan"])
            t.append("  Then sign in:\n", style=THEME["muted"])
            t.append("    fx login\n", style=THEME["cyan"])
            t.append("  Or from SuperQode: ", style=THEME["muted"])
            t.append(":fx login\n", style=THEME["cyan"])
            log.write(t)
            return

        if not signed_in:
            t.append("\n  No credential found at ", style=THEME["muted"])
            t.append(str(auth_path), style=THEME["dim"])
            t.append(".\n", style=THEME["muted"])
            t.append("  Sign in with Vercel's own CLI:\n", style=THEME["muted"])
            t.append("    fx login\n", style=THEME["cyan"])
            t.append("  Or run it from here: ", style=THEME["muted"])
            t.append(":fx login\n", style=THEME["cyan"])
        else:
            t.append("\n  Connect with ", style=THEME["muted"])
            t.append(":fx connect", style=THEME["cyan"])
            t.append(" or ", style=THEME["muted"])
            t.append(":connect fx", style=THEME["cyan"])
            t.append(".\n", style=THEME["muted"])
        log.write(t)

    def _interactive_login_handoff(self, spec, log: ConversationLog) -> None:
        """Give a vendor's interactive sign-in the real terminal.

        Some vendor logins draw their own menu, wait on keys, and open the
        browser themselves rather than printing a device code. Piping such a
        login denies it a TTY, so it never completes and its exit code would be
        mistaken for success. SuperQode suspends itself and hands over instead.

        Only ever reached after the consent prompt, so nothing launches a
        browser without the user asking for it.
        """
        import subprocess

        from superqode.providers.subscription_login import binary_path, login_command

        binary = binary_path(spec)
        if binary is None:
            self._subscription_login_on_success = None
            log.add_error(f"The {spec.label} CLI is not installed.")
            for line in spec.install_hint.splitlines():
                if line.strip():
                    log.add_info(line)
            return

        try:
            with self.app.suspend():
                completed = subprocess.run(login_command(spec))
        except Exception as exc:  # noqa: BLE001 - surface any handoff failure
            self._subscription_login_on_success = None
            log.add_error(f"Could not run `{spec.binary} login`: {exc}")
            return

        # The vendor's own credential store is the authority. A clean exit is
        # not enough on its own: Muse can sign in and then revoke the session
        # when the account has no payment method.
        from superqode.providers.subscription_login import MUSE_BILLING_HINT, has_local_login

        if has_local_login(spec):
            log.add_info(f"Signed in to {spec.label}.")
        else:
            log.add_error(f"{spec.label} did not leave a usable credential.")
            if completed.returncode != 0:
                log.add_info(f"`{spec.binary} login` exited {completed.returncode}.")
            if spec.id == "muse":
                log.add_info(MUSE_BILLING_HINT)
        on_success = getattr(self, "_subscription_login_on_success", None)
        self._subscription_login_on_success = None
        if has_local_login(spec) and callable(on_success):
            on_success()
        elif spec.id == "muse":
            self._show_muse_connect(log)

    def _show_muse_connect(self, log: ConversationLog) -> None:
        """Report Muse Code readiness and hand the user a command to run.

        Muse Code 0.1.0 exposes no ACP server, and SuperQode does not consume
        its headless JSONL events yet, so this route stays honest: it reports
        what is installed and signed in rather than pretending we can stream
        its tool calls. The subscription billing rule still applies, because
        Muse prefers META_API_KEY over the account login this route selects.
        """
        from superqode.providers.connection_profiles import _muse_auth_path, _muse_signed_in
        from superqode.providers.subscription_env import diverting_api_keys

        installed = shutil.which("muse") is not None
        signed_in = _muse_signed_in()
        env_key = bool(os.environ.get("META_API_KEY", "").strip())

        t = Text()
        t.append("\n  Muse Code\n\n", style=f"bold {THEME['text']}")
        t.append("    Status    ", style=THEME["muted"])
        if not installed:
            t.append("not installed\n", style=THEME["warning"])
        elif signed_in or env_key:
            t.append("installed, credential found\n", style=THEME["success"])
        else:
            # Muse owns its credential store, so a session it keeps somewhere
            # this probe cannot see is still a valid session. Report what was
            # observed, never that the user is signed out.
            t.append("installed, no credential detected\n", style=THEME["warning"])
        t.append("    Harness   ", style=THEME["muted"])
        t.append("Muse Code owns the loop (closed source)\n", style=THEME["text"])
        t.append("    Model     ", style=THEME["muted"])
        t.append("Muse Spark, managed by Muse Code\n", style=THEME["dim"])

        if not installed:
            t.append("\n  Install on macOS or Linux:\n", style=THEME["muted"])
            t.append("    curl -fsSL https://dev.meta.ai/install.sh | bash\n", style=THEME["cyan"])
            t.append("  Then sign in:\n", style=THEME["muted"])
            t.append("    muse login\n", style=THEME["cyan"])
            log.write(t)
            return

        # Muse reads META_API_KEY ahead of any stored login, so a key left in
        # the shell silently moves an account session onto per-token billing.
        # SuperQode does not spawn Muse here, so it cannot strip the key the way
        # subscription_child_env does for driven routes: say what will actually
        # happen when the user runs `muse` themselves.
        if signed_in and diverting_api_keys("muse"):
            t.append("\n  META_API_KEY is set in this environment.\n", style=THEME["warning"])
            t.append(
                "  Muse Code prefers it over your account login, so this ", style=THEME["muted"]
            )
            t.append("bills per token.\n", style=THEME["warning"])
            t.append("  Unset it before running ", style=THEME["muted"])
            t.append("muse", style=THEME["cyan"])
            t.append(" to spend your Meta account session instead.\n", style=THEME["muted"])
        elif env_key:
            t.append(
                "\n  META_API_KEY is set, so Muse Code bills per token.\n", style=THEME["warning"]
            )
            t.append("  Run ", style=THEME["muted"])
            t.append("muse login", style=THEME["cyan"])
            t.append(" to use a Meta account session instead.\n", style=THEME["muted"])
        elif not signed_in:
            t.append("\n  No credential found at ", style=THEME["muted"])
            t.append(f"{_muse_auth_path()}", style=THEME["dim"])
            t.append(".\n", style=THEME["muted"])
            t.append("  Sign in with Meta's own CLI, in a terminal:\n", style=THEME["muted"])
            t.append("    muse login\n", style=THEME["cyan"])
            t.append("  Or run it from here with a confirmation first: ", style=THEME["muted"])
            t.append(":muse login\n", style=THEME["cyan"])
            # Signing in is not enough on its own: Muse revokes the credential
            # it just stored when the account cannot be billed, which reads as a
            # login that silently did nothing.
            t.append("\n  Meta requires a payment method before a session ", style=THEME["muted"])
            t.append("survives.\n", style=THEME["muted"])
            t.append(
                "  Without one, Muse signs you back out on the next run.\n", style=THEME["dim"]
            )
        else:
            # Signing in proves who you are, not that Meta will serve you. An
            # account without billing authenticates fine and still fails on the
            # first model call, so never imply sign-in is sufficient.
            t.append(
                "\n  Signed in. Model calls bill to your Meta account, so a\n", style=THEME["muted"]
            )
            t.append(
                "  team without billing enabled still gets refused by Meta.\n", style=THEME["muted"]
            )

        t.append(
            "\n  SuperQode does not drive Muse Code yet. Run it directly:\n", style=THEME["muted"]
        )
        t.append("    muse\n", style=THEME["cyan"])
        t.append("\n  Next:\n", style=THEME["muted"])
        t.append("    • ", style=THEME["dim"])
        t.append(":connect byok meta", style=THEME["cyan"])
        t.append(" to run Muse Spark under a SuperQode harness\n", style=THEME["muted"])
        log.write(t)

    async def _report_copilot_login_state(self, log: ConversationLog) -> None:
        """Say whether the Copilot CLI is signed in, so the user need not guess.

        There is no ``copilot whoami``, and the token is held in the OS
        credential store rather than a readable file, so the only honest check
        is a short handshake with the CLI. It takes a few seconds, which is why
        this runs after the connect has already completed.
        """
        from superqode.providers.copilot_auth import probe_copilot_login

        state = await probe_copilot_login()
        if log is None:
            return
        if state.signed_in:
            log.add_success("GitHub Copilot CLI is signed in.")
            self._toast("Copilot is signed in", "Ready to use your subscription.")
            return
        if state.needs_login:
            log.add_error("GitHub Copilot CLI is not signed in.")
            log.add_info("Run `:copilot login` to sign in without leaving the TUI.")
            self._toast(
                "Copilot needs sign-in",
                "Run :copilot login",
                severity="warning",
            )
            return
        # Indeterminate: never claim a state that was not established.
        log.add_info(
            f"Could not confirm the Copilot sign-in state ({state.detail}). "
            "Run `:copilot status` to check."
        )

    def _apply_subscription_billing_policy(self, profile, log: ConversationLog) -> None:
        """Pin a subscription connection to the subscription, and say so.

        Vendor CLIs generally prefer an exported API key over their own OAuth
        login, so a key left in the shell would quietly move a subscription
        session onto per-token billing. SuperQode has a dedicated BYOK path for
        that, so subscription routes drop those keys, and always report it
        rather than changing billing behind the user's back.
        """
        from superqode.providers.connection_profiles import CONNECT_MENU_SUBSCRIPTIONS
        from superqode.providers.subscription_env import (
            diverting_api_keys,
            resolve_vendor,
            subscription_notice,
        )

        if getattr(profile, "menu", "") != CONNECT_MENU_SUBSCRIPTIONS:
            self._acp_subscription_vendor = None
            return

        vendor = resolve_vendor(getattr(profile, "id", "")) or resolve_vendor(
            getattr(profile, "acp_agent", "") or ""
        )
        self._acp_subscription_vendor = vendor
        if vendor is None or log is None:
            return

        stripped = diverting_api_keys(vendor)
        for line in subscription_notice(getattr(profile, "label", vendor), stripped, vendor=vendor):
            log.add_info(line)

    def _connect_copilot_subscription(self, profile, log: ConversationLog) -> None:
        """Select the best installed official route for one Copilot entry.

        Subscriptions offer the vendor's SDK or its plain CLI, never ACP: the
        ACP channel is a separate connection source, and listing the same
        vendor in both duplicates it. The SDK is preferred because it is the
        only Copilot route that can forward per-tool permission requests; the
        CLI route falls back to GitHub's own non-interactive mode.
        """
        from superqode.providers.connection_profiles import (
            _copilot_acp_ready,
            _copilot_sdk_ready,
        )

        self._apply_subscription_billing_policy(profile, log)

        if _copilot_sdk_ready():
            # Choosing silently taught the user nothing. Connecting on the best
            # route and naming the alternative teaches that the runtime is a
            # swappable layer, without costing a keystroke on the happy path.
            if _copilot_acp_ready():
                self._teach(
                    "_announce_runtime_route",
                    log,
                    product="GitHub Copilot",
                    chosen="Copilot SDK",
                    reason="per-tool approvals, resumable sessions, streaming",
                    alternative="Copilot CLI",
                    alternative_command=":connect copilot-cli",
                )
            self._runtime_cmd(profile.runtime or "copilot-sdk", log)
            return
        if _copilot_acp_ready():
            if log is not None:
                log.add_info(
                    "Using the installed GitHub Copilot CLI on your subscription. "
                    "Install the SDK extra for per-tool approval prompts and "
                    "resumable sessions."
                )
            self._runtime_cmd("copilot-cli", log)
            # Whether the vendor CLI is signed in cannot be read from a file:
            # the token lives in the OS credential store. Probe it in the
            # background so connect stays responsive, then report the answer
            # rather than leaving the user to guess and log in again.
            self.run_worker(self._report_copilot_login_state(log), exclusive=False)
            return
        if self._show_dependency_install_picker(profile.runtime or "copilot-sdk", log):
            return
        if log is not None:
            log.add_info(f"{profile.label} needs setup: {profile.unavailable_hint}")

    def _announce_runtime_route(
        self,
        log: ConversationLog,
        *,
        product: str,
        chosen: str,
        reason: str,
        alternative: str,
        alternative_command: str,
    ) -> None:
        """Say which execution route was taken, and how to take the other one.

        The runtime is the layer most users never learn exists, because it is
        always picked for them. Naming it at the one moment it is being decided
        is the cheapest possible way to teach it.
        """
        if log is None:
            return
        t = Text()
        t.append("\n  ◈ ", style=THEME["purple"])
        t.append(f"{product} has two routes\n", style=f"bold {THEME['text']}")
        t.append("    Using  ", style=THEME["dim"])
        t.append(chosen, style=f"bold {THEME['success']}")
        t.append(f"   {reason}\n", style=THEME["muted"])
        t.append("    Or     ", style=THEME["dim"])
        t.append(alternative, style=THEME["text"])
        t.append("   ", style="")
        t.append(alternative_command, style=THEME["cyan"])
        t.append("\n    Same subscription, different execution layer. ", style=THEME["muted"])
        t.append(":runtime", style=THEME["cyan"])
        t.append(" lists them all.\n", style=THEME["muted"])
        log.write(t)

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
                desc = f"needs setup: {profile.unavailable_hint}"
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
            from superqode.providers.dynamic import connect_provider_ids, resolve_provider_def

            return [
                provider_id
                for provider_id in connect_provider_ids()
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
                if p.connector in {"runtime", "copilot"} and p.runtime == runtime_name
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
            "devin-cli": {
                "auth": "devin auth login, managed by the Devin CLI",
                "model": "managed by Devin CLI (--model)",
                "commands": (
                    (":connect acp devin", "for the richer ACP path with tool calls"),
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
        self._teach(
            "_write_connection_teaching_card",
            log,
            label=label,
            vendor_owned=True,
            harness=label,
            model=details.get("model", ""),
        )
        self._mark_onboarding_complete()
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
        if self._redirect_harness_only_provider(provider, log):
            return
        self._clear_acp_extra_env()
        if provider == "grok-cli":
            # The BYOK provider/model picker can reach this route without
            # passing through `:grok api`. Refresh the imported CLI credential
            # before claiming the connection is ready; otherwise a stale token
            # falls through to LiteLLM as an anonymous OpenAI-compatible call.
            if not self._import_grok_token(
                log,
                on_login_success=lambda: self._connect_byok_mode(
                    provider,
                    model,
                    log,
                    resolved_role,
                    _catalog_refresh_attempted=_catalog_refresh_attempted,
                    session_id=session_id,
                ),
            ):
                return
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

        key_session = getattr(self, "_key_harness_session", None)
        if key_session is not None and key_session.after_auth in {
            "switch-and-model",
            "acp-attach",
        }:
            is_local_pick = bool(provider_def and provider_def.category == ProviderCategory.LOCAL)
            allowed = self._key_harness_allowlist("local" if is_local_pick else "byok")
            if allowed is not None and provider not in allowed:
                log.add_error(f"{provider} is not available for {key_session.entry_id}.")
                return

        # An Open row that ends in someone else's loop never runs the SuperQode
        # one: the picker only chose which credentials that agent is handed.
        if self._attach_key_harness_over_acp(provider, model, provider_def, log):
            return
        if self._attach_key_harness_over_rpc(provider, model, provider_def, log):
            return

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
                t.append(f"{' or '.join(provider_def.env_vars)}\n", style=THEME["yellow"])
                t.append("  Recommended: ", style=THEME["muted"])
                t.append(f"superqode auth login {provider}\n", style=THEME["cyan"])
                t.append("  Or export:   ", style=THEME["muted"])
                t.append(
                    f"export {provider_def.env_vars[0]}='your-api-key'\n",
                    style=THEME["cyan"],
                )
                t.append("  Get a key:   ", style=THEME["muted"])
                if provider_def.docs_url:
                    t.append(f"{provider_def.docs_url}\n", style=THEME["cyan"])
                else:
                    t.append(f"{provider_name} website\n", style=THEME["cyan"])
                t.append("  Retry:       ", style=THEME["muted"])
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
        finish = getattr(self, "_finish_successful_model_connect", None)
        if callable(finish):
            finish(provider, model, exec_mode, log)

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
        vendor_owned = False
        harness = str(getattr(self, "current_harness", "") or "core")
        key_session = getattr(self, "_key_harness_session", None)
        if key_session is not None:
            from superqode.providers.harness_catalog import get_entry

            catalog = get_entry(key_session.entry_id)
            if catalog is not None:
                vendor_owned = catalog.vendor_owned
                harness = catalog.label
        self._teach(
            "_write_connection_teaching_card",
            log,
            label=f"{provider_name or provider} · {model}",
            vendor_owned=vendor_owned,
            harness=harness,
            model=f"{provider}/{model}" if provider else model,
        )
        self._mark_onboarding_complete()

    def _connect_byok_cmd(self, args: str, log: ConversationLog):
        """Handle :connect byok command - Interactive provider/model picker."""
        args = args.strip()

        # ":connect byok all" reveals the collapsed models.dev long tail.
        if args.lower() in {"all", "--all"}:
            self._byok_show_all_providers = True
            self._show_connect_picker(log)
            return

        # If no args provided, show the provider picker
        # This is the main entry point for :connect byok
        if not args:
            self._byok_show_all_providers = False
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
            legacy_provider = args.split("/", 1)[0].split(maxsplit=1)[0]
            if self._redirect_harness_only_provider(legacy_provider, log):
                return
            if normalize_provider_id(legacy_provider) == "github-copilot":
                log.add_info(
                    "The legacy GitHub Copilot BYOK route is hidden from discovery. "
                    "Use `:connect copilot` for the maintained SDK integration."
                )

            # Prevent "byok", "acp", "local" from being treated as provider names
            # These are subcommands, not providers
            if args.lower().strip() in ("byok", "acp", "local"):
                # This shouldn't happen if parsing is correct, but be defensive
                self._show_connect_picker(log)
                return

            # "<provider> <model>" is unambiguous, so whitespace is resolved
            # before the "/" forms. Most open-weight ids contain a slash
            # ("moonshot-ai/Kimi-K3", "accounts/fireworks/models/kimi-k3"), and
            # splitting on "/" first read the provider as "baseten moonshot-ai".
            spaced = args.split(maxsplit=1)
            if len(spaced) == 2:
                provider, model = spaced[0].strip(), spaced[1].strip()
                if provider and model and provider.lower() not in ("byok", "acp", "local"):
                    self._connect_byok_mode(provider, model, log)
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
        """Reconnect the last saved connection, then fall back to byok.last_*."""
        connection = self._load_connection_config()
        category = str(connection.get("category") or "")
        auth_mode = str(connection.get("auth_mode") or "")
        after_auth = str(connection.get("after_auth") or "")
        acp_agent = str(connection.get("acp_agent") or "")
        profile_id = str(connection.get("profile_id") or "")
        provider = str(connection.get("provider") or "")
        model = str(connection.get("model") or "")

        if category == "acp" or (auth_mode == "acp" and not after_auth):
            if acp_agent:
                self._connect_acp_cmd(acp_agent, log)
                return
        elif profile_id:
            from superqode.providers.connection_profiles import get_connection_profile

            profile = get_connection_profile(profile_id)
            if profile is not None:
                if after_auth == "switch-and-model" and provider and model:
                    self._begin_key_harness(profile, log, apply_route=(auth_mode, provider, model))
                else:
                    self._dispatch_connection_profile(profile, log)
                return

        config = self._load_byok_config()
        if config.get("last_provider") and config.get("last_model"):
            self._connect_byok_mode(config["last_provider"], config["last_model"], log)
        else:
            log.add_info("No previous connection saved")
            log.add_system("Use :connect to select a provider")

    def _show_connect_type_picker(
        self,
        log: ConversationLog,
        clear_log: bool = True,
        menu: str | None = None,
        preserve_log: bool = False,
    ):
        """Show a connect screen: the root ownership question, or a submenu.

        Args:
            log: The conversation log widget
            clear_log: If True, clear the log before writing (default: True).
                      Set to False when updating during navigation to reduce flickering.
            menu: Which connect screen to show. Defaults to the root screen on a
                  fresh render, and to the current screen while navigating it.
        """
        from superqode.providers.connection_profiles import (
            CONNECT_MENU_ROOT,
            connect_menu_titles,
            detected_sources,
            normalize_menu,
        )

        current_menu = getattr(self, "_connect_menu", CONNECT_MENU_ROOT)
        if menu is None:
            # A fresh `:connect` always lands on the root screen; arrow-key
            # redraws (clear_log=False) stay on the screen being navigated.
            menu = CONNECT_MENU_ROOT if clear_log else current_menu
        menu = normalize_menu(menu)
        if menu != current_menu:
            self._byok_highlighted_connect_type_index = 0
        self._connect_menu = menu
        # Recorded before the draw so back returns to the screen the user came
        # from rather than this one's declared parent.
        self._record_screen(
            f"connect:{menu}",
            _menu_history_label(menu),
            lambda target=menu: self._show_connect_type_picker(
                self.query_one("#log", ConversationLog), menu=target
            ),
        )

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

        is_root = menu == CONNECT_MENU_ROOT
        title, subtitle = connect_menu_titles().get(menu, ("Connect", ""))

        t = Text()
        t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append(f"{title}\n", style=f"bold {THEME['text']}")
        if subtitle:
            t.append(f"  {subtitle}\n", style=THEME["muted"])
        # Opening the picker clears the log, so carry the caller's context.
        note = getattr(self, "_connect_context_note", "")
        if note:
            t.append(f"  {note}\n", style=f"bold {THEME['success']}")
            self._connect_context_note = ""
        t.append("\n", style="")

        # Show what was detected locally before the user chooses anything.
        if is_root:
            try:
                found = detected_sources()
            except Exception:  # noqa: BLE001 - never let detection break the picker
                found = []
            if found:
                t.append("  Detected here: ", style=THEME["dim"])
                t.append(" · ".join(found), style=THEME["cyan"])
                t.append("\n\n", style="")

        # Grouping is per-menu; most screens are flat. Drawn from the same
        # helper selection indexes, so a filtered row cannot be numbered here
        # and then chosen as something else.
        ordered = [("", self._connect_menu_profiles())]

        # Row numbers, the highlight, arrow keys and typed numbers all count
        # screen position, so a label always matches the row it sits on.
        display = [profile for _group, group_profiles in ordered for profile in group_profiles]
        highlighted_idx = getattr(self, "_byok_highlighted_connect_type_index", 0)
        if not (0 <= highlighted_idx < len(display)):
            highlighted_idx = 0

        # Right-aligned to the widest number, so labels share a column past [9].
        number_width = len(str(len(display))) or 1
        indent = " " * (8 + number_width)
        content_width = self._picker_content_width(log)
        wrap_width = max(24, content_width - len(indent) - 2)

        def append_wrapped(text: str, style: str) -> None:
            """Hanging-indent supporting copy; Rich would wrap it to column zero."""
            for line in textwrap.wrap(text, width=wrap_width) or [text]:
                t.append(f"{indent}{line}\n", style=style)

        position = 0
        for group_name, group_profiles in ordered:
            if group_name:
                t.append(f"  {group_name}\n", style=f"bold {THEME['purple']}")
            for profile in group_profiles:
                num = position + 1
                is_highlighted = position == highlighted_idx
                position += 1

                # The whole row is the click target, not just the number. A
                # mouse user aims at the name they are reading.
                if is_highlighted:
                    link = self._picker_link_style(f"bold {THEME['success']}", num)
                    handle = self._picker_link_style(f"bold {THEME['success']}", num, handle=True)
                    t.append("  ", style="")
                    self._append_picker_dot(t, num, highlighted=True)
                    t.append(f"[{num:>{number_width}}] ", style=link)
                    t.append(profile.label, style=handle)
                    self._append_picker_arrow(t, num)
                    t.append("  ← SELECTED\n", style=link)
                else:
                    link = self._picker_link_style(THEME["dim"], num)
                    t.append("  ", style="")
                    self._append_picker_dot(t, num, highlighted=False)
                    t.append(f"[{num:>{number_width}}] ", style=link)
                    # The coloured dot and number carry the "clickable" signal.
                    # Colouring the name too made a thirteen-row screen one
                    # saturated block, with nothing left to draw the eye.
                    t.append(
                        profile.label,
                        style=self._picker_link_style(f"bold {THEME['text']}", num, handle=True),
                    )
                    self._append_picker_arrow(t, num)
                    t.append("\n", style="")
                # Every row explains itself, so options can be compared at
                # once. Only the row being considered spends more than one
                # line on it: a dozen wrapped paragraphs is a wall, not a list.
                # Prose carries no link style: terminals decorate OSC-8 spans
                # with their own underline and colour, which turned every
                # description into a smeared rule. Clicks on these lines still
                # select the row, resolved by position in _click_selects_picker_row.
                if profile.description:
                    if is_highlighted:
                        append_wrapped(profile.description, THEME["muted"])
                    else:
                        t.append(
                            f"{indent}{textwrap.shorten(profile.description, wrap_width, placeholder=' …')}\n",
                            style=THEME["muted"],
                        )
                badges = profile.badges
                if is_highlighted and badges:
                    append_wrapped(" · ".join(badges), THEME["dim"])
                if is_highlighted and not profile.available and profile.unavailable_hint:
                    append_wrapped(profile.unavailable_hint, THEME["warning"])

        t.append("  💡 ", style=THEME["muted"])
        t.append("↑↓", style=THEME["cyan"])
        t.append(" navigate  ", style=THEME["dim"])
        t.append("Enter", style=THEME["cyan"])
        t.append(" select  ", style=THEME["dim"])
        if not is_root:
            t.append("Esc", style=THEME["purple"])
            t.append(" back  ", style=THEME["dim"])
        t.append("•  ", style=THEME["dim"])
        t.append("or type a number\n", style=THEME["dim"])

        if preserve_log:
            # Opened underneath something the user still needs to read, such as
            # the confirmation that a harness switch succeeded. Append instead
            # of replacing, so the picker adds a question rather than erasing
            # the answer to the previous one.
            log.auto_scroll = False
            log.write(t)
            log.auto_scroll = True
        elif clear_log:
            # Replacing the home screen: cancel welcome reflow and the deferred
            # catalogue chrome line so neither can steal this picker's viewport.
            self._welcome_active = False
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

        self._scroll_to_highlighted_item(log, highlighted_idx, len(display))

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

    #: Hosts pinned to the front of Model Hosts, in this order. Everything else
    #: in the category follows alphabetically.
    _PINNED_MODEL_HOSTS = ("baseten", "fireworks", "together", "modal", "openrouter")

    def _model_host_sort_key(self, entry) -> tuple:
        """Order Model Hosts with the pinned ones first, then by name."""
        pid, pdef = entry[0], entry[1]
        try:
            rank = self._PINNED_MODEL_HOSTS.index(pid)
        except ValueError:
            rank = len(self._PINNED_MODEL_HOSTS)
        return (rank, pdef.name)

    def _show_connect_picker(self, log: ConversationLog, clear_log: bool = True):
        """Show interactive provider picker with model counts and API key guidance."""
        from superqode.providers.registry import PROVIDERS, ProviderCategory, get_free_providers
        from superqode.providers.dynamic import connect_provider_ids, resolve_provider_def
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
        t.append("\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Model providers\n", style=f"bold {THEME['text']}")

        # Get providers with free models
        free_providers = get_free_providers()
        provider_ids = list(connect_provider_ids())
        allowed = self._key_harness_allowlist("byok")
        if allowed is not None:
            provider_ids = [pid for pid in provider_ids if pid in allowed]
        visible_provider_ids = set(provider_ids)
        free_provider_ids = set(free_providers.keys()) & visible_provider_ids

        data_source = get_data_source()
        t.append(
            f"  {len(visible_provider_ids)} providers · metadata from {data_source}\n\n",
            style=THEME["muted"],
        )

        # Helper function to get provider info
        # This screen walks the provider list more than once; memoise so each
        # provider is priced once per render.
        _info_cache: dict = {}

        def get_provider_info(pid, pdef):
            cached = _info_cache.get(pid)
            if cached is not None:
                return cached
            result = _build_provider_info(pid, pdef)
            _info_cache[pid] = result
            return result

        def _build_provider_info(pid, pdef):
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
                # Never spawn a vendor CLI for a row count; it costs seconds.
                models = get_models_for_provider(pid, probe_cli=False)
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

        # models.dev synthesizes a def for every provider it knows, and they all
        # default to Model Hosts. That buried the 16 curated hosts under ~140
        # long-tail entries, so the default view shows the curated ones and
        # collapses the rest. A collapsed provider whose key is already in the
        # environment is still shown: the user clearly uses it, and hiding it
        # would look like SuperQode does not support it.
        show_all_hosts = bool(getattr(self, "_byok_show_all_providers", False))
        providers_by_category = {}
        collapsed_hosts = 0
        for pid in provider_ids:
            pdef = resolve_provider_def(pid)
            if pdef is None:
                continue
            info = get_provider_info(pid, pdef)
            category = pdef.category
            if (
                category is ProviderCategory.MODEL_HOSTS
                and not show_all_hosts
                and pid not in PROVIDERS
                and not info[2]  # configured
            ):
                collapsed_hosts += 1
                continue
            if category not in providers_by_category:
                providers_by_category[category] = []

            providers_by_category[category].append(info)

        idx = 1
        provider_list = []

        # What already works comes first. A user with OPENAI_API_KEY set should
        # not have to find "openai" inside a category list to use it, and
        # leading with their own working setup is the fastest possible start.
        ready_infos = []
        for pid in provider_ids:
            pdef = resolve_provider_def(pid)
            if pdef is None or not pdef.env_vars:
                continue
            info = get_provider_info(pid, pdef)
            if info[2]:  # configured
                ready_infos.append(info)
        ready_infos.sort(key=lambda item: item[1].name)
        ready_provider_ids = {info[0] for info in ready_infos}

        if ready_infos:
            t.append("  Ready — key found\n", style=f"bold {THEME['success']}")
            for pid, pdef, _configured, _missing, model_count in ready_infos:
                is_highlighted = (idx - 1) == getattr(self, "_byok_highlighted_provider_index", 0)
                marker_style = f"bold {THEME['success']}" if is_highlighted else THEME["text"]
                if is_highlighted:
                    t.append("  ▶ ", style=f"bold {THEME['success']}")
                    t.append(
                        f"[{idx:2}] ",
                        style=self._picker_link_style(f"bold {THEME['success']}", idx),
                    )
                else:
                    t.append(f"    [{idx:2}] ", style=self._picker_link_style(THEME["dim"], idx))
                row_link = self._picker_link_style(marker_style, idx)
                t.append("✓ ", style=THEME["success"])
                t.append(pid, style=self._picker_link_style(marker_style, idx, handle=True))
                t.append(" " * max(0, 15 - len(pid)), style=row_link)
                t.append(
                    f"{pdef.name}",
                    style=row_link
                    if is_highlighted
                    else self._picker_link_style(THEME["muted"], idx),
                )
                if is_highlighted:
                    t.append("  ← SELECTED", style=f"bold {THEME['success']}")
                t.append("\n", style="")
                if is_highlighted:
                    t.append(f"        {pdef.env_vars[0]} ✓", style=THEME["dim"])
                    if model_count > 0:
                        t.append(f" · {model_count} models", style=THEME["dim"])
                    t.append("\n", style="")
                provider_list.append((pid, pdef))
                idx += 1
            t.append("\n", style="")

        # Free routes are the strongest possible first run: no key, no card, and
        # coding in under a minute. They were previously reachable only through
        # `superqode providers scan-free`, which nobody finds.
        if free_provider_ids:
            t.append("  Free right now, no card\n", style=f"bold {THEME['success']}")
            free_providers_list = []
            for pid in free_provider_ids:
                pdef = PROVIDERS.get(pid)
                if not pdef or pid in ready_provider_ids:
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
                    t.append("  ▶ ", style=f"bold {THEME['success']}")
                    t.append(
                        f"[{idx:2}] ",
                        style=self._picker_link_style(f"bold {THEME['success']}", idx),
                    )
                    row_link = self._picker_link_style(f"bold {THEME['success']}", idx)
                    t.append(f"{status} ", style=status_style)
                    t.append(
                        pid,
                        style=self._picker_link_style(f"bold {THEME['success']}", idx, handle=True),
                    )
                    t.append(" " * max(0, 15 - len(pid)), style=row_link)
                    t.append(f"{pdef.name}", style=row_link)
                    t.append("  ← SELECTED\n", style=row_link)
                    t.append("        free", style=THEME["success"])
                    if model_count > 0:
                        t.append(
                            f" · {model_count} model{'s' if model_count > 1 else ''}",
                            style=THEME["dim"],
                        )
                    if not configured and pdef.env_vars:
                        t.append(f" · needs {', '.join(missing_keys)}", style=THEME["warning"])
                    t.append("\n", style="")
                else:
                    t.append(f"    [{idx:2}] ", style=self._picker_link_style(THEME["dim"], idx))
                    t.append(f"{status} ", style=status_style)
                    t.append(pid, style=self._picker_link_style(THEME["link"], idx, handle=True))
                    t.append(
                        " " * max(0, 15 - len(pid)),
                        style=self._picker_link_style(THEME["link"], idx),
                    )
                    t.append(f"{pdef.name}", style=self._picker_link_style(THEME["muted"], idx))
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
            if category is ProviderCategory.MODEL_HOSTS:
                category_providers = sorted(
                    providers_by_category[category], key=self._model_host_sort_key
                )
            else:
                category_providers = sorted(
                    providers_by_category[category], key=lambda x: x[1].name
                )

            # Count non-free providers in this category
            non_free_providers = [p for p in category_providers if p[0] not in free_provider_ids]

            # Show category header if there are any providers (even if all are free, show the header)
            if category_providers:
                t.append(f"  {label}\n", style=f"bold {color}")

            for pid, pdef, configured, missing_keys, model_count in category_providers:
                # Skip anything already shown under Ready or Free.
                if pid in free_provider_ids or pid in ready_provider_ids:
                    continue

                status = "✓" if configured else "○"
                status_style = THEME["success"] if configured else THEME["warning"]

                # Highlight current selection
                is_highlighted = (idx - 1) == getattr(self, "_byok_highlighted_provider_index", 0)
                if is_highlighted:
                    t.append("  ▶ ", style=f"bold {THEME['success']}")
                    t.append(
                        f"[{idx:2}] ",
                        style=self._picker_link_style(f"bold {THEME['success']}", idx),
                    )
                    row_link = self._picker_link_style(f"bold {THEME['success']}", idx)
                    t.append(f"{status} ", style=status_style)
                    t.append(
                        pid,
                        style=self._picker_link_style(f"bold {THEME['success']}", idx, handle=True),
                    )
                    t.append(" " * max(0, 15 - len(pid)), style=row_link)
                    t.append(f"{pdef.name}", style=row_link)
                    t.append("  ← SELECTED\n", style=row_link)
                    details = []
                    if model_count > 0:
                        details.append(f"{model_count} model{'s' if model_count > 1 else ''}")
                    if not configured and pdef.env_vars:
                        details.append(f"needs {', '.join(missing_keys)}")
                    if details:
                        t.append("        " + " · ".join(details) + "\n", style=THEME["dim"])
                else:
                    t.append(f"    [{idx:2}] ", style=self._picker_link_style(THEME["dim"], idx))
                    t.append(f"{status} ", style=status_style)
                    t.append(pid, style=self._picker_link_style(THEME["link"], idx, handle=True))
                    t.append(
                        " " * max(0, 15 - len(pid)),
                        style=self._picker_link_style(THEME["link"], idx),
                    )
                    t.append(f"{pdef.name}", style=self._picker_link_style(THEME["muted"], idx))
                    t.append("\n", style="")

                provider_list.append((pid, pdef))
                idx += 1

            t.append("\n", style="")

        if collapsed_hosts:
            t.append(f"  {collapsed_hosts} more hosts", style=THEME["muted"])
            t.append(" from the models.dev catalog are hidden. ", style=THEME["dim"])
            t.append(":connect byok all", style=THEME["cyan"])
            t.append(
                " lists them,\n  or connect by name directly. Any host whose API key is "
                "already set is shown above.\n\n",
                style=THEME["dim"],
            )

        t.append("  💡 ", style=THEME["muted"])
        t.append("↑↓", style=THEME["cyan"])
        t.append(" navigate  ", style=THEME["dim"])
        t.append("Enter", style=THEME["cyan"])
        t.append(" select  •  type a number  •  ", style=THEME["dim"])
        t.append(":hub", style=THEME["cyan"])
        t.append(" model search  •  ", style=THEME["dim"])
        t.append(":connect local", style=THEME["cyan"])
        t.append(" local models\n", style=THEME["dim"])

        # Ensure we have providers to show
        if not provider_list:
            log.add_error("No providers available. Please check your provider configuration.")
            return

        # Clear log and show content from top (like agent finish work)
        if clear_log:
            # Replacing the home screen: cancel welcome reflow and the deferred
            # catalogue chrome line so neither can steal this picker's viewport.
            self._welcome_active = False
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

    def _user_config_path(self) -> Path:
        """The same file `connect_menu` is read from, resolved in one place."""
        from superqode.providers.harness_catalog import user_config_path

        return user_config_path()

    def _read_user_config(self) -> dict:
        """Raw ~/.superqode/config.json. Unknown keys must not be dropped."""
        path = self._user_config_path()
        try:
            if path.exists():
                data = json.loads(path.read_text())
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {}

    def _update_user_config(self, mutate: Callable[[dict], None]) -> None:
        """Read-modify-write user config.json. Same helper as byok.* persist."""
        path = self._user_config_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = self._read_user_config()
            mutate(data)
            path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def _load_byok_config(self) -> dict:
        """Load BYOK config from file."""
        raw = self._read_user_config().get("byok", {})
        return raw if isinstance(raw, dict) else {}

    def _save_byok_config(self, provider: str, model: str):
        """Save BYOK config to file."""

        def _mutate(data: dict) -> None:
            byok = data.get("byok")
            if not isinstance(byok, dict):
                byok = {}
                data["byok"] = byok
            byok["last_provider"] = provider
            byok["last_model"] = model
            history = byok.get("history", [])
            if not isinstance(history, list):
                history = []
            entry = f"{provider}/{model}"
            if entry in history:
                history.remove(entry)
            history.insert(0, entry)
            byok["history"] = history[:20]

        self._update_user_config(_mutate)

    def _load_byok_history(self) -> list:
        """Load BYOK connection history."""
        config = self._load_byok_config()
        return config.get("history", [])

    def _load_connection_config(self) -> dict:
        """Last existing-harness / model connection. Never contains secrets."""
        raw = self._read_user_config().get("connection", {})
        if not isinstance(raw, dict):
            return {}
        return {key: raw[key] for key in _CONNECTION_KEYS if key in raw}

    def _save_connection_config(self, **fields: str) -> None:
        """Persist connection.* via the same RMW helper as byok.*. No secrets."""

        def _mutate(data: dict) -> None:
            current = data.get("connection")
            if not isinstance(current, dict):
                current = {}
            for key in _CONNECTION_KEYS:
                if key in fields:
                    current[key] = str(fields[key] or "")
            data["connection"] = current

        self._update_user_config(_mutate)

    def _persist_acp_connection(self, acp_agent: str) -> None:
        """Write connection.* for an ACP attach. Subscriptions keep their category."""
        from superqode.providers.connection_profiles import get_connection_profile

        connecting_id = str(getattr(self, "_connecting_profile_id", "") or "")
        self._connecting_profile_id = ""
        vendor = getattr(self, "_acp_subscription_vendor", None)
        if vendor:
            category, auth_mode, profile_id = "subscriptions", "subscription", connecting_id
        else:
            category, auth_mode = "acp", "acp"
            known = get_connection_profile(connecting_id) if connecting_id else None
            profile_id = known.id if known is not None else ""
        self._save_connection_config(
            category=category,
            auth_mode=auth_mode,
            harness_id="",
            profile_id=profile_id,
            acp_agent=acp_agent,
            openness="",
            provider=str(getattr(self, "current_provider", "") or ""),
            model=str(getattr(self, "current_model", "") or ""),
            transport="ACP",
            after_auth="",
        )

    def _finish_successful_model_connect(
        self, provider: str, model: str, mode: str, log: ConversationLog
    ) -> None:
        """Write connection.*, run Open-harness post-hooks, then drop the session."""
        key_session = getattr(self, "_key_harness_session", None)
        if key_session is not None and not self._key_harness_session_matches():
            self._clear_key_harness_session()
            key_session = None
        if key_session is None:
            harness_id = str(
                getattr(self, "current_harness", "")
                or os.getenv("SUPERQODE_HARNESS", "core")
                or "core"
            )
            self._save_connection_config(
                category="models",
                auth_mode=mode,
                harness_id=harness_id,
                profile_id="",
                acp_agent="",
                openness="",
                provider=provider,
                model=model,
                transport="",
                after_auth="",
            )
            return

        from superqode.providers.harness_catalog import get_entry

        entry = get_entry(key_session.entry_id)
        self._save_connection_config(
            category=key_session.return_menu,
            auth_mode=mode,
            harness_id=key_session.harness_id or key_session.entry_id,
            profile_id=key_session.entry_id,
            acp_agent=(entry.acp_agent if entry is not None else "") or "",
            openness=key_session.openness,
            provider=provider,
            model=model,
            transport="harness-protocol",
            after_auth=key_session.after_auth,
        )
        _CONNECT_LOG.info(
            "connect.completed category=%s auth_mode=%s harness_id=%s provider=%s after_auth=%s",
            key_session.return_menu,
            mode,
            key_session.entry_id,
            provider,
            key_session.after_auth,
        )
        if key_session.entry_id == "tau":
            self._sync_tau_after_key_connect(provider, model, log)
        if key_session.openness == "open":
            record = getattr(self, "_record_milestone", None)
            if callable(record):
                record("connected_open_harness")
        self._clear_key_harness_session()

    def _sync_tau_after_key_connect(self, provider: str, model: str, log: ConversationLog) -> None:
        """Copy the SuperQode route into Tau without reconnecting."""
        from superqode.providers.credentials import provider_api_key
        from superqode.providers.dynamic import resolve_base_url, resolve_provider_def
        from superqode.providers.registry import ProviderCategory

        provider_def = resolve_provider_def(provider)
        if provider_def is None:
            return
        openai_url = getattr(self, "_tau_openai_base_url", None)
        base_url = (
            openai_url(provider, resolve_base_url(provider_def))
            if callable(openai_url)
            else resolve_base_url(provider_def)
        )
        api_key_env = (
            provider_def.env_vars[0]
            if provider_def.env_vars
            else f"{provider.upper().replace('-', '_')}_API_KEY"
        )
        credential = provider_api_key(provider_def)
        if (
            not credential
            and provider_def.category == ProviderCategory.LOCAL
            and not provider_def.env_vars
        ):
            credential = provider
        if not credential:
            return
        try:
            from superqode.harness.tau_management import configure_tau_provider

            configure_tau_provider(
                provider_name=provider,
                display_name=provider_def.name,
                model=model,
                base_url=base_url,
                api_key_env=api_key_env,
                credential=credential,
                docs_url=provider_def.docs_url,
            )
        except Exception as exc:  # noqa: BLE001 - connect already succeeded
            if log is not None:
                log.add_warning(f"Tau is connected, but :tau login could not sync: {exc}")

    def _connect_acp_cmd(self, args: str, log: ConversationLog):
        """Handle :connect acp command - Connect to ACP agent."""
        if not args:
            # Keep first-run selection focused. Installed agents are always
            # included; the full live registry remains one explicit command
            # away via `:connect acp all`.
            self._show_agents(log, include_all=False, catalog_tier="featured")
            return

        command = args.strip().lower()
        if command in {"all", "--all"}:
            self._show_agents(log, include_all=True)
            return
        if command in {"featured", "--featured", "recommended"}:
            self._show_agents(log, include_all=False, catalog_tier="featured")
            return
        if command in {"enterprise", "--enterprise"}:
            self._show_agents(log, include_all=False, catalog_tier="enterprise")
            return
        if command in {"refresh", "sync"}:
            self._refresh_acp_registry(log)
            return

        # Typed `:connect acp <agent>` is the ACP catalog path. Dispatch of a
        # Subscriptions row sets `_connecting_profile_id` before calling us.
        if not getattr(self, "_connecting_profile_id", ""):
            self._acp_subscription_vendor = None
        # A named ACP attach must not inherit a previous Closed-key inject.
        # vendor-key re-sets extra env after this returns; the client is
        # constructed later, on the first prompt.
        self._clear_acp_extra_env()

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
        self._retain_acp_extra_env_for(agent_id)

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
                elif self.current_agent in ("prime-agent", "prime"):
                    # Prime fixes its model at launch, so the selection lives in
                    # the pinned launch options rather than in the ACP session.
                    # The generic branch below reads a "model" key the catalog
                    # entry does not have, which left the badge empty and made a
                    # picked model look like it had not been applied.
                    hint = (model_hint or "").strip()
                    if hint and hint.lower() not in {"auto", "default", "none"}:
                        self._prime_set_opts(model=hint)
                    opts = self._prime_opts()
                    self.current_model = opts.model
                    self.current_provider = "prime"
                    self._awaiting_model_selection = False

                    badge = self.query_one("#mode-badge", ModeBadge)
                    badge.agent = self.current_agent
                    badge.mode = ""
                    badge.role = ""
                    badge.model = self.current_model or "Prime default"
                    badge.provider = self.current_provider
                    badge.execution_mode = "acp"
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
                announce_harness_switch = getattr(
                    self, "_announce_pending_acp_harness_transition", None
                )
                if callable(announce_harness_switch):
                    announce_harness_switch(log, agent)
                self._finish_vendor_key_or_teach(log, agent)
                if not getattr(self, "_pending_vendor_key", None):
                    self._persist_acp_connection(str(self.current_agent or agent_id))
                self._mark_onboarding_complete()
            else:
                self._pending_harness_acp_transition = None
                self._abandon_vendor_key_attach(agent_id)
                self._announce_transition(
                    title="Agent not found",
                    primary=agent_id,
                    detail="No matching ACP agent is available",
                    severity="error",
                    log=log,
                    guidance="Run :connect acp all to review available agents.",
                )
        except Exception as e:
            self._pending_harness_acp_transition = None
            self._abandon_vendor_key_attach(agent_id)
            self._announce_transition(
                title="Connection failed",
                primary=agent_id,
                detail=str(e),
                severity="error",
                log=log,
                guidance="Run :log verbose for startup details.",
            )
