"""
Tool Permission System - Control tool execution.

Provides fine-grained control over which tools can execute and how:
- ALLOW: Execute without confirmation
- DENY: Block execution
- ASK: Prompt user for confirmation

Permissions can be configured:
- Per-tool (e.g., "bash": "ask")
- Per-group (e.g., "write": "allow" covers write_file, edit_file, etc.)
- Globally (e.g., default: "ask")

Configuration via superqode.yaml:
```yaml
superqode:
  permissions:
    default: ask
    groups:
      read: allow
      write: ask
      shell: ask
      network: deny
    tools:
      bash: deny
      diagnostics: allow
```
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
import asyncio


class Permission(Enum):
    """Permission levels for tool execution."""

    ALLOW = "allow"  # Execute without asking
    DENY = "deny"  # Block execution
    ASK = "ask"  # Prompt user for confirmation


class ToolGroup(Enum):
    """Groups of related tools."""

    READ = "read"  # read_file, list_directory, grep, glob
    WRITE = "write"  # write_file, edit_file, insert_text, patch, multi_edit
    SHELL = "shell"  # bash
    NETWORK = "network"  # fetch, download
    DIAGNOSTICS = "diagnostics"  # diagnostics
    SEARCH = "search"  # code_search
    AGENT = "agent"  # sub-agent spawning


# Mapping of tools to their groups
TOOL_GROUPS: Dict[str, ToolGroup] = {
    # Read operations
    "read_file": ToolGroup.READ,
    "list_directory": ToolGroup.READ,
    "grep": ToolGroup.READ,
    "glob": ToolGroup.READ,
    # Write operations
    "write_file": ToolGroup.WRITE,
    "edit_file": ToolGroup.WRITE,
    "insert_text": ToolGroup.WRITE,
    "patch": ToolGroup.WRITE,
    "multi_edit": ToolGroup.WRITE,
    # Shell
    "bash": ToolGroup.SHELL,
    # Network
    "fetch": ToolGroup.NETWORK,
    "download": ToolGroup.NETWORK,
    # Diagnostics
    "diagnostics": ToolGroup.DIAGNOSTICS,
    # Search
    "code_search": ToolGroup.SEARCH,
    # Agent
    "agent": ToolGroup.AGENT,
    "sub_agent": ToolGroup.AGENT,
}


@dataclass
class PermissionConfig:
    """Configuration for tool permissions."""

    # Default permission for unconfigured tools
    default: Permission = Permission.ASK

    # Group-level permissions
    groups: Dict[ToolGroup, Permission] = field(default_factory=dict)

    # Tool-specific permissions (override groups)
    tools: Dict[str, Permission] = field(default_factory=dict)

    # Patterns to always allow/deny
    allow_patterns: List[str] = field(default_factory=list)
    deny_patterns: List[str] = field(default_factory=list)

    @classmethod
    def from_yaml_dict(cls, data: Dict[str, Any]) -> "PermissionConfig":
        """Create config from YAML dict."""
        config = cls()

        if not data:
            return config

        # Parse default
        default_str = data.get("default", "ask")
        try:
            config.default = Permission(default_str)
        except ValueError:
            pass

        # Parse groups
        groups_data = data.get("groups", {})
        for group_name, perm_str in groups_data.items():
            try:
                group = ToolGroup(group_name)
                perm = Permission(perm_str)
                config.groups[group] = perm
            except ValueError:
                pass

        # Parse tool-specific
        tools_data = data.get("tools", {})
        for tool_name, perm_str in tools_data.items():
            try:
                perm = Permission(perm_str)
                config.tools[tool_name] = perm
            except ValueError:
                pass

        # Parse patterns
        config.allow_patterns = data.get("allow_patterns", [])
        config.deny_patterns = data.get("deny_patterns", [])

        return config

    def get_permission(self, tool_name: str) -> Permission:
        """Get the effective permission for a tool."""
        # Check tool-specific first
        if tool_name in self.tools:
            return self.tools[tool_name]

        # Check group
        group = TOOL_GROUPS.get(tool_name)
        if group and group in self.groups:
            return self.groups[group]

        # Return default
        return self.default


@dataclass
class PermissionRequest:
    """A request for tool execution permission."""

    tool_name: str
    arguments: Dict[str, Any]
    description: str
    risk_level: str = "medium"  # low, medium, high

    def format_for_user(self) -> str:
        """Format the request for display to user."""
        lines = [
            f"Tool: {self.tool_name}",
            f"Risk: {self.risk_level}",
            "",
            "Arguments:",
        ]

        for key, value in self.arguments.items():
            value_str = str(value)
            if len(value_str) > 100:
                value_str = value_str[:100] + "..."
            lines.append(f"  {key}: {value_str}")

        return "\n".join(lines)


class PermissionManager:
    """
    Manages tool execution permissions.

    Usage:
        manager = PermissionManager(config)

        # Check permission
        perm = manager.check_permission("bash", {"command": "rm -rf /"})

        if perm == Permission.DENY:
            return error
        elif perm == Permission.ASK:
            approved = await manager.request_permission(...)
            if not approved:
                return error

        # Execute tool
    """

    def __init__(
        self,
        config: Optional[PermissionConfig] = None,
        on_permission_request: Optional[Callable[["PermissionRequest"], bool]] = None,
    ):
        self.config = config or PermissionConfig()
        self._on_permission_request = on_permission_request

        # Cache of approved commands (for session)
        self._session_approvals: Set[str] = set()

        # Dangerous command patterns
        self._dangerous_patterns = [
            r"rm\s+(-rf?|--recursive)",
            r"rm\s+-[^-]*r",
            r"sudo\s+",
            r"chmod\s+777",
            r">\s*/dev/",
            r"mkfs\.",
            r"dd\s+if=",
            r":(){ :|:& };:",  # Fork bomb
        ]

    def check_permission(self, tool_name: str, arguments: Dict[str, Any]) -> Permission:
        """
        Check the permission level for a tool call.

        Returns the permission level (ALLOW, DENY, or ASK).
        """
        # Check deny patterns first
        if self._matches_deny_pattern(tool_name, arguments):
            return Permission.DENY

        # Check allow patterns
        if self._matches_allow_pattern(tool_name, arguments):
            return Permission.ALLOW

        # Check for dangerous commands in shell
        if tool_name == "bash":
            command = arguments.get("command", "")
            if self._is_dangerous_command(command):
                return Permission.DENY

        # Get configured permission
        return self.config.get_permission(tool_name)

    def _matches_deny_pattern(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        """Check if the call matches a deny pattern."""
        import re

        for pattern in self.config.deny_patterns:
            # Pattern can be tool:arg_pattern or just arg_pattern
            if ":" in pattern:
                tool_pat, arg_pat = pattern.split(":", 1)
                if tool_name != tool_pat:
                    continue
                for value in arguments.values():
                    if re.search(arg_pat, str(value)):
                        return True
            else:
                for value in arguments.values():
                    if re.search(pattern, str(value)):
                        return True

        return False

    def _matches_allow_pattern(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        """Check if the call matches an allow pattern."""
        import re

        for pattern in self.config.allow_patterns:
            if ":" in pattern:
                tool_pat, arg_pat = pattern.split(":", 1)
                if tool_name != tool_pat:
                    continue
                for value in arguments.values():
                    if re.search(arg_pat, str(value)):
                        return True
            else:
                if tool_name == pattern:
                    return True

        return False

    def _is_dangerous_command(self, command: str) -> bool:
        """Check if a shell command is dangerous."""
        import re

        for pattern in self._dangerous_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return True

        return False

    def get_risk_level(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Assess the risk level of a tool call."""
        # Shell commands
        if tool_name == "bash":
            command = arguments.get("command", "")
            if any(kw in command.lower() for kw in ["rm", "delete", "drop", "truncate"]):
                return "high"
            if any(kw in command.lower() for kw in ["mv", "cp", "chmod", "chown"]):
                return "medium"
            return "low"

        # Write operations
        if tool_name in ["write_file", "edit_file", "patch", "multi_edit"]:
            path = arguments.get("path", "")
            if any(p in path for p in ["/etc", "/usr", "/bin", "/var"]):
                return "high"
            return "medium"

        # Network
        if tool_name in ["fetch", "download"]:
            return "medium"

        # Read operations
        if tool_name in ["read_file", "list_directory", "grep", "glob"]:
            return "low"

        return "medium"

    async def request_permission(
        self, tool_name: str, arguments: Dict[str, Any], description: str = ""
    ) -> bool:
        """
        Request permission from user for a tool call.

        Returns True if approved, False if denied.
        """
        # Check session cache
        cache_key = f"{tool_name}:{hash(str(sorted(arguments.items())))}"
        if cache_key in self._session_approvals:
            return True

        # Create request
        request = PermissionRequest(
            tool_name=tool_name,
            arguments=arguments,
            description=description,
            risk_level=self.get_risk_level(tool_name, arguments),
        )

        # Call handler
        if self._on_permission_request:
            approved = self._on_permission_request(request)
        else:
            # Default: deny if no handler
            approved = False

        # Cache approval
        if approved:
            self._session_approvals.add(cache_key)

        return approved

    def clear_session_approvals(self) -> None:
        """Clear session approval cache."""
        self._session_approvals.clear()


# Singleton instance
_permission_manager: Optional[PermissionManager] = None


def get_permission_manager() -> PermissionManager:
    """Get the global permission manager."""
    global _permission_manager
    if _permission_manager is None:
        _permission_manager = PermissionManager()
    return _permission_manager


def set_permission_manager(manager: PermissionManager) -> None:
    """Set the global permission manager."""
    global _permission_manager
    _permission_manager = manager


def load_permission_config(project_root: Path) -> PermissionConfig:
    """Load permission config from superqode.yaml."""
    import yaml

    yaml_path = project_root / "superqode.yaml"
    if not yaml_path.exists():
        return PermissionConfig()

    try:
        with open(yaml_path) as f:
            data = yaml.safe_load(f)

        perm_data = data.get("superqode", {}).get("permissions", {})

        return PermissionConfig.from_yaml_dict(perm_data)

    except Exception:
        return PermissionConfig()
