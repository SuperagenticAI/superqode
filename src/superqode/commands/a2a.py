"""
A2A Commands for the TUI.

Provides :a2a command to discover, connect, and manage A2A agents.
"""

from __future__ import annotations

from typing import Any, Dict


class A2ACommands:
    """Handle A2A-related commands in the TUI."""

    def __init__(self):
        self._registry = None
        self._connected_agents: Dict[str, Any] = {}

    def remember_agent(self, name: str, url: str) -> None:
        """Keep an agent so ``:a2a call <name>`` works after the connect screen."""
        label = (name or url).strip()
        if not label or not url:
            return
        self._connected_agents[label] = {"url": url, "name": label}

    def _agents(self) -> list[dict[str, str]]:
        """Unique saved agents: session memory first, then ``a2a.json``."""
        from superqode.a2a.connection import load_saved_connection

        by_url: dict[str, dict[str, str]] = {}
        saved = load_saved_connection()
        if saved.url:
            by_url[saved.url] = {"name": saved.name or saved.url, "url": saved.url}
        for record in self._connected_agents.values():
            url = str(record.get("url") or "")
            if not url:
                continue
            name = str(record.get("name") or url)
            previous = by_url.get(url)
            if previous and previous["name"] not in {url, ""} and name == url:
                continue
            by_url[url] = {"name": name, "url": url}
        return list(by_url.values())

    def _resolve_url(self, name_or_url: str) -> str:
        if "://" in name_or_url:
            return name_or_url
        for agent in self._agents():
            if agent["name"] == name_or_url or agent["url"] == name_or_url:
                return agent["url"]
        return ""

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
[bold]A2A Commands[/bold]

[green]:a2a connect [url][/green] - Open the A2A screen (URL prefills the origin)
[green]:a2a list[/green]          - List saved agents
[green]:a2a discover <url>[/green] - Discover agent at URL
[green]:a2a call <name> <msg>[/green] - Call a saved agent
[green]:a2a workflow <type>[/green] - Run workflow (parallel, sequential)
[green]:a2a remove <name>[/green] - Remove an agent from this session
[green]:a2a help[/green]           - Show this help

Examples:
  :a2a connect https://agent.example
  :a2a call Pilot "Which coding agents are open source?"
"""
        log.add_info(help_text)

    async def _connect(self, args: str, log: Any):
        """Connect is handled by the TUI screen; this is a fallback."""
        log.add_error("Use :a2a connect or :connect a2a to open the A2A screen.")

    async def _list_agents(self, log: Any):
        """List connected agents."""
        agents = self._agents()
        if not agents:
            log.add_info("No A2A agents saved. Use :a2a connect")
            return

        log.add_info("[bold]Saved A2A agents:[/bold]\n")
        for agent in agents:
            if agent["name"] == agent["url"]:
                log.add_info(f"  • {agent['url']}")
            else:
                log.add_info(f"  • {agent['name']}  {agent['url']}")

    async def _discover(self, args: str, log: Any):
        """Discover agent at URL."""
        if not args:
            log.add_error("Usage: :a2a discover <url>")
            return

        url = args.strip()
        log.add_info(f"Discovering agent at {url}...")

        try:
            from superqode.a2a import A2AClient
            from superqode.a2a.connection import client_auth, resolve_settings

            settings = resolve_settings(url, None)
            async with A2AClient(
                settings.url or url, timeout=180.0, **client_auth(settings)
            ) as client:
                card = await client.get_agent_card()

            log.add_info(f"Discovered: [bold]{card.name}[/bold]")
            log.add_info(f"   Version: {card.version}")
            if card.description:
                log.add_info(f"   Description: {card.description[:100]}")

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
        url = self._resolve_url(name_or_url)
        if not url:
            log.add_error(f"Unknown agent: {name_or_url}. Use :a2a connect first.")
            return

        log.add_info(f"Calling {url}...")

        try:
            from superqode.a2a import A2AClient
            from superqode.a2a.connection import client_auth, resolve_settings
            from superqode.a2a.oauth import satisfy_card_auth
            from superqode.a2a.reply import task_reply

            settings = resolve_settings(url, None)
            async with A2AClient(
                settings.url or url, timeout=180.0, **client_auth(settings)
            ) as client:
                await satisfy_card_auth(
                    client,
                    settings.url or url,
                    token=settings.token,
                    headers=dict(settings.headers),
                    interactive=False,
                )
                task = await client.send_message(message)

            state = (
                task.status.state.value
                if hasattr(task.status.state, "value")
                else str(task.status.state)
            )
            log.add_info(f"Status: {state}")
            text = task_reply(task)
            if text:
                log.add_info(text[:2000])
        except Exception as e:
            log.add_error(f"Call failed: {e}")

    async def _run_workflow(self, args: str, log: Any):
        """Run a multi-agent workflow."""
        agents = self._agents()
        if not agents:
            log.add_info("No agents connected. Connect agents first with :a2a connect")
            return

        workflow_type = args.strip() or "parallel"
        log.add_info(f"Running {workflow_type} workflow...")

        try:
            from ..a2a import A2AWorkflowEngine

            engine = A2AWorkflowEngine()

            for agent in agents:
                await engine.add_agent(agent["name"], agent["url"])

            if workflow_type == "parallel":
                steps = [
                    {"name": agent["name"], "agent_url": agent["url"], "prompt": "Run tests"}
                    for agent in agents
                ]
                result = await engine.parallel(steps, "Run full test suite")

            elif workflow_type == "sequential":
                steps = [{"name": agent["name"], "agent_url": agent["url"]} for agent in agents]
                result = await engine.sequential(steps, "Process task")

            else:
                log.add_error(f"Unknown workflow: {workflow_type}")
                return

            await engine.close()

            log.add_info(f"Workflow complete: {result.pattern.value}")
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
            log.add_info(f"Removed {name} from this session")
        else:
            log.add_error(
                f"Unknown session agent: {name}. Saved connections stay in ~/.superqode/a2a.json."
            )


def create_a2a_commands() -> A2ACommands:
    """Create A2A commands handler."""
    return A2ACommands()
