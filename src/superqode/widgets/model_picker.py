"""
Interactive Model Picker Widget for BYOK Model Selection.

Provides keyboard navigation (arrow keys, Enter) for selecting models.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, TYPE_CHECKING
from dataclasses import dataclass

from rich.text import Text
from textual.widgets import Static, Input, OptionList
from textual.containers import Container, Vertical
from textual.reactive import reactive
from textual.message import Message
from textual import on
from textual.binding import Binding

if TYPE_CHECKING:
    from textual.app import App

try:
    from superqode.design_system import COLORS as SQ_COLORS
except ImportError:

    class SQ_COLORS:
        primary = "#7c3aed"
        success = "#10b981"
        text_secondary = "#e4e4e7"
        text_dim = "#71717a"
        text_ghost = "#52525b"


@dataclass
class ModelOption:
    """Model option data."""

    id: str
    name: str
    price: str = ""
    context: str = ""
    capabilities: List[str] = None
    is_latest: bool = False


class ModelPickerWidget(Container):
    """
    Interactive model picker with keyboard navigation.

    Features:
    - Arrow keys to navigate
    - Enter to select
    - Type to search/filter
    - Visual highlighting
    """

    DEFAULT_CSS = """
    ModelPickerWidget {
        height: auto;
        max-height: 20;
        background: #0a0a0a;
        border: round #7c3aed;
        padding: 1;
        margin: 1 2;
    }

    ModelPickerWidget .header {
        height: 1;
        color: #a855f7;
        text-style: bold;
        margin-bottom: 1;
    }

    ModelPickerWidget Input {
        width: 100%;
        background: #050505;
        border: solid #27272a;
        margin-bottom: 1;
    }

    ModelPickerWidget Input:focus {
        border: solid #7c3aed;
    }

    ModelPickerWidget OptionList {
        height: auto;
        max-height: 12;
        background: #050505;
        border: none;
    }

    ModelPickerWidget OptionList > .option-list--option {
        padding: 0 1;
    }

    ModelPickerWidget OptionList > .option-list--option-highlighted {
        background: #7c3aed40;
    }

    ModelPickerWidget .hint {
        height: 1;
        color: #52525b;
        margin-top: 1;
    }
    """

    class ModelSelected(Message):
        """Posted when a model is selected."""

        def __init__(self, model_id: str) -> None:
            self.model_id = model_id
            super().__init__()

    class Cancelled(Message):
        """Posted when selection is cancelled."""

        pass

    def __init__(self, provider_name: str, models: List[ModelOption], **kwargs):
        super().__init__(**kwargs)
        self.provider_name = provider_name
        self.models = models
        self._filtered_models: List[ModelOption] = models
        self._search_query: str = ""

    def compose(self):
        with Vertical():
            yield Static(
                f"◈ {self.provider_name} - Select Model", classes="header", id="picker-header"
            )
            yield Input(placeholder="Type to search models...", id="picker-search")
            yield OptionList(id="picker-options")
            yield Static("↑↓ Navigate  Enter Select  Esc Cancel", classes="hint", id="picker-hint")

    def on_mount(self) -> None:
        """Initialize the widget."""
        self._update_options()
        try:
            self.query_one("#picker-search", Input).focus()
        except Exception:
            pass

    def _update_options(self) -> None:
        """Update option list based on search."""
        try:
            options = self.query_one("#picker-options", OptionList)
            options.clear_options()

            query = self._search_query.lower()

            # Filter models
            if query:
                self._filtered_models = [
                    m for m in self.models if query in m.id.lower() or query in m.name.lower()
                ]
            else:
                self._filtered_models = self.models

            # Add options
            for model in self._filtered_models[:20]:  # Limit display
                text = self._format_model_option(model)
                options.add_option(text)
        except Exception:
            pass

    def _format_model_option(self, model: ModelOption) -> Text:
        """Format a model option for display."""
        text = Text()

        # Latest indicator
        if model.is_latest:
            text.append("⭐ ", style=SQ_COLORS.success)

        # Model name
        name_style = SQ_COLORS.success if model.is_latest else SQ_COLORS.text_secondary
        text.append(f"{model.name:<30}", style=name_style)

        # Price and context
        if model.price:
            text.append(f"{model.price:>12}", style=SQ_COLORS.success)
        if model.context:
            text.append(f" • {model.context:>6} ctx", style=SQ_COLORS.text_dim)

        # Capabilities
        if model.capabilities:
            text.append(f" • {' '.join(model.capabilities)}", style=SQ_COLORS.text_ghost)

        # Model ID on new line
        text.append(f"\n    {model.id}", style=SQ_COLORS.text_dim)

        return text

    @on(Input.Changed, "#picker-search")
    def _on_search_changed(self, event: Input.Changed) -> None:
        """Handle search input change."""
        self._search_query = event.value
        self._update_options()

    @on(Input.Submitted, "#picker-search")
    def _on_search_submitted(self, event: Input.Submitted) -> None:
        """Handle enter on search - select first option."""
        try:
            options = self.query_one("#picker-options", OptionList)
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
            options = self.query_one("#picker-options", OptionList)
            if options.highlighted is not None:
                self._select_at_index(options.highlighted)
        except Exception:
            pass

    def _select_at_index(self, index: int) -> None:
        """Select model at index."""
        if 0 <= index < len(self._filtered_models):
            model = self._filtered_models[index]
            self.post_message(self.ModelSelected(model.id))

    def action_cancel(self) -> None:
        """Cancel selection."""
        self.post_message(self.Cancelled())
