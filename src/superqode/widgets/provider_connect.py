"""
SuperQode Provider Connect Widget - Interactive provider/model picker.

Interactive connection flow with fuzzy search.

Features:
- Fuzzy search for providers
- Model picker with pricing info
- Recent history
- Favorites support

Usage:
    :connect                    # Interactive picker
    :connect anthropic          # Pick provider, then model
    :connect anthropic claude-sonnet-4  # Direct connect
    :connect -                  # Switch to previous
    :connect !                  # Show history
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from rich.text import Text

from textual.widgets import Static, Input, OptionList
from textual.containers import Container, Vertical, Horizontal
from textual.reactive import reactive
from textual.message import Message
from textual import on
from textual.binding import Binding

if TYPE_CHECKING:
    from textual.app import App


# ============================================================================
# DESIGN
# ============================================================================

try:
    from superqode.design_system import COLORS as SQ_COLORS
except ImportError:

    class SQ_COLORS:
        primary = "#7c3aed"
        primary_light = "#a855f7"
        success = "#10b981"
        warning = "#f59e0b"
        error = "#f43f5e"
        info = "#06b6d4"
        text_primary = "#fafafa"
        text_secondary = "#e4e4e7"
        text_muted = "#a1a1aa"
        text_dim = "#71717a"
        text_ghost = "#52525b"
        bg_elevated = "#0a0a0a"
        border_default = "#27272a"


# ============================================================================
# PROVIDER CONNECT WIDGET
# ============================================================================


class ProviderConnectWidget(Container):
    """
    Interactive provider connection widget with search.

    Two-step flow:
    1. Search and select provider
    2. Search and select model
    """

    DEFAULT_CSS = """
    ProviderConnectWidget {
        height: auto;
        max-height: 20;
        background: #0a0a0a;
        border: round #7c3aed;
        padding: 1;
        margin: 1 2;
    }

    ProviderConnectWidget .header {
        height: 1;
        color: #a855f7;
        text-style: bold;
        margin-bottom: 1;
    }

    ProviderConnectWidget Input {
        width: 100%;
        background: #050505;
        border: solid #27272a;
        margin-bottom: 1;
    }

    ProviderConnectWidget Input:focus {
        border: solid #7c3aed;
    }

    ProviderConnectWidget OptionList {
        height: auto;
        max-height: 12;
        background: #050505;
        border: none;
    }

    ProviderConnectWidget OptionList > .option-list--option {
        padding: 0 1;
    }

    ProviderConnectWidget OptionList > .option-list--option-highlighted {
        background: #7c3aed40;
    }

    ProviderConnectWidget .hint {
        height: 1;
        color: #52525b;
        margin-top: 1;
    }
    """

    class ProviderSelected(Message):
        """Posted when provider and model are selected."""

        def __init__(self, provider_id: str, model: str, provider_name: str) -> None:
            self.provider_id = provider_id
            self.model = model
            self.provider_name = provider_name
            super().__init__()

    class Cancelled(Message):
        """Posted when selection is cancelled."""

        pass

    # State
    step: reactive[str] = reactive("provider")  # "provider" or "model"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._providers: List[Tuple[str, str, bool]] = []  # (id, name, configured)
        self._models: List[str] = []
        self._model_info: Dict = {}  # Model ID -> ModelInfo
        self._selected_provider: Optional[str] = None
        self._selected_provider_name: str = ""
        self._search_query: str = ""

    def compose(self):
        """Compose the widget."""
        yield Static("◈ Connect to Provider", classes="header", id="connect-header")
        yield Input(placeholder="Search providers...", id="connect-search")
        yield OptionList(id="connect-options")
        yield Static("Type number to select • Scroll with mouse • Esc Cancel", classes="hint")

    def on_mount(self) -> None:
        """Load providers on mount."""
        self._load_providers()
        self._update_options()
        self.query_one("#connect-search", Input).focus()

    def _load_providers(self) -> None:
        """Load providers from registry."""
        try:
            from superqode.providers.registry import PROVIDERS, ProviderTier

            self._providers = []

            # Sort by tier then name
            tier_order = {
                ProviderTier.TIER1: 0,
                ProviderTier.TIER2: 1,
                ProviderTier.FREE: 2,
                ProviderTier.LOCAL: 3,
            }

            sorted_providers = sorted(
                PROVIDERS.items(), key=lambda x: (tier_order.get(x[1].tier, 99), x[1].name)
            )

            for provider_id, provider_def in sorted_providers:
                # Check if configured
                configured = False
                if not provider_def.env_vars:
                    configured = True  # Local provider
                else:
                    for env_var in provider_def.env_vars:
                        if os.environ.get(env_var):
                            configured = True
                            break

                self._providers.append((provider_id, provider_def.name, configured))

        except Exception:
            pass

    def _update_options(self) -> None:
        """Update option list based on current step and search."""
        try:
            options = self.query_one("#connect-options", OptionList)
            options.clear_options()

            if self.step == "provider":
                self._update_provider_options(options)
            else:
                self._update_model_options(options)
        except Exception:
            pass

    def _update_provider_options(self, options: OptionList) -> None:
        """Update provider options with search filter."""
        from superqode.utils.fuzzy import fuzzy_search

        query = self._search_query.lower()

        # Filter and score providers
        if query:
            matches = fuzzy_search.search(
                query, [f"{p[0]} {p[1]}" for p in self._providers], max_results=15
            )
            matched_ids = {m.text.split()[0] for m in matches}
            filtered = [p for p in self._providers if p[0] in matched_ids]
        else:
            filtered = self._providers[:15]

        for provider_id, provider_name, configured in filtered:
            status = "✓" if configured else "○"
            status_style = SQ_COLORS.success if configured else SQ_COLORS.text_ghost

            text = Text()
            text.append(f"{status} ", style=status_style)
            text.append(f"{provider_id}", style=SQ_COLORS.text_secondary)
            text.append(f"  {provider_name}", style=SQ_COLORS.text_dim)

            options.add_option(text)

    def _update_model_options(self, options: OptionList) -> None:
        """Update model options with search filter, pricing info, and local/HF badges."""
        from superqode.utils.fuzzy import fuzzy_search

        query = self._search_query.lower()
        model_info = getattr(self, "_model_info", {})
        local_models = getattr(self, "_local_models", {})  # model_id -> LocalModel

        if query:
            matches = fuzzy_search.search(query, self._models, max_results=15)
            filtered = [m.text for m in matches]
        else:
            filtered = self._models[:15]

        for model_id in filtered:
            text = Text()
            text.append("  ", style="")

            # Check if this is a local model
            local_model = local_models.get(model_id)
            if local_model:
                # Local model display with running status and tool support
                if local_model.running:
                    text.append("● ", style=SQ_COLORS.success)
                else:
                    text.append("○ ", style=SQ_COLORS.text_ghost)

                text.append(f"{local_model.name}", style=SQ_COLORS.text_secondary)
                text.append(f"\n    {model_id}", style=SQ_COLORS.text_dim)
                text.append(f"\n    ", style="")

                # Size and quantization
                if local_model.size_display != "unknown":
                    text.append(f"{local_model.size_display}", style=SQ_COLORS.info)
                if local_model.quantization != "unknown":
                    text.append(f" • {local_model.quantization}", style=SQ_COLORS.text_ghost)

                # Local model badges
                badges = []
                if local_model.running:
                    badges.append("[running]")
                if local_model.supports_tools:
                    badges.append("🔧")
                if local_model.supports_vision:
                    badges.append("👁️")
                if badges:
                    text.append(f"  {' '.join(badges)}", style=SQ_COLORS.success)
            else:
                # Regular model (cloud API)
                info = model_info.get(model_id)
                if info:
                    text.append(f"{info.name}", style=SQ_COLORS.text_secondary)
                    text.append(f"\n    {model_id}", style=SQ_COLORS.text_dim)
                    text.append(f"\n    ", style="")
                    text.append(f"{info.price_display}", style=SQ_COLORS.success)
                    text.append(f" • {info.context_display} ctx", style=SQ_COLORS.text_ghost)

                    # Capability badges
                    badges = []
                    if info.supports_tools:
                        badges.append("🔧")
                    if info.supports_vision:
                        badges.append("👁️")
                    if info.supports_reasoning:
                        badges.append("🧠")
                    if badges:
                        text.append(f"  {' '.join(badges)}", style="")
                else:
                    text.append(model_id, style=SQ_COLORS.text_secondary)

            options.add_option(text)

    def watch_step(self, step: str) -> None:
        """Update UI when step changes."""
        try:
            header = self.query_one("#connect-header", Static)
            search_input = self.query_one("#connect-search", Input)

            if step == "provider":
                header.update("◈ Connect to Provider")
                search_input.placeholder = "Search providers..."
            else:
                header.update(f"◈ {self._selected_provider_name} - Select Model")
                search_input.placeholder = "Search models..."

            search_input.value = ""
            self._search_query = ""
            self._update_options()
            search_input.focus()
        except Exception:
            pass

    @on(Input.Changed, "#connect-search")
    def _on_search_changed(self, event: Input.Changed) -> None:
        """Handle search input change."""
        self._search_query = event.value
        self._update_options()

    @on(Input.Submitted, "#connect-search")
    def _on_search_submitted(self, event: Input.Submitted) -> None:
        """Handle enter on search - select first option."""
        try:
            options = self.query_one("#connect-options", OptionList)
            if options.option_count > 0:
                options.highlighted = 0
                self._select_current()
        except Exception:
            pass

    @on(OptionList.OptionSelected)
    def _on_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle option selection."""
        event.stop()
        self._select_at_index(event.option_index)

    def _select_current(self) -> None:
        """Select the currently highlighted option."""
        try:
            options = self.query_one("#connect-options", OptionList)
            if options.highlighted is not None:
                self._select_at_index(options.highlighted)
        except Exception:
            pass

    def _select_at_index(self, index: int) -> None:
        """Select option at index."""
        if self.step == "provider":
            self._select_provider(index)
        else:
            self._select_model(index)

    def _select_provider(self, index: int) -> None:
        """Handle provider selection."""
        # Get filtered list
        query = self._search_query.lower()
        if query:
            from superqode.utils.fuzzy import fuzzy_search

            matches = fuzzy_search.search(
                query, [f"{p[0]} {p[1]}" for p in self._providers], max_results=15
            )
            matched_ids = [m.text.split()[0] for m in matches]
            filtered = [p for p in self._providers if p[0] in matched_ids]
        else:
            filtered = self._providers[:15]

        if 0 <= index < len(filtered):
            provider_id, provider_name, _ = filtered[index]
            self._selected_provider = provider_id
            self._selected_provider_name = provider_name

            # Load models for this provider
            self._load_models(provider_id)

            # Switch to model selection
            self.step = "model"

    def _load_models(self, provider_id: str) -> None:
        """Load models for a provider, with special handling for local providers and HuggingFace."""
        try:
            from superqode.providers.models import get_models_for_provider
            from superqode.providers.registry import PROVIDERS, ProviderCategory

            provider_def = PROVIDERS.get(provider_id)
            self._local_models = {}

            # Check if this is a local provider
            if provider_def and provider_def.category == ProviderCategory.LOCAL:
                # Load models from local provider
                import asyncio

                asyncio.get_event_loop().run_until_complete(self._load_local_models(provider_id))
                return

            # Check if this is HuggingFace
            if provider_id == "huggingface":
                self._load_hf_models()
                return

            # Try getting models from the database (includes live models.dev data)
            # Only use DB models if we did not load local models for local providers.
            if not self._models:
                db_models = get_models_for_provider(provider_id)
            else:
                db_models = {}

            if db_models:
                # Store both model IDs and their info
                self._model_info = db_models
                self._models = list(db_models.keys())
            else:
                # Fall back to registry example models
                if provider_def:
                    self._models = list(provider_def.example_models)
                    self._model_info = {}
                else:
                    self._models = []
                    self._model_info = {}
        except Exception:
            self._models = []
            self._model_info = {}
            self._local_models = {}

    async def _load_local_models(self, provider_id: str) -> None:
        """Load models from a local provider asynchronously."""
        try:
            from superqode.providers.local import (
                OllamaClient,
                LMStudioClient,
                VLLMClient,
                SGLangClient,
                MLXClient,
                TGIClient,
            )

            # Map provider ID to client class
            client_map = {
                "ollama": OllamaClient,
                "lmstudio": LMStudioClient,
                "vllm": VLLMClient,
                "sglang": SGLangClient,
                "mlx": MLXClient,
                "tgi": TGIClient,
            }

            client_class = client_map.get(provider_id)
            if not client_class:
                self._models = []
                self._model_info = {}
                return

            client = client_class()

            if provider_id == "mlx":
                # MLX server can be slow to respond during model load.
                # Try listing models directly before falling back to cache.
                models = []
                try:
                    models = await client.list_models()
                except Exception:
                    models = []

                if not models:
                    try:
                        models = MLXClient.get_available_models()
                    except Exception:
                        models = []

                cached = []
                try:
                    cache_models = MLXClient.discover_huggingface_models()
                    for model_info in cache_models:
                        model_id = model_info["id"]
                        if any(m.id == model_id for m in models):
                            continue
                        cached.append(MLXClient._model_from_cache(model_info, running=False))
                except Exception:
                    cached = []

                # Running models first, then cached models
                models = models + cached
                models_sorted = sorted(models, key=lambda m: (not m.running, m.name))

                self._models = [m.id for m in models_sorted]
                self._local_models = {m.id: m for m in models_sorted}
                self._model_info = {}
                return

            if await client.is_available():
                models = await client.list_models()

                # Preserve order while ensuring running models appear first.
                models_sorted = sorted(models, key=lambda m: (not m.running, m.name))

                self._models = [m.id for m in models_sorted]
                self._local_models = {m.id: m for m in models_sorted}
                self._model_info = {}
            else:
                self._models = []
                self._local_models = {}
                self._model_info = {}

        except Exception:
            self._models = []
            self._local_models = {}
            self._model_info = {}

    def _load_hf_models(self) -> None:
        """Load recommended HuggingFace models."""
        try:
            from superqode.providers.huggingface import RECOMMENDED_MODELS

            # Combine all recommended models
            all_models = []
            for category_models in RECOMMENDED_MODELS.values():
                all_models.extend(category_models)

            # Remove duplicates while preserving order
            seen = set()
            unique = []
            for m in all_models:
                if m not in seen:
                    seen.add(m)
                    unique.append(m)

            self._models = unique
            self._model_info = {}
            self._local_models = {}

        except Exception:
            self._models = []
            self._model_info = {}
            self._local_models = {}

    def _select_model(self, index: int) -> None:
        """Handle model selection."""
        query = self._search_query.lower()
        if query:
            from superqode.utils.fuzzy import fuzzy_search

            matches = fuzzy_search.search(query, self._models, max_results=15)
            filtered = [m.text for m in matches]
        else:
            filtered = self._models[:15]

        if 0 <= index < len(filtered):
            model = filtered[index]
            self.post_message(
                self.ProviderSelected(self._selected_provider, model, self._selected_provider_name)
            )

    def on_key(self, event) -> None:
        """Handle key events."""
        if event.key == "escape":
            if self.step == "model":
                # Go back to provider selection
                self.step = "provider"
            else:
                self.post_message(self.Cancelled())
            event.stop()
        elif event.key == "up":
            try:
                self.query_one("#connect-options", OptionList).action_cursor_up()
            except Exception:
                pass
            event.stop()
        elif event.key == "down":
            try:
                self.query_one("#connect-options", OptionList).action_cursor_down()
            except Exception:
                pass
            event.stop()
        elif event.key == "enter":
            self._select_current()
            event.stop()

    def set_provider(self, provider_id: str) -> None:
        """Pre-select a provider and go to model selection."""
        try:
            from superqode.providers.registry import PROVIDERS

            provider_def = PROVIDERS.get(provider_id)
            if provider_def:
                self._selected_provider = provider_id
                self._selected_provider_name = provider_def.name
                self._load_models(provider_id)
                self.step = "model"
        except Exception:
            pass


