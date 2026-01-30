# Fix CWD before any imports that might resolve it (e.g., logfire via acp, litellm)
# This prevents FileNotFoundError when current directory doesn't exist
import os
import sys
import pathlib

try:
    cwd = os.getcwd()
    if not pathlib.Path(cwd).exists():
        # Change to home directory if CWD doesn't exist
        os.chdir(os.path.expanduser("~"))
except (OSError, FileNotFoundError):
    # If getcwd() fails, change to home directory
    try:
        os.chdir(os.path.expanduser("~"))
    except Exception:
        pass  # Last resort - let it fail naturally

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence, Iterable, List, Dict, Any

import click

# Global variables for interactive mode
current_mode: str = "home"  # Start in neutral home state
interactive_modes: dict[str, dict[str, object]] = {}


# Session state management
class SessionContext:
    """Tracks work context for handoff between agents."""

    def __init__(self):
        self.session_id = f"session_{int(time.time())}"
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.current_role = None
        self.previous_role = None
        self.work_description = ""
        self.files_modified = []
        self.files_created = []
        self.tasks_completed = []
        self.tasks_pending = []
        self.quality_issues = []
        self.handoff_history = []
        self.metadata = {}

    def update_work_context(
        self,
        description: str,
        files_modified: List[str] = None,
        files_created: List[str] = None,
        tasks_completed: List[str] = None,
        tasks_pending: List[str] = None,
    ):
        """Update the current work context."""
        self.work_description = description
        self.updated_at = datetime.now()

        if files_modified:
            self.files_modified.extend(files_modified)
        if files_created:
            self.files_created.extend(files_created)
        if tasks_completed:
            self.tasks_completed.extend(tasks_completed)
        if tasks_pending:
            self.tasks_pending.extend(tasks_pending)

    def add_quality_issue(self, issue: str, severity: str = "medium"):
        """Add a quality issue found during review."""
        self.quality_issues.append(
            {
                "issue": issue,
                "severity": severity,
                "timestamp": datetime.now().isoformat(),
                "resolved": False,
            }
        )

    def resolve_quality_issue(self, index: int):
        """Mark a quality issue as resolved."""
        if 0 <= index < len(self.quality_issues):
            self.quality_issues[index]["resolved"] = True
            self.quality_issues[index]["resolved_at"] = datetime.now().isoformat()

    def record_handoff(self, from_role: str, to_role: str, reason: str = ""):
        """Record a handoff event in history."""
        self.handoff_history.append(
            {
                "timestamp": datetime.now().isoformat(),
                "from_role": from_role,
                "to_role": to_role,
                "reason": reason,
                "work_description": self.work_description,
                "quality_issues_count": len([i for i in self.quality_issues if not i["resolved"]]),
            }
        )
        self.previous_role = from_role
        self.current_role = to_role

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for storage."""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "current_role": self.current_role,
            "previous_role": self.previous_role,
            "work_description": self.work_description,
            "files_modified": self.files_modified,
            "files_created": self.files_created,
            "tasks_completed": self.tasks_completed,
            "tasks_pending": self.tasks_pending,
            "quality_issues": self.quality_issues,
            "handoff_history": self.handoff_history,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionContext":
        """Deserialize from dictionary."""
        context = cls()
        context.session_id = data.get("session_id", f"session_{int(time.time())}")
        context.created_at = (
            datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now()
        )
        context.updated_at = (
            datetime.fromisoformat(data["updated_at"]) if "updated_at" in data else datetime.now()
        )
        context.current_role = data.get("current_role")
        context.previous_role = data.get("previous_role")
        context.work_description = data.get("work_description", "")
        context.files_modified = data.get("files_modified", [])
        context.files_created = data.get("files_created", [])
        context.tasks_completed = data.get("tasks_completed", [])
        context.tasks_pending = data.get("tasks_pending", [])
        context.quality_issues = data.get("quality_issues", [])
        context.handoff_history = data.get("handoff_history", [])
        context.metadata = data.get("metadata", {})
        return context

    def save_to_file(self, filepath: Path):
        """Save context to JSON file."""
        with open(filepath, "w") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)

    @classmethod
    def load_from_file(cls, filepath: Path) -> Optional["SessionContext"]:
        """Load context from JSON file."""
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
            return cls.from_dict(data)
        except (FileNotFoundError, json.JSONDecodeError):
            return None


class HandoffWorkflow:
    """Manages workflow transitions between development and QA roles."""

    def __init__(self):
        self.context_dir = Path.home() / ".superqode" / "sessions"
        self.context_dir.mkdir(parents=True, exist_ok=True)

    def initiate_handoff(
        self,
        from_role: str,
        to_role: str,
        context: SessionContext,
        reason: str = "",
        additional_context: str = "",
    ) -> str:
        """Initiate a handoff between roles with context preservation."""
        # Record the handoff
        context.record_handoff(from_role, to_role, reason)

        # Save current context
        context_file = self.context_dir / f"{context.session_id}.json"
        context.save_to_file(context_file)

        # Generate handoff message
        handoff_message = self._generate_handoff_message(
            from_role, to_role, context, reason, additional_context
        )

        return handoff_message

    def _generate_handoff_message(
        self,
        from_role: str,
        to_role: str,
        context: SessionContext,
        reason: str,
        additional_context: str,
    ) -> str:
        """Generate a comprehensive handoff message."""
        message_parts = []

        # Header
        message_parts.append(f"🤝 **Handoff from {from_role} to {to_role}**")
        message_parts.append(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if reason:
            message_parts.append(f"📝 Reason: {reason}")
        message_parts.append("")

        # Work description
        if context.work_description:
            message_parts.append("📋 **Work Completed:**")
            message_parts.append(f"{context.work_description}")
            message_parts.append("")

        # Files changed
        if context.files_modified or context.files_created:
            message_parts.append("📁 **Files Involved:**")
            for file in context.files_created:
                message_parts.append(f"  🆕 {file}")
            for file in context.files_modified:
                message_parts.append(f"  ✏️  {file}")
            message_parts.append("")

        # Tasks
        if context.tasks_completed:
            message_parts.append("✅ **Tasks Completed:**")
            for task in context.tasks_completed:
                message_parts.append(f"  • {task}")
            message_parts.append("")

        if context.tasks_pending:
            message_parts.append("⏳ **Tasks Pending:**")
            for task in context.tasks_pending:
                message_parts.append(f"  • {task}")
            message_parts.append("")

        # Quality issues
        unresolved_issues = [i for i in context.quality_issues if not i["resolved"]]
        if unresolved_issues:
            message_parts.append("⚠️  **Quality Issues Found:**")
            severity_emojis = {"low": "🟢", "medium": "🟡", "high": "🔴", "critical": "💥"}
            for i, issue in enumerate(unresolved_issues):
                emoji = severity_emojis.get(issue["severity"], "🟡")
                message_parts.append(f"  {emoji} {issue['issue']}")
            message_parts.append("")

        # Context for recipient
        role_contexts = {
            "dev.fullstack": "Please review the implementation for code quality, security, and best practices.",
            "qa.api_tester": "Please test the functionality, validate requirements, and identify any issues.",
        }

        if to_role in role_contexts:
            message_parts.append(f"🎯 **Your Role:** {role_contexts[to_role]}")

        # Additional context
        if additional_context:
            message_parts.append("")
            message_parts.append("📎 **Additional Context:**")
            message_parts.append(additional_context)

        return "\n".join(message_parts)

    def get_pending_handoffs(self) -> List[Dict[str, Any]]:
        """Get list of pending handoffs that need attention."""
        pending = []
        for context_file in self.context_dir.glob("*.json"):
            context = SessionContext.load_from_file(context_file)
            if context:
                # Show handoffs that are not yet approved
                if not context.metadata.get("approved", False):
                    pending.append(
                        {
                            "session_id": context.session_id,
                            "current_role": context.current_role,
                            "work_description": context.work_description,
                            "pending_tasks": len(context.tasks_pending),
                            "quality_issues": len(
                                [i for i in context.quality_issues if not i["resolved"]]
                            ),
                            "last_updated": context.updated_at,
                        }
                    )
        return sorted(pending, key=lambda x: x["last_updated"], reverse=True)

    def approve_work(self, session_id: str, approval_notes: str = "") -> bool:
        """Approve work for deployment."""
        context_file = self.context_dir / f"{session_id}.json"
        context = SessionContext.load_from_file(context_file)

        if not context:
            return False

        # Mark all quality issues as resolved
        for issue in context.quality_issues:
            if not issue["resolved"]:
                issue["resolved"] = True
                issue["resolved_at"] = datetime.now().isoformat()
                issue["approved_by"] = context.current_role

        # Clear pending tasks
        context.tasks_pending.clear()

        # Add approval metadata
        context.metadata["approved"] = True
        context.metadata["approved_at"] = datetime.now().isoformat()
        context.metadata["approved_by"] = context.current_role
        context.metadata["approval_notes"] = approval_notes

        # Save updated context
        context.save_to_file(context_file)
        return True


class SessionState:
    def __init__(self):
        self.state = "superqode"  # "superqode" | "agent_connected" | "role_mode"
        self.connected_agent = None  # Agent data when in agent_connected state
        self.agent_role_info = None  # Role info when connected via role
        self.current_context = SessionContext()  # Current work context
        self.handoff_workflow = HandoffWorkflow()  # Handoff management
        self.acp_manager = None  # ACP agent manager for real connections
        self.execution_mode = "acp"  # "acp" or "byok"

    def connect_to_agent(self, agent_data, role_info=None, model=None, execution_mode="acp"):
        """Connect to an agent directly (bypassing roles)

        Args:
            agent_data: Agent information dict
            role_info: Optional role information
            model: Optional model override
            execution_mode: "acp" for coding agent, "byok" for direct LLM
        """
        self.state = "agent_connected"
        self.connected_agent = agent_data
        self.agent_role_info = role_info
        self.selected_model = model  # Store selected model for direct connections
        self.execution_mode = execution_mode  # Track execution mode

    def set_acp_manager(self, manager):
        """Set the active ACP manager for real-time communication"""
        self.acp_manager = manager

    def disconnect_acp_manager(self):
        """Disconnect the ACP manager"""
        if self.acp_manager:
            import asyncio

            asyncio.run(self.acp_manager.disconnect())
            self.acp_manager = None

    def disconnect_agent(self):
        """Disconnect from agent and return to superqode mode"""
        self.state = "superqode"
        self.connected_agent = None
        self.agent_role_info = None
        self.selected_model = None
        self.execution_mode = "acp"  # Reset to default

    def switch_to_role_mode(self, mode):
        """Switch to role-based mode"""
        self.state = "role_mode"
        global current_mode
        current_mode = mode

        # Check for pending handoffs for this role
        pending = self.get_pending_handoffs()
        role_handoffs = [h for h in pending if h["current_role"] == mode]

        if role_handoffs:
            # Automatically resume the most recent handoff for this role
            latest_handoff = role_handoffs[0]  # Already sorted by updated_at desc
            if self.load_context_from_session(latest_handoff["session_id"]):
                print(f"🤝 Resumed pending handoff: {latest_handoff['work_description'][:50]}...")
                return True
        return False

    def is_connected_to_agent(self):
        """Check if currently connected to an agent"""
        return self.state == "agent_connected" and self.connected_agent is not None

    def get_prompt_suffix(self):
        """Get the prompt suffix based on current state"""
        if self.state == "agent_connected":
            agent_name = (
                self.connected_agent.get("short_name", "Unknown")
                if self.connected_agent
                else "Unknown"
            )
            # Show execution mode in prompt
            if self.execution_mode == "acp":
                return f"🔗 ACP • {agent_name.upper()}"
            elif self.execution_mode == "byok":
                return f"⚡ BYOK • {agent_name.upper()}"
            else:
                return f"🔗 {agent_name.upper()}"
        elif self.state == "role_mode":
            return current_mode.replace(".", "/").upper()
        else:  # superqode
            if current_mode == "home":
                return "🏠 HOME"
            else:
                return current_mode.replace(".", "/").upper()

    def get_connection_info(self):
        """Get detailed connection information for display"""
        if not self.is_connected_to_agent():
            return None

        info = {
            "agent": self.connected_agent.get("name", "Unknown")
            if self.connected_agent
            else "Unknown",
            "short_name": self.connected_agent.get("short_name", "unknown")
            if self.connected_agent
            else "unknown",
            "type": self.connected_agent.get("type", "unknown")
            if self.connected_agent
            else "unknown",
            "description": self.connected_agent.get("description", "")
            if self.connected_agent
            else "",
            "execution_mode": self.execution_mode,  # Include execution mode
        }

        # Add role info if connected via role
        if self.agent_role_info:
            info.update(
                {
                    "role": self.agent_role_info.get("role", ""),
                    "provider": self.agent_role_info.get("provider", ""),
                    "model": self.agent_role_info.get("model", ""),
                    "job_description": self.agent_role_info.get("job_description", ""),
                }
            )

        return info

    def update_context(
        self,
        description: str = None,
        files_modified: List[str] = None,
        files_created: List[str] = None,
        tasks_completed: List[str] = None,
        tasks_pending: List[str] = None,
    ):
        """Update the current work context."""
        if description or files_modified or files_created or tasks_completed or tasks_pending:
            self.current_context.update_work_context(
                description or self.current_context.work_description,
                files_modified,
                files_created,
                tasks_completed,
                tasks_pending,
            )

    def add_quality_issue(self, issue: str, severity: str = "medium"):
        """Add a quality issue to the current context."""
        self.current_context.add_quality_issue(issue, severity)

    def resolve_quality_issue(self, index: int):
        """Resolve a quality issue by index."""
        self.current_context.resolve_quality_issue(index)

    def initiate_handoff(self, to_role: str, reason: str = "", additional_context: str = "") -> str:
        """Initiate a handoff to another role."""
        from_role = self.get_current_role_name()

        if not from_role:
            return "Error: Not currently in a role mode for handoff"

        handoff_message = self.handoff_workflow.initiate_handoff(
            from_role, to_role, self.current_context, reason, additional_context
        )

        # Reset context for new role (but keep session ID)
        old_session_id = self.current_context.session_id
        self.current_context = SessionContext()
        self.current_context.session_id = old_session_id
        self.current_context.previous_role = from_role
        self.current_context.current_role = to_role

        return handoff_message

    def approve_work(self, approval_notes: str = "") -> bool:
        """Approve current work for deployment."""
        return self.handoff_workflow.approve_work(self.current_context.session_id, approval_notes)

    def get_pending_handoffs(self) -> List[Dict[str, Any]]:
        """Get list of pending handoffs."""
        return self.handoff_workflow.get_pending_handoffs()

    def get_current_role_name(self) -> Optional[str]:
        """Get the current role name for handoffs."""
        if self.state == "role_mode":
            return current_mode
        elif self.agent_role_info:
            role = self.agent_role_info.get("role", "")
            mode = self.agent_role_info.get("mode", "")
            if mode and role:
                return f"{mode}.{role}"
        return None

    def load_context_from_session(self, session_id: str) -> bool:
        """Load a previous session context."""
        context_file = self.handoff_workflow.context_dir / f"{session_id}.json"
        context = SessionContext.load_from_file(context_file)
        if context:
            self.current_context = context
            return True
        return False


# Global session state instance
session = SessionState()

# Main CLI group
import click


@click.group(invoke_without_command=True)
@click.version_option(version="0.1.5")
@click.option("--tui", is_flag=True, help="Launch the Textual TUI interface")
@click.pass_context
def cli_main(ctx, tui):
    """SuperQode - Developer TUI for multi-agent coding and exploration.

    Interactive interface for orchestrating coding agents across dev, QE, and DevOps.
    For automation and CI, use the `superqe` CLI.
    """

    # If no command is provided, launch Textual app (default behavior)
    if ctx.invoked_subcommand is None or tui:
        import time

        # Show simple loading message before TUI starts
        print("🚀 Starting SuperQode...", end="", flush=True)
        time.sleep(0.5)

        # Clear the loading message before TUI takes over
        print("\r" + " " * 50 + "\r", end="", flush=True)

        # Import and run the TUI
        from superqode.app import run_textual_app

        run_textual_app()
        return


# Configuration management commands - defined before main() for proper registration
@cli_main.group()
def config():
    """Manage SuperQode configuration."""
    pass


@config.command("list-modes")
def config_list_modes():
    """List all configured modes and roles."""
    from superqode.config import load_enabled_modes
    from rich.console import Console
    from rich.table import Table

    console = Console()
    enabled_modes = load_enabled_modes()

    if not enabled_modes:
        console.print(
            "[yellow]No modes configured. Run 'superqode init' to create a repo configuration.[/yellow]"
        )
        return

    table = Table(title="Configured Modes and Roles")
    table.add_column("Mode", style="cyan", no_wrap=True)
    table.add_column("Role", style="magenta", no_wrap=True)
    table.add_column("Agent", style="green")
    table.add_column("Description", style="white")

    for mode_name, mode_config in enabled_modes.items():
        if mode_config.direct_role:
            table.add_row(
                mode_name,
                "(direct)",
                f"{mode_config.direct_role.coding_agent} ({mode_config.direct_role.agent_type})",
                mode_config.direct_role.description,
            )
        elif mode_config.roles:
            for role_name, role_config in mode_config.roles.items():
                table.add_row(
                    mode_name,
                    role_name,
                    f"{role_config.coding_agent} ({role_config.agent_type})",
                    role_config.description,
                )

    console.print(table)


@config.command("init")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing configuration")
def config_init(force):
    """Initialize default SuperQode configuration."""
    from superqode.config import create_default_config, save_config, find_config_file
    from pathlib import Path
    import os

    config_path = find_config_file()
    if config_path and config_path.exists() and not force:
        click.echo(f"Configuration already exists at {config_path}")
        click.echo("Use --force to overwrite")
        return

    if not config_path:
        config_path = Path.cwd() / "superqode.yaml"

    # Create default config
    config = create_default_config()
    save_config(config, config_path)

    click.echo(f"Created default configuration at {config_path}")
    click.echo("Edit the file to customize your development team!")


@config.command("set-model")
@click.argument("mode_role", metavar="MODE.ROLE")
@click.argument("model", metavar="MODEL")
def config_set_model(mode_role, model):
    """Set the model for a specific mode/role."""
    from superqode.config import load_config, save_config, resolve_role

    parts = mode_role.split(".", 1)
    if len(parts) != 2:
        click.echo("Error: MODE.ROLE must be in format 'mode.role' (e.g., 'dev.backend')")
        return

    mode_name, role_name = parts
    config = load_config()

    resolved_role = resolve_role(mode_name, role_name, config)
    if not resolved_role:
        click.echo(f"Error: Role '{mode_role}' not found in configuration")
        return

    if resolved_role.agent_type == "acp":
        click.echo("Error: Cannot set model for ACP agents. ACP agents use their own models.")
        return

    # Update the configuration
    if role_name:
        config.team.modes[mode_name].roles[role_name].model = model
    else:
        config.team.modes[mode_name].model = model

    save_config(config)
    click.echo(f"Updated {mode_role} to use model '{model}'")


@config.command("set-agent")
@click.argument("mode_role", metavar="MODE.ROLE")
@click.argument("agent", metavar="AGENT")
@click.option("--provider", "-p", help="Provider for SuperQode agents")
def config_set_agent(mode_role, agent, provider):
    """Set the agent for a specific mode/role."""
    from superqode.config import load_config, save_config, resolve_role

    parts = mode_role.split(".", 1)
    if len(parts) != 2:
        click.echo("Error: MODE.ROLE must be in format 'mode.role' (e.g., 'dev.backend')")
        return

    mode_name, role_name = parts
    config = load_config()

    resolved_role = resolve_role(mode_name, role_name, config)
    if not resolved_role:
        click.echo(f"Error: Role '{mode_role}' not found in configuration")
        return

    # Update the configuration
    if role_name:
        config.team.modes[mode_name].roles[role_name].coding_agent = agent
        if provider:
            config.team.modes[mode_name].roles[role_name].provider = provider
    else:
        config.team.modes[mode_name].coding_agent = agent
        if provider:
            config.team.modes[mode_name].provider = provider

    save_config(config)
    click.echo(
        f"Updated {mode_role} to use agent '{agent}'{' with provider ' + provider if provider else ''}"
    )


@config.command("enable-role")
@click.argument("mode_role", metavar="MODE.ROLE")
def config_enable_role(mode_role):
    """Enable a disabled role."""
    from superqode.config import load_config, save_config

    parts = mode_role.split(".", 1)
    if len(parts) != 2:
        click.echo("Error: MODE.ROLE must be in format 'mode.role' (e.g., 'dev.mobile')")
        return

    mode_name, role_name = parts
    config = load_config()

    if mode_name not in config.team.modes:
        click.echo(f"Error: Mode '{mode_name}' not found")
        return

    mode_config = config.team.modes[mode_name]
    if role_name not in mode_config.roles:
        click.echo(f"Error: Role '{role_name}' not found in mode '{mode_name}'")
        return

    mode_config.roles[role_name].enabled = True
    save_config(config)
    click.echo(f"Enabled role '{mode_role}'")


@config.command("disable-role")
@click.argument("mode_role", metavar="MODE.ROLE")
def config_disable_role(mode_role):
    """Disable an enabled role."""
    from superqode.config import load_config, save_config

    parts = mode_role.split(".", 1)
    if len(parts) != 2:
        click.echo("Error: MODE.ROLE must be in format 'mode.role' (e.g., 'dev.mobile')")
        return

    mode_name, role_name = parts
    config = load_config()

    if mode_name not in config.team.modes:
        click.echo(f"Error: Mode '{mode_name}' not found")
        return

    mode_config = config.team.modes[mode_name]
    if role_name not in mode_config.roles:
        click.echo(f"Error: Role '{role_name}' not found in mode '{mode_name}'")
        return

    mode_config.roles[role_name].enabled = False
    save_config(config)
    click.echo(f"Disabled role '{mode_role}'")


# TUI command
@cli_main.command("tui")
def tui_command():
    """Launch the Textual TUI interface."""
    from superqode.app import run_textual_app

    run_textual_app()


# Init command (top-level for convenience)
@cli_main.command("init")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing configuration")
def init_command(force):
    """Initialize SuperQode in current directory.

    Creates a superqode.yaml with all team roles enabled
    configured to use OpenCode with free models.
    """
    from superqode.config import find_config_file
    from pathlib import Path
    import os

    config_path = find_config_file()
    if config_path and config_path.exists() and not force:
        click.echo(f"✓ Configuration already exists at {config_path}")
        click.echo("  Use --force to overwrite")
        return

    config_path = Path.cwd() / "superqode.yaml"

    # Copy the full configuration from the template
    template_path = Path(__file__).parent.parent.parent / "superqode-template.yaml"
    if template_path.exists():
        import shutil

        shutil.copy2(template_path, config_path)
        click.echo(f"✓ Created {config_path} with all roles available")
    else:
        # Fallback: create basic config if template not found
        default_config = """# =============================================================================
