"""
A2A Commands for the TUI.

Provides :a2a command to discover, connect, and manage A2A agents.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class A2ACommands:
    """Handle A2A-related commands in the TUI."""

    def __init__(self):
        self._registry = None
        self._connected_agents: Dict[str, Any] = {}

    async def handle_command(
        self,
        subcommand: str,
        args: str,
        log: Any,
    ) -> bool:
        """Handle :a2a commands.

        Args:
            subcommand: The subcommand (connect, list, discover, call, workflow)
            args: Arguments for the command
            log: Logger for output

        Returns:
            True if command was handled
        """
        if not subcommand:
            await self._show_help(log)
            return True

        if subcommand == "help":
            await self._show_help(log)
            return True
        elif subcommand == "connect" or subcommand == "add":
            await self._connect(args, log)
            return True
        elif subcommand == "list" or subcommand == "ls":
            await self._list_agents(log)
            return True
        elif subcommand == "discover":
            await self._discover(args, log)
            return True
        elif subcommand == "call":
            await self._call_agent(args, log)
            return True
        elif subcommand == "workflow":
            await self._run_workflow(args, log)
            return True
        elif subcommand == "remove" or subcommand == "rm":
            await self._remove_agent(args, log)
            return True
        else:
            log.add_error(f"Unknown A2A command: {subcommand}")
            await self._show_help(log)
            return True

    async def _show_help(self, log: Any):
        """Show A2A help."""
        help_text = """
[bold cyan]A2A Commands[/bold cyan]

[green]:a2a connect <url>[/green] - Connect to an A2A agent
[green]:a2a list[/green]          - List connected agents
[green]:a2a discover <url>[/green] - Discover agent at URL
[green]:a2a call <name> <msg>[/green] - Call an agent
[green]:a2a workflow <type>[/green] - Run workflow (parallel, sequential)
[green]:a2a remove <name>[/green] - Remove an agent
[green]:a2a help[/green]           - Show this help

Examples:
  :a2a connect http://localhost:8000
  :a2a discover http://gemini-agent:8080
  :a2a call gemini "Write a unit test"
  :a2a workflow parallel
"""
        log.add_info(help_text)

    async def _connect(self, args: str, log: Any):
        """Connect to an A2A agent."""
        if not args:
            log.add_error("Usage: :a2a connect <url>")
            return

        url = args.strip()
        log.add_info(f"Connecting to {url}...")

        try:
            from ..a2a import A2AClient, A2ARegistry

            if not self._registry:
                self._registry = A2ARegistry()

            # Try to add and verify
            success = await self._registry.add(url.split("/")[-1] or "agent", url)

            if success:
                log.add_info(f"✅ Connected to {url}")
                self._connected_agents[url] = {"url": url, "connected": True}
            else:
                log.add_warning(f"⚠️ Added but not verified: {url}")

        except ImportError:
            log.add_error("A2A not installed. Run: uv tool install 'superqode[a2a]'")
        except Exception as e:
            log.add_error(f"Failed to connect: {e}")

    async def _list_agents(self, log: Any):
        """List connected agents."""
        if not self._connected_agents:
            log.add_info("No A2A agents connected. Use :a2a connect <url>")
            return

        log.add_info("[bold]Connected A2A Agents:[/bold]\n")
        for name, info in self._connected_agents.items():
            status = "✅ connected" if info.get("connected") else "❌ disconnected"
            log.add_info(f"  • {name}: {status}")

    async def _discover(self, args: str, log: Any):
        """Discover agent at URL."""
        if not args:
            log.add_error("Usage: :a2a discover <url>")
            return

        url = args.strip()
        log.add_info(f"Discovering agent at {url}...")

        try:
            from ..a2a import A2AClient

            client = A2AClient(url)
            card = await client.get_agent_card()
            await client.close()

            log.add_info(f"✅ Discovered: [bold]{card.name}[/bold]")
            log.add_info(f"   Version: {card.version}")
            log.add_info(f"   Description: {card.description[:100]}...")

            if card.skills:
                log.add_info(f"   Skills: {len(card.skills)}")
                for skill in card.skills[:5]:
                    log.add_info(f"     - {skill.name}")

        except Exception as e:
            log.add_error(f"Discovery failed: {e}")

    async def _call_agent(self, args: str, log: Any):
        """Call an A2A agent."""
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            log.add_error("Usage: :a2a call <name_or_url> <message>")
            return

        name_or_url = parts[0]
        message = parts[1]

        # Check if it's a URL or name
        if "http" in name_or_url:
            url = name_or_url
        elif self._connected_agents.get(name_or_url):
            url = self._connected_agents[name_or_url]["url"]
        else:
            log.add_error(f"Unknown agent: {name_or_url}. Use :a2a connect first.")
            return

        log.add_info(f"Calling {url}...")

        try:
            from ..a2a import A2AClient

            client = A2AClient(url)
            task = await client.send_message(message)
            await client.close()

            status = task.status.state.value
            log.add_info(f"Status: {status}")

            # Extract result
            if task.history:
                for msg in reversed(task.history):
                    if hasattr(msg, "role") and msg.role.value == "agent":
                        if hasattr(msg, "parts") and msg.parts:
                            result = (
                                msg.parts[0].text[:200]
                                if hasattr(msg.parts[0], "text")
                                else "No text"
                            )
                            log.add_info(f"Result: {result}...")
                            break

        except Exception as e:
            log.add_error(f"Call failed: {e}")

    async def _run_workflow(self, args: str, log: Any):
        """Run a multi-agent workflow."""
        if not self._connected_agents:
            log.add_info("No agents connected. Connect agents first with :a2a connect")
            return

        workflow_type = args.strip() or "parallel"
        log.add_info(f"Running {workflow_type} workflow...")

        try:
            from ..a2a import A2AWorkflowEngine

            engine = A2AWorkflowEngine()

            # Add connected agents
            for name, info in self._connected_agents.items():
                await engine.add_agent(name, info["url"])

            if workflow_type == "parallel":
                steps = [
                    {"name": name, "agent_url": info["url"], "prompt": "Run tests"}
                    for name, info in self._connected_agents.items()
                ]
                result = await engine.parallel(steps, "Run full test suite")

            elif workflow_type == "sequential":
                steps = [
                    {"name": name, "agent_url": info["url"]}
                    for name, info in self._connected_agents.items()
                ]
                result = await engine.sequential(steps, "Process task")

            else:
                log.add_error(f"Unknown workflow: {workflow_type}")
                return

            await engine.close()

            log.add_info(f"✅ Workflow complete: {result.pattern.value}")
            log.add_info(f"   Success: {result.success}")
            log.add_info(f"   Time: {result.total_time:.2f}s")

        except Exception as e:
            log.add_error(f"Workflow failed: {e}")

    async def _remove_agent(self, args: str, log: Any):
        """Remove an agent."""
        if not args:
            log.add_error("Usage: :a2a remove <name>")
            return

        name = args.strip()
        if name in self._connected_agents:
            del self._connected_agents[name]
            log.add_info(f"Removed {name}")
        else:
            log.add_error(f"Unknown agent: {name}")


def create_a2a_commands() -> A2ACommands:
    """Create A2A commands handler."""
    return A2ACommands()
