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

HARNESS_TEMPLATE_CHOICES = (
    "coding",
    "no-tool",
    "gemma4-coding",
    "gemma4-no-tool",
    "ds4-coding",
    "ds4-fast-local",
)

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
@click.option(
    "--harness",
    "harness_path",
    envvar="SUPERQODE_HARNESS",
    default=None,
    type=click.Path(exists=True),
    help="HarnessSpec YAML/JSON for the interactive TUI",
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
@click.option(
    "--verbose",
    "-v",
    "verbose_logs",
    is_flag=True,
    envvar="SUPERQODE_VERBOSE",
    help="Show full tool outputs (equivalent to SUPERQODE_LOG_VERBOSITY=verbose)",
)
@click.option(
    "--quiet",
    "-q",
    "quiet_logs",
    is_flag=True,
    envvar="SUPERQODE_QUIET",
    help="Show only tool status (equivalent to SUPERQODE_LOG_VERBOSITY=minimal)",
)
@click.option(
    "--runtime",
    "runtime_name",
    envvar="SUPERQODE_RUNTIME",
    default=None,
    type=click.Choice(["builtin", "adk", "openai-agents"]),
    help="Agent runtime backend (default: builtin). adk and openai-agents require optional extras.",
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
    harness_path,
    resume,
    fork_from,
    sandbox_backend,
    changes,
    verbose_logs,
    quiet_logs,
    runtime_name,
    _headless_messages=None,
):
    # Tool-output verbosity propagates through env so the TUI widget
    # picks it up at construction time without us threading another
    # argument through every Textual subclass. The env-first design
    # also means downstream subprocesses (e.g. ACP clients we may
    # later spawn) inherit it.
    import os as _os

    if verbose_logs and not quiet_logs:
        _os.environ["SUPERQODE_LOG_VERBOSITY"] = "verbose"
    elif quiet_logs and not verbose_logs:
        _os.environ["SUPERQODE_LOG_VERBOSITY"] = "minimal"

    # Runtime precedence: CLI flag > superqode.yaml > env > default. We resolve
    # the YAML value here (best-effort: ignore failures so a broken config
    # doesn't crash startup) and set the env var so downstream code that uses
    # resolve_runtime_name() picks it up.
    yaml_runtime: Optional[str] = None
    if not runtime_name:
        try:
            from superqode.config.loader import load_config

            yaml_runtime = load_config().superqode.runtime
        except Exception:  # noqa: BLE001 — startup must remain resilient
            yaml_runtime = None
    effective_runtime = runtime_name or yaml_runtime
    if effective_runtime:
        _os.environ["SUPERQODE_RUNTIME"] = effective_runtime
    if harness_path:
        _os.environ["SUPERQODE_HARNESS"] = str(harness_path)
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
                        runtime=effective_runtime,
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
def harness():
    """Create, validate, and run SuperQode harness specs."""
    pass


@harness.command("list-templates")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_list_templates(json_output):
    """List built-in harness templates."""
    from superqode.harness import BUILTIN_TEMPLATES, get_harness_template, harness_spec_to_dict

    rows = []
    for name in sorted(BUILTIN_TEMPLATES):
        if "_" in name:
            continue
        spec = get_harness_template(name)
        rows.append(
            {
                "name": name,
                "flavor": spec.flavor.value,
                "runtime": spec.runtime.backend,
                "description": spec.description,
            }
        )

    if json_output:
        payload = [
            {**row, "spec": harness_spec_to_dict(get_harness_template(row["name"]))} for row in rows
        ]
        click.echo(json.dumps(payload, indent=2))
        return

    for row in rows:
        click.echo(f"{row['name']}  {row['flavor']}  {row['runtime']}  {row['description']}")


@harness.command("list-backends")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_list_backends(json_output):
    """List available harness runtime backends."""
    from superqode.harness import backend_capabilities, known_harness_backend_names

    rows = [backend_capabilities(name).to_dict() for name in known_harness_backend_names()]
    if json_output:
        click.echo(json.dumps(rows, indent=2))
        return

    for row in rows:
        install = f" install: {row['install_hint']}" if row["install_hint"] else ""
        click.echo(
            f"{row['backend']}  {row['availability']}  "
            f"coding={'yes' if row['supports_coding'] else 'no'}  "
            f"no_tool={'yes' if row['supports_no_tool'] else 'no'}  "
            f"streaming={'yes' if row['supports_streaming'] else 'no'}  "
            f"approvals={'yes' if row['supports_approvals'] else 'no'}"
            f"{install}"
        )


@harness.command("init")
@click.argument("name", required=False, default="superqode-coding")
@click.option(
    "--template",
    "-t",
    type=click.Choice(HARNESS_TEMPLATE_CHOICES),
    default="coding",
    show_default=True,
    help="Built-in template name",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("harness.yaml"),
    show_default=True,
    help="Harness spec file to write",
)
@click.option("--force", is_flag=True, help="Overwrite an existing spec file")
def harness_init(name, template, output, force):
    """Scaffold a harness spec and local agent directories."""
    from dataclasses import replace

    from superqode.harness import get_harness_template, save_harness_spec

    if output.exists() and not force:
        raise click.ClickException(f"{output} already exists. Use --force to overwrite.")

    spec = replace(get_harness_template(template), name=name)
    save_harness_spec(spec, output)
    (Path(".agents") / "skills").mkdir(parents=True, exist_ok=True)
    (Path(".agents") / "roles").mkdir(parents=True, exist_ok=True)
    click.echo(f"Created {output}")
    click.echo("Created .agents/skills and .agents/roles")


@harness.command("validate")
@click.argument("spec_arg", required=False, type=click.Path(exists=True, path_type=Path))
@click.option("--spec", "spec_option", type=click.Path(exists=True, path_type=Path), help="Harness spec file")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.option("--schema", "schema_output", is_flag=True, help="Emit HarnessSpec JSON Schema")
def harness_validate(spec_arg, spec_option, json_output, schema_output):
    """Validate a harness spec file."""
    from superqode.harness import harness_spec_json_schema, harness_spec_to_dict, load_harness_spec

    if schema_output:
        click.echo(json.dumps(harness_spec_json_schema(), indent=2))
        return
    spec_path = spec_option or spec_arg
    if spec_path is None:
        raise click.ClickException("Missing harness spec. Pass --spec <path>.")
    if spec_option is not None and spec_arg is not None and spec_option != spec_arg:
        raise click.ClickException("Pass the harness spec either as --spec or positional path, not both.")

    try:
        spec = load_harness_spec(spec_path)
    except Exception as exc:
        payload = {"valid": False, "error": str(exc)}
        if json_output:
            click.echo(json.dumps(payload, indent=2))
            return
        raise click.ClickException(str(exc)) from exc

    payload = {
        "valid": True,
        "name": spec.name,
        "flavor": spec.flavor.value,
        "runtime": spec.runtime.backend,
        "workflow": spec.workflow.mode.value,
        "spec": harness_spec_to_dict(spec),
    }
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(
        f"Valid harness: {spec.name} "
        f"({spec.flavor.value}, runtime={spec.runtime.backend}, workflow={spec.workflow.mode.value})"
    )


@harness.command("inspect")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--runtime", "runtime_name", default=None, help="Override runtime or backend")
@click.option("--sandbox", "sandbox_backend", default=None, help="Override sandbox backend")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_inspect(spec_path, runtime_name, sandbox_backend, json_output):
    """Inspect a HarnessSpec and backend capability compatibility."""
    from superqode.harness import (
        harness_spec_to_dict,
        inspect_harness_backend,
        load_harness_spec,
        resolve_harness_model_policy,
    )

    spec = load_harness_spec(spec_path)
    backend_name = runtime_name or spec.runtime.backend
    inspection = inspect_harness_backend(
        backend_name,
        spec,
        sandbox_backend=sandbox_backend,
    )
    model_policy = resolve_harness_model_policy(
        spec,
        provider=spec.model_policy.config.get("provider", ""),
        model=spec.model_policy.primary or "",
    )
    payload = {
        "name": spec.name,
        "flavor": spec.flavor.value,
        "runtime": backend_name,
        "workflow": spec.workflow.mode.value,
        "sandbox": sandbox_backend or spec.execution_policy.sandbox,
        "tools": sorted({tool for agent in spec.agents for tool in agent.tools}),
        "model_policy": {
            "profile": model_policy.profile,
            "system_level": model_policy.system_level.value,
            "tool_profile": model_policy.tool_profile,
            "reasoning": model_policy.reasoning,
            "temperature": model_policy.temperature,
            "max_iterations": model_policy.max_iterations,
            "parallel_tools": model_policy.parallel_tools,
        },
        "backend": inspection.to_dict(),
        "spec": harness_spec_to_dict(spec),
    }
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return

    click.echo(f"Harness: {spec.name}")
    click.echo(f"Flavor: {spec.flavor.value}")
    click.echo(f"Runtime: {backend_name}")
    click.echo(f"Workflow: {spec.workflow.mode.value}")
    click.echo(f"Sandbox: {payload['sandbox']}")
    click.echo(f"Compatibility: {'ok' if inspection.ok else 'blocked'}")
    click.echo("Capabilities:")
    for key, value in inspection.capabilities.to_dict().items():
        if key in {"backend", "notes"}:
            continue
        click.echo(f"  {key}: {'yes' if value else 'no'}")
    if inspection.capabilities.notes:
        click.echo("Notes:")
        for note in inspection.capabilities.notes:
            click.echo(f"  - {note}")
    if inspection.issues:
        click.echo("Issues:")
        for issue in inspection.issues:
            click.echo(f"  [{issue.severity}] {issue.code}: {issue.message}")


@harness.command("compile")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--provider", default=None, help="Provider used to resolve model policy")
@click.option("--model", "model_name", default=None, help="Model used to resolve model policy")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_compile(spec_path, provider, model_name, json_output):
    """Print the effective HarnessSpec and resolved runtime policy."""
    from superqode.harness import (
        compile_to_headless_profile,
        harness_spec_to_dict,
        load_harness_spec,
        resolve_harness_model_policy,
    )

    spec = load_harness_spec(spec_path)
    effective_policy = resolve_harness_model_policy(
        spec,
        provider=provider or spec.model_policy.config.get("provider", ""),
        model=model_name or spec.model_policy.primary or "",
    )
    profile = compile_to_headless_profile(spec)
    payload = {
        "spec": harness_spec_to_dict(spec),
        "effective_model_policy": {
            "profile": effective_policy.profile,
            "family": effective_policy.family,
            "temperature": effective_policy.temperature,
            "system_level": effective_policy.system_level.value,
            "tool_profile": effective_policy.tool_profile,
            "tool_call_format": effective_policy.tool_call_format,
            "reasoning": effective_policy.reasoning,
            "parallel_tools": effective_policy.parallel_tools,
            "max_iterations": effective_policy.max_iterations,
            "session_history_limit": effective_policy.session_history_limit,
        },
        "headless_profile": {
            "name": profile.name,
            "description": profile.description,
            "system_level": profile.system_level.value,
            "tools": profile.tools,
            "permissions": _permission_config_to_dict(profile.permissions),
            "job_description": profile.job_description,
        },
    }
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(json.dumps(payload, indent=2))


@harness.command("diff")
@click.argument("left", type=click.Path(exists=True, path_type=Path))
@click.argument("right", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_diff(left, right, json_output):
    """Show policy, tool, and agent differences between two HarnessSpecs."""
    from superqode.harness import harness_spec_to_dict, load_harness_spec

    left_payload = harness_spec_to_dict(load_harness_spec(left))
    right_payload = harness_spec_to_dict(load_harness_spec(right))
    changes = _diff_dicts(left_payload, right_payload)
    payload = {
        "left": str(left),
        "right": str(right),
        "changed": bool(changes),
        "changes": changes,
    }
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    if not changes:
        click.echo("No differences.")
        return
    for change in changes:
        click.echo(
            f"{change['path']}: {change.get('left')!r} -> {change.get('right')!r}"
        )


@harness.command("doctor")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--runtime", "runtime_name", default=None, help="Override runtime or backend")
@click.option("--sandbox", "sandbox_backend", default=None, help="Override sandbox backend")
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Override harness event store directory",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_doctor(spec_path, runtime_name, sandbox_backend, store_path, json_output):
    """Diagnose a harness spec before running it."""
    from superqode.harness import (
        create_harness_store,
        backend_capabilities,
        get_sandbox_capabilities,
        inspect_harness_backend,
        load_harness_spec,
    )

    spec = load_harness_spec(spec_path)
    backend_name = runtime_name or spec.runtime.backend
    selected_sandbox = sandbox_backend or spec.execution_policy.sandbox
    store_root = Path(store_path) if store_path is not None else Path(spec.context.session_storage)
    inspection = inspect_harness_backend(
        backend_name,
        spec,
        sandbox_backend=selected_sandbox,
    )
    capabilities = backend_capabilities(backend_name)

    checks = []

    def add_check(name, status, message, **extra):
        checks.append({"name": name, "status": status, "message": message, **extra})

    add_check("spec", "ok", f"Loaded HarnessSpec '{spec.name}'.")
    add_check(
        "backend",
        "ok" if capabilities.availability == "available" else "error",
        (
            f"Backend '{backend_name}' is available."
            if capabilities.availability == "available"
            else f"Backend '{backend_name}' is missing."
        ),
        install_hint=capabilities.install_hint,
    )
    add_check(
        "compatibility",
        "ok" if inspection.ok else "error",
        "Backend can run this spec." if inspection.ok else "Backend/spec compatibility is blocked.",
        issues=[issue.to_dict() for issue in inspection.issues],
    )
    model_check = _harness_model_registry_check(spec)
    add_check(
        "model_registry",
        model_check["status"],
        model_check["message"],
        provider=model_check["provider"],
        models=model_check["models"],
        unknown_models=model_check["unknown_models"],
    )

    if selected_sandbox in {"", "none", None}:
        add_check(
            "sandbox",
            "ok",
            "No sandbox is requested for this harness.",
            backend="none",
            capabilities={
                "backend": "none",
                "can_read": False,
                "can_write": False,
                "can_shell": False,
                "can_network": False,
                "description": "No tool or sandbox access.",
            },
        )
    else:
        try:
            sandbox_caps = get_sandbox_capabilities(selected_sandbox)
        except ValueError as exc:
            add_check("sandbox", "error", f"Unknown sandbox backend '{selected_sandbox}': {exc}")
        else:
            add_check(
                "sandbox",
                "ok",
                f"Sandbox policy '{selected_sandbox}' is recognized.",
                backend=selected_sandbox,
                capabilities={
                    "backend": sandbox_caps.backend.value,
                    "can_read": sandbox_caps.can_read,
                    "can_write": sandbox_caps.can_write,
                    "can_shell": sandbox_caps.can_shell,
                    "can_network": sandbox_caps.can_network,
                    "description": sandbox_caps.description,
                },
            )

    store_kind = spec.observability.run_store
    try:
        create_harness_store(store_kind, store_root)
    except Exception as exc:  # noqa: BLE001
        add_check(
            "event_store",
            "error",
            f"Cannot initialize harness event store '{store_kind}' at {store_root}: {exc}",
        )
    else:
        add_check(
            "event_store",
            "ok",
            (
                "Harness event store 'memory' initialized."
                if store_kind == "memory"
                else f"Harness event store '{store_kind}' is writable at {store_root}."
            ),
            graph=True,
            store=store_kind,
        )

    rich_event_backends = {"builtin", "pydanticai", "openai-agents", "deepagents"}
    add_check(
        "event_graph",
        "ok" if backend_name in rich_event_backends else "warning",
        (
            f"Backend '{backend_name}' emits rich graph events."
            if backend_name in rich_event_backends
            else f"Backend '{backend_name}' emits coarse graph events."
        ),
        rich_events=backend_name in rich_event_backends,
    )

    if spec.execution_policy.approval_profile != "deny":
        add_check(
            "approvals",
            "ok" if capabilities.supports_approvals else "warning",
            (
                f"Backend '{backend_name}' supports approval pauses."
                if capabilities.supports_approvals
                else f"Backend '{backend_name}' may not pause for approvals."
            ),
        )

    mcp_path = _harness_mcp_config_path(spec)
    if mcp_path is not None:
        add_check(
            "mcp",
            "ok" if mcp_path.exists() else "warning",
            (
                f"MCP config exists at {mcp_path}."
                if mcp_path.exists()
                else f"MCP config path does not exist: {mcp_path}."
            ),
            path=str(mcp_path),
        )

    status = "ok"
    if any(check["status"] == "error" for check in checks):
        status = "error"
    elif any(check["status"] == "warning" for check in checks):
        status = "warning"

    payload = {
        "status": status,
        "name": spec.name,
        "runtime": backend_name,
        "flavor": spec.flavor.value,
        "workflow": spec.workflow.mode.value,
        "sandbox": selected_sandbox,
        "checks": checks,
    }
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        if status == "error":
            raise click.exceptions.Exit(1)
        return

    click.echo(f"Harness doctor: {spec.name}")
    click.echo(f"Status: {status}")
    for check in checks:
        click.echo(f"[{check['status']}] {check['name']}: {check['message']}")
        if check.get("install_hint"):
            click.echo(f"  install: {check['install_hint']}")
        for issue in check.get("issues", []):
            click.echo(f"  [{issue['severity']}] {issue['code']}: {issue['message']}")
    if status == "error":
        raise click.Abort()


@harness.command("run")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--prompt", "-p", required=True, help="Prompt to run")
@click.option("--provider", envvar="SUPERQODE_PROVIDER", default="openai", show_default=True)
@click.option(
    "--model", "model_name", envvar="SUPERQODE_MODEL", default="gpt-4o-mini", show_default=True
)
@click.option("--runtime", "runtime_name", default=None, help="Override runtime or backend")
@click.option("--session", "session_id", default=None, help="Reuse a harness session id")
@click.option(
    "--store",
    "store_kind",
    type=click.Choice(["memory", "file", "sqlite"]),
    default=None,
    help="Override observability.run_store",
)
@click.option(
    "--working-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=False,
)
@click.option("--sandbox", "sandbox_backend", default="local", show_default=True)
@click.option("--stream", is_flag=True, help="Print normalized stream events")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_run(
    spec_path,
    prompt,
    provider,
    model_name,
    runtime_name,
    session_id,
    store_kind,
    working_dir,
    sandbox_backend,
    stream,
    json_output,
):
    """Run one prompt through a HarnessSpec."""
    import asyncio

    from superqode.harness import create_harness_store, init_harness, load_harness_spec

    async def _run():
        spec = load_harness_spec(spec_path)
        store = create_harness_store(
            store_kind or spec.observability.run_store,
            (
                Path(spec.context.session_storage) / "store.sqlite3"
                if (store_kind or spec.observability.run_store) == "sqlite"
                else Path(spec.context.session_storage)
            ),
        )
        kernel = await init_harness(spec, store=store)
        session_obj = await kernel.session(session_id)
        if stream:
            events = []
            async for event in session_obj.stream(
                prompt,
                provider=provider,
                model=model_name,
                runtime=runtime_name,
                working_directory=working_dir,
                sandbox_backend=sandbox_backend,
            ):
                item = {
                    "type": event.type,
                    "data": event.data,
                    "session_id": event.session_id,
                    "run_id": event.run_id,
                }
                events.append(item)
                if json_output:
                    click.echo(json.dumps(item))
                elif event.type == "delta":
                    click.echo(event.data.get("text", ""), nl=False)
            if json_output:
                return None
            click.echo()
            return {"events": events}
        result = await session_obj.prompt(
            prompt,
            provider=provider,
            model=model_name,
            runtime=runtime_name,
            working_directory=working_dir,
            sandbox_backend=sandbox_backend,
        )
        pending_approvals = list(session_obj.pending_approvals())
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "content": result.content,
                        "session_id": result.session_id,
                        "run_id": result.run_id,
                        "tool_calls_made": result.tool_calls_made,
                        "iterations": result.iterations,
                        "harness": result.spec.name,
                        "stopped_reason": result.response.stopped_reason,
                        "pending_approvals": pending_approvals,
                    },
                    indent=2,
                )
            )
        else:
            click.echo(result.content)
            if result.response.stopped_reason == "needs_approval" and pending_approvals:
                click.echo("Approval required:")
                for entry in pending_approvals:
                    tool = entry.get("tool_name") or "<unknown>"
                    args_preview = str(entry.get("arguments", {}))
                    if len(args_preview) > 120:
                        args_preview = args_preview[:117] + "..."
                    click.echo(f"  [{entry.get('index', 0)}] {tool} {args_preview}")
                click.echo("Use the TUI to approve or reject the paused tool call.")
        return result

    try:
        asyncio.run(_run())
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc), "success": False}, indent=2))
        else:
            click.echo(f"Error: {exc}", err=True)
        raise click.Abort() from exc