# SuperQode - Team Configuration
# =============================================================================
# Multi-agent software development team
# Run: superqode (TUI) or superqode --help (CLI)
# =============================================================================

superqode:
  version: "1.0"
  team_name: "Full Stack Development Team"
  description: "AI-powered software development team"

# Default configuration for all roles
default:
  mode: "acp"
  agent: "opencode"
  agent_config:
    provider: "opencode"
    model: "glm-4.7-free"

# =============================================================================
# TEAM ROLES - All enabled by default
# =============================================================================
team:
  # Development roles
  dev:
    description: "Software Development"
    roles:
      fullstack:
        description: "Full-stack development"
        mode: "acp"
        agent: "opencode"
        agent_config:
          provider: "opencode"
          model: "glm-4.7-free"
        enabled: false
        job_description: |
          You are a Senior Full-Stack Developer.
          Write clean, maintainable code. Follow best practices.
          Implement features end-to-end across frontend and backend.

  # QE roles
  qe:
    description: "Quality Engineering"
    roles:
      fullstack:
        description: "Full-stack QE engineer"
        mode: "acp"
        agent: "opencode"
        agent_config:
          provider: "opencode"
          model: "grok-code"
        enabled: false
        job_description: |
          You are a Senior QE Engineer.
          Review code for bugs, security issues, and best practices.
          Write and run tests. Validate requirements are met.

  # DevOps roles
  devops:
    description: "DevOps & Infrastructure"
    roles:
      fullstack:
        description: "Full-stack DevOps engineer"
        mode: "acp"
        agent: "opencode"
        agent_config:
          provider: "opencode"
          model: "gpt-5-nano"
        enabled: false
        job_description: |
          You are a Senior DevOps Engineer.
          Design CI/CD pipelines, containerize apps, manage infrastructure.
          Ensure security, monitoring, and deployment best practices.

