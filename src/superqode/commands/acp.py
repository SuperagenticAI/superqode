"""ACP (Agent-Client Protocol) commands for SuperQode."""

import asyncio
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from superqode.agents.client import ACPAgentManager
from superqode.agents.discovery import get_agent_by_identity, get_agent_by_short_name, read_agents

if TYPE_CHECKING:
    from superqode.agents.schema import Agent

_console = Console()


def check_agent_installed(agent: "Agent") -> bool:
    """Check if an agent is installed on the system."""
    import shutil

    run_command = agent.get("run_command", {}).get("*", "")
    if not run_command:
        return False

    # Extract the command name (first part before any spaces or arguments)
    cmd_name = run_command.split()[0]

    # Check if command exists in PATH
    return shutil.which(cmd_name) is not None


def create_agent_card(
    agent: "Agent", is_enabled: bool = False, is_installed: bool | None = None
) -> Panel:
    """Create a beautiful agent card."""
    # Check installation status if not provided
    if is_installed is None:
        is_installed = check_agent_installed(agent)

    # Status indicators
    status_icon = "✅" if is_enabled else "⏳" if is_installed else "📦"
    status_text = "Enabled" if is_enabled else "Ready" if is_installed else "Available"
    status_color = "green" if is_enabled else "yellow" if is_installed else "dim"

    # Agent info
    name = agent["name"]
    short_name = agent["short_name"]
    description = agent["description"]
    author = agent["author_name"]
    agent_type = agent["type"]

    # Type badge
    type_badge = f"[bold white on blue] {agent_type.upper()} [/bold white on blue]"

    content = f"""[bold cyan]{name}[/bold cyan] [dim]({short_name})[/dim]
{type_badge}

[white]{description}[/white]

[dim]By {author}[/dim]
[{status_color}]{status_icon} {status_text}[/{status_color}]"""

    border_style = "bright_green" if is_enabled else "cyan" if is_installed else "dim"

    return Panel.fit(
        content,
        border_style=border_style,
        padding=(1, 2),
        title=f"[bold]{short_name}[/bold]",
        title_align="center",
    )


def show_agents_store() -> None:
    """Show the beautiful Agent Store interface."""
    import asyncio
    from superqode.config import load_config
    from superqode.agents.registry import get_all_acp_agents

    try:
        agents = asyncio.run(get_all_acp_agents())
    except Exception as e:
        _console.print(f"[red]Error loading agents: {e}[/red]")
        return

    if not agents:
        _console.print("[yellow]No ACP agents found. Agent configurations may be missing.[/yellow]")
        return

    # Get current configuration
    config = load_config()
    config_agents = (
        getattr(config, "agents", {}).get("acp", {}) if hasattr(config, "agents") else {}
    )

    # Count installed vs not installed
    installed_count = sum(1 for agent_data in agents.values() if check_agent_installed(agent_data))
    not_installed_count = len(agents) - installed_count

    # Header
    header = Panel.fit(
        "[bold bright_blue]🛍️  SuperQode Agent Store[/bold bright_blue]\n"
        "[dim]Discover and install AI coding agents for your development team[/dim]\n\n"
        f"[cyan]📊 {len(agents)} agents available[/cyan] | "
        f"[green]✓ {installed_count} installed[/green] | "
        f"[yellow]○ {not_installed_count} not installed[/yellow]",
        border_style="bright_blue",
        padding=(1, 2),
    )

    _console.print(header)
    _console.print()

    # Create agent cards in a grid layout (3 per row)
    agent_cards = []
    for agent_id, agent_data in agents.items():
        is_enabled = config_agents.get(agent_id, {}).get("enabled", False)
        is_installed = check_agent_installed(agent_data)
        card = create_agent_card(agent_data, is_enabled, is_installed)
        agent_cards.append(card)

    # Display in rows of 3
    from rich.columns import Columns

    for i in range(0, len(agent_cards), 3):
        row_cards = agent_cards[i : i + 3]
        if len(row_cards) == 1:
            _console.print(row_cards[0])
        else:
            _console.print(Columns(row_cards, equal=True, expand=True))
        _console.print()

    # Footer with commands
    footer = Panel.fit(
        "[bold cyan]🚀 Quick Commands:[/bold cyan]\n\n"
        "[green]superqode agents show <agent>[/green]      View detailed agent info\n"
        "[green]superqode agents install <agent>[/green]   Install agent on your system\n"
        "[green]superqode agents connect <agent> [model][/green]   Connect with specific model\n\n"
        "[bold cyan]💻 Interactive Commands:[/bold cyan]\n"
        "[yellow]:agents[/yellow]                          Browse this marketplace\n"
        "[yellow]:agents install <agent>[/yellow]         Install directly from here\n"
        "[yellow]:agents connect <agent> [model][/yellow]         Connect with model\n"
        "[yellow]:agent <command>[/yellow]                Same as :agents (singular)\n\n"
        "[dim]💡 Configure agents in your superqode.yaml to enable them in your team[/dim]",
        border_style="cyan",
        padding=(1, 2),
    )

    _console.print(footer)