@harness.command("events")
@click.argument("run_id")
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--after", type=int, default=0, show_default=True, help="First event index")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_events(run_id, store_path, after, json_output):
    """Show normalized events for a harness run."""
    from superqode.harness import FileHarnessStore

    store = FileHarnessStore(store_path)
    try:
        events = store.get_events(run_id, after=after)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc

    payload = [event.to_dict() for event in events]
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return

    for index, event in enumerate(events, start=after):
        preview = (
            event.data.get("text") or event.data.get("status") or event.data.get("error") or ""
        )
        preview = str(preview).replace("\n", " ")
        if len(preview) > 100:
            preview = preview[:97] + "..."
        suffix = f"  {preview}" if preview else ""
        click.echo(f"{index:04d}  {event.type}{suffix}")


@harness.command("graph")
@click.argument("run_id")
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_graph(run_id, store_path, json_output):
    """Show the persisted event graph for a harness run."""
    from superqode.harness import FileHarnessStore

    store = FileHarnessStore(store_path)
    try:
        graph = store.get_event_graph(run_id)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        click.echo(json.dumps(graph.to_dict(), indent=2))
        return

    click.echo(f"Run: {graph.run_id}")
    click.echo("Nodes:")
    for node in graph.nodes:
        click.echo(f"  {node.node_id}  {node.type}  {node.label}")
    if graph.edges:
        click.echo("Edges:")
        for edge in graph.edges:
            click.echo(f"  {edge.source} -> {edge.target}  {edge.type}")