# ============================================================================
# INLINE PROVIDER PICKER (for log display)
# ============================================================================


def render_provider_list(
    providers: List[Tuple[str, str, bool]],
    selected_index: int = -1,
    max_items: int = 10,
) -> Text:
    """
    Render a provider list for inline display.

    Args:
        providers: List of (id, name, configured) tuples
        selected_index: Currently selected index (-1 for none)
        max_items: Maximum items to show

    Returns:
        Rich Text object
    """
    text = Text()
    text.append("◈ Select Provider\n\n", style=f"bold {SQ_COLORS.primary}")

    for i, (provider_id, provider_name, configured) in enumerate(providers[:max_items]):
        is_selected = i == selected_index

        # Selection marker
        if is_selected:
            text.append("▸ ", style=f"bold {SQ_COLORS.primary}")
        else:
            text.append("  ", style="")

        # Status indicator
        status = "✓" if configured else "○"
        status_style = SQ_COLORS.success if configured else SQ_COLORS.text_ghost
        text.append(f"{status} ", style=status_style)

        # Provider info
        text.append(f"[{i + 1}] ", style=SQ_COLORS.text_dim)
        text.append(
            f"{provider_id}",
            style=SQ_COLORS.text_secondary if is_selected else SQ_COLORS.text_muted,
        )
        text.append(f"  {provider_name}\n", style=SQ_COLORS.text_dim)

    if len(providers) > max_items:
        text.append(f"\n  ... and {len(providers) - max_items} more\n", style=SQ_COLORS.text_ghost)

    text.append("\n  Type number to select • Scroll to see more: ", style=SQ_COLORS.text_dim)

    return text