def show_agents_list() -> None:
    """Show a list of available ACP agents with installation status."""
    import asyncio
    from superqode.config import load_config
    from superqode.agents.registry import get_all_acp_agents, get_agent_installation_info

    try:
        agents = asyncio.run(get_all_acp_agents())
    except Exception as e:
        _console.print(f"[red]Error loading agents: {e}[/red]")
        return

    if not agents:
        _console.print("[yellow]No ACP agents found. Agent configurations may be missing.[/yellow]")
        return

    # Get current configuration
    config = load_config()
    config_agents = (
        getattr(config, "agents", {}).get("acp", {}) if hasattr(config, "agents") else {}
    )

    _console.print()
    _console.print("[bold bright_blue]🤖 Available ACP Coding Agents[/bold bright_blue]")
    _console.print()

    # Separate agents by installation status
    installed_agents = []
    not_installed_agents = []

    for agent_id, agent_data in agents.items():
        is_installed = check_agent_installed(agent_data)
        if is_installed:
            installed_agents.append((agent_id, agent_data))
        else:
            not_installed_agents.append((agent_id, agent_data))

    # Show installed agents first
    if installed_agents:
        _console.print("[bold green]✓ Installed Agents[/bold green]")
        _console.print()

        table = Table(show_header=True, header_style="bold green")
        table.add_column("Name", style="cyan", no_wrap=True)
        table.add_column("Short Name", style="green")
        table.add_column("Description", style="white", max_width=50)
        table.add_column("Author", style="yellow")
        table.add_column("Status", style="cyan", no_wrap=True)

        for agent_id, agent_data in sorted(installed_agents, key=lambda x: x[1]["name"]):
            is_enabled = config_agents.get(agent_id, {}).get("enabled", False)
            status = "[green]✓ Enabled[/green]" if is_enabled else "[dim]Not configured[/dim]"

            table.add_row(
                agent_data["name"],
                agent_data["short_name"],
                agent_data["description"][:50] + "..."
                if len(agent_data["description"]) > 50
                else agent_data["description"],
                agent_data["author_name"],
                status,
            )

        _console.print(table)
        _console.print()

    # Show not installed agents with installation commands
    if not_installed_agents:
        _console.print("[bold yellow]○ Not Installed Agents[/bold yellow]")
        _console.print()

        table = Table(show_header=True, header_style="bold yellow")
        table.add_column("Name", style="cyan", no_wrap=True)
        table.add_column("Short Name", style="green")
        table.add_column("Description", style="white", max_width=40)
        table.add_column("Install Command", style="magenta", no_wrap=False)

        for agent_id, agent_data in sorted(not_installed_agents, key=lambda x: x[1]["name"]):
            install_info = get_agent_installation_info(agent_data)
            install_cmd = install_info.get("command", "N/A")

            # Truncate long commands
            if len(install_cmd) > 40:
                install_cmd = install_cmd[:37] + "..."

            table.add_row(
                agent_data["name"],
                agent_data["short_name"],
                agent_data["description"][:40] + "..."
                if len(agent_data["description"]) > 40
                else agent_data["description"],
                f"[dim]{install_cmd}[/dim]"
                if install_cmd == "N/A"
                else f"[cyan]{install_cmd}[/cyan]",
            )

        _console.print(table)
        _console.print()
        _console.print("[dim]💡 To install an agent, run:[/dim]")
        _console.print("[cyan]  superqode agents install <short-name>[/cyan]")
        _console.print("[dim]  or[/dim]")
        _console.print("[cyan]  :acp install <short-name>[/cyan]")
        _console.print()

    _console.print("[dim]Use 'superqode agents store' to see the beautiful store interface[/dim]")
    _console.print("[dim]Use 'superqode connect acp <short-name>' to connect to an agent[/dim]")
    _console.print()


