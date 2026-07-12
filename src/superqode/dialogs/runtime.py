"""Runtime selection dialog.

Mirrors `ProviderDialog`'s prompt_toolkit-driven pattern but is much simpler —
the runtime menu is a closed set of three names. Used by the `/runtime` slash
command in the TUI.
"""

from __future__ import annotations

from typing import List, Optional

from prompt_toolkit import prompt
from prompt_toolkit.completion import Completer, Completion
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ..runtime import RuntimeInfo, list_runtimes, resolve_runtime_name

_console = Console()


class _RuntimeCompleter(Completer):
    def __init__(self, runtimes: List[RuntimeInfo]):
        self.runtimes = runtimes

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lower()
        for idx, info in enumerate(self.runtimes, 1):
            if text in info.name.lower() or text == str(idx):
                yield Completion(
                    info.name,
                    start_position=-len(text),
                    display=f"{idx}. {info.name}",
                )


class RuntimeDialog:
    """Modal-style runtime picker shown by `/runtime` and the status-bar badge.

    Returns the chosen runtime name (e.g. ``"adk"``) or ``None`` if the user
    cancels or selects an unavailable runtime.
    """

    def __init__(self, active: Optional[str] = None):
        self.runtimes = list_runtimes()
        self.active = active or resolve_runtime_name()

    def show(self) -> Optional[str]:
        """Display the picker and return the chosen runtime name (or None)."""
        _console.print()
        _console.print(
            Panel.fit(
                "[bold cyan]Select agent runtime[/bold cyan]\n"
                "[dim]Type number or runtime name. Empty to cancel.[/dim]",
                border_style="bright_cyan",
            )
        )
        _console.print()

        table = Table(show_header=True, header_style="bold magenta", box=None)
        table.add_column("#", style="dim", width=3)
        table.add_column("Runtime", style="cyan", width=18)
        table.add_column("Status", width=28)
        table.add_column("Description", style="dim")

        for idx, info in enumerate(self.runtimes, 1):
            if info.name == self.active:
                status = "[green]✓ active[/green]"
            elif not info.installed:
                status = f"[yellow]missing[/yellow] {info.install_hint or ''}".strip()
            elif not info.implemented:
                status = "[red]stub (not implemented)[/red]"
            elif not info.ready:
                status = f"[yellow]unavailable[/yellow] {info.status_detail or ''}".strip()
            else:
                status = "[green]✓ available[/green]"
            table.add_row(str(idx), info.name, status, info.description)

        _console.print(table)
        _console.print()

        try:
            answer = prompt(
                "runtime> ",
                completer=_RuntimeCompleter(self.runtimes),
            ).strip()
        except (EOFError, KeyboardInterrupt):
            return None

        if not answer:
            return None

        selected = self._resolve_answer(answer)
        if selected is None:
            _console.print(f"[red]Unknown runtime: '{answer}'[/red]")
            return None

        if not selected.installed:
            _console.print(
                f"[yellow]Runtime '{selected.name}' is not installed.[/yellow] "
                f"[dim]{selected.install_hint or ''}[/dim]"
            )
            return None

        if not selected.implemented:
            _console.print(f"[red]Runtime '{selected.name}' is a stub and not yet usable.[/red]")
            return None

        if not selected.ready:
            _console.print(
                f"[yellow]Runtime '{selected.name}' is not ready.[/yellow] "
                f"[dim]{selected.status_detail or ''}[/dim]"
            )
            return None

        return selected.name

    def _resolve_answer(self, answer: str) -> Optional[RuntimeInfo]:
        """Resolve a numeric or name answer to a RuntimeInfo, or None if unknown."""
        if answer.isdigit():
            idx = int(answer) - 1
            if 0 <= idx < len(self.runtimes):
                return self.runtimes[idx]
            return None
        normalized = answer.strip().lower()
        for info in self.runtimes:
            if info.name == normalized:
                return info
        return None