def _harness_mcp_config_path(spec) -> Path | None:
    runtime_config = spec.runtime.config
    pydanticai_config = runtime_config.get("pydanticai", {})
    if isinstance(pydanticai_config, dict):
        configured = pydanticai_config.get("mcp_config_path") or pydanticai_config.get("mcp_config")
        if configured:
            return Path(configured)
    configured = runtime_config.get("mcp_config_path") or runtime_config.get("mcp_config")
    return Path(configured) if configured else None


def _harness_model_registry_check(spec) -> dict:
    provider = str(spec.model_policy.config.get("provider") or "").strip().lower()
    models = [item for item in (spec.model_policy.primary, *spec.model_policy.fallbacks) if item]
    if not models:
        return {
            "status": "ok",
            "message": "No model policy models are configured.",
            "provider": provider,
            "models": [],
            "unknown_models": [],
        }

    from superqode.providers.registry import PROVIDERS

    normalized = [_normalize_harness_model_id(model) for model in models]
    if not provider and ":" in str(models[0]):
        provider = str(models[0]).split(":", 1)[0].lower()
    if provider == "local":
        unknown = [
            model
            for model, normalized_model in zip(models, normalized)
            if not (
                normalized_model.endswith("-local")
                or normalized_model == "local-model"
                or "/" in normalized_model
            )
        ]
        status = "warning" if unknown else "ok"
        return {
            "status": status,
            "message": (
                "Local model aliases look usable."
                if not unknown
                else "Some local model aliases are not recognized by SuperQode's static hints."
            ),
            "provider": provider,
            "models": models,
            "unknown_models": unknown,
        }
    provider_def = PROVIDERS.get(provider)
    if provider_def is None:
        return {
            "status": "warning",
            "message": (
                "Model availability was not checked because no known provider is configured."
            ),
            "provider": provider,
            "models": models,
            "unknown_models": [],
        }
    known = {
        _normalize_harness_model_id(model)
        for model in (*provider_def.example_models, *provider_def.free_models)
    }
    unknown = [
        model for model, normalized_model in zip(models, normalized) if normalized_model not in known
    ]
    return {
        "status": "warning" if unknown else "ok",
        "message": (
            f"Model policy models are listed for provider '{provider}'."
            if not unknown
            else f"Some model policy models are not listed for provider '{provider}'."
        ),
        "provider": provider,
        "models": models,
        "unknown_models": unknown,
    }