def format_installation_instructions(agent: "Agent") -> Text:
    """Format installation instructions for an agent.

    Args:
        agent: Agent dict.

    Returns:
        Formatted Text object with installation instructions.
    """
    from superqode.agents.registry import get_agent_installation_info
    import asyncio

    install_info = get_agent_installation_info(agent)
    command = install_info.get("command", "")
    description = install_info.get("description", "Install agent")
    instructions = install_info.get("instructions", "")

    text = Text()
    text.append(f"\n  📦 ", style="bold cyan")
    text.append(f"Installation Instructions for {agent['name']}\n\n", style="bold")

    if command:
        text.append("  Installation Command:\n", style="bold yellow")
        text.append(f"    {command}\n\n", style="cyan")

    if instructions:
        text.append("  Instructions:\n", style="bold yellow")
        # Split instructions by lines and format
        for line in instructions.split("\n"):
            if line.strip():
                text.append(f"    {line}\n", style="white")
        text.append("\n", style="")

    # Show requirements if available
    run_command = agent.get("run_command", {}).get("*", "")
    if run_command:
        text.append("  Verification:\n", style="bold yellow")
        text.append(f"    After installation, verify with: ", style="dim")
        text.append(f"which {run_command.split()[0]}\n", style="cyan")
        text.append("\n", style="")

    return text


def show_agent_installation_steps(agent_identifier: str) -> None:
    """Display detailed installation instructions for an agent.

    Args:
        agent_identifier: Agent short name or identity.
    """
    import asyncio
    from superqode.agents.discovery import (
        get_agent_by_short_name_async,
        get_agent_by_identity_async,
    )
    from superqode.agents.registry import get_all_acp_agents

    async def show_steps_async():
        # Try to find agent
        agent = await get_agent_by_short_name_async(agent_identifier, include_registry=True)
        if not agent:
            agent = await get_agent_by_identity_async(agent_identifier, include_registry=True)

        if not agent:
            _console.print(f"[red]Agent '{agent_identifier}' not found.[/red]")
            _console.print("[dim]Use 'superqode agents list' to see available agents.[/dim]")
            return

        # Check if already installed
        is_installed = check_agent_installed(agent)
        if is_installed:
            _console.print(f"[green]✓ {agent['name']} is already installed![/green]")
            _console.print(
                f"[dim]Run command: {agent.get('run_command', {}).get('*', 'N/A')}[/dim]"
            )
            return

        # Show installation instructions
        instructions = format_installation_instructions(agent)
        _console.print(instructions)

        # Show prerequisites
        install_info = get_agent_installation_info(agent)
        command = install_info.get("command", "")

        if command:
            if "npm" in command:
                _console.print("  Prerequisites:\n", style="bold yellow")
                _console.print("    - Node.js (v16 or higher)\n", style="white")
                _console.print("    - npm (comes with Node.js)\n", style="white")
            elif "pip" in command:
                _console.print("  Prerequisites:\n", style="bold yellow")
                _console.print("    - Python 3.8 or higher\n", style="white")
                _console.print("    - pip (Python package manager)\n", style="white")
            elif "cargo" in command:
                _console.print("  Prerequisites:\n", style="bold yellow")
                _console.print("    - Rust toolchain (rustc and cargo)\n", style="white")
                _console.print("    - Cargo package manager\n", style="white")

            _console.print("\n  Quick Install:\n", style="bold green")
            _console.print(f"    {command}\n", style="cyan")
            _console.print("\n  Or use SuperQode:\n", style="bold green")
            _console.print(f"    superqode agents install {agent['short_name']}\n", style="cyan")

    asyncio.run(show_steps_async())


