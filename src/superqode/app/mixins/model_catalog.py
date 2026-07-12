"""Model catalogs, live model data, and per-provider selection."""

from __future__ import annotations
import asyncio
import shutil
from typing import Any, Dict, List, Optional
from rich.text import Text
from superqode.providers.model_specs import (
    split_provider_model_ref,
)
from superqode.app.constants import (
    THEME,
    AGENT_COLORS,
    AGENT_ICONS,
)
from superqode.app.widgets import (
    ModeBadge,
    ConversationLog,
)
from superqode.design_system import (
    COLORS as SQ_COLORS,
    GRADIENT_PURPLE,
)
from superqode.providers.models import LATEST_GOOGLE_FLASH_MODEL, LATEST_GOOGLE_PRO_MODEL

# --- helpers extracted from app_main (A1) ---
from superqode.app.recipes import PromptCompletionCandidate
from superqode.app.session_state import get_session


class ModelCatalogMixin:
    """Provider model catalogs, models.dev refresh, and model selection."""

    @property
    def opencode_models(self) -> List[Dict]:
        """Lazy load OpenCode models."""
        if self._opencode_models is None:
            self._opencode_models = self._get_opencode_models()
        return self._opencode_models

    def _get_opencode_models(self) -> List[Dict]:
        """Get OpenCode models from the live CLI catalog, newest releases first."""
        try:
            from superqode.providers.models import sort_models_newest_first
            from superqode.providers.opencode_models import get_opencode_models_sync

            models = get_opencode_models_sync()

            # Convert to our format. Show all discovered OpenCode models, not
            # only free ones, because the catalog and free-tier markers change.
            return sort_models_newest_first(
                [
                    {
                        "id": m["id"],
                        "name": m.get("name", m["id"].split("/")[-1]),
                        "context": m.get("context", 128000),
                        "free": bool(m.get("is_free", False)),
                        "recommended": bool(m.get("recommended", False)),
                        "desc": m.get("description") or m.get("source", "OpenCode"),
                        "catalog_unavailable": bool(m.get("catalog_unavailable", False)),
                    }
                    for m in models
                ]
            )
        except Exception:
            return []

    @property
    def gemini_models(self) -> List[Dict]:
        """Lazy load Gemini models."""
        if self._gemini_models is None:
            self._gemini_models = self._get_gemini_models()
        return self._gemini_models

    def _get_gemini_models(self) -> List[Dict]:
        """Get Gemini models list - synced with providers/models.py."""
        return [
            {
                "id": LATEST_GOOGLE_PRO_MODEL,
                "name": "Gemini 3.1 Pro Preview",
                "context": 2000000,
                "desc": "Latest Gemini Pro from models.dev - 2M context",
                "recommended": True,
            },
            {
                "id": LATEST_GOOGLE_FLASH_MODEL,
                "name": "Gemini Flash Latest",
                "context": 1000000,
                "desc": "Latest Gemini Flash alias from models.dev - 1M context",
                "recommended": True,
            },
        ]

    @property
    def claude_models(self) -> List[Dict]:
        """Lazy load Claude models."""
        if self._claude_models is None:
            self._claude_models = self._get_claude_models()
        return self._claude_models

    def _get_claude_models(self) -> List[Dict]:
        """Get Claude models list - synced with providers/models.py."""
        return [
            {
                "id": "claude-opus-4-8",
                "name": "Claude Opus 4.8 (Latest)",
                "context": 1000000,
                "desc": "Latest Claude Opus from models.dev - 1M context",
                "recommended": True,
            },
            {
                "id": "claude-opus-4-7",
                "name": "Claude Opus 4.7",
                "context": 1000000,
                "desc": "Recent Claude Opus with 1M context",
                "recommended": True,
            },
            {
                "id": "claude-sonnet-4-6",
                "name": "Claude Sonnet 4.6",
                "context": 1000000,
                "desc": "Latest Claude Sonnet coding model - 1M context",
                "recommended": True,
            },
            {
                "id": "claude-opus-4-5",
                "name": "Claude Opus 4.5",
                "context": 200000,
                "desc": "Claude Opus 4.5 alias from models.dev",
            },
            {
                "id": "claude-haiku-4-5",
                "name": "Claude Haiku 4.5",
                "context": 200000,
                "desc": "Fast and cost-effective Claude model",
            },
        ]

    @property
    def openhands_models(self) -> List[Dict]:
        """Lazy load OpenHands models."""
        if self._openhands_models is None:
            self._openhands_models = self._get_openhands_models()
        return self._openhands_models

    def _get_openhands_models(self) -> List[Dict]:
        """Get OpenHands models list."""
        return [
            {"id": "gpt-5.4", "name": "GPT-5.4 (Latest)", "context": 1000000},
            {"id": "gpt-5.4-pro", "name": "GPT-5.4 Pro", "context": 1000000},
            {"id": "gpt-5.3-codex", "name": "GPT-5.3 Codex", "context": 256000},
            {"id": "gpt-5.2", "name": "GPT-5.2", "context": 256000},
            {"id": "gpt-5.2-pro", "name": "GPT-5.2 Pro", "context": 256000},
            {
                "id": "claude-opus-4-8",
                "name": "Claude Opus 4.8 (Latest)",
                "context": 1000000,
            },
            {
                "id": "claude-sonnet-4-6",
                "name": "Claude Sonnet 4.6",
                "context": 1000000,
            },
            {
                "id": "claude-opus-4-7",
                "name": "Claude Opus 4.7",
                "context": 1000000,
            },
            {
                "id": LATEST_GOOGLE_PRO_MODEL,
                "name": "Gemini 3.1 Pro Preview (Latest Pro)",
                "context": 2000000,
            },
            {
                "id": LATEST_GOOGLE_FLASH_MODEL,
                "name": "Gemini Flash Latest",
                "context": 1000000,
            },
            {"id": "gpt-4o", "name": "GPT-4o", "context": 128000},
            {"id": "claude-haiku-4-5", "name": "Claude Haiku 4.5", "context": 200000},
        ]

    def _start_models_dev_refresh(self) -> None:
        """Refresh the models.dev catalog without blocking the TUI."""
        self.run_worker(self._load_models_dev_data())

    def _apply_live_models(self, client) -> bool:
        """Push the client's current provider/model data into the live registry."""
        from superqode.providers.models import set_live_models

        live_models = {}
        for provider_id in client.get_providers().keys():
            provider_models = client.get_models_for_provider(provider_id)
            if provider_models:
                live_models[provider_id] = provider_models
        if live_models:
            set_live_models(live_models)
            return True
        return False

    async def _load_models_dev_data(self):
        """Load models from models.dev: cached instantly, then force-refresh.

        Runs in the background so the UI stays responsive. Each TUI launch shows
        the cached catalog immediately, then pulls a fresh copy from models.dev
        and swaps it in — so newly launched models appear without any manual
        list update.
        """
        try:
            from superqode.providers.models_dev import get_models_dev

            client = get_models_dev()
            # 1) Instant: whatever is cached on disk.
            if await client.ensure_loaded():
                self._apply_live_models(client)
            # 2) Fresh: force a network refresh and swap in the latest.
            try:
                if await client.refresh(force=True):
                    self._apply_live_models(client)
            except Exception:
                pass  # offline / transient — cached data stands
        except Exception:
            # Silent failure - live data is optional
            pass

    def _unload_ollama_model(self, model: str) -> bool:
        """Ask Ollama to unload a resident model without killing the Ollama app."""
        import json as _json
        import os as _os
        import urllib.request as _request

        model = (model or "").strip()
        if not model:
            return False
        if model.startswith("ollama/"):
            model = model.split("/", 1)[1]

        host = _os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip()
        if not host.startswith(("http://", "https://")):
            host = f"http://{host}"
        url = host.rstrip("/") + "/api/generate"
        payload = _json.dumps(
            {"model": model, "prompt": "", "stream": False, "keep_alive": 0}
        ).encode("utf-8")
        req = _request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "SuperQode"},
            method="POST",
        )
        try:
            with _request.urlopen(req, timeout=2) as response:  # noqa: S310
                response.read(1024)
            return True
        except Exception:
            return False

    def _select_model_by_number(self, num: int):
        """Select a model by number when awaiting model selection."""
        # Only work if we're awaiting selection
        if not self._awaiting_model_selection:
            return

        log = self.query_one("#log", ConversationLog)

        # Handle based on current agent
        if self.current_agent == "opencode":
            if 1 <= num <= len(self.opencode_models):
                model = self.opencode_models[num - 1]
                model_id = model.get("id", "")
                model_name = model.get("name", "")

                self.current_model = model_id
                self.current_provider = "opencode"
                self._awaiting_model_selection = False

                # Update badge with execution mode - ACP for :acp connect
                badge = self.query_one("#mode-badge", ModeBadge)
                badge.model = model_id
                badge.provider = self.current_provider
                badge.execution_mode = "acp"  # ACP mode for agent connections

                # Show confirmation
                t = Text()
                t.append(f"\n  ✅ ", style=f"bold {THEME['success']}")
                t.append("Model selected: ", style=THEME["text"])
                t.append(f"{model_name}", style=f"bold {THEME['cyan']}")
                t.append(f" ({model_id})\n", style=THEME["dim"])
                t.append(f"  🆓 This is a FREE model! Ready to chat.\n", style=THEME["success"])
                log.write(t)
            else:
                log.add_error(f"Invalid selection. Choose 1-{len(self.opencode_models)}")

        elif self.current_agent == "gemini":
            if 1 <= num <= len(self._gemini_models):
                model = self._gemini_models[num - 1]
                model_id = model.get("id", "")
                model_name = model.get("name", "")

                self.current_model = model_id
                self.current_provider = "gemini"
                self._awaiting_model_selection = False

                # Update badge
                badge = self.query_one("#mode-badge", ModeBadge)
                badge.model = model_id
                badge.provider = self.current_provider
                badge.execution_mode = "acp"

                # Show confirmation
                t = Text()
                t.append(f"\n  ✅ ", style=f"bold {THEME['success']}")
                t.append("Model selected: ", style=THEME["text"])
                t.append(f"{model_name}", style=f"bold {THEME['cyan']}")
                t.append(f" ({model_id})\n", style=THEME["dim"])
                t.append(f"  ✨ Ready to chat with Gemini!\n", style=THEME["success"])
                log.write(t)
            else:
                log.add_error(f"Invalid selection. Choose 1-{len(self._gemini_models)}")

        elif self.current_agent == "claude":
            if 1 <= num <= len(self._claude_models):
                model = self._claude_models[num - 1]
                model_id = model.get("id", "")
                model_name = model.get("name", "")

                self.current_model = model_id
                self.current_provider = "claude"
                self._awaiting_model_selection = False

                # Update badge
                badge = self.query_one("#mode-badge", ModeBadge)
                badge.model = model_id
                badge.provider = self.current_provider
                badge.execution_mode = "acp"

                # Show confirmation
                t = Text()
                t.append(f"\n  ✅ ", style=f"bold {THEME['success']}")
                t.append("Model selected: ", style=THEME["text"])
                t.append(f"{model_name}", style=f"bold {THEME['cyan']}")
                t.append(f" ({model_id})\n", style=THEME["dim"])
                t.append(f"  🧡 Ready to chat with Claude Code!\n", style=THEME["success"])
                log.write(t)
            else:
                log.add_error(f"Invalid selection. Choose 1-{len(self._claude_models)}")

        elif self.current_agent == "codex":
            if 1 <= num <= len(self._codex_models):
                model = self._codex_models[num - 1]
                model_id = model.get("id", "")
                model_name = model.get("name", "")

                self.current_model = model_id
                self.current_provider = "codex"
                self._awaiting_model_selection = False

                # Update badge
                badge = self.query_one("#mode-badge", ModeBadge)
                badge.model = model_id
                badge.provider = self.current_provider
                badge.execution_mode = "acp"

                # Show confirmation
                t = Text()
                t.append(f"\n  ✅ ", style=f"bold {THEME['success']}")
                t.append("Model selected: ", style=THEME["text"])
                t.append(f"{model_name}", style=f"bold {THEME['cyan']}")
                t.append(f" ({model_id})\n", style=THEME["dim"])
                t.append(f"  📜 Ready to chat with Codex CLI!\n", style=THEME["success"])
                log.write(t)
            else:
                log.add_error(f"Invalid selection. Choose 1-{len(self._codex_models)}")

        elif self.current_agent == "openhands":
            if 1 <= num <= len(self._openhands_models):
                model = self._openhands_models[num - 1]
                model_id = model.get("id", "")
                model_name = model.get("name", "")

                self.current_model = model_id
                self.current_provider = "openhands"
                self._awaiting_model_selection = False

                # Update badge
                badge = self.query_one("#mode-badge", ModeBadge)
                badge.model = model_id
                badge.provider = self.current_provider
                badge.execution_mode = "acp"

                # Show confirmation
                t = Text()
                t.append(f"\n  ✅ ", style=f"bold {THEME['success']}")
                t.append("Model selected: ", style=THEME["text"])
                t.append(f"{model_name}", style=f"bold {THEME['cyan']}")
                t.append(f" ({model_id})\n", style=THEME["dim"])
                t.append(f"  🤝 Ready to chat with OpenHands!\n", style=THEME["success"])
                log.write(t)
            else:
                log.add_error(f"Invalid selection. Choose 1-{len(self._openhands_models)}")

    def action_select_model_1(self):
        """Select item 1 in current selection mode."""
        self._select_by_number_universal(1)

    def action_select_model_2(self):
        """Select item 2 in current selection mode."""
        self._select_by_number_universal(2)

    def action_select_model_3(self):
        """Select item 3 in current selection mode."""
        self._select_by_number_universal(3)

    def action_select_model_4(self):
        """Select item 4 in current selection mode."""
        self._select_by_number_universal(4)

    def action_select_model_5(self):
        """Select item 5 in current selection mode."""
        self._select_by_number_universal(5)

    def action_select_model_6(self):
        """Select item 6 in current selection mode."""
        self._select_by_number_universal(6)

    def action_select_model_7(self):
        """Select item 7 in current selection mode."""
        self._select_by_number_universal(7)

    def action_select_model_8(self):
        """Select item 8 in current selection mode."""
        self._select_by_number_universal(8)

    def action_select_model_9(self):
        """Select item 9 in current selection mode."""
        self._select_by_number_universal(9)

    def action_navigate_model_up(self):
        """Navigate to previous model (arrow up)."""
        # Check if we're in model selection mode
        if not getattr(self, "_awaiting_byok_model", False):
            return

        model_list = getattr(self, "_byok_model_list", [])
        if not model_list:
            # Try to get provider and rebuild list if needed
            provider_id = getattr(self, "_byok_selected_provider", None)
            if provider_id:
                log = self.query_one("#log", ConversationLog)
                self._show_provider_models(provider_id, log, use_picker=False, clear_log=False)
            return

        current_idx = getattr(self, "_byok_highlighted_model_index", 0)
        new_idx = max(0, current_idx - 1)
        if new_idx != current_idx:
            self._byok_highlighted_model_index = new_idx
            provider_id = getattr(self, "_byok_selected_provider", None)
            if provider_id:
                log = self.query_one("#log", ConversationLog)
                self._show_provider_models(provider_id, log, use_picker=False, clear_log=False)
                # Scroll to keep highlighted item visible
                self._scroll_to_highlighted_item(log, new_idx, len(model_list))
                # Ensure input stays focused
                self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_model_down(self):
        """Navigate to next model (arrow down)."""
        # Check if we're in model selection mode
        if not getattr(self, "_awaiting_byok_model", False):
            return

        model_list = getattr(self, "_byok_model_list", [])
        if not model_list:
            # Try to get provider and rebuild list if needed
            provider_id = getattr(self, "_byok_selected_provider", None)
            if provider_id:
                log = self.query_one("#log", ConversationLog)
                self._show_provider_models(provider_id, log, use_picker=False, clear_log=False)
            return

        current_idx = getattr(self, "_byok_highlighted_model_index", 0)
        new_idx = min(len(model_list) - 1, current_idx + 1)
        if new_idx != current_idx:
            self._byok_highlighted_model_index = new_idx
            provider_id = getattr(self, "_byok_selected_provider", None)
            if provider_id:
                log = self.query_one("#log", ConversationLog)
                self._show_provider_models(provider_id, log, use_picker=False, clear_log=False)
                # Scroll to keep highlighted item visible
                self._scroll_to_highlighted_item(log, new_idx, len(model_list))
                # Ensure input stays focused
                self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_opencode_model_up(self):
        """Navigate to previous opencode model (arrow up)."""
        if not getattr(self, "_awaiting_model_selection", False):
            return

        if self.current_agent != "opencode":
            return

        models = self.opencode_models
        if not models:
            return

        current_idx = getattr(self, "_opencode_highlighted_model_index", 0)
        new_idx = max(0, current_idx - 1)
        if new_idx != current_idx:
            self._opencode_highlighted_model_index = new_idx
            log = self.query_one("#log", ConversationLog)
            # Use stored agent data if available, otherwise get from agent list
            agent = getattr(self, "_opencode_agent_data", None)
            if not agent:
                # Try to get from _acp_agent_list
                agent_list = getattr(self, "_acp_agent_list", [])
                for agent_id, agent_data in agent_list:
                    if agent_id == "opencode":
                        agent = agent_data
                        break
            if not agent:
                # Fallback: create minimal agent dict
                agent = {"name": "OpenCode", "short_name": "opencode"}
            self._show_opencode_models_selection(agent, log, clear_log=False)
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_opencode_model_down(self):
        """Navigate to next opencode model (arrow down)."""
        if not getattr(self, "_awaiting_model_selection", False):
            return

        if self.current_agent != "opencode":
            return

        models = self.opencode_models
        if not models:
            return

        current_idx = getattr(self, "_opencode_highlighted_model_index", 0)
        new_idx = min(len(models) - 1, current_idx + 1)
        if new_idx != current_idx:
            self._opencode_highlighted_model_index = new_idx
            log = self.query_one("#log", ConversationLog)
            # Use stored agent data if available, otherwise get from agent list
            agent = getattr(self, "_opencode_agent_data", None)
            if not agent:
                # Try to get from _acp_agent_list
                agent_list = getattr(self, "_acp_agent_list", [])
                for agent_id, agent_data in agent_list:
                    if agent_id == "opencode":
                        agent = agent_data
                        break
            if not agent:
                # Fallback: create minimal agent dict
                agent = {"name": "OpenCode", "short_name": "opencode"}
            self._show_opencode_models_selection(agent, log, clear_log=False)
            # Ensure input stays focused
            self.set_timer(0.05, self._ensure_input_focus)

    def action_select_highlighted_opencode_model(self):
        """Select the currently highlighted opencode model (Enter key)."""
        if not getattr(self, "_awaiting_model_selection", False):
            return

        if self.current_agent != "opencode":
            return

        models = self.opencode_models
        if not models:
            return

        current_idx = getattr(self, "_opencode_highlighted_model_index", 0)
        if 0 <= current_idx < len(models):
            model = models[current_idx]
            model_id = model.get("id", "")
            if model_id == "opencode/auto":
                model_id = ""
            # Remove "opencode/" prefix if present
            elif model_id.startswith("opencode/"):
                model_id = model_id[9:]

            log = self.query_one("#log", ConversationLog)
            self._awaiting_model_selection = False
            self.current_model = model_id
            self.current_provider = "opencode"

            # Connect to the model
            # _connect_agent is decorated with @work, so calling it directly
            # returns a Worker that will run the async method
            self._connect_agent("opencode", model_id)

    def _current_acp_model_list(self) -> list[Any]:
        """Return model list for the active ACP model picker."""
        agent = getattr(self, "current_agent", "")
        if agent == "opencode":
            return list(self.opencode_models)
        if agent == "gemini":
            return list(getattr(self, "gemini_models", []))
        if agent == "claude":
            return list(getattr(self, "claude_models", []))
        if agent == "codex":
            return list(getattr(self, "codex_models", []))
        if agent == "openhands":
            return list(getattr(self, "openhands_models", []))
        return []

    def _redraw_current_acp_model_picker(
        self, log: ConversationLog, clear_log: bool = False
    ) -> None:
        """Redraw the visible ACP model picker after keyboard navigation."""
        agent_data = getattr(self, f"_{self.current_agent}_agent_data", None)
        if agent_data is None:
            agent_data = {"name": self.current_agent or "Agent", "short_name": self.current_agent}
        if self.current_agent == "opencode":
            self._show_opencode_models_selection(agent_data, log, clear_log=clear_log)
        elif self.current_agent == "gemini":
            if not clear_log:
                log.clear()
            self._show_gemini_models_selection(agent_data, log)
        elif self.current_agent == "claude":
            if not clear_log:
                log.clear()
            self._show_claude_models_selection(agent_data, log)
        elif self.current_agent == "codex":
            if not clear_log:
                log.clear()
            self._show_codex_models_selection(agent_data, log)
        elif self.current_agent == "openhands":
            if not clear_log:
                log.clear()
            self._show_openhands_models_selection(agent_data, log)

    def action_navigate_acp_model_up(self):
        """Navigate to previous ACP model for the current agent."""
        if not getattr(self, "_awaiting_model_selection", False):
            return
        models = self._current_acp_model_list()
        if not models:
            return
        current_idx = getattr(self, "_opencode_highlighted_model_index", 0)
        self._opencode_highlighted_model_index = max(0, current_idx - 1)
        log = self.query_one("#log", ConversationLog)
        self._redraw_current_acp_model_picker(log, clear_log=False)
        self.set_timer(0.05, self._ensure_input_focus)

    def action_navigate_acp_model_down(self):
        """Navigate to next ACP model for the current agent."""
        if not getattr(self, "_awaiting_model_selection", False):
            return
        models = self._current_acp_model_list()
        if not models:
            return
        current_idx = getattr(self, "_opencode_highlighted_model_index", 0)
        self._opencode_highlighted_model_index = min(len(models) - 1, current_idx + 1)
        log = self.query_one("#log", ConversationLog)
        self._redraw_current_acp_model_picker(log, clear_log=False)
        self.set_timer(0.05, self._ensure_input_focus)

    def action_select_highlighted_acp_model(self):
        """Select highlighted model for the current ACP agent."""
        if not getattr(self, "_awaiting_model_selection", False):
            return
        models = self._current_acp_model_list()
        if not models:
            return
        current_idx = getattr(self, "_opencode_highlighted_model_index", 0)
        if 0 <= current_idx < len(models):
            self._select_model_by_number(current_idx + 1)

    def action_refresh_opencode_models(self):
        """Refresh OpenCode models from CLI."""
        if not getattr(self, "_awaiting_model_selection", False):
            return

        if self.current_agent != "opencode":
            return

        # Clear cache and refresh models
        try:
            from superqode.providers.opencode_models import clear_cache

            clear_cache()
            # Re-fetch models
            self._opencode_models = None
            models = self.opencode_models

            # Show updated list
            log = self.query_one("#log", ConversationLog)
            agent = getattr(self, "_opencode_agent_data", None)
            if not agent:
                agent_list = getattr(self, "_acp_agent_list", [])
                for agent_id, agent_data in agent_list:
                    if agent_id == "opencode":
                        agent = agent_data
                        break
            if not agent:
                agent = {"name": "OpenCode", "short_name": "opencode"}

            # Reset highlight index to 0
            self._opencode_highlighted_model_index = 0

            # Show message
            t = Text()
            t.append("\n  🔄 ", style=THEME["success"])
            t.append("Refreshing models from OpenCode...", style=THEME["text"])
            log.write(t)

            # Then show the model list
            self.set_timer(0.5, lambda: self._show_opencode_models_selection(agent, log))

        except Exception as e:
            log = self.query_one("#log", ConversationLog)
            t = Text()
            t.append(f"\n  ⚠️  Error refreshing: {str(e)}", style=THEME["error"])
            log.write(t)

    def action_select_highlighted_model(self):
        """Select the currently highlighted model (Enter key)."""
        if not getattr(self, "_awaiting_byok_model", False):
            return

        model_list = getattr(self, "_byok_model_list", [])
        if not model_list:
            return

        current_idx = getattr(self, "_byok_highlighted_model_index", 0)
        if 0 <= current_idx < len(model_list):
            model = model_list[current_idx]
            provider_id = getattr(self, "_byok_selected_provider", None)
            if provider_id:
                log = self.query_one("#log", ConversationLog)
                self._awaiting_byok_model = False
                self._connect_byok_mode(provider_id, model, log)

    def _complete_model_switch(self, value: str, prefix: str) -> str | None:
        candidates = self._model_switch_candidates(value, prefix)
        return candidates[0].value if candidates else None

    def _model_switch_candidates(self, value: str, prefix: str) -> list[PromptCompletionCandidate]:
        partial = value[len(prefix) :]
        if "/" not in partial:
            if partial in self._all_provider_ids():
                provider = partial
                return [
                    PromptCompletionCandidate(
                        value=value + "/",
                        label=provider,
                        description="show models for provider",
                        kind="provider",
                    )
                ]
            return [
                PromptCompletionCandidate(
                    value=f"{prefix}{provider}/",
                    label=provider,
                    description=self._provider_description(provider),
                    kind="provider",
                )
                for provider in self._all_provider_ids()
                if provider.lower().startswith(partial.lower())
            ][:8]
        provider, model_partial = partial.split("/", 1)
        return [
            PromptCompletionCandidate(
                value=f"{prefix}{provider}/{model}",
                label=model,
                description=self._model_description(provider, model),
                kind="model",
            )
            for model in self._model_ids_for_provider(provider)
            if model.lower().startswith(model_partial.lower())
        ][:8]

    @staticmethod
    def _model_description(provider_id: str, model_id: str) -> str:
        try:
            from superqode.providers.models import get_models_for_provider

            model = get_models_for_provider(provider_id, include_all=True).get(model_id)
            if model is None:
                return ""
            labels = []
            if getattr(model, "supports_tools", False):
                labels.append("tools")
            if getattr(model, "supports_reasoning", False):
                labels.append("reasoning")
            if getattr(model, "is_code_optimized", False):
                labels.append("code")
            prefix = ", ".join(labels)
            context = getattr(model, "context_display", "")
            price = getattr(model, "price_display", "")
            return " | ".join(part for part in [prefix, context, price] if part)
        except Exception:
            return ""

    @staticmethod
    def _model_ids_for_provider(provider_id: str) -> list[str]:
        try:
            from superqode.providers.models import get_models_for_provider

            return list(get_models_for_provider(provider_id, include_all=True).keys())
        except Exception:
            return []

    def _model_supports_vision(self, model: str) -> bool:
        """Best-effort check whether the active model accepts images."""
        try:
            from superqode.providers.models import get_model_info

            info = get_model_info(getattr(self, "current_provider", "") or "", model)
            if info is not None:
                return bool(getattr(info, "supports_vision", False))
        except Exception:
            pass
        # Unknown: don't discourage; assume capable.
        return True

    def _set_status_model(self, model: str) -> None:
        """Show the active model in the visible status bar (ColorfulStatusBar)."""
        try:
            from superqode.app.widgets import ColorfulStatusBar

            self.query_one("#status-bar", ColorfulStatusBar).active_model = model or ""
        except Exception:  # noqa: BLE001
            pass

    def _show_grok_models(self, log) -> None:
        """Schedule CLI model discovery without blocking the Textual event loop."""
        self.run_worker(self._show_grok_models_async(log), exclusive=False)

    async def _show_grok_models_async(self, log) -> None:
        """List the subscription models the signed-in Grok CLI reports."""
        from superqode.providers import grok_cli_auth
        from superqode.providers.models import get_models_for_provider

        # An explicit list request always re-probes the CLI.
        grok_cli_auth.clear_cli_models_cache()
        listing: dict = {}
        try:
            listing = await asyncio.to_thread(grok_cli_auth.cached_cli_models)
        except Exception:  # noqa: BLE001 - CLI probing is best-effort
            pass
        live = bool(listing.get("models"))
        default_id = str(listing.get("default") or "grok-build")
        models = get_models_for_provider("grok-cli")

        t = Text()
        t.append("\n  Grok subscription models\n\n", style=f"bold {THEME['text']}")
        for info in models.values():
            marker = "▸ " if info.id == default_id else "  "
            t.append(f"  {marker}", style=THEME["success" if marker.strip() else "muted"])
            t.append(f"{info.id:28s}", style=THEME["cyan"])
            t.append(f"{info.context_display:>6s}  ", style=THEME["muted"])
            t.append(f"{info.description}\n", style=THEME["dim"])
        t.append("\n  Source: ", style=THEME["muted"])
        if live:
            t.append("`grok models` (signed-in CLI catalog)\n", style=THEME["text"])
        elif shutil.which("grok") is None:
            t.append("builtin fallback: Grok CLI not installed\n", style=THEME["warning"])
            t.append("  Install: ", style=THEME["muted"])
            t.append("curl -fsSL https://x.ai/cli/install.sh | bash\n", style=THEME["cyan"])
        else:
            t.append(
                "builtin fallback: CLI not signed in; run `grok login`\n",
                style=THEME["warning"],
            )
        t.append("  Select and connect with ", style=THEME["muted"])
        t.append(":grok model", style=THEME["cyan"])
        t.append(" (picker) or ", style=THEME["muted"])
        t.append(":grok model <name>\n", style=THEME["cyan"])
        log.write_feedback(t)

    def _show_grok_model_picker(self, log) -> None:
        """Interactive picker over the subscription catalog; Enter connects.

        Reuses the BYOK model picker (numbers, arrows, search), so selecting a
        model connects grok-cli/<model> on the subscription without switching
        to the Grok CLI.
        """
        if not self._import_grok_token(
            log, on_login_success=lambda: self._show_grok_model_picker(log)
        ):
            return
        self.run_worker(self._show_grok_model_picker_async(log), exclusive=False)

    async def _show_grok_model_picker_async(self, log) -> None:
        """Warm the CLI catalog off-thread, then open the native model picker."""
        from superqode.providers import grok_cli_auth

        try:
            await asyncio.to_thread(grok_cli_auth.cached_cli_models)
        except Exception:  # noqa: BLE001 - the picker has a builtin fallback
            pass
        self._show_provider_models("grok-cli", log, use_picker=False)

    def _claude_model_cmd(self, model: str, log) -> None:
        from superqode.runtime.claude_agent_sdk import CLAUDE_MODELS

        if not model:
            t = Text()
            t.append("\n  Claude models (curated):\n", style=f"bold {THEME['text']}")
            for i, (mid, name) in enumerate(CLAUDE_MODELS, 1):
                t.append(f"    [{i}] ", style=THEME["dim"])
                t.append(f"{name}", style=THEME["text"])
                t.append(f"  {mid or '(default)'}\n", style=THEME["muted"])
            t.append("\n  Set with ", style=THEME["muted"])
            t.append(":claude model <id>", style=THEME["cyan"])
            t.append("  (e.g. :claude model claude-opus-4-8)\n", style=THEME["muted"])
            log.write(t)
            return
        chosen = "" if model.lower() in {"default", "none", "auto"} else model
        try:
            runtime = self._claude_runtime_or_connect(log)
            runtime.set_model(chosen)
            if getattr(self, "_pure_mode", None) is not None:
                self._pure_mode.session.model = chosen
            self._set_status_model(chosen)
            log.add_success(f"Claude model set to {chosen or 'Claude Code default'}")
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Could not set Claude model: {exc}")

    def _workflow_provider_model(self, spec) -> tuple[str, str]:
        """Resolve provider/model for an explicit workflow run."""
        provider = getattr(self, "current_provider", "") or ""
        model = getattr(self, "current_model", "") or ""
        primary = getattr(getattr(spec, "model_policy", None), "primary", None)
        if (not provider or not model) and primary:
            primary_text = str(primary)
            parsed_primary = split_provider_model_ref(primary_text)
            if parsed_primary.provider:
                inferred_provider, inferred_model = parsed_primary.provider, parsed_primary.model
                provider = provider or inferred_provider
                model = model or inferred_model
            else:
                model = model or primary_text
        return provider, model

    def _is_model_query(self, text: str) -> bool:
        """Check if the user is asking about which model/AI is being used."""
        text_lower = text.lower().strip()

        # Common patterns for asking about the model
        model_query_patterns = [
            "what model",
            "which model",
            "what ai",
            "which ai",
            "who are you",
            "what are you",
            "which llm",
            "what llm",
            "model are you",
            "model you are",
            "ai are you",
            "ai you are",
            "what's your model",
            "what is your model",
            "your model name",
            "model name",
            "are you gpt",
            "are you claude",
            "are you gemini",
            "are you llama",
            "are you glm",
            "are you qwen",
            "are you deepseek",
        ]

        for pattern in model_query_patterns:
            if pattern in text_lower:
                return True

        return False

    def _answer_model_query(self, log: ConversationLog):
        """Answer the user's question about which model is being used."""
        t = Text()
        t.append("\n")

        if self.current_model:
            # We have model info
            t.append("  🤖 ", style=f"bold {THEME['purple']}")
            t.append("Current AI Model:\n\n", style=f"bold {THEME['text']}")

            t.append("  📊 Model: ", style=THEME["muted"])
            t.append(f"{self.current_model}\n", style=f"bold {THEME['cyan']}")

            if self.current_provider:
                t.append("  ☁️  Provider: ", style=THEME["muted"])
                t.append(f"{self.current_provider}\n", style=f"bold {THEME['success']}")

            if self.current_agent:
                t.append("  🔧 Agent: ", style=THEME["muted"])
                t.append(f"{self.current_agent}\n", style=f"bold {THEME['orange']}")

            # Execution mode
            badge = self.query_one("#mode-badge", ModeBadge)
            if badge.execution_mode:
                mode_labels = {
                    "acp": "ACP (Agent Control Protocol)",
                    "byok": "BYOK (Bring Your Own Key)",
                }
                t.append("  ⚡ Mode: ", style=THEME["muted"])
                t.append(
                    f"{mode_labels.get(badge.execution_mode, badge.execution_mode)}\n",
                    style=THEME["text"],
                )

        elif hasattr(self, "_pure_mode") and self._pure_mode.session.connected:
            # Pure mode
            t.append("  🧪 ", style=f"bold {THEME['pink']}")
            t.append("Session Active:\n\n", style=f"bold {THEME['text']}")

            t.append("  📊 Model: ", style=THEME["muted"])
            t.append(f"{self._pure_mode.session.model}\n", style=f"bold {THEME['cyan']}")

            t.append("  ☁️  Provider: ", style=THEME["muted"])
            t.append(f"{self._pure_mode.session.provider}\n", style=f"bold {THEME['success']}")

        else:
            # Not connected
            t.append("  ℹ️  ", style=f"bold {THEME['muted']}")
            t.append("No AI model connected yet.\n", style=THEME["text"])
            t.append("  Use ", style=THEME["muted"])
            t.append(":connect acp <name>", style=f"bold {THEME['cyan']}")
            t.append(" to connect to an agent.\n", style=THEME["muted"])

        t.append("\n")
        log.write(t)

    @staticmethod
    def _normalize_acp_model_id(agent_type: str, model: str) -> str | None:
        """Normalize a UI model value before sending it to an ACP agent."""
        if not model or agent_type not in ("codex", "grok", "openhands", "opencode"):
            return None
        normalized = model.strip()
        # "auto"/"default" is a UI placeholder meaning "let the agent
        # pick its configured default model" — it is NOT a real model id.
        if normalized.lower() in (
            "auto",
            "default",
            "opencode/auto",
            "opencode/default",
            "grok/auto",
            "grok/default",
        ):
            return None
        # OpenCode model ids are provider/model pairs (for example
        # opencode/big-pickle or deepseek/deepseek-v4...). Only prefix legacy
        # bare ids; do not rewrite real provider ids.
        if agent_type == "opencode" and "/" not in normalized:
            return f"opencode/{normalized}"
        # Grok Build expects bare xAI model ids (grok-4.5, grok-build-0.1) or
        # its own "grok-build" default alias; strip UI/provider prefixes.
        if agent_type == "grok":
            for prefix in ("xai/", "grok/"):
                if normalized.lower().startswith(prefix):
                    normalized = normalized[len(prefix) :]
                    break
            return normalized or None
        return normalized

    def _show_agent_header_with_model(self, name: str, model: str, log: ConversationLog):
        """Show agent output header with model information and approval mode.

        SuperQode style: Quantum-inspired, minimal, clean.
        """
        header = Text()
        header.append("\n")

        # Gradient line using SuperQode purple palette
        line = "─" * 60
        for i, char in enumerate(line):
            color = GRADIENT_PURPLE[i % len(GRADIENT_PURPLE)]
            header.append(char, style=color)
        header.append("\n")

        # Agent name with quantum icon (no emoji)
        header.append(f"  ◈ ", style=f"bold {SQ_COLORS.primary}")
        header.append(f"{name.upper()} ", style=f"bold {SQ_COLORS.text_primary}")
        header.append("is working", style=SQ_COLORS.text_muted)
        header.append("\n")

        # Model info
        header.append(f"  Model: ", style=SQ_COLORS.text_dim)
        header.append(f"{model}", style=f"bold {SQ_COLORS.info}")
        header.append("  │  ", style=SQ_COLORS.text_ghost)

        # Show approval mode indicator (using ● instead of colored circles emoji)
        mode_colors = {"auto": SQ_COLORS.success, "ask": SQ_COLORS.warning, "deny": SQ_COLORS.error}
        mode_labels = {"auto": "AUTO", "ask": "ASK", "deny": "DENY"}

        mode = getattr(self, "approval_mode", "ask")
        color = mode_colors.get(mode, SQ_COLORS.warning)
        label = mode_labels.get(mode, "ASK")

        header.append("● ", style=f"bold {color}")
        header.append(f"{label}", style=f"bold {color}")
        header.append("\n")
        header.append(f"  [Ctrl+T] hide logs  ", style=SQ_COLORS.text_ghost)
        header.append("[Esc] cancel  ", style=SQ_COLORS.text_ghost)
        header.append("[Ctrl+Z] undo\n", style=SQ_COLORS.text_ghost)
        log.write(header)

        # Create checkpoint before agent operation
        self._create_checkpoint_before_agent(f"{name} operation")

    def _show_provider_models(
        self,
        provider_id: str,
        log: ConversationLog,
        use_picker: bool = False,
        clear_log: bool = True,
    ):
        """Show models for a specific provider with smart grouping and API key guidance.

        Args:
            provider_id: Provider ID
            log: Conversation log
            use_picker: If True, use interactive picker widget. If False, use numbered list.
            clear_log: If True, clear log and scroll to top. If False, update in place (for navigation).
        """
        # CRITICAL SAFEGUARD: If we just showed the BYOK picker, don't show models
        # This prevents "2" or other inputs from immediately selecting a provider
        if getattr(self, "_just_showed_byok_picker", False):
            if not getattr(self, "_awaiting_byok_model", False):
                log.add_error(
                    f"Unexpected model display for {provider_id}. Showing provider list instead."
                )
                self._show_connect_picker(log)
                return

        from superqode.providers.registry import ProviderCategory
        from superqode.providers.dynamic import resolve_provider_def
        from superqode.providers.models import (
            get_models_for_provider,
            get_data_source,
        )
        import os

        # Try interactive picker first if enabled
        if use_picker:
            try:
                self._show_provider_models_picker(provider_id, log)
                return
            except Exception as e:
                # Fall back to numbered list if picker fails
                pass

        provider_def = resolve_provider_def(provider_id)
        if not provider_def:
            log.add_error(f"Unknown provider: {provider_id}")
            return

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append(f"{provider_def.name} Models\n", style=f"bold {THEME['text']}")

        # Check configuration status
        configured = False
        missing_keys = []
        if provider_def.env_vars:
            for env_var in provider_def.env_vars:
                if os.environ.get(env_var):
                    configured = True
                    break
                else:
                    missing_keys.append(env_var)
        else:
            configured = True  # No API key needed

        if not configured:
            t.append(f"\n  ⚠️  ", style=THEME["warning"])
            t.append("API Key Required\n", style=f"bold {THEME['warning']}")
            t.append(
                "    'Free' below means $0 per token — the provider still requires\n"
                "    an account + API key. SuperQode never stores keys.\n",
                style=THEME["muted"],
            )
            t.append(f"    Set: ", style=THEME["muted"])
            t.append(
                f"export {'='.join(provider_def.env_vars[:1])}='your-api-key'\n",
                style=THEME["cyan"],
            )
            if len(provider_def.env_vars) > 1:
                t.append(f"    Or: ", style=THEME["muted"])
                t.append(
                    f"export {'='.join(provider_def.env_vars[1:2])}='your-api-key'\n",
                    style=THEME["cyan"],
                )
            if provider_def.docs_url:
                t.append(f"    Get key: ", style=THEME["muted"])
                t.append(f"{provider_def.docs_url}\n", style=THEME["cyan"])
            t.append("\n", style="")

        # Check if this is a local provider
        if provider_def.category == ProviderCategory.LOCAL:
            # CRITICAL: Only show models if we're actually in model selection mode
            # If we're supposed to show the provider picker, don't show models!
            if not getattr(self, "_awaiting_local_model", False) and not getattr(
                self, "_awaiting_byok_model", False
            ):
                # We should be showing provider picker, not models!
                # Redirect to local provider picker instead
                log.add_info(f"Showing local providers. Select a provider first.")
                self._show_local_provider_picker(log)
                return
            # Load local models asynchronously (only if we're in model selection mode)
            self.run_worker(self._show_local_provider_models(provider_id, log))
            return

        t.append(f"  📊 Source: {get_data_source()}\n", style=THEME["dim"])
        t.append(
            "  Labels: 🔧 tools  👁️ vision  🧠 reasoning  💻 coding  ctx=context  price=$/1M\n\n",
            style=THEME["dim"],
        )

        # Get models from database
        db_models = get_models_for_provider(provider_id, include_all=True)

        if db_models:
            # Helper function to detect latest models for any provider
            def is_latest_model(model_id: str, info) -> bool:
                """Detect if a model is the latest version for its provider."""
                model_lower = model_id.lower()
                name_lower = info.name.lower()

                # Generic patterns that indicate latest models
                latest_indicators = [
                    "latest",
                    "new",
                    "preview",
                    "newest",
                    "current",
                    # Version patterns (highest versions)
                    "5.4",
                    "5.3",
                    "5.2",
                    "5.1",
                    "4.8",
                    "4.7",
                    "4.6",
                    "4.5",
                    "3.2",
                    "3.1",
                    "3.0",
                    # Specific latest model patterns by provider
                    "gpt-5.4",
                    "gpt-5.3-codex",
                    "gpt-5.2",
                    "gpt-5.1",
                    "gemini-flash-latest",
                    "gemini-3.1-pro",
                    "gemini 3.5",
                    "gemini 3.1",
                    "claude-opus-4-8",
                    "claude-opus-4-7",
                    "claude-sonnet-4-6",
                    "claude-opus-4-5",
                    "claude-haiku-4-5",
                    "glm-4.7",
                    "glm-4-plus",
                    "glm-4-air",
                    "glm-4",  # Zhipu GLM-4.7
                    "deepseek-v3.2",
                    "deepseek-v3",
                    "deepseek-r1",  # DeepSeek V3.2
                    "grok-3",
                    "grok-3-",  # xAI Grok-3
                    "mistral-large-2411",
                    "codestral-latest",  # Mistral
                    "qwen3",
                    "qwen2.5",  # Alibaba Qwen
                    "llama-3.3",
                    "llama3.3",  # Meta Llama
                    "moonshot-v1-128k",
                    "kimi-k2",  # Moonshot
                    "abab6.5",  # MiniMax
                ]

                # Check for latest indicators
                if any(
                    indicator in model_lower or indicator in name_lower
                    for indicator in latest_indicators
                ):
                    return True

                # Check release date - if released in 2025+ likely latest
                if info.released and (
                    info.released.startswith("2025") or info.released.startswith("2026")
                ):
                    return True

                return False

            # Group models by category
            recommended = []  # Code-optimized or reasoning models
            budget = []  # < $1 input price
            free = []  # Free models
            others = []  # Everything else

            for model_id, info in db_models.items():
                is_latest = is_latest_model(model_id, info)

                if info.input_price == 0 and info.output_price == 0:
                    free.append((model_id, info))
                elif is_latest or info.is_code_optimized or info.supports_reasoning:
                    # Latest models always go to recommended, even if not explicitly code-optimized
                    recommended.append((model_id, info))
                elif info.input_price < 1.0:
                    budget.append((model_id, info))
                else:
                    others.append((model_id, info))

            # Sort each group - prioritize latest models across all providers
            def get_latest_priority(model_id: str, info) -> int:
                """Get priority score for latest models - lower is higher priority."""
                model_lower = model_id.lower()
                name_lower = info.name.lower()

                # Highest priority: Very latest models (2026+, then late 2025 releases)
                if info.released:
                    if info.released.startswith("2026"):
                        return -11
                    if "-12" in info.released:
                        return -10  # Highest priority
                    elif "-11" in info.released:
                        return -9
                    elif "-10" in info.released:
                        return -8
                    elif info.released.startswith("2025"):
                        return -7

                # High priority: Latest version indicators
                # Priority order: -10 (highest) to -6 (medium)
                latest_patterns = [
                    ("gpt-5.4-pro", -12),
                    ("gpt-5.4", -12),
                    ("gpt-5.3-codex", -11),
                    ("5.3", -11),
                    ("claude-opus-4-8", -12),
                    ("claude-opus-4-7", -12),
                    ("claude-sonnet-4-6", -11),
                    ("claude-opus-4-6", -9),
                    # Latest flagship models (2025-12 releases)
                    ("gpt-5.2", -10),
                    ("5.2", -10),
                    ("gemini-flash-latest", -10),
                    ("gemini-3.1-pro", -10),
                    ("gemini 3.5", -10),
                    ("gemini 3.1", -10),
                    # Latest major versions (2025 releases)
                    ("glm-4.7", -9),
                    ("glm-4-plus", -9),
                    ("glm-4-air", -9),  # Zhipu GLM-4.7
                    ("deepseek-v3.2", -9),
                    ("deepseek-v3", -9),
                    ("deepseek-r1", -9),  # DeepSeek V3.2
                    ("grok-3", -9),
                    ("grok-3-", -9),  # xAI Grok-3
                    ("claude-opus-4-5", -8),
                    ("claude-haiku-4-5", -9),  # Claude 4.5
                    # Recent major versions
                    ("gpt-5.1", -8),
                    ("5.1", -8),
                    ("mistral-large-2411", -8),
                    ("codestral-latest", -8),  # Mistral
                    ("qwen3", -8),
                    ("qwen2.5", -7),  # Alibaba Qwen
                    ("llama-3.3", -7),
                    ("llama3.3", -7),  # Meta Llama
                    ("kimi-k2", -8),  # Moonshot Kimi
                    ("abab6.5", -8),  # MiniMax
                ]

                for pattern, prio in latest_patterns:
                    if pattern in model_lower or pattern in name_lower:
                        return prio

                # Medium priority: Preview/latest indicators
                if "preview" in model_lower or "latest" in model_lower or "newest" in model_lower:
                    return -6

                return 0  # Default priority

            def sort_key_recommended(x):
                model_id, info = x
                priority = get_latest_priority(model_id, info)
                # Then by code-optimized, then by price
                return (priority, not info.is_code_optimized, info.input_price)

            def sort_key_others(x):
                model_id, info = x
                priority = get_latest_priority(model_id, info)
                return (priority, info.name)

            recommended.sort(key=sort_key_recommended)
            budget.sort(key=lambda x: x[1].input_price)
            free.sort(key=lambda x: x[1].name)
            others.sort(key=sort_key_others)

            idx = 1
            model_list = []

            # Show Recommended models first
            if recommended:
                t.append(f"  🎯 Recommended for Coding:\n", style=f"bold {THEME['success']}")

                # Show latest models first (all providers)
                def is_latest_display(m):
                    model_id, info = m
                    return get_latest_priority(model_id, info) < 0

                latest_models = [m for m in recommended if is_latest_display(m)]
                other_recommended = [m for m in recommended if m not in latest_models]
                # Combine: latest models first, then others
                sorted_recommended = latest_models + other_recommended

                for model_id, info in sorted_recommended[
                    :15
                ]:  # Increased limit to show more latest models
                    # Highlight current selection - make it VERY visible
                    is_highlighted = (idx - 1) == getattr(self, "_byok_highlighted_model_index", 0)
                    if is_highlighted:
                        # Simple highlight - just bold and arrow
                        t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                        t.append(
                            f"[{idx:2}] ",
                            style=self._picker_link_style(f"bold {THEME['success']}", idx),
                        )
                        t.append(f"{info.name:<25}", style=f"bold {THEME['success']}")
                        t.append(f"{info.price_display:>12}", style=f"bold {THEME['success']}")
                        t.append(
                            f" • {info.context_display:>6} ctx", style=f"bold {THEME['success']}"
                        )
                        caps = []
                        if info.supports_tools:
                            caps.append("🔧")
                        if info.supports_vision:
                            caps.append("👁️")
                        if info.supports_reasoning:
                            caps.append("🧠")
                        if info.is_code_optimized:
                            caps.append("💻")
                        if caps:
                            t.append(f" • {' '.join(caps)}", style=f"bold {THEME['success']}")
                        t.append(f"  ← SELECTED\n", style=f"bold {THEME['success']}")
                        t.append(f"         {model_id}\n", style=THEME["muted"])
                    else:
                        t.append(
                            f"    [{idx:2}] ",
                            style=self._picker_link_style(THEME["dim"], idx),
                        )
                        # Highlight latest models
                        is_latest = get_latest_priority(model_id, info) < 0
                        name_style = (
                            f"bold {THEME['success']}" if is_latest else f"bold {THEME['text']}"
                        )
                        t.append(f"{info.name:<25}", style=name_style)
                        t.append(f"{info.price_display:>12}", style=THEME["gold"])
                        t.append(f" • {info.context_display:>6} ctx", style=THEME["cyan"])

                        # Capabilities
                        caps = []
                        if info.supports_tools:
                            caps.append("🔧")
                        if info.supports_vision:
                            caps.append("👁️")
                        if info.supports_reasoning:
                            caps.append("🧠")
                        if info.is_code_optimized:
                            caps.append("💻")
                        if caps:
                            t.append(f" • {' '.join(caps)}", style=THEME["dim"])

                        t.append(f"\n         {model_id}\n", style=THEME["muted"])

                    model_list.append(model_id)
                    idx += 1
                t.append("\n", style="")

            # Show Budget options
            if budget:
                t.append(f"  💰 Budget-Friendly (< $1/1M):\n", style=f"bold {THEME['cyan']}")
                for model_id, info in budget[:6]:
                    t.append(f"    [{idx:2}] ", style=self._picker_link_style(THEME["dim"], idx))
                    t.append(f"{info.name:<25}", style=f"bold {THEME['text']}")
                    t.append(f"{info.price_display:>12}", style=THEME["gold"])
                    t.append(f" • {info.context_display:>6} ctx", style=THEME["cyan"])

                    caps = []
                    if info.supports_tools:
                        caps.append("🔧")
                    if caps:
                        t.append(f" • {' '.join(caps)}", style=THEME["dim"])

                    t.append(f"\n         {model_id}\n", style=THEME["muted"])

                    model_list.append(model_id)
                    idx += 1
                t.append("\n", style="")

            # Show Free models
            if free:
                if configured:
                    t.append(f"  🆓 Free Models ($0/token):\n", style=f"bold {THEME['success']}")
                else:
                    t.append(f"  🆓 Free Models ($0/token — ", style=f"bold {THEME['success']}")
                    t.append(
                        f"needs {provider_def.env_vars[0] if provider_def.env_vars else 'API key'}",
                        style=f"bold {THEME['warning']}",
                    )
                    t.append("):\n", style=f"bold {THEME['success']}")
                for model_id, info in free[:6]:
                    t.append(f"    [{idx:2}] ", style=self._picker_link_style(THEME["dim"], idx))
                    t.append(f"{info.name:<25}", style=f"bold {THEME['success']}")
                    t.append(f"{'FREE':>12}", style=THEME["success"])
                    t.append(f" • {info.context_display:>6} ctx", style=THEME["cyan"])

                    caps = []
                    if info.supports_tools:
                        caps.append("🔧")
                    if info.is_code_optimized:
                        caps.append("💻")
                    if caps:
                        t.append(f" • {' '.join(caps)}", style=THEME["dim"])

                    t.append(f"\n         {model_id}\n", style=THEME["muted"])

                    model_list.append(model_id)
                    idx += 1
                t.append("\n", style="")

            # Show others if there are many (latest models first)
            if others and idx < 30:  # Increased limit
                remaining = 30 - idx
                # Prioritize latest models in others too
                latest_others = [m for m in others if get_latest_priority(m[0], m[1]) < 0]
                regular_others = [m for m in others if m not in latest_others]
                sorted_others = latest_others + regular_others

                for model_id, info in sorted_others[:remaining]:
                    t.append(f"    [{idx:2}] ", style=self._picker_link_style(THEME["dim"], idx))
                    # Highlight latest models
                    is_latest = get_latest_priority(model_id, info) < 0
                    name_style = f"bold {THEME['success']}" if is_latest else THEME["text"]
                    t.append(f"{info.name:<25}", style=name_style)
                    t.append(f"{info.price_display:>12}", style=THEME["gold"])
                    t.append(f" • {info.context_display:>6} ctx", style=THEME["cyan"])
                    t.append(f"\n         {model_id}\n", style=THEME["muted"])

                    model_list.append(model_id)
                    idx += 1

            if len(db_models) > len(model_list):
                remaining = len(db_models) - len(model_list)
                t.append(f"    ... and {remaining} more model(s)\n", style=THEME["dim"])
        else:
            # Fall back to example models - prioritize latest ones
            t.append(f"  Available models:\n", style=THEME["muted"])
            model_list = []

            # Special case: Hugging Face BYOK should show recommended models
            if provider_id == "huggingface":
                try:
                    from superqode.providers.huggingface import RECOMMENDED_MODELS

                    all_models = []
                    for category_models in RECOMMENDED_MODELS.values():
                        all_models.extend(category_models)

                    seen = set()
                    unique_models = []
                    for m in all_models:
                        if m not in seen:
                            seen.add(m)
                            unique_models.append(m)

                    if unique_models:
                        t.append(f"  Recommended models:\n", style=THEME["muted"])
                        for idx, model in enumerate(unique_models[:30], 1):
                            is_highlighted = (idx - 1) == getattr(
                                self, "_byok_highlighted_model_index", 0
                            )
                            if is_highlighted:
                                t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                                t.append(
                                    f"[{idx:2}] ",
                                    style=self._picker_link_style(f"bold {THEME['success']}", idx),
                                )
                                t.append(f"{model}", style=f"bold {THEME['success']}")
                                t.append(f"  ← SELECTED\n", style=f"bold {THEME['success']}")
                            else:
                                t.append(
                                    f"    [{idx:2}] ",
                                    style=self._picker_link_style(THEME["dim"], idx),
                                )
                                t.append(f"{model}\n", style=THEME["text"])
                            model_list.append(model)
                except Exception:
                    pass

            if not model_list:
                # Sort example models to show latest first
                def sort_example_models(model_id: str) -> int:
                    """Sort example models - latest first."""
                    model_lower = model_id.lower()
                    # Latest models get higher priority (lower number)
                    if any(
                        x in model_lower
                        for x in ["5.4", "4.7", "5.2", "5.1", "3.2", "3.3", "k2", "6.5"]
                    ):
                        return 0
                    elif any(x in model_lower for x in ["4.5", "4-plus", "4-air", "2.5"]):
                        return 1
                    else:
                        return 2

                sorted_models = sorted(provider_def.example_models, key=sort_example_models)

                for idx, model in enumerate(sorted_models[:15], 1):  # Show more models
                    # Highlight current selection
                    is_highlighted = (idx - 1) == getattr(self, "_byok_highlighted_model_index", 0)
                    if is_highlighted:
                        t.append(f"  ▶ ", style=f"bold {THEME['success']}")
                        t.append(
                            f"[{idx:2}] ",
                            style=self._picker_link_style(f"bold {THEME['success']}", idx),
                        )
                        # Highlight latest models
                        is_latest = any(
                            x in model.lower()
                            for x in ["5.4", "4.7", "5.2", "5.1", "3.2", "3.3", "k2", "6.5"]
                        )
                        name_style = (
                            f"bold {THEME['success']}" if is_latest else f"bold {THEME['success']}"
                        )
                        t.append(f"{model}", style=name_style)
                        t.append(f"  ← SELECTED\n", style=f"bold {THEME['success']}")
                    else:
                        t.append(
                            f"    [{idx:2}] ",
                            style=self._picker_link_style(THEME["dim"], idx),
                        )
                        # Highlight latest models
                        is_latest = any(
                            x in model.lower()
                            for x in ["5.4", "4.7", "5.2", "5.1", "3.2", "3.3", "k2", "6.5"]
                        )
                        name_style = f"bold {THEME['success']}" if is_latest else THEME["text"]
                        t.append(f"{model}\n", style=name_style)
                    model_list.append(model)

        t.append(f"\n  💡 Quick Connect:\n", style=THEME["muted"])
        t.append(f"    Type number (1-{len(model_list)}) to select by number\n", style=THEME["dim"])
        t.append(f"    Or type model name to search and select\n", style=THEME["dim"])
        t.append(f"    Or: ", style=THEME["dim"])
        t.append(f":connect {provider_id}/<model>", style=THEME["success"])
        t.append(" for direct connect\n", style=THEME["text"])
        t.append(f"    Use ", style=THEME["dim"])
        t.append(f":back", style=THEME["cyan"])
        t.append(" to return to provider list, or ", style=THEME["dim"])
        t.append(f":home", style=THEME["cyan"])
        t.append(" to cancel\n", style=THEME["text"])
        t.append("\n", style="")

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

        # Store for selection - use model_list which matches display order
        # This ensures navigation index matches the displayed models
        # CRITICAL: Always set the model list to match the display order
        # model_list is always defined (initialized in both if db_models and else blocks)
        self._byok_model_list = model_list if model_list else []
        self._byok_all_model_list = list(db_models) if db_models else list(self._byok_model_list)

        if db_models:
            self._byok_model_info = db_models  # Store model info for picker
        else:
            self._byok_model_info = {}
        self._byok_selected_provider = provider_id
        # Only set _awaiting_byok_model if it's not being handled by the caller
        # This prevents the same input from being processed as model selection
        # immediately after provider selection
        if not hasattr(self, "_skip_set_awaiting_model") or not self._skip_set_awaiting_model:
            self._awaiting_byok_model = True
        else:
            # Clear the flag so it doesn't affect future calls
            self._skip_set_awaiting_model = False
        # Preserve current highlight if already set, otherwise start with first
        # Only reset on initial display, preserve during navigation
        if clear_log:
            if not hasattr(self, "_byok_highlighted_model_index"):
                self._byok_highlighted_model_index = 0
            else:
                # Reset to 0 on initial display
                self._byok_highlighted_model_index = 0
        else:
            # During navigation, preserve the index (it's already set by navigation methods)
            if not hasattr(self, "_byok_highlighted_model_index"):
                self._byok_highlighted_model_index = 0

        # Ensure input stays focused for keyboard navigation
        self.set_timer(0.05, self._ensure_input_focus)

    def _show_provider_models_picker(self, provider_id: str, log: ConversationLog):
        """Show interactive model picker widget with keyboard navigation."""
        from superqode.providers.dynamic import resolve_provider_def
        from superqode.providers.models import get_models_for_provider
        from superqode.widgets.model_picker import ModelPickerWidget, ModelOption

        provider_def = resolve_provider_def(provider_id)
        if not provider_def:
            log.add_error(f"Unknown provider: {provider_id}")
            return

        # Get models
        db_models = get_models_for_provider(provider_id, include_all=True)

        if not db_models:
            # Fall back to numbered list
            self._show_provider_models(provider_id, log, use_picker=False)
            return

        # Helper to check if model is latest (same logic as in _show_provider_models)
        def is_latest_model(model_id: str, info) -> bool:
            """Check if model is latest."""
            model_lower = model_id.lower()
            name_lower = info.name.lower()

            # Check release date
            if info.released and (
                info.released.startswith("2025") or info.released.startswith("2026")
            ):
                return True

            # Check latest patterns
            latest_patterns = [
                "gpt-5.4",
                "gpt-5.3-codex",
                "5.3",
                "gpt-5.2",
                "5.2",
                "gemini-flash-latest",
                "gemini-3.1-pro",
                "gemini 3.5",
                "gemini 3.1",
                "glm-4.7",
                "glm-4-plus",
                "deepseek-v3.2",
                "grok-3",
                "claude-opus-4-8",
                "claude-opus-4-7",
                "claude-sonnet-4-6",
                "claude-opus-4-5",
                "claude-haiku-4-5",
                "preview",
                "latest",
            ]

            return any(
                pattern in model_lower or pattern in name_lower for pattern in latest_patterns
            )

        # Convert to ModelOption format
        model_options = []
        for model_id, info in db_models.items():
            # Get capabilities
            caps = []
            if info.supports_tools:
                caps.append("🔧")
            if info.supports_vision:
                caps.append("👁️")
            if info.supports_reasoning:
                caps.append("🧠")
            if info.is_code_optimized:
                caps.append("💻")

            # Check if latest
            is_latest = is_latest_model(model_id, info)

            model_options.append(
                ModelOption(
                    id=model_id,
                    name=info.name,
                    price=info.price_display,
                    context=info.context_display,
                    capabilities=caps,
                    is_latest=is_latest,
                )
            )

        # Sort by latest first (same logic as numbered list)
        def sort_models(m: ModelOption) -> tuple:
            priority = 0
            if m.is_latest:
                priority = -10
            return (priority, m.name)

        model_options.sort(key=sort_models)

        # Create and mount picker widget
        from superqode.widgets.model_picker import ModelPickerWidget

        picker = ModelPickerWidget(provider_def.name, model_options)

        # Set up message handlers using textual's message system
        def handle_model_selected(event: ModelPickerWidget.ModelSelected) -> None:
            """Handle model selection from picker."""
            self._awaiting_byok_model = False
            self._connect_byok_mode(provider_id, event.model_id, log)
            # Remove picker widget
            try:
                picker.remove()
            except Exception:
                pass

        def handle_picker_cancelled(event: ModelPickerWidget.Cancelled) -> None:
            """Handle picker cancellation."""
            self._awaiting_byok_model = False
            try:
                picker.remove()
            except Exception:
                pass

        # Use textual's message watching

        self.set_timer(0.1, lambda: self._setup_picker_handlers(picker, provider_id, log))

        # Mount picker to the app
        self.mount(picker)

        # Store for cleanup
        self._model_picker_widget = picker
        self._picker_provider_id = provider_id
        self._picker_log = log

    async def _show_openai_compatible_models(self, provider_id: str, log: ConversationLog):
        """List models from an OpenAI-compatible local server (llama.cpp, custom).

        These servers (llama-server, vLLM-style, custom endpoints) expose
        ``/v1/models`` and load their model at launch, so we read whatever is
        currently served and let the user connect to it.
        """
        import asyncio
        import os

        from superqode.local.bench import list_endpoint_models
        from superqode.providers.dynamic import resolve_provider_def
        from superqode.providers.local.base import is_embedding_model

        provider_def = resolve_provider_def(provider_id)
        name = provider_def.name if provider_def else provider_id
        base_url = ""
        if provider_def:
            if provider_def.base_url_env:
                base_url = os.environ.get(provider_def.base_url_env, "") or ""
            base_url = base_url or provider_def.default_base_url or ""
        base_url = base_url or "http://localhost:8080/v1"

        log.add_info(f"Checking {name} at {base_url}...")
        try:
            ids = await asyncio.to_thread(list_endpoint_models, base_url)
        except Exception:
            ids = []
        models = [m for m in ids if not is_embedding_model(m)]

        if not models:
            # No server is up. Cached GGUF files are useful start hints, but
            # they are not chat-ready models until llama-server is actually
            # serving one, so never put them in the selectable model list here.
            if provider_id == "llamacpp":
                from superqode.local.servers import discover_gguf_models

                gguf = await asyncio.to_thread(discover_gguf_models)
                t = Text()
                t.append("\n  🟡 ", style=THEME["warning"])
                t.append(f"No {name} answering at {base_url}\n", style=f"bold {THEME['text']}")
                if gguf:
                    t.append(
                        f"  Found {len(gguf)} cached GGUF file(s), but none are being served yet.\n",
                        style=THEME["muted"],
                    )
                    first_path = gguf[0]["path"]
                    t.append(
                        "  Start llama.cpp with one of them, for example:\n", style=THEME["muted"]
                    )
                    t.append("      ", style="")
                    t.append(
                        self._native_local_server_command("llama.cpp", model=first_path),
                        style=THEME["cyan"],
                    )
                    t.append("\n", style="")
                    t.append(
                        "      Edit the model path, port, or context if needed.\n",
                        style=THEME["dim"],
                    )
                else:
                    t.append(
                        "  No cached GGUF models found. Download one, e.g.:\n", style=THEME["muted"]
                    )
                    t.append("      hf download <repo> <file>.gguf\n", style=THEME["cyan"])
                    t.append("  or point at a running server:\n", style=THEME["muted"])
                    t.append(
                        "      llama-server -m /path/to/model.gguf --port 8081\n",
                        style=THEME["cyan"],
                    )
                t.append("\n  Then ", style=THEME["muted"])
                t.append(":connect", style=f"bold {THEME['cyan']}")
                t.append(" again and pick llama.cpp.\n", style=THEME["muted"])
                t.append(
                    "  (LLAMACPP_HOST overrides the port if you use a different one.)\n",
                    style=THEME["dim"],
                )
                self._awaiting_local_model = False
                self._awaiting_local_provider = False
                log.write(t)
                self._pin_local_prompt_to_input(
                    "Start llama.cpp first, then run :connect local",
                    log,
                )
                return

            t = Text()
            t.append("\n  🟡 ", style=THEME["warning"])
            t.append(f"No {name} answering at {base_url}\n", style=f"bold {THEME['text']}")
            t.append("  No cached GGUF models found. Download one, e.g.:\n", style=THEME["muted"])
            t.append("      hf download <repo> <file>.gguf\n", style=THEME["cyan"])
            t.append("  or point at a running server:\n", style=THEME["muted"])
            t.append("      llama-server -m /path/to/model.gguf --port 8081\n", style=THEME["cyan"])
            t.append("\n  Then ", style=THEME["muted"])
            t.append(":connect", style=f"bold {THEME['cyan']}")
            t.append(" again and pick llama.cpp.\n", style=THEME["muted"])
            t.append(
                "  (LLAMACPP_HOST overrides the port if you use a different one.)\n",
                style=THEME["dim"],
            )
            # Stable final state — no auto-reopen (that clears the log = flash).
            self._awaiting_local_model = False
            self._awaiting_local_provider = False
            log.write(t)
            return

        self._local_selected_provider = provider_id
        self._local_model_list = models
        self._local_cached_models = models
        self._awaiting_local_model = True
        self._awaiting_local_provider = False
        if not hasattr(self, "_local_highlighted_model_index"):
            self._local_highlighted_model_index = 0
        highlighted_idx = getattr(self, "_local_highlighted_model_index", 0)

        t = Text()
        t.append(f"\n  🟢 {name}", style=f"bold {THEME['success']}")
        t.append(f"  {base_url}\n", style=THEME["dim"])
        t.append(f"  {len(models)} model(s) served\n\n", style=THEME["dim"])
        for idx, model_id in enumerate(models, 1):
            is_hl = (idx - 1) == highlighted_idx
            marker = "  ▶ " if is_hl else "    "
            style = f"bold {THEME['success']}" if is_hl else f"bold {THEME['text']}"
            t.append(marker, style=f"bold {THEME['success']}")
            t.append(f"[{idx:2}] ", style=self._picker_link_style(THEME["dim"], idx))
            t.append(model_id, style=style)
            if is_hl:
                t.append("  ← SELECTED", style=f"bold {THEME['success']}")
            t.append("\n", style="")
        t.append("\n  💡 ", style=THEME["muted"])
        t.append("Select a model number or name to connect\n", style=THEME["text"])
        log.write(t)
        self.set_timer(0.05, self._ensure_input_focus)

    def _models_cmd(self, args: str, log: ConversationLog):
        """Handle :models command - Show/switch models."""
        args = args.strip()

        if args == "update":
            # :models update - Refresh from models.dev
            self._models_update_cmd(log)
            return

        if args.startswith("search "):
            # :models search <query>
            query = args[7:].strip()
            self._models_search_cmd(query, log)
            return

        if args == "info":
            # :models info - Show data source info
            self._models_info_cmd(log)
            return

        if args.startswith("set "):
            # :models set <model>
            model = args[4:].strip()
            self._set_byok_model(model, log)
            return

        if args:
            # :models <provider> - Show models for provider
            self._show_provider_models(args, log)
            return

        # :models - Show models for current provider
        session = get_session()
        if session.execution_mode not in ("byok", "local") or not hasattr(self, "_pure_mode"):
            log.add_info("Not connected to BYOK provider")
            log.add_system("Use :connect to select a provider first")
            return

        provider = getattr(self._pure_mode, "_provider", None)
        if provider:
            self._show_provider_models(provider, log)
        else:
            log.add_info("No provider selected")

    def _model_cmd(self, args: str, log: ConversationLog):
        """Handle current model status and lightweight runtime overrides."""
        args = args.strip()
        parts = args.split(maxsplit=1) if args else []
        sub = parts[0].lower() if parts else "status"
        value = parts[1].strip() if len(parts) > 1 else ""

        if sub in {"", "status", "current"}:
            self._show_model_status(log)
            return
        if sub in {"doctor", "check"}:
            self._doctor_cmd("current", log)
            return
        if sub in {"switch", "use", "set"}:
            if not value:
                log.add_info("Usage: :model switch <provider>/<model> or :model switch <model>")
                return
            parsed = split_provider_model_ref(value, default_provider=self.current_provider)
            provider, model = parsed.provider, parsed.model
            if not provider or not model:
                log.add_error(
                    "No provider/model selected. Use :connect byok or :connect local first."
                )
                return
            local_providers = {
                "ds4",
                "ollama",
                "lmstudio",
                "mlx",
                "vllm",
                "sglang",
                "tgi",
                "huggingface-local",
            }
            if provider in local_providers:
                self._connect_local_mode(provider, model, log)
            else:
                self._connect_byok_mode(provider, model, log)
            return
        if sub in {"reasoning", "temperature", "verbosity", "web_search", "web-search"}:
            if not value:
                current = getattr(self, f"_model_{sub.replace('-', '_')}", None)
                log.add_info(f"{sub}: {current if current is not None else 'default'}")
                return
            attr = f"_model_{sub.replace('-', '_')}"
            setattr(self, attr, value)
            log.add_info(
                f"Model override set for this TUI session: {sub}={value}. "
                "HarnessSpec-backed runs should encode durable settings in the spec."
            )
            return
        log.add_info(
            "Usage: :model [doctor|switch <provider>/<model>|reasoning <value>|temperature <n>|verbosity <value>]"
        )

    def _show_model_status(self, log: ConversationLog):
        """Show active provider/model and known capability hints."""
        from superqode.providers.models import get_models_for_provider
        from superqode.providers.registry import PROVIDERS

        provider = self.current_provider or ""
        model = self.current_model or ""
        t = Text()
        t.append("\n  ◇ ", style=f"bold {THEME['purple']}")
        t.append("Current Model\n\n", style=f"bold {THEME['text']}")
        t.append("  Provider    ", style=THEME["muted"])
        t.append(f"{provider or '-'}\n", style=f"bold {THEME['cyan']}")
        t.append("  Model       ", style=THEME["muted"])
        t.append(f"{model or '-'}\n", style=f"bold {THEME['text']}")

        provider_def = PROVIDERS.get(provider)
        if provider_def is not None:
            t.append("  Provider    ", style=THEME["muted"])
            t.append(f"{provider_def.name}\n", style=THEME["text"])
            if provider_def.notes:
                t.append("  Notes       ", style=THEME["muted"])
                t.append(f"{provider_def.notes}\n", style=THEME["dim"])

        model_info = get_models_for_provider(provider).get(model) if provider and model else None
        if model_info is not None:
            labels = []
            if model_info.supports_tools:
                labels.append(("tools", THEME["success"]))
            if model_info.supports_reasoning:
                labels.append(("reasoning", THEME["purple"]))
            if model_info.is_code_optimized:
                labels.append(("code", THEME["cyan"]))
            if model_info.supports_vision:
                labels.append(("vision", THEME["orange"]))
            t.append("  Context     ", style=THEME["muted"])
            t.append(f"{model_info.context_display}\n", style=THEME["cyan"])
            t.append("  Price       ", style=THEME["muted"])
            t.append(f"{model_info.price_display}\n", style=THEME["gold"])
            if labels:
                t.append("  Capability  ", style=THEME["muted"])
                for idx, (label, style) in enumerate(labels):
                    if idx:
                        t.append(", ", style=THEME["dim"])
                    t.append(label, style=style)
                t.append("\n")
        else:
            t.append("  Capability  ", style=THEME["muted"])
            t.append(
                "unknown; run :doctor current or :providers <provider>\n", style=THEME["warning"]
            )

        overrides = {
            "reasoning": getattr(self, "_model_reasoning", None),
            "temperature": getattr(self, "_model_temperature", None),
            "verbosity": getattr(self, "_model_verbosity", None),
            "web_search": getattr(self, "_model_web_search", None),
        }
        active_overrides = {key: val for key, val in overrides.items() if val is not None}
        if active_overrides:
            t.append("  Overrides   ", style=THEME["muted"])
            t.append(
                ", ".join(f"{key}={val}" for key, val in active_overrides.items()),
                style=THEME["text"],
            )
            t.append("\n")

        t.append("\n  Commands: ", style=THEME["muted"])
        t.append(":model doctor", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":model switch <provider>/<model>", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":recommend coding\n", style=THEME["cyan"])
        self._show_command_output(log, t)

    def _models_update_cmd(self, log: ConversationLog):
        """Handle :models update - Refresh model data from models.dev."""
        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Updating Model Database\n\n", style=f"bold {THEME['text']}")
        t.append("  ⏳ Fetching from models.dev...\n", style=THEME["muted"])
        log.write(t)

        # Run the update in background
        self.run_worker(self._do_models_update(log))

    async def _do_models_update(self, log: ConversationLog):
        """Actually perform the models.dev update."""
        try:
            from superqode.providers.models_dev import get_models_dev
            from superqode.providers.models import set_live_models

            client = get_models_dev()
            success = await client.refresh(force=True)

            if success:
                # Update global models database
                live_models = {}
                for provider_id in client.get_providers().keys():
                    provider_models = client.get_models_for_provider(provider_id)
                    if provider_models:
                        live_models[provider_id] = provider_models

                if live_models:
                    set_live_models(live_models)

                # Show success
                cache_info = client.get_cache_info()
                t = Text()
                t.append(f"\n  ✓ ", style=f"bold {THEME['success']}")
                t.append("Model database updated!\n\n", style=f"bold {THEME['text']}")
                t.append(f"  Providers: ", style=THEME["muted"])
                t.append(f"{cache_info['provider_count']}\n", style=THEME["text"])
                t.append(f"  Models:    ", style=THEME["muted"])
                t.append(f"{cache_info['model_count']}\n", style=THEME["text"])
                t.append(f"  Source:    ", style=THEME["muted"])
                t.append("models.dev\n", style=THEME["cyan"])
                log.write(t)
            else:
                t = Text()
                t.append(f"\n  ✗ ", style=f"bold {THEME['error']}")
                t.append("Failed to fetch from models.dev\n", style=THEME["text"])
                t.append("  Using cached/built-in data\n", style=THEME["muted"])
                log.write(t)

        except Exception as e:
            t = Text()
            t.append(f"\n  ✗ ", style=f"bold {THEME['error']}")
            t.append(f"Update failed: {e}\n", style=THEME["text"])
            log.write(t)

    def _models_search_cmd(self, query: str, log: ConversationLog):
        """Handle :models search <query> - Search across all models."""
        from superqode.providers.models import search_models, get_data_source

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append(f"Search: ", style=f"bold {THEME['text']}")
        t.append(f'"{query}"\n', style=THEME["cyan"])
        t.append(f"  Data source: {get_data_source()}\n\n", style=THEME["dim"])

        results = search_models(query, limit=15)

        if not results:
            t.append("  No models found matching query\n", style=THEME["muted"])
            log.write(t)
            return

        for idx, model in enumerate(results, 1):
            t.append(f"  [{idx:2}] ", style=THEME["dim"])
            t.append(f"{model.provider}", style=f"bold {THEME['success']}")
            t.append(f" / ", style=THEME["dim"])
            t.append(f"{model.name}\n", style=f"bold {THEME['text']}")

            # Model ID
            t.append(f"       ", style="")
            t.append(f"{model.id}\n", style=THEME["muted"])

            # Pricing and context
            t.append(f"       ", style="")
            t.append(f"{model.price_display}", style=THEME["gold"])
            t.append(f" per 1M  •  ", style=THEME["dim"])
            t.append(f"{model.context_display}", style=THEME["cyan"])
            t.append(" ctx\n", style=THEME["dim"])

            t.append("\n", style="")

        t.append(f"  💡 ", style=THEME["muted"])
        t.append(":connect <provider>/<model>", style=THEME["success"])
        t.append(" to connect\n", style=THEME["muted"])

        log.write(t)

    def _models_info_cmd(self, log: ConversationLog):
        """Handle :models info - Show model database info."""
        from superqode.providers.models import (
            is_using_live_data,
            get_data_source,
            get_all_models,
            get_all_providers,
        )

        t = Text()
        t.append(f"\n  ◈ ", style=f"bold {THEME['purple']}")
        t.append("Model Database Info\n\n", style=f"bold {THEME['text']}")

        t.append(f"  Source:     ", style=THEME["muted"])
        source = get_data_source()
        if "live" in source:
            t.append(f"{source}\n", style=f"bold {THEME['success']}")
        else:
            t.append(f"{source}\n", style=THEME["text"])

        providers = get_all_providers()
        models = get_all_models()

        t.append(f"  Providers:  ", style=THEME["muted"])
        t.append(f"{len(providers)}\n", style=THEME["text"])

        t.append(f"  Models:     ", style=THEME["muted"])
        t.append(f"{len(models)}\n", style=THEME["text"])

        # Show cache info if live
        if is_using_live_data():
            try:
                from superqode.providers.models_dev import get_models_dev

                client = get_models_dev()
                cache_info = client.get_cache_info()

                t.append(f"\n  Cache:\n", style=THEME["muted"])
                t.append(f"    File:     ", style=THEME["dim"])
                t.append(f"{cache_info['cache_file']}\n", style=THEME["text"])

                if cache_info.get("fetched_at"):
                    t.append(f"    Fetched:  ", style=THEME["dim"])
                    t.append(f"{cache_info['fetched_at'][:19]}\n", style=THEME["text"])

                t.append(f"    Expired:  ", style=THEME["dim"])
                expired = cache_info.get("is_expired", False)
                t.append(
                    f"{'Yes' if expired else 'No'}\n",
                    style=THEME["error"] if expired else THEME["success"],
                )

            except Exception:
                pass

        t.append(f"\n  💡 ", style=THEME["muted"])
        t.append(":models update", style=THEME["success"])
        t.append(" to refresh from models.dev\n", style=THEME["muted"])

        log.write(t)

    def _set_model(self, model_name: str, log: ConversationLog):
        """Set the model for the current agent."""
        model_name = model_name.strip()

        if not self.current_agent:
            log.add_error("Not connected to any agent. Use :acp connect <name> first")
            return

        # For opencode, validate against available models
        if self.current_agent == "opencode":
            # Check if it's a number (1-5) for quick selection
            if model_name.isdigit():
                idx = int(model_name) - 1
                if 0 <= idx < len(self.opencode_models):
                    model_name = self.opencode_models[idx]["id"]
                else:
                    log.add_error(f"Invalid selection. Choose 1-{len(self.opencode_models)}")
                    return

            # Check if it's a valid opencode model
            valid_ids = [m["id"] for m in self.opencode_models]

            # Allow short names too (e.g., "glm-4.7-free" -> "opencode/glm-4.7-free")
            if not model_name.startswith("opencode/"):
                full_id = f"opencode/{model_name}"
                if full_id in valid_ids:
                    model_name = full_id

            if model_name not in valid_ids:
                log.add_error(f"Unknown model: {model_name}")
                log.add_info("Available models (use number or full ID):")
                for i, m in enumerate(self.opencode_models, 1):
                    log.add_info(f"  [{i}] {m['id']} - {m['name']}")
                return

            # Find model info
            model_info = next((m for m in self.opencode_models if m["id"] == model_name), None)
            model_display = model_info["name"] if model_info else model_name
            selected_is_free = bool(model_info and model_info.get("free"))
            if model_name == "opencode/auto":
                stored_model_name = ""
                badge_model_name = "opencode/default"
            else:
                stored_model_name = model_name
                badge_model_name = model_name
        else:
            model_display = model_name
            selected_is_free = False
            stored_model_name = model_name
            badge_model_name = model_name

        # Store the model
        self.current_model = stored_model_name
        self._awaiting_model_selection = False  # Clear the flag

        # Update badge
        badge = self.query_one("#mode-badge", ModeBadge)
        badge.model = badge_model_name

        t = Text()
        t.append(f"\n  ✅ ", style=f"bold {THEME['success']}")
        t.append("Model changed to ", style=THEME["text"])
        t.append(f"{model_display}", style=f"bold {THEME['cyan']}")
        t.append(f" ({badge_model_name})\n", style=THEME["dim"])

        if self.current_agent == "opencode" and selected_is_free:
            t.append(f"  🆓 This is a FREE model!\n", style=THEME["success"])

        log.write(t)

    def _auto_select_opencode_model(
        self, model_hint: str, agent: Dict[str, Any], log: ConversationLog
    ):
        """Auto-select an OpenCode model based on user hint."""
        model_hint_lower = model_hint.lower().strip()

        # Try to find a matching model
        matched_model = None
        for model in self.opencode_models:
            model_id = model.get("id", "").lower()
            model_name = model.get("name", "").lower()

            # Check if hint matches model id or name
            if model_hint_lower in model_id or model_hint_lower in model_name:
                matched_model = model
                break

        if matched_model:
            model_id = matched_model.get("id", "")
            model_name = matched_model.get("name", "")
            selected_is_free = bool(matched_model.get("free"))
            if model_id == "opencode/auto":
                stored_model_id = ""
                badge_model_id = "opencode/default"
            else:
                stored_model_id = model_id
                badge_model_id = model_id

            self.current_model = stored_model_id
            self.current_provider = "opencode"
            self._awaiting_model_selection = False

            # Update badge - ACP mode for agent connections
            badge = self.query_one("#mode-badge", ModeBadge)
            badge.agent = self.current_agent
            badge.model = badge_model_id
            badge.provider = self.current_provider
            badge.execution_mode = "acp"  # ACP mode for :acp connect

            # Show confirmation
            t = Text()
            t.append(f"\n  ✅ ", style=f"bold {THEME['success']}")
            t.append("Connected with model: ", style=THEME["text"])
            t.append(f"{model_name}", style=f"bold {THEME['cyan']}")
            t.append(f" ({badge_model_id})\n", style=THEME["dim"])
            if selected_is_free:
                t.append(f"  🆓 This is a FREE model! Ready to chat.\n", style=THEME["success"])
            else:
                t.append("  Ready to chat.\n", style=THEME["success"])
            log.write(t)
        else:
            # No match found, show available models
            log.add_info(f"Model '{model_hint}' not found. Available models:")
            self._show_opencode_models_selection(agent, log)

    def _show_opencode_models_selection(
        self, agent: Dict[str, Any], log: ConversationLog, clear_log: bool = True
    ):
        """Show OpenCode available models for selection.

        Args:
            agent: Agent data dictionary
            log: Conversation log widget
            clear_log: If True, clear the log before writing (default: True).
                      Set to False when updating during navigation to reduce flickering.
        """
        name = agent.get("name", "OpenCode")
        color = AGENT_COLORS.get("opencode", THEME["success"])
        icon = AGENT_ICONS.get("opencode", "🌿")

        # Initialize highlighted index if not set
        if not hasattr(self, "_opencode_highlighted_model_index"):
            self._opencode_highlighted_model_index = 0

        highlighted_idx = getattr(self, "_opencode_highlighted_model_index", 0)

        t = Text()
        t.append(f"\n  ╭{'─' * 58}╮\n", style=color)
        t.append(f"  │  {icon} ", style=color)
        t.append("Connected to ", style=THEME["text"])
        t.append("OPENCODE", style=f"bold {color}")
        t.append(f"{'':>32}│\n", style=color)
        t.append(f"  ├{'─' * 58}┤\n", style=color)

        # Show available models
        t.append(f"  │  🆓 ", style=color)
        t.append("SELECT OPENCODE MODEL", style=f"bold {THEME['success']}")
        t.append(f"{'':>34}│\n", style=color)
        t.append(f"  ├{'─' * 58}┤\n", style=color)

        models = self.opencode_models
        if not models:
            t.append(f"  │  ", style=color)
            t.append("No models discovered from OpenCode CLI", style=THEME["warning"])
            t.append(f"{'':>10}│\n", style=color)
            t.append(f"  │  ", style=color)
            t.append("Press R to refresh or configure OpenCode", style=THEME["muted"])
            t.append(f"{'':>18}│\n", style=color)

        for i, model in enumerate(models):
            model_id = model.get("id", "")
            model_name = model.get("name", "")
            desc = model.get("desc", "")
            is_recommended = model.get("recommended", False)
            is_free = model.get("free", False)
            catalog_unavailable = model.get("catalog_unavailable", False)
            is_highlighted = i == highlighted_idx

            # Number for selection
            num = i + 1
            t.append(f"  │  ", style=color)

            if is_highlighted:
                t.append(f"▶ ", style=f"bold {THEME['success']}")
                t.append(
                    f"[{num}]",
                    style=self._picker_link_style(f"bold {THEME['success']}", num),
                )
                t.append(f" {model_name:<18}", style=f"bold {THEME['success']}")
                if is_recommended:
                    t.append("⭐ ", style=THEME["gold"])
                elif is_free:
                    t.append("FREE ", style=THEME["success"])
                elif catalog_unavailable:
                    t.append("AUTO ", style=THEME["warning"])
                else:
                    t.append("   ", style="")
                t.append("  ← SELECTED", style=f"bold {THEME['success']}")
            else:
                t.append(
                    f"  [{num}]",
                    style=self._picker_link_style(f"bold {THEME['cyan']}", num),
                )
                t.append(f" {model_name:<18}", style=f"bold {THEME['text']}")
                if is_recommended:
                    t.append("⭐ ", style=THEME["gold"])
                elif is_free:
                    t.append("FREE ", style=THEME["success"])
                elif catalog_unavailable:
                    t.append("AUTO ", style=THEME["warning"])
                else:
                    t.append("   ", style="")

            # Truncate desc to fit
            desc_short = desc[:25] + ".." if len(desc) > 25 else desc
            padding = 27 - len(desc_short) - (12 if is_highlighted else 0)
            t.append(
                f"{desc_short}{' ' * padding}│\n",
                style=THEME["dim"] if not is_highlighted else THEME["muted"],
            )

        t.append(f"  ├{'─' * 58}┤\n", style=color)

        # Show how to select - ARROW KEYS OR TYPE NUMBER
        t.append(f"  │  ⌨️  ", style=color)
        t.append("↑↓", style=f"bold {THEME['cyan']}")
        t.append(" Navigate  ", style=THEME["muted"])
        t.append("Enter", style=f"bold {THEME['cyan']}")
        t.append(" select  ", style=THEME["muted"])
        t.append("R", style=f"bold {THEME['cyan']}")
        t.append(" refresh", style=THEME["muted"])
        t.append(f"{'':>16}│\n", style=color)
        t.append(f"  │      Or type ", style=color)
        t.append("1", style=f"bold {THEME['cyan']}")
        t.append("-", style=THEME["muted"])
        t.append(f"{len(models)}", style=f"bold {THEME['cyan']}")
        t.append(" in prompt and press Enter", style=THEME["muted"])
        t.append(f"{'':>10}│\n", style=color)

        t.append(f"  ╰{'─' * 58}╯\n", style=color)

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

        # Set flag to await model selection
        self._awaiting_model_selection = True
        # Store agent data for navigation
        self._opencode_agent_data = agent

        # DO NOT auto-select model - user must choose
        self.current_model = ""  # No model selected yet
        self.current_provider = ""

        badge = self.query_one("#mode-badge", ModeBadge)
        badge.agent = self.current_agent
        badge.mode = ""
        badge.role = ""
        badge.model = ""
        badge.provider = ""

    def _show_gemini_models_selection(self, agent: Dict[str, Any], log: ConversationLog):
        """Show Gemini available models for selection."""
        name = agent.get("name", "Gemini CLI")
        color = THEME["cyan"]
        icon = "✨"

        t = Text()
        t.append(f"\n  ╭{'─' * 58}╮\n", style=color)
        t.append(f"  │  {icon} ", style=color)
        t.append("Connected to ", style=THEME["text"])
        t.append("GEMINI CLI", style=f"bold {color}")
        t.append(f"{'':>32}│\n", style=color)
        t.append(f"  ├{'─' * 58}┤\n", style=color)

        # Show available models
        t.append(f"  │  🤖 ", style=color)
        t.append("SELECT A MODEL", style=f"bold {THEME['cyan']}")
        t.append(f"{'':>38}│\n", style=color)
        t.append(f"  ├{'─' * 58}┤\n", style=color)

        for i, model in enumerate(self.gemini_models):
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
        t.append(f"{len(self._gemini_models)}", style=f"bold {THEME['cyan']}")
        t.append(" in prompt and press Enter", style=THEME["muted"])
        t.append(f"{'':>14}│\n", style=color)

        t.append(f"  ╰{'─' * 58}╯\n", style=color)

        log.write(t)

        # Set flag to await model selection
        self._awaiting_model_selection = True
        self._gemini_agent_data = agent

        # No model selected yet
        self.current_model = ""
        self.current_provider = "gemini"

        badge = self.query_one("#mode-badge", ModeBadge)
        badge.agent = self.current_agent
        badge.mode = ""
        badge.role = ""
        badge.model = ""
        badge.provider = "gemini"

    def _auto_select_gemini_model(
        self, model_hint: str, agent: Dict[str, Any], log: ConversationLog
    ):
        """Auto-select a Gemini model based on user hint."""
        model_hint_lower = model_hint.lower().strip()

        # Try to find a matching model
        matched_model = None
        for model in self._gemini_models:
            model_id = model.get("id", "").lower()
            model_name = model.get("name", "").lower()

            # Check various match patterns
            if model_hint_lower in model_id or model_hint_lower in model_name:
                matched_model = model
                break

            # Check for partial matches
            if "flash" in model_hint_lower and "flash" in model_name:
                matched_model = model
                break
            if "pro" in model_hint_lower and "pro" in model_name:
                matched_model = model
                break
            if "2.5" in model_hint_lower and "2.5" in model_name:
                matched_model = model
                break

        if matched_model:
            model_id = matched_model.get("id", "")
            model_name = matched_model.get("name", "")

            self.current_model = model_id
            self.current_provider = "gemini"
            self._awaiting_model_selection = False

            badge = self.query_one("#mode-badge", ModeBadge)
            badge.agent = self.current_agent
            badge.model = model_id
            badge.provider = "gemini"

            t = Text()
            t.append(f"\n  ✨ ", style=THEME["cyan"])
            t.append("Model selected: ", style=THEME["text"])
            t.append(f"{model_name}", style=f"bold {THEME['cyan']}")
            t.append(f" ({model_id})\n", style=THEME["dim"])
            t.append(f"  💬 Ready! Type your message.\n", style=THEME["success"])
            log.write(t)
        else:
            # No match found, show available models
            log.add_info(f"Model '{model_hint}' not found. Available models:")
            self._show_gemini_models_selection(agent, log)

    def _show_claude_models_selection(self, agent: Dict[str, Any], log: ConversationLog):
        """Show Claude Code available models for selection."""
        name = agent.get("name", "Claude Code")
        color = THEME["orange"]
        icon = "🧡"

        t = Text()
        t.append(f"\n  ╭{'─' * 58}╮\n", style=color)
        t.append(f"  │  {icon} ", style=color)
        t.append("Connected to ", style=THEME["text"])
        t.append("CLAUDE CODE", style=f"bold {color}")
        t.append(f"{'':>31}│\n", style=color)
        t.append(f"  ├{'─' * 58}┤\n", style=color)

        # Show available models
        t.append(f"  │  🤖 ", style=color)
        t.append("SELECT A MODEL", style=f"bold {THEME['cyan']}")
        t.append(f"{'':>38}│\n", style=color)
        t.append(f"  ├{'─' * 58}┤\n", style=color)

        for i, model in enumerate(self.claude_models):
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
        t.append(f"{len(self._claude_models)}", style=f"bold {THEME['cyan']}")
        t.append(" in prompt and press Enter", style=THEME["muted"])
        t.append(f"{'':>14}│\n", style=color)

        t.append(f"  ╰{'─' * 58}╯\n", style=color)

        # Show API key requirement
        t.append(f"\n  💡 ", style=THEME["gold"])
        t.append("Requires ", style=THEME["muted"])
        t.append("ANTHROPIC_API_KEY", style=f"bold {THEME['cyan']}")
        t.append(" environment variable\n", style=THEME["muted"])

        log.write(t)

        # Set flag to await model selection
        self._awaiting_model_selection = True
        self._claude_agent_data = agent

        # No model selected yet
        self.current_model = ""
        self.current_provider = "claude"

        badge = self.query_one("#mode-badge", ModeBadge)
        badge.agent = self.current_agent
        badge.mode = ""
        badge.role = ""
        badge.model = ""
        badge.provider = "claude"

    def _auto_select_claude_model(
        self, model_hint: str, agent: Dict[str, Any], log: ConversationLog
    ):
        """Auto-select a Claude model based on user hint."""
        model_hint_lower = model_hint.lower().strip()

        # Try to find a matching model
        matched_model = None
        for model in self._claude_models:
            model_id = model.get("id", "").lower()
            model_name = model.get("name", "").lower()

            # Check various match patterns
            if model_hint_lower in model_id or model_hint_lower in model_name:
                matched_model = model
                break

            # Check for partial matches
            if "sonnet" in model_hint_lower and "sonnet" in model_name:
                matched_model = model
                break
            if "haiku" in model_hint_lower and "haiku" in model_name:
                matched_model = model
                break
            if "opus" in model_hint_lower and "opus" in model_name:
                matched_model = model
                break
            if "4" in model_hint_lower and "4" in model_name:
                matched_model = model
                break
            if "3.5" in model_hint_lower and "3.5" in model_name:
                matched_model = model
                break

        if matched_model:
            model_id = matched_model.get("id", "")
            model_name = matched_model.get("name", "")

            self.current_model = model_id
            self.current_provider = "claude"
            self._awaiting_model_selection = False

            badge = self.query_one("#mode-badge", ModeBadge)
            badge.agent = self.current_agent
            badge.model = model_id
            badge.provider = "claude"

            t = Text()
            t.append(f"\n  🧡 ", style=THEME["orange"])
            t.append("Model selected: ", style=THEME["text"])
            t.append(f"{model_name}", style=f"bold {THEME['orange']}")
            t.append(f" ({model_id})\n", style=THEME["dim"])
            t.append(f"  💬 Ready! Type your message.\n", style=THEME["success"])
            log.write(t)
        else:
            # No match found, show available models
            log.add_info(f"Model '{model_hint}' not found. Available models:")
            self._show_claude_models_selection(agent, log)

    def _show_openhands_models_selection(self, agent: Dict[str, Any], log: ConversationLog):
        """Show OpenHands available models for selection."""
        name = agent.get("name", "OpenHands")
        color = THEME["orange"]
        icon = "🤝"

        t = Text()
        t.append(f"\n  ╭{'─' * 58}╮\n", style=color)
        t.append(f"  │  {icon} ", style=color)
        t.append("Connected to ", style=THEME["text"])
        t.append("OPENHANDS", style=f"bold {color}")
        t.append(f"{'':>33}│\n", style=color)
        t.append(f"  ├{'─' * 58}┤\n", style=color)

        # Show available models
        t.append(f"  │  🤖 ", style=color)
        t.append("SELECT A MODEL", style=f"bold {THEME['cyan']}")
        t.append(f"{'':>38}│\n", style=color)
        t.append(f"  ├{'─' * 58}┤\n", style=color)

        for i, model in enumerate(self.openhands_models):
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
        t.append(f"{len(self._openhands_models)}", style=f"bold {THEME['cyan']}")
        t.append(" in prompt and press Enter", style=THEME["muted"])
        t.append(f"{'':>14}│\n", style=color)

        t.append(f"  ╰{'─' * 58}╯\n", style=color)

        # Show setup info
        t.append(f"\n  💡 ", style=THEME["gold"])
        t.append("Setup: ", style=THEME["muted"])
        t.append(
            "uv tool install openhands -U --python 3.12 && openhands login",
            style=f"bold {THEME['cyan']}",
        )
        t.append("\n", style="")

        log.write(t)

        # Set flag to await model selection
        self._awaiting_model_selection = True
        self._openhands_agent_data = agent

        # No model selected yet
        self.current_model = ""
        self.current_provider = "openhands"

        badge = self.query_one("#mode-badge", ModeBadge)
        badge.agent = self.current_agent
        badge.mode = ""
        badge.role = ""
        badge.model = ""
        badge.provider = "openhands"

    def _auto_select_openhands_model(
        self, model_hint: str, agent: Dict[str, Any], log: ConversationLog
    ):
        """Auto-select an OpenHands model based on user hint."""
        model_hint_lower = model_hint.lower().strip()

        # Try to find a matching model
        matched_model = None
        for model in self._openhands_models:
            model_id = model.get("id", "").lower()
            model_name = model.get("name", "").lower()

            # Check various match patterns
            if model_hint_lower in model_id or model_hint_lower in model_name:
                matched_model = model
                break

            # Check for partial matches
            if "ollama" in model_hint_lower and "ollama" in model_name:
                matched_model = model
                break
            if "local" in model_hint_lower and "local" in model_name:
                matched_model = model
                break
            if "claude" in model_hint_lower and "claude" in model_name:
                matched_model = model
                break
            if "gpt" in model_hint_lower and "gpt" in model_name:
                matched_model = model
                break
            if "gemini" in model_hint_lower and "gemini" in model_name:
                matched_model = model
                break
            if "default" in model_hint_lower and "default" in model_name:
                matched_model = model
                break

        if matched_model:
            model_id = matched_model.get("id", "")
            model_name = matched_model.get("name", "")

            self.current_model = model_id
            self.current_provider = "openhands"
            self._awaiting_model_selection = False

            badge = self.query_one("#mode-badge", ModeBadge)
            badge.agent = self.current_agent
            badge.model = model_id
            badge.provider = "openhands"

            t = Text()
            t.append(f"\n  🤝 ", style=THEME["orange"])
            t.append("Model selected: ", style=THEME["text"])
            t.append(f"{model_name}", style=f"bold {THEME['orange']}")
            t.append(f" ({model_id})\n", style=THEME["dim"])
            t.append(f"  💬 Ready! Type your message.\n", style=THEME["success"])
            log.write(t)
        else:
            # No match found, show available models
            log.add_info(f"Model '{model_hint}' not found. Available models:")
            self._show_openhands_models_selection(agent, log)

    def _models_cmd(self, args: str, log: ConversationLog):
        """`:models` — browse the models.dev catalog from the TUI.

        Usage:
          :models [search terms]
          :models free
          :models provider <id>
          :models cap <tools|vision|reasoning|code|long|json>
          :models providers
        Flags can combine, e.g. `:models coder cap code provider deepinfra`.
        """
        from superqode.providers.catalog import (
            load_models_catalog_cached,
            filter_models,
            parse_capability,
            render_models_table,
            render_providers_table,
        )

        parts = (args or "").split()
        if parts and parts[0] in {
            "show",
            "hub",
            "download",
            "convert-mlx",
            "cached",
            "rm",
        }:
            self._run_cli_group("models", args, log, "Models command")
            return
        if parts and parts[0] in ("providers", "provider-list"):
            self._show_command_output(log, render_providers_table())
            return

        live = "live" in parts
        free = "free" in parts
        cap = None
        provider = None
        terms = []
        i = 0
        while i < len(parts):
            token = parts[i]
            if token == "cap" and i + 1 < len(parts):
                cap = parts[i + 1]
                i += 2
                continue
            if token in ("provider", "from") and i + 1 < len(parts):
                provider = parts[i + 1]
                i += 2
                continue
            if token in ("free", "live"):
                i += 1
                continue
            terms.append(token)
            i += 1
        search = " ".join(terms) or None

        if live:
            if not provider:
                log.add_error("Live discovery needs a provider: `:models provider <id> live`")
                return
            log.add_info(f"Discovering {provider} models live from its endpoint...")
            self.run_worker(self._models_live_render(provider, log), exclusive=False)
            return

        if cap and parse_capability(cap) is None:
            log.add_error("Unknown capability. Use: tools, vision, reasoning, code, long, json.")
            return

        models = load_models_catalog_cached()
        if not models:
            log.add_info(
                "No model catalog cached yet. Run `superqode models --refresh` once "
                "(with network) to populate it."
            )
            return

        matched = filter_models(
            models,
            search=search,
            provider=provider,
            capability=parse_capability(cap),
            free=free,
            limit=None,
        )
        total = len(matched)
        self._show_command_output(log, render_models_table(matched[:40], total=total))

    async def _models_live_render(self, provider: str, log: ConversationLog):
        """Worker: query a provider's live /v1/models endpoint and render it."""
        from superqode.providers.live_models import discover_provider_models
        from superqode.providers.catalog import render_models_table

        try:
            result = await discover_provider_models(provider)
        except Exception as exc:  # noqa: BLE001
            log.add_error(f"Live discovery failed: {exc}")
            return
        note = {
            "live": f"live from {result.endpoint}",
            "models.dev": "models.dev catalog (live endpoint unavailable)",
            "none": "no models found (set the API key / base URL, or check the endpoint)",
        }.get(result.source, result.source)
        header = f"# {provider}: {note}\n\n"
        self._show_command_output(
            log, header + render_models_table(result.models[:40], total=len(result.models))
        )
