"""
SuperQode Command Suggester - Autocompletion for commands.

Optimized for zero-latency typing - returns immediately without blocking.
"""

from typing import Optional
from textual.suggester import Suggester

from .constants import COMMANDS


class CommandSuggester(Suggester):
    """Autocomplete for : commands.

    Performance optimizations:
    - Pre-computed command lists
    - Fast early-exit checks
    - Non-blocking async implementation
    - Minimal processing per keystroke
    """

    def __init__(self):
        super().__init__()
        # Pre-compute lowercase commands for faster matching
        self._commands_lower = tuple(cmd.lower() for cmd in COMMANDS)
        self._commands = tuple(COMMANDS)
        # Pre-filter commands starting with ':' for even faster lookup
        self._colon_commands = tuple(cmd for cmd in COMMANDS if cmd.startswith(":"))
        self._colon_commands_lower = tuple(cmd.lower() for cmd in self._colon_commands)

    async def get_suggestion(self, value: str) -> str | None:
        """Get suggestion for command autocomplete.

        Returns immediately to avoid any blocking or delay.
        Designed for zero-latency typing experience.

        Supports:
        - Basic commands: :help, :clear, etc.
        """
        # Ultra-fast path: not a command (most common case)
        if not value:
            return None

        # Fast path: doesn't start with ':'
        if not value.startswith(":"):
            return None

        value_lower = value.lower()
        if value_lower in self._colon_commands_lower:
            return None
        if value_lower in {":c", ":co", ":con", ":conn", ":conne", ":connec"}:
            return ":connect"

        # Fast matching - use pre-filtered colon commands
        # Find first command that starts with the value
        pairs = sorted(
            zip(self._colon_commands_lower, self._colon_commands),
            key=lambda pair: self._sort_key(value_lower, pair[0]),
        )
        for cmd_lower, command in pairs:
            if cmd_lower.startswith(value_lower) and cmd_lower != value_lower:
                return command

        return None

    @staticmethod
    def _sort_key(value_lower: str, command_lower: str) -> tuple[int, str]:
        priority: dict[str, dict[str, int]] = {
            ":": {
                ":connect": 0,
                ":connect acp": 1,
                ":connect antigravity": 2,
                ":connect grok": 3,
                ":connect byok": 4,
                ":connect local": 5,
                ":exit": 6,
                ":quit": 7,
            },
            ":c": {
                ":connect": 0,
                ":connect acp": 1,
                ":connect antigravity": 2,
                ":connect grok": 3,
                ":connect byok": 4,
                ":connect local": 5,
                ":clear": 20,
            },
            ":co": {
                ":connect": 0,
                ":connect acp": 1,
                ":connect antigravity": 2,
                ":connect grok": 3,
                ":connect byok": 4,
                ":connect local": 5,
            },
            ":q": {
                ":quit": 0,
            },
            ":e": {
                ":exit": 0,
            },
        }
        for prefix, scores in priority.items():
            if value_lower.startswith(prefix):
                return (scores.get(command_lower, 10), command_lower)
        return (10, command_lower)