def show_agent_details(agent: "Agent") -> None:
    """Show detailed information about a specific agent."""
    _console.print()
    _console.print(f"[bold bright_blue]🤖 {agent['name']}[/bold bright_blue]")
    _console.print(f"[dim]{agent['url']}[/dim]")
    _console.print()

    # Basic info
    _console.print("[bold cyan]Basic Information:[/bold cyan]")
    _console.print(f"  Author: {agent['author_name']} ({agent['author_url']})")
    _console.print(f"  Type: {agent['type']}")
    _console.print(f"  Protocol: {agent['protocol']}")
    _console.print()

    # Description
    _console.print("[bold cyan]Description:[/bold cyan]")
    _console.print(f"  {agent['description']}")
    _console.print()

    # Help
    if agent.get("help"):
        _console.print("[bold cyan]Help:[/bold cyan]")
        _console.print(agent["help"])
        _console.print()

    # Actions
    if agent.get("actions", {}).get("*"):
        _console.print("[bold cyan]Available Actions:[/bold cyan]")
        for action_name, action_data in agent["actions"]["*"].items():
            _console.print(f"  [green]{action_name}[/green]: {action_data['description']}")
        _console.print()


def validate_agent_environment(agent: "Agent") -> list[str]:
    """Validate environment variables required for an agent.

    Args:
        agent: Agent configuration

    Returns:
        List of missing environment variables
    """
    missing_vars = []

    # Agent-specific environment variable requirements
    # This could be extended to read from agent config
    agent_name = agent.get("short_name", "").lower()

    # Define known environment variable requirements for agents
    env_requirements = {
        "claude": ["ANTHROPIC_API_KEY"],
        "opencode": ["ZHIPUAI_API_KEY"],  # GLM-4.7 uses ZHIPUAI
        "gemini": ["GOOGLE_API_KEY"],
        "openai": ["OPENAI_API_KEY"],
        "kimi": ["MOONSHOT_API_KEY"],
        "grok": ["XAI_API_KEY"],
    }

    # Check if agent requires specific environment variables
    if agent_name in env_requirements:
        required_vars = env_requirements[agent_name]
        for var in required_vars:
            if not os.getenv(var):
                missing_vars.append(var)

    return missing_vars


def perform_agent_health_check(agent: "Agent") -> tuple[bool, list[str]]:
    """Perform comprehensive health checks before launching an agent.

    Args:
        agent: Agent configuration

    Returns:
        Tuple of (is_healthy, list_of_issues)
    """
    issues = []

    # Check 1: Installation status
    if not check_agent_installed(agent):
        issues.append(f"Agent '{agent['short_name']}' is not installed")
        return False, issues

    # Check 2: Environment variables
    missing_env_vars = validate_agent_environment(agent)
    if missing_env_vars:
        issues.extend([f"Missing environment variable: {var}" for var in missing_env_vars])

    # Check 3: Run command validity
    run_command = agent.get("run_command", {}).get("*")
    if not run_command:
        issues.append("No run command configured")
    else:
        import shutil

        cmd_parts = run_command.split()
        if not shutil.which(cmd_parts[0]):
            issues.append(f"Command '{cmd_parts[0]}' not found in PATH")

    # Check 4: Protocol support
    protocol = agent.get("protocol")
    if protocol != "acp":
        issues.append(f"Unsupported protocol: {protocol} (only ACP is supported)")

    # Check 5: Required fields
    required_fields = ["identity", "name", "short_name"]
    for field in required_fields:
        if field not in agent:
            issues.append(f"Missing required field: {field}")

    is_healthy = len(issues) == 0
    return is_healthy, issues


def diagnose_agent_issues(agent: "Agent", issues: list[str]) -> None:
    """Provide helpful diagnostics and solutions for agent issues.

    Args:
        agent: Agent configuration
        issues: List of identified issues
    """
    if not issues:
        return

    _console.print(f"[yellow]🔍 Diagnostics for {agent['name']}:[/yellow]")

    for issue in issues:
        if "not installed" in issue:
            _console.print(f"  [red]• {issue}[/red]")
            _console.print(
                f"    [cyan]Solution: superqode agents install {agent['short_name']}[/cyan]"
            )
        elif "Missing environment variable" in issue:
            var_name = issue.split(": ")[1]
            _console.print(f"  [red]• {issue}[/red]")
            _console.print(f"    [cyan]Solution: export {var_name}=your_api_key_here[/cyan]")
            _console.print(
                f"    [dim]Get your API key from: {agent.get('author_url', 'the provider website')}[/dim]"
            )
        elif "not found in PATH" in issue:
            cmd_name = issue.split("'")[1]
            _console.print(f"  [red]• {issue}[/red]")
            _console.print(
                f"    [cyan]Solution: Install {cmd_name} and ensure it's in your PATH[/cyan]"
            )
        elif "Unsupported protocol" in issue:
            _console.print(f"  [red]• {issue}[/red]")
            _console.print(f"    [dim]This agent uses an unsupported protocol[/dim]")
        else:
            _console.print(f"  [red]• {issue}[/red]")

    _console.print()