def _normalize_harness_model_id(model: str) -> str:
    value = str(model).strip()
    if ":" in value and "/" not in value.split(":", 1)[0]:
        value = value.split(":", 1)[1]
    if "/" in value:
        prefix, rest = value.split("/", 1)
        if prefix in {"openai", "anthropic", "google", "gemini", "ollama"}:
            return rest
    return value


def _diff_dicts(left: object, right: object, path: str = "") -> list[dict]:
    if isinstance(left, dict) and isinstance(right, dict):
        changes: list[dict] = []
        for key in sorted(set(left) | set(right)):
            child_path = f"{path}.{key}" if path else str(key)
            if key not in left:
                changes.append({"path": child_path, "left": None, "right": right[key]})
            elif key not in right:
                changes.append({"path": child_path, "left": left[key], "right": None})
            else:
                changes.extend(_diff_dicts(left[key], right[key], child_path))
        return changes
    if isinstance(left, list) and isinstance(right, list):
        if left == right:
            return []
        if all(isinstance(item, dict) and "id" in item for item in left + right):
            left_by_id = {item["id"]: item for item in left}
            right_by_id = {item["id"]: item for item in right}
            return _diff_dicts(left_by_id, right_by_id, path)
        return [{"path": path, "left": left, "right": right}]
    if left != right:
        return [{"path": path, "left": left, "right": right}]
    return []


