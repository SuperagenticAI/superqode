"""Provider selection dialog with keyboard navigation."""

import os
from typing import Optional, List
from prompt_toolkit import prompt
from prompt_toolkit.completion import Completer, Completion
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.box import ROUNDED
from getpass import getpass

from superqode.providers import ProviderManager, ProviderInfo, ModelInfo
from superqode.providers.registry import get_free_providers, PROVIDERS

_console = Console()


class ProviderCompleter(Completer):
    """Completer for provider selection."""

    def __init__(self, providers: List[ProviderInfo]):
        self.providers = providers

    def get_completions(self, document, complete_event):
        """Get completions for provider names."""
        text = document.text_before_cursor.lower()
        for idx, provider in enumerate(self.providers, 1):
            if text in provider.name.lower() or text in provider.id.lower() or text == str(idx):
                yield Completion(
                    provider.id,
                    start_position=-len(text),
                    display=f"{idx}. {provider.name}",
                )


class CategoryCompleter(Completer):
    """Completer for category selection."""

    def __init__(self, categories: List[str]):
        self.categories = categories

    def get_completions(self, document, complete_event):
        """Get completions for category names."""
        text = document.text_before_cursor.lower()
        for idx, category in enumerate(self.categories, 1):
            display_name = category.replace("-", " ").title()
            if text in display_name.lower() or text in category.lower() or text == str(idx):
                yield Completion(
                    category,
                    start_position=-len(text),
                    display=f"{idx}. {display_name}",
                )


class ModelCompleter(Completer):
    """Completer for model selection."""

    def __init__(self, models: List[ModelInfo]):
        self.models = models

    def get_completions(self, document, complete_event):
        """Get completions for model names."""
        text = document.text_before_cursor.lower()
        for idx, model in enumerate(self.models, 1):
            if text in model.name.lower() or text in model.id.lower() or text == str(idx):
                yield Completion(
                    model.id,
                    start_position=-len(text),
                    display=f"{idx}. {model.name}",
                )


