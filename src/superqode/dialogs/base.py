"""Base dialog class for interactive dialogs."""

from abc import ABC, abstractmethod
from typing import Any, Optional, List
from prompt_toolkit import Application
from prompt_toolkit.layout import Layout, HSplit, VSplit
from prompt_toolkit.widgets import TextArea, Label
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from rich.console import Console

_console = Console()


class Dialog(ABC):
    """Base class for interactive dialogs."""

    def __init__(self, title: str):
        self.title = title
        self.result: Optional[Any] = None
        self.cancelled = False

    @abstractmethod
    def show(self) -> Optional[Any]:
        """Show the dialog and return the result."""
        pass

    def _create_style(self) -> Style:
        """Create a style for the dialog."""
        return Style.from_dict(
            {
                "dialog": "bg:#1e1e1e",
                "dialog.frame": "bg:#2d2d2d #ffffff",
                "dialog.body": "bg:#1e1e1e #ffffff",
                "dialog.title": "bg:#2d2d2d #ffffff bold",
                "selected": "bg:#0078d4 #ffffff",
                "unselected": "bg:#1e1e1e #ffffff",
            }
        )
