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

from superqode import __version__

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


class SuperQodeGroup(click.Group):
    """Click group that allows headless prompts where subcommands normally go."""

    def resolve_command(self, ctx, args):
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            if args and (ctx.params.get("print_mode") or ctx.params.get("output_mode") == "json"):
                ctx.params["_headless_messages"] = tuple(args)
                return "__headless__", click.Command("__headless__", hidden=True), []
            raise


@click.group(
    cls=SuperQodeGroup,
    invoke_without_command=True,
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.version_option(version=__version__)
@click.option("--tui", is_flag=True, help="Launch the Textual TUI interface")
@click.option("--print", "print_mode", "-p", is_flag=True, help="Run once and print response")
@click.option(
    "--mode",
    "output_mode",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Headless output mode",
)
@click.option("--profile", default="build", help="Harness profile: build, plan, review, qe")
@click.option("--plan", "plan_only", is_flag=True, help="Run headless prompt in plan-only mode")
@click.option("--provider", envvar="SUPERQODE_PROVIDER", default="openai", help="Model provider")
@click.option(
    "--model", "model_name", envvar="SUPERQODE_MODEL", default="gpt-5.4", help="Model name"
)
@click.option("--resume", help="Resume a stored session by id or unique prefix")
@click.option("--fork", "fork_from", help="Fork a stored session by id or unique prefix")
@click.option(
    "--sandbox",
    "sandbox_backend",
    default="local",
    type=click.Choice(
        [
            "local",
            "read-only",
            "no-shell",
            "git-worktree",
            "docker",
            "e2b",
            "daytona",
            "modal",
            "vercel",
            "runloop",
            "agentcore",
            "langsmith",
            "remote",
        ]
    ),
    help="Sandbox backend capability profile",
)
@click.option(
    "--changes",
    type=click.Choice(["summary", "files", "diff", "none"]),
    default="summary",
    show_default=True,
    help="How to show workspace changes after headless coding tasks",
)
@click.pass_context
def cli_main(
    ctx,
    tui,
    print_mode,
    output_mode,
    profile,
    plan_only,
    provider,
    model_name,
    resume,
    fork_from,
    sandbox_backend,
    changes,
    _headless_messages=None,
):
    """SuperQode - coding agent harness for developer workflows.

    Use the TUI for interactive coding work or headless mode for one-shot tasks.
    """

    messages = tuple(_headless_messages or ()) or tuple(ctx.args)
    if plan_only:
        profile = "plan"
    headless_requested = (
        print_mode or output_mode == "json" or bool(messages) or resume or fork_from
    )

    # If no command is provided, launch Textual app (default behavior)
    if ctx.invoked_subcommand is None or tui or messages:
        if headless_requested and not tui:
            import asyncio
            import sys

            from superqode.headless import response_to_json, run_headless
            from superqode.workspace.change_summary import (
                capture_workspace_changes,
                render_change_summary,
                summarize_workspace_changes,
            )

            prompt_parts = [" ".join(messages).strip()]
            if not sys.stdin.isatty():
                stdin_text = sys.stdin.read().strip()
                if stdin_text:
                    prompt_parts.insert(0, stdin_text)

            prompt = "\n\n".join(part for part in prompt_parts if part)
            if not prompt:
                raise click.UsageError("Headless mode requires a prompt or piped stdin.")

            change_baseline = capture_workspace_changes(Path.cwd())
            try:
                response = asyncio.run(
                    run_headless(
                        prompt=prompt,
                        provider=provider,
                        model=model_name,
                        profile_name=profile,
                        session_id=resume,
                        fork_from=fork_from,
                        sandbox_backend=sandbox_backend,
                    )
                )
            except Exception as e:
                if output_mode == "json":
                    click.echo(
                        json.dumps(
                            {
                                "type": "superqode.error",
                                "profile": profile,
                                "provider": provider,
                                "model": model_name,
                                "error": str(e),
                                "success": False,
                            }
                        )
                    )
                else:
                    click.echo(f"Error: {e}", err=True)
                ctx.exit(1)

            change_summary = summarize_workspace_changes(
                Path.cwd(),
                before=change_baseline,
                include_diff=changes == "diff",
            )
            if output_mode == "json":
                click.echo(
                    response_to_json(
                        response,
                        provider,
                        model_name,
                        profile,
                        change_summary=change_summary.to_dict(),
                    )
                )
            else:
                click.echo(response.content)
                rendered_changes = render_change_summary(change_summary, changes)
                if rendered_changes:
                    click.echo()
                    click.echo(rendered_changes)
            ctx.exit(0 if response.stopped_reason == "complete" and not response.error else 1)

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


@cli_main.command("doctor")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def doctor(json_output):
    """Check basic SuperQode developer setup."""
    from superqode.headless import list_sessions
    from superqode.providers.recommendations import provider_doctor_cards, recommend_models

    provider_cards = provider_doctor_cards(["ds4", "ollama", "openai", "anthropic", "google"])
    ready_providers = [card["provider"] for card in provider_cards if card["configured"]]
    sessions = list_sessions(limit=5)
    recommendations = recommend_models("coding", limit=3)
    payload = {
        "version": __version__,
        "cwd": str(Path.cwd()),
        "ready": bool(ready_providers),
        "ready_providers": ready_providers,
        "providers": provider_cards,
        "recent_sessions": [
            {
                "session_id": session.session_id,
                "provider": session.provider,
                "model": session.model,
                "message_count": session.message_count,
                "updated_at": session.updated_at,
            }
            for session in sessions
        ],
        "recommended_models": [item.to_dict() for item in recommendations],
        "next_steps": [
            "superqode",
            "superqode providers recommend coding",
            "superqode -p 'summarize this repo'",
        ],
    }
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return

    click.echo(f"SuperQode {__version__}")
    click.echo(f"CWD: {payload['cwd']}")
    if ready_providers:
        click.echo(f"Ready providers: {', '.join(ready_providers)}")
    else:
        click.echo("Ready providers: none")
        missing = [
            f"{card['provider']} ({card['setup_hint']})"
            for card in provider_cards
            if not card["configured"]
        ]
        if missing:
            click.echo(f"Setup: {', '.join(missing[:3])}")
    if recommendations:
        top = recommendations[0]
        click.echo(f"Suggested coding model: {top.provider}/{top.model}")
    click.echo("Next: run `superqode` for the TUI or `superqode -p 'summarize this repo'`.")


# Configuration management commands - defined before main() for proper registration
@cli_main.group()
def config():
    """Manage SuperQode configuration."""
    pass


@cli_main.group()
def sessions():
    """Manage stored SuperQode coding sessions."""
    pass


@sessions.command("list")
@click.option("--limit", default=20, type=int, help="Maximum sessions to show")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def sessions_list(limit, json_output):
    """List stored sessions."""
    from superqode.headless import list_sessions

    items = list_sessions(limit=limit)
    if json_output:
        click.echo(
            json.dumps(
                [
                    {
                        "session_id": item.session_id,
                        "created_at": item.created_at,
                        "updated_at": item.updated_at,
                        "provider": item.provider,
                        "model": item.model,
                        "message_count": item.message_count,
                    }
                    for item in items
                ]
            )
        )
        return

    if not items:
        click.echo("No sessions found.")
        return

    for item in items:
        click.echo(
            f"{item.session_id}  {item.provider or '-'}  {item.model or '-'}  "
            f"{item.message_count} messages  {item.updated_at}"
        )


@sessions.command("tree")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def sessions_tree(json_output):
    """Show session fork lineage."""
    from superqode.headless import session_tree

    tree = session_tree()
    if json_output:
        click.echo(json.dumps(tree, indent=2))
        return

    def print_node(node, indent=0):
        click.echo(
            "  " * indent
            + f"{node['session_id']}  {node['model'] or '-'}  {node['message_count']} messages"
        )
        for child in node["children"]:
            print_node(child, indent + 1)

    if not tree:
        click.echo("No sessions found.")
        return
    for node in tree:
        print_node(node)


@sessions.command("show")
@click.argument("session_id")
@click.option("--format", "fmt", type=click.Choice(["markdown", "json"]), default="markdown")
def sessions_show(session_id, fmt):
    """Show a stored session."""
    from superqode.headless import export_session

    click.echo(export_session(session_id, fmt=fmt), nl=False)


@sessions.command("export")
@click.argument("session_id")
@click.option("--format", "fmt", type=click.Choice(["markdown", "json"]), default="markdown")
@click.option("--output", "-o", type=click.Path(), help="Write export to file")
def sessions_export(session_id, fmt, output):
    """Export a stored session."""
    from pathlib import Path
    from superqode.headless import export_session

    content = export_session(session_id, fmt=fmt)
    if output:
        Path(output).write_text(content, encoding="utf-8")
        click.echo(f"Exported session to {output}")
    else:
        click.echo(content, nl=False)


@sessions.command("delete")
@click.argument("session_id")
def sessions_delete(session_id):
    """Delete a stored session."""
    from superqode.headless import resolve_session_id
    from superqode.agent.session_manager import SessionManager

    resolved = resolve_session_id(session_id)
    SessionManager(storage_dir=".superqode/sessions").delete_session(resolved)
    click.echo(f"Deleted session {resolved}")


@cli_main.group()
def plugins():
    """Inspect SuperQode plugin manifests."""
    pass


@plugins.command("list")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def plugins_list(json_output):
    """List discoverable plugins."""
    from superqode.plugins import load_plugins

    loaded = load_plugins(Path.cwd())
    if json_output:
        click.echo(json.dumps([plugin.to_dict() for plugin in loaded]))
        return

    if not loaded:
        click.echo("No plugins found.")
        return

    for plugin in loaded:
        click.echo(f"{plugin.id}  {plugin.version}  {plugin.name}")


@plugins.command("show")
@click.argument("plugin_id")
def plugins_show(plugin_id):
    """Show one plugin manifest."""
    from superqode.plugins import load_plugins

    for plugin in load_plugins(Path.cwd()):
        if plugin.id == plugin_id or plugin.name == plugin_id:
            click.echo(json.dumps(plugin.to_dict(), indent=2))
            return
    raise click.ClickException(f"Plugin not found: {plugin_id}")


@plugins.command("validate")
@click.argument("path", type=click.Path(exists=True))
def plugins_validate(path):
    """Validate a plugin manifest file."""
    from superqode.plugins import validate_plugin_manifest

    issues = validate_plugin_manifest(path)
    if issues:
        for issue in issues:
            click.echo(f"Error: {issue}")
        raise click.ClickException("Plugin manifest is invalid")
    click.echo("Plugin manifest is valid.")


@cli_main.group()
def sandbox():
    """Inspect and run sandbox execution backends."""
    pass


@sandbox.command("doctor")
@click.argument("backend", required=False)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def sandbox_doctor(backend, json_output):
    """Show setup status for sandbox providers."""
    from superqode.sandbox import get_sandbox_capabilities, sandbox_provider_status

    backends = (
        [backend]
        if backend
        else [
            "docker",
            "e2b",
            "daytona",
            "modal",
            "vercel",
            "runloop",
            "agentcore",
            "langsmith",
        ]
    )
    payload = []
    for name in backends:
        status = sandbox_provider_status(name).to_dict()
        try:
            caps = get_sandbox_capabilities(name)
            status["capabilities"] = {
                "can_read": caps.can_read,
                "can_write": caps.can_write,
                "can_shell": caps.can_shell,
                "can_network": caps.can_network,
                "description": caps.description,
            }
        except ValueError:
            status["capabilities"] = None
        payload.append(status)

    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return

    for item in payload:
        marker = "ready" if item["available"] else "missing"
        click.echo(f"{item['backend']}  {marker}  {item['detail']}")


@sandbox.command("run", context_settings={"ignore_unknown_options": True})
@click.argument(
    "backend",
    type=click.Choice(
        ["docker", "e2b", "daytona", "modal", "vercel", "runloop", "agentcore", "langsmith"]
    ),
)
@click.argument("command", nargs=-1, required=True)
@click.option("--cwd", type=click.Path(file_okay=False, path_type=Path), default=Path.cwd)
@click.option("--timeout", type=int, default=300, show_default=True)
@click.option("--image", default="python:3.12-slim", show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def sandbox_run(backend, command, cwd, timeout, image, json_output):
    """Run a command in Docker or a remote sandbox provider."""
    from superqode.sandbox import run_in_sandbox

    shell_command = " ".join(command).strip()
    if not shell_command:
        raise click.UsageError("sandbox run requires a command")

    try:
        result = run_in_sandbox(backend, shell_command, cwd, timeout=timeout, image=image)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        click.echo(json.dumps(result.to_dict(), indent=2))
        raise SystemExit(result.exit_code)

    if result.stdout:
        click.echo(result.stdout, nl=not result.stdout.endswith("\n"))
    if result.stderr:
        click.echo(result.stderr, err=True, nl=not result.stderr.endswith("\n"))
    raise SystemExit(result.exit_code)


@cli_main.group()
def benchmark():
    """Run coding harness benchmarks."""
    pass


@benchmark.command("run")
@click.argument("tasks_file", type=click.Path(exists=True))
@click.option(
    "--target",
    "targets",
    multiple=True,
    help="Target to run: superqode, opencode, pi, deepagents",
)
def benchmark_run(tasks_file, targets):
    """Run benchmark tasks against harness CLIs."""
    from superqode.benchmarks import DEFAULT_TARGETS, load_tasks, run_benchmark_suite

    selected = [DEFAULT_TARGETS[name] for name in targets] if targets else None
    results = run_benchmark_suite(load_tasks(tasks_file), selected)
    click.echo(json.dumps({"results": results}, indent=2))


@cli_main.group()
def profiles():
    """List built-in SuperQode harness profiles."""
    pass


@profiles.command("list")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def profiles_list(json_output):
    """List harness profiles."""
    from superqode.headless import get_harness_profiles

    items = get_harness_profiles()
    payload = [
        {
            "name": profile.name,
            "description": profile.description,
            "system_level": profile.system_level.value,
            "tools": profile.tools,
        }
        for profile in items.values()
    ]
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    for item in payload:
        click.echo(f"{item['name']}  {item['system_level']}  {item['description']}")


@cli_main.group()
def tools():
    """Inspect coding harness tools."""
    pass


@tools.command("list")
@click.option("--profile", default="build", help="Harness profile to inspect")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def tools_list(profile, json_output):
    """List tools available to a harness profile."""
    from superqode.headless import create_tool_registry, get_harness_profiles
    from superqode.tools.permissions import TOOL_GROUPS

    profiles_map = get_harness_profiles()
    if profile not in profiles_map:
        raise click.ClickException(f"Unknown profile: {profile}")

    harness_profile = profiles_map[profile]
    registry = create_tool_registry(harness_profile)
    payload = []
    for tool in sorted(registry.list(), key=lambda item: item.name):
        group = TOOL_GROUPS.get(tool.name)
        permission = harness_profile.permissions.get_permission(tool.name).value
        payload.append(
            {
                "name": tool.name,
                "group": group.value if group else "other",
                "permission": permission,
                "description": tool.description,
            }
        )

    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return

    for item in payload:
        click.echo(f"{item['name']}  {item['group']}  {item['permission']}  {item['description']}")


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
    model: "minimax-m2.5-free"

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
          model: "minimax-m2.5-free"
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
          model: "nemotron-3-super-free"
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
# Available free models: big-pickle, minimax-m2.5-free, nemotron-3-super-free,
#                        gpt-5-nano, hy3-preview-free, ling-2.6-flash-free,
#                        trinity-large-preview-free, qwen3.6-plus-free
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


@agents.command("doctor")
@click.argument("agent", metavar="AGENT", required=False)
@click.option("--live", is_flag=True, help="Start the ACP agent and check protocol support")
@click.option("--timeout", default=10.0, type=float, help="Live protocol check timeout")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def agents_doctor(agent, live, timeout, json_output):
    """Check ACP agent install, setup, and optional protocol health."""
    import asyncio

    from superqode.acp.doctor import acp_doctor

    results = asyncio.run(acp_doctor(agent, live=live, timeout=timeout))
    if agent and not results:
        raise click.ClickException(f"ACP agent not found: {agent}")

    if json_output:
        click.echo(json.dumps(results, indent=2))
        return

    for result in results:
        status = "installed" if result["installed"] else "missing"
        click.echo(f"{result['short_name']} ({result['name']}): {status}")
        if result.get("command"):
            click.echo(f"  command: {result['command']}")
        if result.get("missing_env_vars"):
            click.echo(f"  env: set one of {', '.join(result['missing_env_vars'])}")
        if not result["installed"] and result.get("install_command"):
            click.echo(f"  install: {result['install_command']}")
        live_result = result.get("live")
        if live_result:
            started = "yes" if live_result.get("started") else "no"
            click.echo(f"  protocol started: {started}")
            if live_result.get("session"):
                click.echo("  session: yes")
            if live_result.get("models"):
                click.echo(f"  models: {len(live_result['models'])}")
            if live_result.get("modes"):
                click.echo(f"  modes: {len(live_result['modes'])}")
            if live_result.get("error"):
                click.echo(f"  error: {live_result['error']}")


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


@providers_cmd.command("models")
@click.argument("provider_id")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def providers_models(provider_id, json_output):
    """List example models for a provider."""
    from superqode.providers.registry import PROVIDERS

    provider_def = PROVIDERS.get(provider_id)
    if not provider_def:
        raise click.ClickException(f"Provider not found: {provider_id}")

    payload = {
        "provider": provider_id,
        "name": provider_def.name,
        "models": provider_def.example_models,
        "recommended_models": getattr(provider_def, "recommended_models", []),
        "env_vars": provider_def.env_vars,
    }
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"{provider_def.name} ({provider_id})")
    for model in provider_def.example_models:
        click.echo(f"  {model}")


@providers_cmd.command("doctor")
@click.argument("provider_id", required=False)
@click.option("--live", is_flag=True, help="Run live local-provider health checks")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def providers_doctor(provider_id, live, json_output):
    """Show provider configuration status and setup hints."""
    import asyncio
    import os
    from superqode.providers.registry import PROVIDERS, ProviderCategory

    selected = {provider_id: PROVIDERS[provider_id]} if provider_id else PROVIDERS
    if provider_id and provider_id not in PROVIDERS:
        raise click.ClickException(f"Provider not found: {provider_id}")
    if live and not provider_id:
        raise click.ClickException(
            "Use --live with a specific local provider, e.g. providers doctor ollama --live"
        )

    results = []
    for pid, provider_def in selected.items():
        configured_vars = [var for var in provider_def.env_vars if os.environ.get(var)]
        item = {
            "provider": pid,
            "name": provider_def.name,
            "configured": bool(configured_vars) or not provider_def.env_vars,
            "configured_env_vars": configured_vars,
            "required_env_vars": provider_def.env_vars,
            "base_url_env": provider_def.base_url_env,
            "example_models": provider_def.example_models[:5],
            "docs_url": provider_def.docs_url,
        }
        if live:
            if provider_def.category != ProviderCategory.LOCAL:
                raise click.ClickException("--live is only supported for local providers")
            from superqode.providers.local.smoke import smoke_local_provider

            item["live"] = asyncio.run(smoke_local_provider(pid, tool_test=False))
        results.append(item)

    if json_output:
        click.echo(json.dumps(results, indent=2))
        return

    for result in results:
        status = "ok" if result["configured"] else "missing"
        click.echo(f"{result['provider']} ({result['name']}): {status}")
        if not result["configured"] and result["required_env_vars"]:
            click.echo(f"  set one of: {', '.join(result['required_env_vars'])}")
        if result["example_models"]:
            click.echo(f"  models: {', '.join(result['example_models'])}")
        if live and result.get("live"):
            live_result = result["live"]
            click.echo(f"  server: {'reachable' if live_result['available'] else 'not reachable'}")
            click.echo(f"  smoke client: {'yes' if live_result.get('supported') else 'no'}")
            if live_result.get("host"):
                click.echo(f"  host: {live_result['host']}")


@providers_cmd.command("recommend")
@click.argument("task", required=False, default="coding")
@click.option("--limit", default=8, type=int, help="Maximum recommendations")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def providers_recommend(task, limit, json_output):
    """Recommend models by task with cost/context/tool labels."""
    from superqode.providers.recommendations import recommend_models

    recommendations = recommend_models(task, limit=limit)
    if json_output:
        click.echo(json.dumps([item.to_dict() for item in recommendations], indent=2))
        return
    for item in recommendations:
        setup = "ready" if item.setup.configured else item.setup.setup_hint
        click.echo(
            f"{item.provider}/{item.model}  score={item.score}  "
            f"price={item.price}  ctx={item.context}  tools={item.tool_support}  {setup}"
        )
        click.echo(f"  {item.reason}")


@providers_cmd.command("guide")
@click.argument("provider_id", required=False)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def providers_guide(provider_id, json_output):
    """Show provider setup and model quality labels."""
    from superqode.providers.recommendations import provider_doctor_cards
    from superqode.providers.registry import PROVIDERS

    if provider_id and provider_id not in PROVIDERS:
        raise click.ClickException(f"Provider not found: {provider_id}")
    cards = provider_doctor_cards([provider_id] if provider_id else None)
    if json_output:
        click.echo(json.dumps(cards, indent=2))
        return
    for card in cards:
        status = "ready" if card["configured"] else "missing"
        labels = ", ".join(card["labels"]) or "-"
        click.echo(f"{card['provider']} ({card['name']}): {status}  [{labels}]")
        click.echo(f"  setup: {card['setup_hint']}")
        for model in card["models"][:3]:
            click.echo(
                f"  - {model['model']}  price={model['price']}  "
                f"ctx={model['context']}  tools={model['tool_support']}"
            )


@providers_cmd.command("smoke")
@click.argument("provider_id")
@click.option("--model", help="Model to check")
@click.option("--run", "run_prompt", is_flag=True, help="Run a real local completion")
@click.option("--prompt", default="Reply with: ok", help="Prompt for --run")
@click.option(
    "--no-tool-test",
    is_flag=True,
    help="Skip the provider-specific tool-calling probe",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def providers_smoke(provider_id, model, run_prompt, prompt, no_tool_test, json_output):
    """Run an opt-in local provider smoke check."""
    import asyncio

    from superqode.providers.local.smoke import (
        all_local_provider_ids,
        smoke_local_provider,
        supported_local_smoke_providers,
    )

    if provider_id not in all_local_provider_ids():
        supported = ", ".join(all_local_provider_ids())
        raise click.ClickException(
            f"Local provider not found: {provider_id}. Choose one of: {supported}"
        )

    payload = asyncio.run(
        smoke_local_provider(
            provider_id,
            model,
            run_prompt=run_prompt,
            prompt=prompt,
            tool_test=not no_tool_test,
        )
    )
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return

    click.echo(f"{payload['name']} ({payload['provider']})")
    if payload.get("host"):
        click.echo(f"  host: {payload['host']}")
    click.echo(f"  registered: {'yes' if payload['registered'] else 'no'}")
    click.echo(f"  smoke client: {'yes' if payload.get('supported') else 'no'}")
    if not payload.get("supported"):
        supported = ", ".join(supported_local_smoke_providers())
        click.echo(f"  supported smoke providers: {supported}")
        if payload.get("setup_hint"):
            click.echo(f"  setup: {payload['setup_hint']}")
        if payload.get("error"):
            click.echo(f"  error: {payload['error']}")
        return
    click.echo(f"  server: {'reachable' if payload['available'] else 'not reachable'}")
    click.echo(f"  model: {payload['model'] or '-'}")
    click.echo(f"  models: {', '.join(payload['models']) or '-'}")
    if payload.get("running_models"):
        click.echo(f"  running: {', '.join(payload['running_models'])}")
    click.echo(f"  tools: {'yes' if payload['tool_support'] else 'no'}")
    tool_result = payload.get("tool_result") or {}
    if tool_result.get("notes"):
        click.echo(f"  tool notes: {tool_result['notes']}")
    if tool_result.get("error"):
        click.echo(f"  tool error: {tool_result['error']}")
    if payload["completion_ran"]:
        status = "ok" if payload["completion_ok"] else "failed"
        click.echo(f"  completion: {status}")
        if payload.get("response_preview"):
            click.echo(f"  response: {payload['response_preview']}")
    if payload.get("error"):
        click.echo(f"  error: {payload['error']}")
    if payload.get("status_error") and not payload.get("available"):
        click.echo(f"  status: {payload['status_error']}")
    if not run_prompt:
        click.echo(
            f"  run a real local completion with: superqode providers smoke {provider_id} --run"
        )


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