class ProviderDialog:
    """Dialog for selecting a provider with keyboard navigation."""

    def __init__(self, manager: Optional[ProviderManager] = None):
        self.manager = manager or ProviderManager()
        self.selected_provider: Optional[ProviderInfo] = None

    def show(self) -> Optional[str]:
        """
        Show the provider selection dialog.

        Returns:
            Selected provider ID, or None if cancelled
        """
        providers = self.manager.list_providers()

        if not providers:
            _console.print(
                "[red]No providers available. Please configure at least one provider.[/red]"
            )
            return None

        # Group providers
        popular_providers = []
        other_providers = []
        chinese_providers = []

        popular_ids = {"ollama", "anthropic", "github-copilot", "openai", "google", "openrouter"}
        chinese_ids = {
            "qwen",
            "deepseek",
            "zhipu",
            "moonshot",
            "minimax",
            "baidu",
            "tencent",
            "doubao",
            "01-ai",
        }

        for provider in providers:
            if provider.id in popular_ids:
                popular_providers.append(provider)
            elif provider.id in chinese_ids:
                chinese_providers.append(provider)
            else:
                other_providers.append(provider)

        # Flatten for selection
        all_providers = popular_providers + other_providers + chinese_providers

        # Display provider selection
        _console.print()
        _console.print(
            Panel.fit(
                "[bold cyan]Select Provider[/bold cyan]\n[dim]Type number, provider name, or use Tab to autocomplete[/dim]",
                border_style="bright_cyan",
            )
        )
        _console.print()

        # Create table for popular providers
        if popular_providers:
            _console.print("[bold bright_yellow]Popular Providers:[/bold bright_yellow]")
            _console.print()
            table = Table(show_header=True, header_style="bold magenta", box=None)
            table.add_column("#", style="dim", width=3)
            table.add_column("Provider", style="cyan", width=25)
            table.add_column("Status", width=20)
            table.add_column("Description", style="dim")

            for idx, provider in enumerate(popular_providers, 1):
                status = (
                    "[green]✓ Configured[/green]"
                    if provider.configured
                    else "[yellow]⚠ Needs API Key[/yellow]"
                )
                table.add_row(
                    str(idx),
                    provider.name,
                    status,
                    provider.description,
                )

            _console.print(table)
            _console.print()

        # Create table for other providers
        if other_providers:
            _console.print("[bold bright_cyan]Other Providers:[/bold bright_cyan]")
            _console.print()
            table = Table(show_header=True, header_style="bold magenta", box=None)
            table.add_column("#", style="dim", width=3)
            table.add_column("Provider", style="cyan", width=25)
            table.add_column("Status", width=20)
            table.add_column("Description", style="dim")

            start_idx = len(popular_providers) + 1
            for idx, provider in enumerate(other_providers, start_idx):
                status = (
                    "[green]✓ Configured[/green]"
                    if provider.configured
                    else "[yellow]⚠ Needs API Key[/yellow]"
                )
                table.add_row(
                    str(idx),
                    provider.name,
                    status,
                    provider.description,
                )

            _console.print(table)
            _console.print()

        # Create table for Chinese providers
        if chinese_providers:
            _console.print("[bold bright_red]Chinese Providers:[/bold bright_red]")
            _console.print()
            table = Table(show_header=True, header_style="bold magenta", box=None)
            table.add_column("#", style="dim", width=3)
            table.add_column("Provider", style="cyan", width=25)
            table.add_column("Status", width=20)
            table.add_column("Description", style="dim")

            start_idx = len(popular_providers) + len(other_providers) + 1
            for idx, provider in enumerate(chinese_providers, start_idx):
                status = (
                    "[green]✓ Configured[/green]"
                    if provider.configured
                    else "[yellow]⚠ Needs API Key[/yellow]"
                )
                table.add_row(
                    str(idx),
                    provider.name,
                    status,
                    provider.description,
                )

            _console.print(table)
            _console.print()

        # Get user selection with autocomplete
        completer = ProviderCompleter(all_providers)

        while True:
            try:
                choice = prompt(
                    "Select provider (number/name, Tab to autocomplete, 'q' to cancel): ",
                    completer=completer,
                ).strip()

                if choice.lower() in ("q", "quit", "exit", ""):
                    return None

                # Try number selection
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(all_providers):
                        selected = all_providers[idx]
                        break
                except ValueError:
                    pass

                # Try name/ID selection
                choice_lower = choice.lower()
                for provider in all_providers:
                    if choice_lower == provider.id.lower() or choice_lower in provider.name.lower():
                        selected = provider
                        break
                else:
                    _console.print(f"[red]Invalid selection: {choice}[/red]")
                    _console.print(
                        "[dim]Please enter a number, provider name, or use Tab for autocomplete.[/dim]"
                    )
                    continue

                break

            except KeyboardInterrupt:
                return None

        self.selected_provider = selected

        # Show experimental warning for vLLM and SGLang
        if selected.id in ("vllm", "sglang"):
            _console.print()
            _console.print(
                Panel(
                    f"[yellow]⚠️  Experimental Provider Warning[/yellow]\n\n"
                    f"{selected.name} support is [bold yellow]EXPERIMENTAL[/bold yellow]. "
                    f"Features may be unstable and behavior may change.\n\n"
                    f"Please report any issues you encounter.",
                    border_style="yellow",
                    title="Experimental Feature",
                )
            )
            _console.print()

        # If not configured, prompt for API key
        if not selected.configured and selected.requires_api_key:
            api_key = self._prompt_api_key(selected)
            if api_key is None:
                return None
            # Set the API key in environment for this session
            env_var = self._get_env_var_for_provider(selected.id)
            os.environ[env_var] = api_key
            # Google - also set GEMINI_API_KEY for compatibility
            if selected.id == "google":
                os.environ["GEMINI_API_KEY"] = api_key
            _console.print(f"[green]✓ API key set for {selected.name}[/green]")
            # Re-check configuration
            selected.configured = True

        # Test connection
        _console.print(f"\n[yellow]Testing connection to {selected.name}...[/yellow]")
        success, error = self.manager.test_connection(selected.id)

        if not success:
            _console.print(f"[red]Connection failed: {error}[/red]")
            if selected.requires_api_key:
                env_var = self._get_env_var_for_provider(selected.id)
                _console.print(f"\n[dim]To configure {selected.name}, set the API key:[/dim]")
                _console.print(f"[dim]  export {env_var}=your-key[/dim]")
                _console.print(f"[dim]  or[/dim]")
                _console.print(f"[dim]  export CODEOPTIX_LLM_API_KEY=your-key[/dim]")
            return None

        _console.print(f"[green]✓ Selected: {selected.name}[/green]")
        return selected.id

    def _prompt_api_key(self, provider: ProviderInfo) -> Optional[str]:
        """Prompt user for API key (like OpenAI does - hidden input)."""
        env_var = self._get_env_var_for_provider(provider.id)

        _console.print()
        _console.print(
            Panel.fit(
                f"[bold cyan]Configure {provider.name}[/bold cyan]\n\n"
                f"[dim]Please enter your API key for {provider.name}.[/dim]\n"
                f"[dim]This will be set for the current session only.[/dim]\n"
                f"[dim]Environment variable: {env_var}[/dim]\n\n"
                f"[yellow]Note: Your API key will be hidden for security (like password input).[/yellow]",
                border_style="bright_cyan",
            )
        )
        _console.print()

        try:
            # Use getpass for security (hides input like password)
            api_key = getpass(f"Enter API key for {provider.name}: ").strip()

            if not api_key:
                _console.print("[yellow]No API key provided. Cancelled.[/yellow]")
                return None

            # Confirm the key (optional, but good UX)
            api_key_confirm = getpass(f"Confirm API key: ").strip()

            if api_key != api_key_confirm:
                _console.print("[red]API keys do not match. Cancelled.[/red]")
                return None

            return api_key
        except KeyboardInterrupt:
            _console.print("\n[yellow]Cancelled.[/yellow]")
            return None

    def _get_env_var_for_provider(self, provider_id: str) -> str:
        """Get environment variable name for a provider."""
        env_var_mapping = {
            # US/International Providers
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY",
            "xai": "XAI_API_KEY",
            "groq": "GROQ_API_KEY",
            "cerebras": "CEREBRAS_API_KEY",
            "together": "TOGETHER_API_KEY",
            "deepinfra": "DEEPINFRA_API_KEY",
            "github-copilot": "GITHUB_TOKEN",
            "openrouter": "OPENROUTER_API_KEY",
            "perplexity": "PERPLEXITY_API_KEY",
            "mistral": "MISTRAL_API_KEY",
            "meta": "META_API_KEY",
            "azure-openai": "AZURE_OPENAI_API_KEY",
            "vertex-ai": "GOOGLE_APPLICATION_CREDENTIALS",
            "openai-compatible": "OPENAI_COMPATIBLE_API_KEY",
            # Chinese Providers
            "qwen": "DASHSCOPE_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "zhipu": "ZHIPU_API_KEY",
            "moonshot": "MOONSHOT_API_KEY",
            "minimax": "MINIMAX_API_KEY",
            "baidu": "BAIDU_API_KEY",
            "tencent": "TENCENT_API_KEY",
            "doubao": "DOUBAO_API_KEY",
            "01-ai": "ZEROONE_API_KEY",
            # Legacy mappings for backward compatibility
            "together-ai": "TOGETHER_API_KEY",
            "google-vertex": "GOOGLE_APPLICATION_CREDENTIALS",
            "azure": "AZURE_OPENAI_API_KEY",
            "cohere": "COHERE_API_KEY",
            "amazon-bedrock": "AWS_ACCESS_KEY_ID",
            "gateway": "GATEWAY_API_KEY",
        }
        return env_var_mapping.get(provider_id, f"{provider_id.upper()}_API_KEY")