def _permission_config_to_dict(config) -> dict:
    return {
        "default": config.default.value,
        "groups": {group.value: permission.value for group, permission in config.groups.items()},
        "tools": {tool: permission.value for tool, permission in config.tools.items()},
        "allow_patterns": list(config.allow_patterns),
        "deny_patterns": list(config.deny_patterns),
    }


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

  # validation roles
  qe:
    description: "validation and evaluation"
    roles:
      fullstack:
        description: "Full-stack validation engineer"
        mode: "acp"
        agent: "opencode"
        agent_config:
          provider: "opencode"
          model: "nemotron-3-super-free"
        enabled: false
        job_description: |
          You are a Senior validation Engineer.
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
    click.echo("    superqode qe roles            # List configured validation roles")
    click.echo("    superqode qe run .            # Run validation using your superqode.yaml")
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


@agents.command("free-models")
@click.option(
    "--agent",
    "agent_filter",
    default=None,
    help="Only show free models from this agent (identity or short_name)",
)
@click.option("--refresh", is_flag=True, help="Skip the discovery cache and re-probe live")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON instead of a table")
def agents_free_models(agent_filter, refresh, as_json):
    """List free-tier models discovered across all installed ACP agents.

    Each agent declares its catalog via the optional [free_models] section
    in its TOML descriptor; SuperQode probes them in parallel and falls
    back to a curated list when the live probe is unavailable.
    """
    from superqode.commands.acp import show_free_models

    exit(show_free_models(agent_filter=agent_filter, refresh=refresh, as_json=as_json))


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

# Add validation commands (superqode qe ...)
cli_main.add_command(qe_cmd, name="qe")

# Add roles commands (superqode roles list, superqode roles info, etc.)
cli_main.add_command(roles_cmd, name="roles")

# Add suggestions commands (superqode suggestions list, superqode suggestions apply, etc.)
cli_main.add_command(suggestions_cmd, name="suggestions")

# Add Server commands (superqode serve lsp, superqode serve web, etc.)
cli_main.add_command(serve_cmd, name="serve")

# Add runtime management commands (superqode runtime list, superqode runtime doctor)
from superqode.commands.runtime import runtime_cmd  # noqa: E402

cli_main.add_command(runtime_cmd, name="runtime")

# Note: agents command already exists, so we add the new one with a different approach
# The existing agents command handles ACP agents, we'll enhance it


if __name__ == "__main__":
    """Entry point for the SuperQode CLI."""
    cli_main()