async def connect_to_agent(agent_identifier: str, project_dir: str | None = None) -> int:
    """Connect to an ACP coding agent.

    Args:
        agent_identifier: Short name or identity of the agent
        project_dir: Project directory to work in

    Returns:
        Exit code
    """
    # Find the agent
    from superqode.agents.discovery import (
        get_agent_by_short_name_async,
        get_agent_by_identity_async,
    )

    agent = await get_agent_by_short_name_async(agent_identifier)
    if not agent:
        agent = await get_agent_by_identity_async(agent_identifier)

    if not agent:
        _console.print(f"[red]Agent '{agent_identifier}' not found.[/red]")
        _console.print("[dim]Use 'superqode agents list' to see available agents.[/dim]")
        return 1

    # Perform comprehensive health check
    _console.print(f"[cyan]🔍 Checking {agent['name']}...[/cyan]")
    is_healthy, issues = perform_agent_health_check(agent)

    if not is_healthy:
        _console.print(f"[red]❌ Health check failed for {agent['name']}[/red]")
        diagnose_agent_issues(agent, issues)
        return 1

    _console.print(f"[green]✓ Health check passed[/green]")
    _console.print(f"[green]Connecting to {agent['name']}...[/green]")

    # Get the run command
    run_command = agent.get("run_command", {}).get("*")
    if not run_command:
        _console.print(f"[red]No run command configured for agent '{agent['name']}'.[/red]")
        return 1

    # Check if the command exists
    import shutil

    cmd_parts = run_command.split()
    if not shutil.which(cmd_parts[0]):
        _console.print(
            f"[red]Command '{cmd_parts[0]}' not found. Please install the agent first.[/red]"
        )
        _console.print(f"[dim]Run: superqode agents install {agent['short_name']}[/dim]")
        return 1

    # Create agent manager
    manager = ACPAgentManager()

    try:
        # Connect to the agent
        cwd = project_dir or os.getcwd()
        success = await manager.connect_to_agent(run_command, cwd)

        if not success:
            _console.print(f"[red]Failed to connect to {agent['name']}.[/red]")
            return 1

        _console.print(f"[green]✓ Connected to {agent['name']}![/green]")
        _console.print(
            "[dim]Type your messages and press Enter. Type 'exit' or 'quit' to disconnect.[/dim]"
        )
        _console.print()

        # Interactive loop
        while True:
            try:
                # Get user input
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input("> ").strip()
                )

                if user_input.lower() in ("exit", "quit", "q"):
                    break

                if not user_input:
                    continue

                # Send message to agent
                await manager.send_message(user_input)

                # Receive and display responses
                messages = await manager.receive_messages()
                for message in messages:
                    if hasattr(message, "content"):
                        print(f"Agent: {message.content}")
                    else:
                        print(f"Agent: {message}")

            except KeyboardInterrupt:
                break
            except EOFError:
                break

    except Exception as e:
        _console.print(f"[red]Connection error: {e}[/red]")
        return 1
    finally:
        await manager.disconnect()

    _console.print("[green]Disconnected from agent.[/green]")
    return 0


def check_system_dependencies() -> dict[str, bool]:
    """Check for common system dependencies required by agents.

    Returns:
        Dict mapping dependency names to availability status
    """
    import shutil

    dependencies = {
        "npm": shutil.which("npm") is not None,
        "node": shutil.which("node") is not None,
        "python": shutil.which("python") is not None or shutil.which("python3") is not None,
        "uv": shutil.which("uv") is not None,
        "pip": shutil.which("pip") is not None or shutil.which("pip3") is not None,
        "curl": shutil.which("curl") is not None,
    }

    return dependencies


def get_os_command(actions: dict, action_name: str) -> str | None:
    """Get the appropriate command for the current OS."""
    import platform

    system = platform.system().lower()

    # Try OS-specific command first
    os_command = actions.get(system, {}).get("command")
    if os_command:
        return os_command

    # Fall back to wildcard
    wildcard_command = actions.get("*", {}).get("command")
    if wildcard_command:
        return wildcard_command

    return None


