"""
SuperQode Command Suggester - Autocompletion for commands.

Optimized for zero-latency typing - returns immediately without blocking.
"""

from typing import List, Tuple, Optional
from textual.suggester import Suggester

from .constants import COMMANDS


def get_role_suggestions(mode: str, partial_role: str) -> List[Tuple[str, bool, str]]:
    """Get role suggestions for a mode matching partial_role.

    Args:
        mode: Mode name ('qe', 'dev', 'devops')
        partial_role: Partial role name to match (empty string returns all roles)

    Returns:
        List of (role_name, enabled, description) tuples, sorted by enabled first, then alphabetically
    """
    try:
        from superqode.config import load_config

        config = load_config()
        mode_config = config.team.modes.get(mode)
        if not mode_config or not mode_config.roles:
            return []

        partial_lower = partial_role.lower()
        suggestions = []

        for role_name, role_config in mode_config.roles.items():
            # Use prefix match for more predictable autocomplete behavior
            # Empty partial_role matches all roles
            if not partial_lower or role_name.lower().startswith(partial_lower):
                enabled = role_config.enabled
                desc = role_config.description or ""
                suggestions.append((role_name, enabled, desc))

        # Sort: enabled first, then alphabetically
        suggestions.sort(key=lambda x: (not x[1], x[0]))
        return suggestions
    except Exception:
        return []


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
        - Mode commands with roles: :qe <role>, :dev <role>, :devops <role>
        """
        # Ultra-fast path: not a command (most common case)
        if not value:
            return None

        # Fast path: doesn't start with ':'
        if not value.startswith(":"):
            return None

        # Fast path: too short (just ':')
        if len(value) < 2:
            return None

        value_lower = value.lower()

        # Check for mode commands with role patterns: :qe <role>, :dev <role>, :devops <role>
        mode_patterns = [("qe", ":qe"), ("dev", ":dev"), ("devops", ":devops")]
        for mode_name, mode_prefix in mode_patterns:
            if value_lower == mode_prefix or value_lower.startswith(mode_prefix + " "):
                # Determine the prefix with space
                prefix_with_space = mode_prefix + " "
                # Extract partial role name (everything after the mode prefix and space)
                if len(value) > len(prefix_with_space):
                    partial_role = value[len(prefix_with_space) :]
                else:
                    # User typed just ":qe" or ":qe " - return first enabled role
                    partial_role = ""

                # Get role suggestions
                try:
                    suggestions = get_role_suggestions(mode_name, partial_role)
                    if suggestions:
                        role_name, enabled, _ = suggestions[0]
                        status = "" if enabled else " [DISABLED]"
                        # Keep the space in prefix - don't strip it!
                        return f"{prefix_with_space}{role_name}{status}"
                except Exception:
                    # If role suggestions fail, fall through to normal command matching
                    pass
                # No suggestions found - let normal command matching continue
                break

        # Fast matching - use pre-filtered colon commands
        # Find first command that starts with the value
        for i, cmd_lower in enumerate(self._colon_commands_lower):
            if cmd_lower.startswith(value_lower) and cmd_lower != value_lower:
                return self._colon_commands[i]

        return None