class ConnectDialog:
    """Modal dialog for connecting to LLM providers with category selection."""

    # Provider categories
    CATEGORIES = {
        "us-labs": {
            "name": "[bright_blue]US Labs[/bright_blue]",
            "description": "Premium models from leading US AI companies",
            "providers": ["openai", "anthropic", "google", "xai", "amazon-bedrock"],
        },
        "china-labs": {
            "name": "[bright_red]China Labs[/bright_red]",
            "description": "Models from Chinese AI companies",
            "providers": [
                "deepseek",
                "qwen",
                "zhipu",
                "moonshot",
                "minimax",
                "baidu",
                "tencent",
                "doubao",
            ],
        },
        "other-labs": {
            "name": "[bright_green]Other Labs[/bright_green]",
            "description": "Labs from other countries with their own models",
            "providers": ["mistral"],
        },
        "model-hosts": {
            "name": "[bright_magenta]Model Hosts[/bright_magenta]",
            "description": "Services hosting many open and proprietary models",
            "providers": [
                "openrouter",
                "together",
                "groq",
                "fireworks",
                "huggingface",
                "cerebras",
                "perplexity",
                "cohere",
                "opencode",
                "github-copilot",
                "azure",
                "vertex",
                "cloudflare",
            ],
        },
        "local": {
            "name": "[bright_cyan]Local & Self-Hosted[/bright_cyan]",
            "description": "Local engines and OpenAI-compatible self-hosted endpoints",
            "providers": [
                "ollama",
                "lmstudio",
                "mlx",
                "vllm",
                "sglang",
                "tgi",
                "huggingface",
                "openai-compatible",
            ],
        },
        "free-models": {
            "name": "[bright_yellow]🆓 Free Models[/bright_yellow]",
            "description": "Providers offering free models or free tiers",
            "providers": [],  # Will be populated dynamically
        },
    }

    def __init__(self, manager: Optional[ProviderManager] = None):
        self.manager = manager or ProviderManager()
        self.selected_provider: Optional[ProviderInfo] = None
        self.selected_model: Optional[ModelInfo] = None
        # Dynamically populate free-models category
        self._populate_free_models_category()

    def _populate_free_models_category(self):
        """Dynamically populate the free-models category from registry."""
        free_providers = get_free_providers()
        # Get provider IDs that have free models
        free_provider_ids = list(free_providers.keys())
        # Update the category
        if "free-models" in self.CATEGORIES:
            self.CATEGORIES["free-models"]["providers"] = free_provider_ids

    def show(self) -> Optional[tuple[str, str]]:
        """
        Show the connect dialog with category selection.

        Returns:
            Tuple of (provider_id, model_id) or None if cancelled
        """
        while True:
            category = self._show_category_selection()
            if category is None:
                return None

            provider_id = self._show_provider_selection(category)
            if provider_id is None:
                continue  # Go back to category selection

            model_id = self._show_model_selection(provider_id)
            if model_id is None:
                continue  # Go back to provider selection

            return (provider_id, model_id)

    def _show_category_selection(self) -> Optional[str]:
        """Show category selection modal."""
        _console.print()
        _console.print(
            Panel.fit(
                "[bold bright_blue]🔗 SuperQode Connect[/bold bright_blue]\n"
                "[dim]Choose a category to browse available providers and models[/dim]",
                border_style="bright_blue",
            )
        )
        _console.print()

        # Display categories
        table = Table(show_header=True, header_style="bold magenta", box=ROUNDED)
        table.add_column("#", style="dim cyan", width=3, justify="center")
        table.add_column("Category", style="bold white", width=25)
        table.add_column("Description", style="dim")
        table.add_column("Providers", style="yellow", justify="center")

        for idx, (category_id, category_info) in enumerate(self.CATEGORIES.items(), 1):
            # Count configured providers in this category
            providers = self.manager.list_providers()
            configured_count = sum(
                1 for p in providers if p.id in category_info["providers"] and p.configured
            )
            total_count = len(category_info["providers"])

            table.add_row(
                str(idx),
                category_info["name"],
                category_info["description"],
                f"{configured_count}/{total_count} configured",
            )

        _console.print(table)
        _console.print()

        # Get selection
        while True:
            try:
                choice = prompt(
                    "Select category (number, 'q' to cancel): ",
                    completer=CategoryCompleter(list(self.CATEGORIES.keys())),
                ).strip()

                if choice.lower() in ("q", "quit", "exit", ""):
                    return None

                # Try number selection
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(self.CATEGORIES):
                        return list(self.CATEGORIES.keys())[idx]
                except ValueError:
                    pass

                # Try name selection
                choice_lower = choice.lower().replace(" ", "-")
                if choice_lower in self.CATEGORIES:
                    return choice_lower

                _console.print(f"[red]Invalid selection: {choice}[/red]")
                _console.print("[dim]Please enter a number or category name.[/dim]")

            except KeyboardInterrupt:
                return None

    def _show_provider_selection(self, category_id: str) -> Optional[str]:
        """Show provider selection for the chosen category."""
        category_info = self.CATEGORIES[category_id]
        providers = self.manager.list_providers()

        # Filter providers for this category
        category_providers = [p for p in providers if p.id in category_info["providers"]]

        if not category_providers:
            _console.print(f"[red]No providers available in {category_info['name']}[/red]")
            return None

        _console.print()
        _console.print(
            Panel.fit(
                f"[bold bright_green]{category_info['name']}[/bold bright_green]\n"
                f"[dim]{category_info['description']}[/dim]",
                border_style="bright_green",
            )
        )
        _console.print()

        # Display providers
        table = Table(show_header=True, header_style="bold magenta", box=ROUNDED)
        table.add_column("#", style="dim cyan", width=3, justify="center")
        table.add_column("Provider", style="bold white", width=25)
        table.add_column("Status", width=20)
        table.add_column("Models", style="yellow", justify="center")
        table.add_column("Description", style="dim")

        # Get list of providers with free models for badge display
        free_provider_ids = set(get_free_providers().keys())

        for idx, provider in enumerate(category_providers, 1):
            status = (
                "[green]✓ Configured[/green]"
                if provider.configured
                else "[yellow]⚠ Needs Setup[/yellow]"
            )
            model_count = len(provider.models) if provider.models else 0

            # Add free badge if provider offers free models
            provider_name = provider.name
            if provider.id in free_provider_ids:
                provider_name = f"{provider.name} [bright_yellow]🆓 Free[/bright_yellow]"

            table.add_row(str(idx), provider_name, status, str(model_count), provider.description)

        _console.print(table)
        _console.print()

        # Get selection
        while True:
            try:
                choice = prompt(
                    "Select provider (number/name, 'back' for categories, 'q' to cancel): ",
                    completer=ProviderCompleter(category_providers),
                ).strip()

                if choice.lower() in ("q", "quit", "exit", ""):
                    return None
                if choice.lower() == "back":
                    return None  # Go back to category selection

                # Try number selection
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(category_providers):
                        selected = category_providers[idx]
                        break
                except ValueError:
                    pass

                # Try name/ID selection
                choice_lower = choice.lower()
                for provider in category_providers:
                    if choice_lower == provider.id.lower() or choice_lower in provider.name.lower():
                        selected = provider
                        break
                else:
                    _console.print(f"[red]Invalid selection: {choice}[/red]")
                    continue

                break

            except KeyboardInterrupt:
                return None

        self.selected_provider = selected

        # Show experimental warning for vLLM and SGLang
        if selected.id in ("vllm", "sglang"):
            _console.print()
            _console.print(
                Panel(
                    f"[yellow]⚠️  Experimental Provider Warning[/yellow]\n\n"
                    f"{selected.name} support is [bold yellow]EXPERIMENTAL[/bold yellow]. "
                    f"Features may be unstable and behavior may change.\n\n"
                    f"Please report any issues you encounter.",
                    border_style="yellow",
                    title="Experimental Feature",
                )
            )
            _console.print()

        # Show available models first (before asking for API keys)
        models = self.manager.get_models(selected.id)
        if models:
            _console.print(f"\n[bold cyan]Available models for {selected.name}:[/bold cyan]")
            for i, model in enumerate(models[:5], 1):  # Show first 5 models
                _console.print(f"  {i}. {model.name}")
            if len(models) > 5:
                _console.print(f"  ... and {len(models) - 5} more models")
            _console.print()

        # Handle configuration if needed
        if not selected.configured and selected.requires_api_key:
            _console.print(f"[yellow]⚠ {selected.name} requires API key configuration[/yellow]")
            if not self._configure_provider(selected):
                return None  # Configuration failed

        return selected.id

    def _show_model_selection(self, provider_id: str) -> Optional[str]:
        """Show model selection for the chosen provider."""
        if not self.selected_provider:
            return None

        models = self.manager.get_models(provider_id)
        if not models:
            _console.print(
                f"[yellow]No models available for {self.selected_provider.name}[/yellow]"
            )
            _console.print("[dim]This provider may require additional setup or API access.[/dim]")
            return None

        _console.print()
        _console.print(
            Panel.fit(
                f"[bold bright_magenta]{self.selected_provider.name} Models[/bold bright_magenta]",
                border_style="bright_magenta",
            )
        )
        _console.print()

        # Display models
        table = Table(show_header=True, header_style="bold cyan", box=ROUNDED)
        table.add_column("#", style="dim cyan", width=3, justify="center")
        table.add_column("Model", style="bold white", width=30)
        table.add_column("Context", style="yellow", justify="right", width=10)
        table.add_column("Status", width=15)

        for idx, model in enumerate(models[:20], 1):  # Limit to first 20 models
            # Model status (experimental, deprecated, etc.)
            status = "[green]active[/green]"
            if hasattr(model, "status") and model.status:
                if model.status == "experimental":
                    status = "[yellow]experimental[/yellow]"
                elif model.status == "deprecated":
                    status = "[red]deprecated[/red]"

            table.add_row(
                str(idx),
                model.name,
                f"{model.context_size:,}" if model.context_size else "unknown",
                status,
            )

        _console.print(table)

        if len(models) > 20:
            _console.print(f"[dim]... and {len(models) - 20} more models[/dim]")

        _console.print()

        # Get selection
        while True:
            try:
                choice = prompt(
                    "Select model (number/name, 'back' for providers, 'q' to cancel): ",
                    completer=ModelCompleter(models),
                ).strip()

                if choice.lower() in ("q", "quit", "exit", ""):
                    return None
                if choice.lower() == "back":
                    return None  # Go back to provider selection

                # Try number selection
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(models):
                        selected = models[idx]
                        break
                except ValueError:
                    pass

                # Try name selection
                choice_lower = choice.lower()
                for model in models:
                    if choice_lower == model.id.lower() or choice_lower in model.name.lower():
                        selected = model
                        break
                else:
                    _console.print(f"[red]Invalid selection: {choice}[/red]")
                    continue

                break

            except KeyboardInterrupt:
                return None

        self.selected_model = selected
        return selected.id

    def _configure_provider(self, provider: ProviderInfo) -> bool:
        """Configure a provider that needs API key setup."""
        api_key = self._prompt_api_key(provider)
        if api_key is None:
            return False

        # Set the API key in environment
        env_var = self._get_env_var_for_provider(provider.id)
        os.environ[env_var] = api_key
        # Google - also set GEMINI_API_KEY for compatibility
        if provider.id == "google":
            os.environ["GEMINI_API_KEY"] = api_key

        # Test connection
        _console.print(f"\n[yellow]Testing connection to {provider.name}...[/yellow]")
        success, error = self.manager.test_connection(provider.id)

        if not success:
            _console.print(f"[red]Connection failed: {error}[/red]")
            _console.print(f"\n[dim]To configure {provider.name} later, set:[/dim]")
            _console.print(f"[dim]  export {env_var}=your-key[/dim]")
            return False

        _console.print(f"[green]✓ Successfully configured {provider.name}[/green]")
        provider.configured = True
        return True

    def _prompt_api_key(self, provider: ProviderInfo) -> Optional[str]:
        """Prompt user for API key."""
        env_var = self._get_env_var_for_provider(provider.id)

        _console.print()
        _console.print(
            Panel.fit(
                f"[bold cyan]🔑 Configure {provider.name}[/bold cyan]\n\n"
                f"[dim]{provider.description}[/dim]\n\n"
                f"[yellow]API Key Required[/yellow]\n"
                f"[dim]Environment variable: {env_var}[/dim]\n\n"
                f"[yellow]Note: Your API key will be hidden for security.[/yellow]",
                border_style="bright_cyan",
            )
        )
        _console.print()

        try:
            api_key = getpass(f"Enter API key for {provider.name}: ").strip()

            if not api_key:
                _console.print("[yellow]No API key provided. Cancelled.[/yellow]")
                return None

            # Optional confirmation
            confirm = prompt("Confirm API key? (y/n): ", default="y").strip().lower()
            if confirm not in ("y", "yes", ""):
                return None

            return api_key
        except KeyboardInterrupt:
            _console.print("\n[yellow]Cancelled.[/yellow]")
            return None

    def _get_env_var_for_provider(self, provider_id: str) -> str:
        """Get environment variable name for a provider."""
        env_var_mapping = {
            # US/International Providers
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "google": "GOOGLE_API_KEY",
            "xai": "XAI_API_KEY",
            "groq": "GROQ_API_KEY",
            "cerebras": "CEREBRAS_API_KEY",
            "together": "TOGETHER_API_KEY",
            "deepinfra": "DEEPINFRA_API_KEY",
            "github-copilot": "GITHUB_TOKEN",
            "openrouter": "OPENROUTER_API_KEY",
            "perplexity": "PERPLEXITY_API_KEY",
            "mistral": "MISTRAL_API_KEY",
            "meta": "META_API_KEY",
            "azure-openai": "AZURE_OPENAI_API_KEY",
            "vertex-ai": "GOOGLE_APPLICATION_CREDENTIALS",
            "openai-compatible": "OPENAI_COMPATIBLE_API_KEY",
            # Chinese Providers
            "qwen": "DASHSCOPE_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "zhipu": "ZHIPU_API_KEY",
            "moonshot": "MOONSHOT_API_KEY",
            "minimax": "MINIMAX_API_KEY",
            "baidu": "BAIDU_API_KEY",
            "tencent": "TENCENT_API_KEY",
            "doubao": "DOUBAO_API_KEY",
            "01-ai": "ZEROONE_API_KEY",
            # Legacy mappings for backward compatibility
            "together-ai": "TOGETHER_API_KEY",
            "google-vertex": "GOOGLE_APPLICATION_CREDENTIALS",
            "azure": "AZURE_OPENAI_API_KEY",
            "cohere": "COHERE_API_KEY",
            "amazon-bedrock": "AWS_ACCESS_KEY_ID",
            "gateway": "GATEWAY_API_KEY",
        }
        return env_var_mapping.get(provider_id, f"{provider_id.upper()}_API_KEY")