def install_system_dependency(dep_name: str) -> bool:
    """Attempt to install a system dependency.

    Args:
        dep_name: Name of the dependency to install

    Returns:
        True if installation succeeded or was skipped
    """
    import subprocess
    import platform

    system = platform.system().lower()

    install_commands = {
        "uv": {
            "darwin": "curl -LsSf https://astral.sh/uv/install.sh | sh",
            "linux": "curl -LsSf https://astral.sh/uv/install.sh | sh",
            "windows": 'powershell -c "irm https://astral.sh/uv/install.sh | iex"',
        },
        "npm": {
            "darwin": "brew install node",
            "linux": "curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - && sudo apt-get install -y nodejs",
            "windows": "choco install nodejs",
        },
    }

    if dep_name in install_commands and system in install_commands[dep_name]:
        cmd = install_commands[dep_name][system]
        _console.print(f"[cyan]Installing {dep_name}...[/cyan]")
        _console.print(f"[dim]{cmd}[/dim]")

        try:
            result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
            _console.print(f"[green]✓ {dep_name} installed successfully[/green]")
            return True
        except subprocess.CalledProcessError as e:
            _console.print(f"[yellow]⚠️ Could not auto-install {dep_name}[/yellow]")
            _console.print(f"[dim]Please install {dep_name} manually[/dim]")
            return False

    return False