def render_model_list(
    provider_name: str,
    models: List[str],
    selected_index: int = -1,
    max_items: int = 10,
    model_info: Optional[Dict] = None,
    local_models: Optional[Dict] = None,
) -> Text:
    """
    Render a model list for inline display.

    Args:
        provider_name: Name of the provider
        models: List of model IDs
        selected_index: Currently selected index (-1 for none)
        max_items: Maximum items to show
        model_info: Optional dict of model_id -> ModelInfo for pricing/features
        local_models: Optional dict of model_id -> LocalModel for local providers
    """
    text = Text()
    text.append(f"◈ {provider_name} Models\n\n", style=f"bold {SQ_COLORS.primary}")

    for i, model_id in enumerate(models[:max_items]):
        is_selected = i == selected_index

        if is_selected:
            text.append("▸ ", style=f"bold {SQ_COLORS.primary}")
        else:
            text.append("  ", style="")

        text.append(f"[{i + 1}] ", style=SQ_COLORS.text_dim)

        # Check for local model first
        local_model = local_models.get(model_id) if local_models else None
        if local_model:
            # Running status indicator
            if local_model.running:
                text.append("● ", style=SQ_COLORS.success)
            else:
                text.append("○ ", style=SQ_COLORS.text_ghost)

            text.append(
                f"{local_model.name}\n",
                style=SQ_COLORS.text_secondary if is_selected else SQ_COLORS.text_muted,
            )
            text.append(f"      {model_id}\n", style=SQ_COLORS.text_ghost)

            # Local model details
            details = []
            if local_model.size_display != "unknown":
                details.append(local_model.size_display)
            if local_model.quantization != "unknown":
                details.append(local_model.quantization)
            if local_model.supports_tools:
                details.append("🔧 tools")
            if local_model.running:
                details.append("[running]")

            if details:
                text.append(f"      {' • '.join(details)}\n", style=SQ_COLORS.text_ghost)
        else:
            # Cloud model with pricing info
            info = model_info.get(model_id) if model_info else None
            if info:
                text.append(
                    f"{info.name}\n",
                    style=SQ_COLORS.text_secondary if is_selected else SQ_COLORS.text_muted,
                )
                text.append(f"      {model_id}\n", style=SQ_COLORS.text_ghost)
                text.append(f"      {info.price_display}", style=SQ_COLORS.success)
                text.append(f" • {info.context_display} ctx", style=SQ_COLORS.text_ghost)

                # Capability badges
                badges = []
                if info.supports_tools:
                    badges.append("🔧")
                if info.supports_vision:
                    badges.append("👁️")
                if badges:
                    text.append(f"  {' '.join(badges)}", style="")
                text.append("\n", style="")
            else:
                text.append(
                    f"{model_id}\n",
                    style=SQ_COLORS.text_secondary if is_selected else SQ_COLORS.text_muted,
                )

    text.append("\n  Type number to select • Scroll to see more: ", style=SQ_COLORS.text_dim)

    return text


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "ProviderConnectWidget",
    "render_provider_list",
    "render_model_list",
]