# =============================================================================
# Available free models: glm-4.7-free, grok-code, kimi-k2.5-free,
#                        gpt-5-nano, minimax-m2.1-free, big-pickle
# =============================================================================
"""

        with open(config_path, "w") as f:
            f.write(default_config)
        click.echo(f"✓ Created {config_path} with basic roles available")

    click.echo("")
    click.echo("  Quick start:")
    click.echo("    superqode               # Launch TUI")
    click.echo("    superqe roles            # List configured QE roles")
    click.echo("    superqe run .            # Run QE using your superqode.yaml")
    click.echo("")
    click.echo("  Edit superqode.yaml to add or enable roles as needed.")


# ACP Agent commands
@cli_main.group()
def agents():
    """Manage ACP (Agent-Client Protocol) coding agents."""
    pass


@agents.command("list")
@click.option("--store", is_flag=True, help="Show agent store interface")
def agents_list(store):
    """List all available ACP coding agents."""
    from superqode.commands.acp import show_agents_list, show_agents_store

    if store:
        show_agents_store()
    else:
        show_agents_list()


@agents.command("store")
def agents_store():
    """Show the beautiful agent store interface."""
    from superqode.commands.acp import show_agents_store

    show_agents_store()


@agents.command("show")
@click.argument("agent", metavar="AGENT")
def agents_show(agent):
    """Show detailed information about a specific agent."""
    from superqode.commands.acp import show_agent

    show_agent(agent)


@agents.command("connect")
@click.argument("agent", metavar="AGENT")
@click.option("--project-dir", "-d", metavar="DIR", help="Project directory to work in")
def agents_connect(agent, project_dir):
    """Connect to an ACP coding agent. (Deprecated: use 'superqode connect acp' instead)"""
    import warnings

    warnings.warn(
        "'superqode agents connect' is deprecated. Use 'superqode connect acp' instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    from superqode.commands.acp import connect_agent

    exit(connect_agent(agent, project_dir))


@agents.command("install")
@click.argument("agent", metavar="AGENT")
def agents_install(agent):
    """Install an ACP coding agent."""
    from superqode.commands.acp import install_agent_cmd

    exit(install_agent_cmd(agent))


@cli_main.group()
def connect():
    """Connect to models via ACP agents, BYOK providers, or LOCAL providers."""
    pass


@connect.command("acp")
@click.argument("agent", metavar="AGENT")
@click.option("--project-dir", "-d", metavar="DIR", help="Project directory to work in")
def connect_acp(agent, project_dir):
    """Connect to an ACP coding agent."""
    from superqode.commands.acp import connect_agent

    exit(connect_agent(agent, project_dir))


@connect.command("byok")
@click.argument("provider", metavar="PROVIDER", required=False)
@click.argument("model", metavar="MODEL", required=False)
def connect_byok(provider, model):
    """Connect to a BYOK provider/model."""
    from superqode.commands.providers import connect_provider

    exit(connect_provider(provider, model))


@connect.command("local")
@click.argument("provider", metavar="PROVIDER", required=False)
@click.argument("model", metavar="MODEL", required=False)
def connect_local(provider, model):
    """Connect to a local/self-hosted provider/model."""
    from superqode.commands.providers import connect_local_provider

    exit(connect_local_provider(provider, model))


# Alias for backward compatibility
main = cli_main


# Simple toast replacement since UI components were removed
class ToastType:
    SUCCESS = "success"
    ERROR = "error"
    INFO = "info"
    WARNING = "warning"


def show_toast(message: str, toast_type: str) -> None:
    """Simple toast replacement - just print the message."""
    if toast_type == ToastType.SUCCESS:
        _console.print(f"[green]✓ {message}[/green]")
    elif toast_type == ToastType.ERROR:
        _console.print(f"[red]✗ {message}[/red]")
    elif toast_type == ToastType.WARNING:
        _console.print(f"[yellow]⚠️ {message}[/yellow]")
    else:
        _console.print(f"[blue]ℹ️ {message}[/blue]")


from rich.text import Text
from rich.panel import Panel
from rich.live import Live
from rich.spinner import Spinner
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.align import Align
from rich.box import DOUBLE, ROUNDED
from rich.columns import Columns
from rich.table import Table
from rich.markup import escape
import rich.box

from superqode import __version__
from superqode.providers import ProviderManager
from superqode.dialogs import ProviderDialog, ModelDialog, ConnectDialog
from superqode.tui import (
    SuperQodeUI,
    ThinkingSpinner,
    ResponsePanel,
    print_disconnect_message,
    print_exit_message,
)

# Alias for backward compatibility
SuperQodeTUI = SuperQodeUI

# LLM provider management
from superqode.providers.manager import ProviderManager

# Register new BYOK provider and agent commands
from superqode.commands.providers import providers as providers_cmd
from superqode.commands.agents import agents as agents_cmd_new
from superqode.commands.auth import auth as auth_cmd
from superqode.commands.qe import qe as qe_cmd
from superqode.commands.roles import roles as roles_cmd
from superqode.commands.suggestions import suggestions as suggestions_cmd
from superqode.commands.serve import serve as serve_cmd

# Add provider commands (superqode providers list, superqode providers show, etc.)
cli_main.add_command(providers_cmd, name="providers")

# Add auth commands (superqode auth info, superqode auth check, etc.)
cli_main.add_command(auth_cmd, name="auth")

# Add QE commands (superqode qe ...)
cli_main.add_command(qe_cmd, name="qe")

# Add roles commands (superqode roles list, superqode roles info, etc.)
cli_main.add_command(roles_cmd, name="roles")

# Add suggestions commands (superqode suggestions list, superqode suggestions apply, etc.)
cli_main.add_command(suggestions_cmd, name="suggestions")

# Add Server commands (superqode serve lsp, superqode serve web, etc.)
cli_main.add_command(serve_cmd, name="serve")

# Note: agents command already exists, so we add the new one with a different approach
# The existing agents command handles ACP agents, we'll enhance it


if __name__ == "__main__":
    """Entry point for the SuperQode CLI."""
    cli_main()
