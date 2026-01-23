"""Model selection dialog."""

from typing import Optional, List
from prompt_toolkit import prompt
from prompt_toolkit.completion import Completer, Completion
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from superqode.providers import ProviderManager, ModelInfo

_console = Console()


class ModelCompleter(Completer):
    """Completer for model selection."""

    def __init__(self, models: List[ModelInfo]):
        self.models = models

    def get_completions(self, document, complete_event):
        """Get completions for model names."""
        text = document.text_before_cursor.lower()
        for model in self.models:
            if text in model.name.lower() or text in model.id.lower():
                yield Completion(
                    model.id,
                    start_position=-len(text),
                    display=f"{model.name} ({model.id})",
                )


class ModelDialog:
    """Dialog for selecting a model."""

    def __init__(self, provider_id: str, manager: Optional[ProviderManager] = None):
        self.provider_id = provider_id
        self.manager = manager or ProviderManager()
        self.selected_model: Optional[ModelInfo] = None

    def show(self) -> Optional[str]:
        """
        Show the model selection dialog.

        Returns:
            Selected model ID, or None if cancelled
        """
        models = self.manager.get_models(self.provider_id, refresh=True)

        if not models:
            _console.print(f"[red]No models available for provider '{self.provider_id}'.[/red]")
            _console.print("[dim]Make sure the provider is configured correctly.[/dim]")
            return None

        # Get provider info for display
        providers = self.manager.list_providers()
        provider = next((p for p in providers if p.id == self.provider_id), None)
        provider_name = provider.name if provider else self.provider_id

        # Display model selection
        _console.print()
        _console.print(
            Panel.fit(
                f"[bold cyan]Select Model ({provider_name})[/bold cyan]", border_style="bright_cyan"
            )
        )
        _console.print()

        # Create table
        table = Table(show_header=True, header_style="bold magenta", box=None)
        table.add_column("#", style="dim", width=3)
        table.add_column("Model", style="cyan", width=30)
        table.add_column("Description", style="dim")

        for idx, model in enumerate(models, 1):
            desc = model.description or f"Model ID: {model.id}"
            table.add_row(
                str(idx),
                model.name,
                desc,
            )

        _console.print(table)
        _console.print()

        # Get user selection
        completer = ModelCompleter(models)

        while True:
            try:
                choice = prompt(
                    "Select model (number or name, 'q' to cancel): ",
                    completer=completer,
                ).strip()

                if choice.lower() in ("q", "quit", "exit", ""):
                    return None

                # Try number selection
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(models):
                        selected = models[idx]
                        break
                except ValueError:
                    pass

                # Try name/ID selection
                choice_lower = choice.lower()
                for model in models:
                    if (
                        choice_lower == model.id.lower()
                        or choice_lower in model.name.lower()
                        or choice_lower in model.id.lower()
                    ):
                        selected = model
                        break
                else:
                    _console.print(f"[red]Invalid selection: {choice}[/red]")
                    continue

                break

            except KeyboardInterrupt:
                return None

        self.selected_model = selected
        _console.print(f"[green]✓ Selected: {selected.name} ({selected.id})[/green]")
        return selected.id
