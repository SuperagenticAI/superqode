"""
Slash Commands Handler.

Adds / prefix command support alongside : prefix (vim-style).
Both formats work interchangeably.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class SlashCommand:
    """Definition of a slash command."""
    name: str
    description: str
    handler: Callable
    aliases: list[str] = field(default_factory=list)
    category: str = "general"


class SlashCommandHandler:
    """Handler for slash commands (/command).
    
    Both /command and :command formats work identically.
    
    Usage:
        handler = SlashCommandHandler()
        
        # Register commands
        handler.register(SlashCommand(
            name="help",
            description="Show help",
            handler=show_help,
        ))
        
        handler.register(SlashCommand(
            name="exit",
            description="Exit the session",
            handler=do_exit,
            aliases=["quit", "q"],
        ))
        
        # Parse input
        command, args = handler.parse_input("/help")
        # Or from : style
        command, args = handler.parse_input(":help")
        
        # Execute
        if command:
            await command.handler(args)
    """

    def __init__(self):
        self._commands: dict[str, SlashCommand] = {}

    def register(self, command: SlashCommand) -> None:
        """Register a slash command."""
        self._commands[command.name] = command
        
        # Register aliases
        for alias in command.aliases:
            self._commands[alias] = command

    def unregister(self, name: str) -> bool:
        """Unregister a command."""
        if name in self._commands:
            del self._commands[name]
            return True
        return False

    def parse_input(self, input_str: str) -> tuple[Optional[SlashCommand], str]:
        """Parse input to extract command and arguments.
        
        Handles both /command and :command formats.
        
        Args:
            input_str: User input starting with / or :
            
        Returns:
            tuple of (SlashCommand or None, remaining args string)
        """
        if not input_str:
            return None, ""
        
        # Determine prefix and strip it
        if input_str.startswith("/"):
            prefix = "/"
            rest = input_str[1:]
        elif input_str.startswith(":"):
            prefix = ":"
            rest = input_str[1:]
        elif input_str.startswith("!"):
            prefix = "!"
            rest = input_str[1:]
        elif input_str.startswith(">"):
            prefix = ">"
            rest = input_str[1:]
        else:
            return None, input_str
        
        # If it's a shell prefix, return a special "shell" command indicator
        if prefix in ("!", ">"):
            return SlashCommand(name="shell", description="Run shell command", handler=lambda x: None), rest

        # Parse command and args
        parts = rest.split(maxsplit=1)
        cmd_name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        # Find command
        command = self._commands.get(cmd_name)
        
        return command, args

    def get_command(self, name: str) -> Optional[SlashCommand]:
        """Get a command by name or alias."""
        return self._commands.get(name.lower())

    def list_commands(self) -> list[SlashCommand]:
        """List all registered commands."""
        # Deduplicate by name (not aliases)
        seen = set()
        unique = []
        for cmd in self._commands.values():
            if cmd.name not in seen:
                seen.add(cmd.name)
                unique.append(cmd)
        return sorted(unique, key=lambda c: c.name)

    def get_commands_by_category(self, category: str) -> list[SlashCommand]:
        """Get commands filtered by category."""
        return [c for c in self.list_commands() if c.category == category]

    def help_text(self, prefix: str = "/") -> str:
        """Generate help text for all commands."""
        lines = ["Available Commands:"]
        
        categories = {}
        for cmd in self.list_commands():
            if cmd.category not in categories:
                categories[cmd.category] = []
            categories[cmd.category].append(cmd)
        
        for category, commands in categories.items():
            lines.append(f"\n[{category.upper()}]")
            for cmd in commands:
                aliases = f" (alias: {', '.join(cmd.aliases)})" if cmd.aliases else ""
                lines.append(f"  {prefix}{cmd.name}{aliases} - {cmd.description}")
        
        return "\n".join(lines)


# Built-in commands
def create_builtin_commands(handlers: dict) -> list[SlashCommand]:
    """Create built-in slash commands."""
    commands = []
    
    # Help command
    commands.append(SlashCommand(
        name="help",
        description="Show available commands",
        handler=handlers.get("help", lambda _: None),
        category="general",
    ))
    
    # Exit commands
    commands.append(SlashCommand(
        name="exit",
        description="Exit the current session",
        handler=handlers.get("exit", lambda _: None),
        aliases=["quit", "q"],
        category="general",
    ))
    
    # Switch commands
    commands.append(SlashCommand(
        name="switch",
        description="Switch provider or model",
        handler=handlers.get("switch", lambda _: None),
        category="session",
    ))
    
    # Clear commands
    commands.append(SlashCommand(
        name="clear",
        description="Clear the screen",
        handler=handlers.get("clear", lambda _: None),
        aliases=["cls"],
        category="session",
    ))
    
    # Mode commands
    commands.append(SlashCommand(
        name="mode",
        description="Switch mode (dev/qe/devops)",
        handler=handlers.get("mode", lambda _: None),
        category="session",
    ))
    
    # Sessions commands
    commands.append(SlashCommand(
        name="sessions",
        description="List session history",
        handler=handlers.get("sessions", lambda _: None),
        category="session",
    ))

    # Fork commands
    commands.append(SlashCommand(
        name="fork",
        description="Fork current session into a new branch",
        handler=handlers.get("fork", lambda _: None),
        aliases=["branch"],
        category="session",
    ))
    
    # Share commands
    commands.append(SlashCommand(
        name="share",
        description="Share current session",
        handler=handlers.get("share", lambda _: None),
        aliases=["export"],
        category="session",
    ))
    
    # A2A commands
    commands.append(SlashCommand(
        name="a2a",
        description="A2A agent commands",
        handler=handlers.get("a2a", lambda _: None),
        category="agents",
    ))
    
    return commands


# Singleton instance
_command_handler: Optional[SlashCommandHandler] = None


def get_command_handler() -> SlashCommandHandler:
    """Get the global command handler."""
    global _command_handler
    if _command_handler is None:
        _command_handler = SlashCommandHandler()
    return _command_handler