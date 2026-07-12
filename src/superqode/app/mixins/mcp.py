"""MCP server config and attachment helpers."""

from __future__ import annotations
import shlex
from urllib.parse import urlparse
from pathlib import Path
from rich.text import Text
from superqode.app.constants import (
    THEME,
)
from superqode.app.widgets import (
    ConversationLog,
)

# --- helpers extracted from app_main (A1) ---
from superqode.app.recipes import PromptCompletionCandidate


class McpMixin:
    """MCP server configuration and resource-attachment helpers."""

    @staticmethod
    def _mcp_server_completion_candidates() -> list[PromptCompletionCandidate]:
        try:
            from superqode.mcp.config import load_mcp_config

            servers = load_mcp_config(Path.cwd() / ".superqode" / "mcp.json")
        except Exception:
            return []
        candidates = []
        for server_id, server in servers.items():
            transport = getattr(server.config, "transport", "mcp")
            enabled = "enabled" if server.enabled else "disabled"
            candidates.append(
                PromptCompletionCandidate(
                    value=server_id,
                    label=server_id,
                    description=f"{transport}, {enabled}",
                    kind="mcp",
                )
            )
        return candidates

    @staticmethod
    def _mcp_resource_ref(server_id: str, uri: str) -> str:
        return f"mcp://{server_id}/{uri}"

    @staticmethod
    def _mcp_resource_completion_candidates() -> list[PromptCompletionCandidate]:
        try:
            from superqode.mcp import integration

            manager = getattr(integration, "_mcp_manager", None)
            if manager is None:
                return []
            resources = manager.list_all_resources()
        except Exception:
            return []
        candidates = []
        for resource in resources:
            label = f"{resource.server_id}/{resource.uri}"
            description = resource.name or resource.mime_type or ""
            if resource.description:
                description = (
                    f"{description} - {resource.description}"
                    if description
                    else resource.description
                )
            candidates.append(
                PromptCompletionCandidate(
                    value=label,
                    label=label,
                    description=description,
                    kind="resource",
                )
            )
        return candidates[:25]

    @staticmethod
    def _mcp_server_config_from_target(server_id: str, target: str):
        """Build an MCPServerConfig from a URL or stdio command string."""
        from superqode.mcp.config import MCPHttpConfig, MCPServerConfig, MCPStdioConfig

        target = target.strip()
        if target.startswith(("http://", "https://")):
            return MCPServerConfig(
                id=server_id,
                name=server_id,
                enabled=True,
                auto_connect=True,
                config=MCPHttpConfig(url=target),
            )
        argv = shlex.split(target)
        if not argv:
            raise ValueError("MCP target cannot be empty")
        command = argv[0]
        args = argv[1:]
        if command.startswith("@"):
            args = [command, *args]
            command = "npx"
        return MCPServerConfig(
            id=server_id,
            name=server_id,
            enabled=True,
            auto_connect=True,
            config=MCPStdioConfig(command=command, args=args),
        )

    @staticmethod
    def _mcp_id_from_target(target: str) -> str:
        """Generate a stable-ish MCP server id for direct connect targets."""
        target = target.strip()
        if target.startswith(("http://", "https://")):
            parsed = urlparse(target)
            base = parsed.netloc or parsed.path
        else:
            try:
                parts = shlex.split(target)
            except ValueError:
                parts = target.split()
            base = parts[0] if parts else "mcp"
            if base.startswith("@"):
                base = base.split("/")[-1]
        safe = "".join(ch if ch.isalnum() else "-" for ch in base.lower()).strip("-")
        return safe or "mcp-server"

    async def _mcp_attach_resource(self, manager, target: str, log: ConversationLog) -> None:
        """Stage an MCP resource reference for the next prompt."""
        resource = self._resolve_mcp_resource_ref(manager, target)
        if resource is None:
            log.add_error(f"MCP resource not found or ambiguous: {target}")
            log.add_info("Use :mcp resources, then :mcp attach <index|server/uri>.")
            return
        ref = self._mcp_resource_ref(resource.server_id, resource.uri)
        refs = list(getattr(self, "_attached_refs", []))
        if ref not in refs:
            refs.append(ref)
        self._attached_refs = refs
        self._sync_attachment_prefill()
        detail = resource.name or resource.uri
        if resource.mime_type:
            detail = f"{detail} ({resource.mime_type})"
        log.add_info(f"Attached MCP resource: {detail}")

    async def _mcp_cmd(self, args: str, log: ConversationLog):
        """Handle MCP status and inventory commands."""
        try:
            from superqode.mcp.integration import get_mcp_manager
        except ImportError as exc:
            log.add_error(f"MCP support is not installed: {exc}")
            return

        parts = args.split(maxsplit=1)
        subcommand = parts[0].lower() if parts else "status"
        subargs = parts[1].strip() if len(parts) > 1 else ""
        if subcommand == "list":
            subcommand = "status"

        manager = await get_mcp_manager()

        if subcommand in ("", "status"):
            configs = manager.get_server_configs()
            summary = manager.get_status_summary()
            t = Text()
            t.append("\n  🔗 ", style=f"bold {THEME['cyan']}")
            t.append("MCP Servers\n\n", style=f"bold {THEME['cyan']}")
            t.append("  Configured: ", style=THEME["muted"])
            t.append(f"{summary['total_servers']}  ", style=f"bold {THEME['text']}")
            t.append("Connected: ", style=THEME["muted"])
            t.append(f"{summary['connected']}  ", style=f"bold {THEME['success']}")
            t.append("Tools: ", style=THEME["muted"])
            t.append(f"{summary['total_tools']}  ", style=f"bold {THEME['text']}")
            t.append("Resources: ", style=THEME["muted"])
            t.append(f"{summary['total_resources']}  ", style=f"bold {THEME['text']}")
            t.append("Prompts: ", style=THEME["muted"])
            t.append(f"{summary['total_prompts']}\n\n", style=f"bold {THEME['text']}")

            if not configs:
                t.append("  No MCP servers configured.\n", style=THEME["muted"])
                t.append(
                    "  Add servers in .superqode/mcp.json or your MCP config file.\n",
                    style=THEME["dim"],
                )
            else:
                for server_id, config in configs.items():
                    state = manager.get_connection_state(server_id).value
                    server_summary = summary["servers"].get(server_id, {})
                    status_style = (
                        THEME["success"]
                        if state == "connected"
                        else THEME["warning"]
                        if state == "error"
                        else THEME["muted"]
                    )
                    t.append(f"  {server_id:<18}", style=f"bold {THEME['cyan']}")
                    t.append(f"{state:<13}", style=status_style)
                    t.append(f"{config.name or server_id:<22}", style=THEME["text"])
                    t.append(
                        f"{server_summary.get('tools', 0)} tools  {server_summary.get('resources', 0)} resources  {server_summary.get('prompts', 0)} prompts",
                        style=THEME["muted"],
                    )
                    error = server_summary.get("error")
                    if error:
                        t.append(f"  {error}", style=THEME["warning"])
                    t.append("\n")

            t.append("\n  Commands: ", style=THEME["muted"])
            t.append(":mcp connect [server]", style=THEME["cyan"])
            t.append(", ", style=THEME["muted"])
            t.append(":mcp disconnect [server]", style=THEME["cyan"])
            t.append(", ", style=THEME["muted"])
            t.append(":mcp tools", style=THEME["cyan"])
            t.append(", ", style=THEME["muted"])
            t.append(":mcp resources", style=THEME["cyan"])
            t.append(", ", style=THEME["muted"])
            t.append(":mcp attach <resource>", style=THEME["cyan"])
            t.append("\n", style=THEME["muted"])
            self._show_command_output(log, t)
            return

        if subcommand == "add":
            try:
                tokens = shlex.split(subargs)
            except ValueError as exc:
                log.add_error(f"Could not parse MCP add command: {exc}")
                return
            if len(tokens) < 2:
                log.add_info("Usage: :mcp add <name> <url|stdio command>")
                return
            if not self._ensure_project_trusted_for(log, "add an MCP server"):
                return
            server_id = tokens[0]
            target = " ".join(shlex.quote(token) for token in tokens[1:])
            ok, message = await self._add_mcp_server_config(manager, server_id, target)
            if ok:
                log.add_info(message)
                log.add_info(f"Connect it with :mcp connect {server_id}")
            else:
                log.add_error(message)
            return

        if subcommand == "connect":
            if subargs:
                configs = manager.get_server_configs()
                server_id = subargs
                if subargs not in configs:
                    if not self._ensure_project_trusted_for(log, "add an MCP server"):
                        return
                    server_id = self._mcp_id_from_target(subargs)
                    ok, message = await self._add_mcp_server_config(manager, server_id, subargs)
                    if not ok:
                        log.add_error(message)
                        return
                    log.add_info(message)
                ok = await manager.connect(server_id)
                log.add_info(
                    f"MCP server {server_id}: {'connected' if ok else 'failed to connect'}"
                )
            else:
                results = await manager.connect_all()
                if not results:
                    log.add_info("No enabled MCP servers configured.")
                else:
                    connected = sum(1 for ok in results.values() if ok)
                    log.add_info(f"Connected {connected}/{len(results)} MCP servers.")
            return

        if subcommand in {"reconnect", "restart"}:
            if subargs:
                ok = await manager.restart_server(subargs)
                log.add_info(
                    f"MCP server {subargs}: {'reconnected' if ok else 'failed to reconnect'}"
                )
            else:
                configs = manager.get_server_configs()
                if not configs:
                    log.add_info("No MCP servers configured.")
                    return
                results = {}
                for server_id in configs:
                    results[server_id] = await manager.restart_server(server_id)
                connected = sum(1 for ok in results.values() if ok)
                log.add_info(f"Reconnected {connected}/{len(results)} MCP servers.")
            return

        if subcommand == "disconnect":
            if subargs:
                await manager.disconnect(subargs)
                log.add_info(f"MCP server {subargs}: disconnected")
            else:
                await manager.disconnect_all()
                log.add_info("Disconnected all MCP servers.")
            return

        if subcommand in {"doctor", "diagnostics", "diag"}:
            self._show_mcp_doctor(manager, subargs, log)
            return

        if subcommand == "attach":
            if not subargs:
                log.add_info("Usage: :mcp attach <index|server/uri|mcp://server/uri>")
                log.add_info("Use :mcp resources to list attachable resources.")
                return
            await self._mcp_attach_resource(manager, subargs, log)
            return

        if subcommand == "tools":
            tools = manager.list_all_tools()
            t = Text()
            t.append("\n  🧰 ", style=f"bold {THEME['cyan']}")
            t.append("MCP Tools\n\n", style=f"bold {THEME['cyan']}")
            if not tools:
                t.append(
                    "  No MCP tools are available from connected servers.\n", style=THEME["muted"]
                )
                t.append("  Run ", style=THEME["muted"])
                t.append(":mcp connect", style=THEME["cyan"])
                t.append(" first if servers are configured.\n", style=THEME["muted"])
            for tool in tools:
                t.append(f"  {tool.server_id:<16}", style=f"bold {THEME['purple']}")
                t.append(f"{tool.name}", style=THEME["text"])
                if tool.description:
                    t.append(f" - {tool.description[:120]}", style=THEME["muted"])
                t.append("\n")
            self._show_command_output(log, t)
            return

        if subcommand == "resources":
            resources = manager.list_all_resources()
            t = Text()
            t.append("\n  📚 ", style=f"bold {THEME['cyan']}")
            t.append("MCP Resources\n\n", style=f"bold {THEME['cyan']}")
            if not resources:
                t.append(
                    "  No MCP resources are available from connected servers.\n",
                    style=THEME["muted"],
                )
            for index, resource in enumerate(resources, 1):
                t.append(f"  [{index}] ", style=THEME["dim"])
                t.append(f"{resource.server_id:<16}", style=f"bold {THEME['purple']}")
                t.append(f"{resource.name}", style=THEME["text"])
                t.append(f"  {resource.uri}", style=THEME["muted"])
                if resource.mime_type:
                    t.append(f"  {resource.mime_type}", style=THEME["dim"])
                t.append("\n")
            if resources:
                t.append("\n  Attach: ", style=THEME["muted"])
                t.append(":mcp attach <index|server/uri>", style=THEME["cyan"])
                t.append("\n", style=THEME["muted"])
            self._show_command_output(log, t)
            return

        if subcommand == "prompts":
            prompts = manager.list_all_prompts()
            t = Text()
            t.append("\n  💬 ", style=f"bold {THEME['cyan']}")
            t.append("MCP Prompts\n\n", style=f"bold {THEME['cyan']}")
            if not prompts:
                t.append(
                    "  No MCP prompts are available from connected servers.\n", style=THEME["muted"]
                )
            for prompt in prompts:
                t.append(f"  {prompt.server_id:<16}", style=f"bold {THEME['purple']}")
                t.append(prompt.name, style=THEME["text"])
                if prompt.description:
                    t.append(f" - {prompt.description[:120]}", style=THEME["muted"])
                t.append("\n")
            self._show_command_output(log, t)
            return

        log.add_info(
            "Usage: :mcp status|add|connect|reconnect|disconnect|doctor|tools|resources|attach|prompts"
        )