def install_agent(agent_identifier: str) -> int:
    """Install an ACP agent with smart dependency detection.

    Args:
        agent_identifier: Short name or identity of the agent

    Returns:
        Exit code
    """
    import asyncio
    import subprocess

    async def install_agent_async():
        # Find the agent (include registry)
        from superqode.agents.discovery import (
            get_agent_by_short_name_async,
            get_agent_by_identity_async,
        )

        agent = await get_agent_by_short_name_async(agent_identifier, include_registry=True)
        if not agent:
            agent = await get_agent_by_identity_async(agent_identifier, include_registry=True)

        if not agent:
            _console.print(f"[red]Agent '{agent_identifier}' not found.[/red]")
            _console.print("[dim]Use 'superqode agents list' to see available agents.[/dim]")
            return 1

        # Get available actions
        actions = agent.get("actions", {})

        # If no actions in agent, try to get from registry
        if not actions:
            from superqode.agents.registry import get_agent_installation_info

            install_info = get_agent_installation_info(agent)
            command = install_info.get("command", "")

            if command:
                # Create temporary actions structure
                actions = {
                    "*": {
                        "install": {
                            "command": command,
                            "description": install_info.get(
                                "description", f"Install {agent['name']}"
                            ),
                        }
                    }
                }
            else:
                _console.print(
                    f"[red]No installation actions available for '{agent['name']}'.[/red]"
                )
                _console.print(
                    "[dim]Please check the agent's documentation for installation instructions.[/dim]"
                )
                return 1

    # Pre-flight checks
    _console.print(f"[bold cyan]🚀 Installing {agent['name']}[/bold cyan]")
    _console.print(f"[dim]{agent.get('description', '')}[/dim]")
    _console.print()

    # Check system dependencies
    deps = check_system_dependencies()
    missing_deps = [dep for dep, available in deps.items() if not available]

    if missing_deps:
        _console.print("[yellow]⚠️ Missing system dependencies detected:[/yellow]")
        for dep in missing_deps:
            _console.print(f"  [red]• {dep}[/red]")

        # Try to auto-install critical dependencies
        critical_deps = ["uv"]  # Add more as needed
        for dep in critical_deps:
            if dep in missing_deps:
                if not install_system_dependency(dep):
                    _console.print(
                        f"[red]Cannot proceed without {dep}. Please install it manually.[/red]"
                    )
                    return 1

        _console.print()

    # Get the install command for current OS
    install_command = get_os_command(actions, "install")
    if not install_command:
        _console.print("[red]No installation command found for this agent on your OS.[/red]")
        return 1

    # Check for bootstrap_uv flag
    needs_uv_bootstrap = False
    for os_actions in actions.values():
        if isinstance(os_actions, dict) and os_actions.get("bootstrap_uv", False):
            needs_uv_bootstrap = True
            break

    # Bootstrap UV if needed
    if needs_uv_bootstrap and not deps.get("uv", False):
        _console.print("[cyan]Bootstrapping UV package manager...[/cyan]")
        if not install_system_dependency("uv"):
            _console.print("[red]UV bootstrap failed. Cannot proceed.[/red]")
            return 1

    _console.print(f"[green]Installing {agent['name']}...[/green]")
    _console.print(f"[dim]Command: {install_command}[/dim]")
    _console.print()

    # Run the installation command with progress feedback
    try:
        # Use a more interactive approach for long-running installs
        process = subprocess.Popen(
            install_command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )

        # Show progress
        _console.print("[cyan]Installation in progress...[/cyan]")

        # Wait for completion
        stdout, stderr = process.communicate()

        if process.returncode == 0:
            _console.print("[green]✓ Installation completed successfully![/green]")

            # Verify installation
            if check_agent_installed(agent):
                _console.print(f"[green]✓ Agent '{agent['short_name']}' is ready to use![/green]")
                _console.print(f"[dim]Try: superqode agents connect {agent['short_name']}[/dim]")
            else:
                _console.print("[yellow]⚠️ Agent installed but verification failed[/yellow]")
                _console.print(
                    f"[dim]You may need to restart your shell or check the installation manually[/dim]"
                )

            return 0
        else:
            _console.print(f"[red]✗ Installation failed (exit code {process.returncode})[/red]")

            # Enhanced error analysis
            error_msg = stderr.lower() if stderr else ""

            if "eacces" in error_msg or "permission denied" in error_msg:
                _console.print("[yellow]💡 Permission Error:[/yellow]")
                _console.print("  This command requires administrator privileges.")
                _console.print(f"  Try: [bold]sudo {install_command}[/bold]")
                _console.print(
                    "  Or use a Node version manager like nvm/fnm for user-space installation"
                )
            elif "command not found" in error_msg or "npm: command not found" in error_msg:
                _console.print("[yellow]💡 Missing npm:[/yellow]")
                _console.print("  Node.js/npm is not installed. Install from:")
                _console.print("  https://nodejs.org/ or use your system package manager")
            elif "uv: command not found" in error_msg:
                _console.print("[yellow]💡 Missing UV:[/yellow]")
                _console.print("  UV package manager is not installed. Install with:")
                _console.print("  curl -LsSf https://astral.sh/uv/install.sh | sh")
            elif "certificate" in error_msg or "ssl" in error_msg:
                _console.print("[yellow]💡 SSL/Certificate Error:[/yellow]")
                _console.print("  There may be network or certificate issues.")
                _console.print("  Try updating your system's CA certificates.")
            else:
                # Show the actual error output
                if stdout.strip():
                    _console.print("[dim]Output:[/dim]")
                    _console.print(stdout.strip())
                if stderr.strip():
                    _console.print("[dim]Error:[/dim]")
                    _console.print(stderr.strip())

            _console.print(
                f"\n[dim]💡 Alternative: Try installing manually with: {install_command}[/dim]"
            )
            return 1

    except FileNotFoundError:
        _console.print(
            f"[red]Command not found. Please ensure required dependencies are installed.[/red]"
        )
        return 1
    except Exception as e:
        _console.print(f"[red]Installation error: {e}[/red]")
        return 1

    try:
        return asyncio.run(install_agent_async())
    except RuntimeError as e:
        if "asyncio.run() cannot be called from a running event loop" in str(e):
            # We're already in an async context
            import nest_asyncio

            nest_asyncio.apply()
            return asyncio.run(install_agent_async())
        else:
            raise


# Main command functions for CLI integration
def list_agents() -> None:
    """List all available ACP agents."""
    show_agents_list()


def show_agent(agent_identifier: str) -> None:
    """Show details about a specific agent."""
    import asyncio

    agent = get_agent_by_short_name(agent_identifier)
    if not agent:
        agent = get_agent_by_identity(agent_identifier)

    if not agent:
        _console.print(f"[red]Agent '{agent_identifier}' not found.[/red]")
        return

    show_agent_details(agent)


def connect_agent(agent_identifier: str, project_dir: str | None = None) -> int:
    """Connect to an ACP agent (synchronous wrapper)."""
    try:
        return asyncio.run(connect_to_agent(agent_identifier, project_dir))
    except RuntimeError as e:
        if "asyncio.run() cannot be called from a running event loop" in str(e):
            # We're already in an async context, create a new task
            import nest_asyncio

            nest_asyncio.apply()
            return asyncio.run(connect_to_agent(agent_identifier, project_dir))
        else:
            raise


def install_agent_cmd(agent_identifier: str) -> int:
    """Install an ACP agent (synchronous wrapper)."""
    return install_agent(agent_identifier)
