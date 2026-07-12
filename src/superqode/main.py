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
from superqode.runtime import known_runtime_names
from superqode.providers.connection_profiles import connection_profile_ids

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
@click.option(
    "--profile",
    default=None,
    help="Legacy headless profile (prefer --harness): build, plan, review, no-tool",
)
@click.option("--plan", "plan_only", is_flag=True, help="Run headless prompt in plan-only mode")
@click.option(
    "--output-schema",
    "output_schema",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="JSON Schema file the headless answer must validate against",
)
@click.option(
    "--rubric",
    "rubric",
    default=None,
    help="Rubric text (or @file) the answer is self-graded against before finishing",
)
@click.option("--provider", envvar="SUPERQODE_PROVIDER", default="openai", help="Model provider")
@click.option(
    "--model", "model_name", envvar="SUPERQODE_MODEL", default="gpt-5.4", help="Model name"
)
@click.option(
    "--harness",
    "harness_path",
    envvar="SUPERQODE_HARNESS",
    default=None,
    help="Harness name or HarnessSpec YAML/JSON path (default: core)",
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
    type=click.Choice(known_runtime_names()),
    help=(
        "Agent runtime backend (default: builtin). Non-builtin runtimes "
        "(adk, openai-agents, pydanticai, codex-sdk) require their optional extras."
    ),
)
@click.option(
    "--connect",
    "connect_name",
    default=None,
    type=click.Choice(connection_profile_ids()),
    help=(
        "Connection source to start with: codex / claude / antigravity / grok / byok / "
        "local / acp. e.g. `--connect codex` to use your Codex subscription."
    ),
)
@click.pass_context
def cli_main(
    ctx,
    tui,
    print_mode,
    output_mode,
    profile,
    plan_only,
    output_schema,
    rubric,
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
    connect_name=None,
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
    yaml_harness: Optional[str] = None
    try:
        from superqode.config.loader import load_config

        loaded_config = load_config().superqode
        yaml_runtime = loaded_config.runtime
        yaml_harness = loaded_config.harness
    except Exception:  # noqa: BLE001 — startup must remain resilient
        yaml_runtime = None
        yaml_harness = None
    effective_runtime = runtime_name or yaml_runtime
    # A connection profile (e.g. --connect codex) can imply a runtime backend.
    if connect_name:
        try:
            from superqode.providers.connection_profiles import get_connection_profile

            _profile = get_connection_profile(connect_name)
        except Exception:  # noqa: BLE001 — startup must remain resilient
            _profile = None
        if _profile is not None:
            # Runtime-connector profiles (Codex) map to a runtime backend; an
            # explicit --runtime still wins.
            if _profile.connector == "runtime" and _profile.runtime and not runtime_name:
                effective_runtime = _profile.runtime
            # Hint the TUI to auto-run the connection on startup.
            _os.environ["SUPERQODE_CONNECT"] = _profile.id
    if effective_runtime:
        _os.environ["SUPERQODE_RUNTIME"] = effective_runtime
    effective_harness = str(harness_path or yaml_harness or "core")
    _os.environ["SUPERQODE_HARNESS"] = effective_harness
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

            # --rubric accepts inline text or @path-to-file.
            rubric_text = rubric
            if rubric_text and rubric_text.startswith("@"):
                rubric_text = Path(rubric_text[1:]).expanduser().read_text(encoding="utf-8")

            change_baseline = capture_workspace_changes(Path.cwd())
            try:
                response = asyncio.run(
                    run_headless(
                        prompt=prompt,
                        provider=provider,
                        model=model_name,
                        profile_name=profile or effective_harness,
                        session_id=resume,
                        fork_from=fork_from,
                        sandbox_backend=sandbox_backend,
                        runtime=effective_runtime,
                        output_schema=output_schema,
                        rubric=rubric_text,
                    )
                )
            except Exception as e:
                if output_mode == "json":
                    click.echo(
                        json.dumps(
                            {
                                "type": "superqode.error",
                                "profile": profile or effective_harness,
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
                        profile or effective_harness,
                        change_summary=change_summary.to_dict(),
                    )
                )
            else:
                if output_schema and response.schema_errors is not None:
                    if response.schema_errors:
                        click.echo(response.content)
                        click.echo("Output schema validation failed:", err=True)
                        for schema_error in response.schema_errors:
                            click.echo(f"  - {schema_error}", err=True)
                    else:
                        click.echo(json.dumps(response.structured_output, indent=2))
                else:
                    click.echo(response.content)
                rendered_changes = render_change_summary(change_summary, changes)
                if rendered_changes:
                    click.echo()
                    click.echo(rendered_changes)
            if output_schema and response.schema_errors:
                ctx.exit(2)
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


@cli_main.command("mcp")
@click.option("--http", is_flag=True, help="Serve over streamable HTTP instead of stdio")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8765, show_default=True, type=int)
@click.option("--dir", "harness_dir", default=None, help="Directory of harness specs")
def mcp(http, host, port, harness_dir):
    """Expose SuperQode harnesses over MCP (stdio by default).

    Any MCP client (Claude Desktop, IDEs, other agents) can then discover and
    run your HarnessSpec workflows. Complements the A2A and ACP servers.
    """
    from superqode.mcp.harness_server import run_server

    if not http:
        # stdio talks JSON-RPC on stdout; keep human chatter on stderr only.
        click.echo("Starting SuperQode harness MCP server on stdio…", err=True)
    else:
        click.echo(f"Starting SuperQode harness MCP server on http://{host}:{port}")
    run_server("http" if http else "stdio", host, port, harness_dir)


# Configuration management commands - defined before main() for proper registration
@cli_main.group()
def config():
    """Manage SuperQode configuration."""
    pass


def _scaffold_project_config(force: bool = False) -> tuple[Path, list[Path]]:
    """Create project config plus the harness files it references."""
    import shutil
    from dataclasses import replace

    from superqode.harness import ModelPolicySpec, get_harness_template, save_harness_spec

    config_path = Path.cwd() / "superqode.yaml"
    if config_path.exists() and not force:
        raise click.ClickException(
            f"Configuration already exists at {config_path}. Use --force to overwrite."
        )

    template_path = Path(__file__).parent / "data" / "superqode-template.yaml"
    if template_path.exists():
        shutil.copy2(template_path, config_path)
    else:
        config_path.write_text(
            'superqode:\n  version: "1.0"\n'
            '  team_name: "My SuperQode Project"\n'
            '  description: "Local-first coding agent harness"\n\n'
            'default:\n  description: "Local-first coding model"\n'
            "  mode: local\n  provider: ollama\n  model: qwen3:8b\n\n"
            "providers:\n"
            "  ollama:\n"
            '    description: "Local Ollama runtime"\n'
            "    base_url: http://localhost:11434\n"
            "    recommended_models:\n"
            "      - qwen3:8b\n"
            "      - qwen3-coder:30b-a3b\n"
            "      - gemma4:e4b\n\n"
            "mcp_servers: {}\n",
            encoding="utf-8",
        )

    harness_dir = Path(".superqode") / "harnesses"
    local_model_policy = ModelPolicySpec(
        primary="ollama/qwen3:8b",
        fallbacks=("ollama/qwen3-coder:30b-a3b", "ollama/gemma4:e4b"),
        profile="qwen-coding",
        temperature=0.2,
        tool_call_format="prompt",
        pack="qwen-coder",
        config={"provider": "ollama"},
    )
    harness_specs = {
        "coding": replace(
            get_harness_template("coding"),
            name="coding",
            model_policy=local_model_policy,
        ),
        "planning": replace(
            get_harness_template("no-tool"),
            name="planning",
            model_policy=local_model_policy,
        ),
        "review": replace(
            get_harness_template("no-tool"),
            name="review",
            model_policy=local_model_policy,
        ),
    }
    created_harnesses: list[Path] = []
    for name, spec in harness_specs.items():
        path = harness_dir / f"{name}.yaml"
        if force or not path.exists():
            created_harnesses.append(save_harness_spec(spec, path))

    (Path(".agents") / "skills").mkdir(parents=True, exist_ok=True)
    (Path(".agents") / "roles").mkdir(parents=True, exist_ok=True)
    return config_path, created_harnesses


try:
    from superqode.commands.config import config_show as _config_show_cmd
    from superqode.commands.config import config_validate as _config_validate_cmd

    config.add_command(_config_show_cmd, name="show")
    config.add_command(_config_validate_cmd, name="validate")
except Exception:
    # Optional compatibility commands should not make CLI startup brittle.
    pass


from superqode.commands.sessions import sessions
cli_main.add_command(sessions, name="sessions")


from superqode.commands.factory import factory
cli_main.add_command(factory, name="factory")


from superqode.commands.share import share
cli_main.add_command(share, name="share")


from superqode.commands.trust import trust
cli_main.add_command(trust, name="trust")


from superqode.commands.memory import memory
cli_main.add_command(memory, name="memory")


from superqode.commands.skillopt import skillopt
cli_main.add_command(skillopt, name="skillopt")


from superqode.commands.skills import skills
cli_main.add_command(skills, name="skills")


from superqode.commands.harness import harness
cli_main.add_command(harness, name="harness")


from superqode.commands.plugins import plugins
cli_main.add_command(plugins, name="plugins")


from superqode.commands.sandbox import sandbox
cli_main.add_command(sandbox, name="sandbox")


from superqode.commands.benchmark import benchmark
cli_main.add_command(benchmark, name="benchmark")


from superqode.commands.profiles import profiles
cli_main.add_command(profiles, name="profiles")


from superqode.commands.tools import tools
cli_main.add_command(tools, name="tools")


from superqode.commands.models import models
cli_main.add_command(models, name="models")


@config.command("init")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing configuration")
def config_init(force):
    """Initialize local-first SuperQode configuration."""
    config_path, harness_paths = _scaffold_project_config(force=force)
    click.echo(f"Created local-first configuration at {config_path}")
    for path in harness_paths:
        click.echo(f"Created harness spec at {path}")
    click.echo("Created .agents/skills and .agents/roles")


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

    Creates a harness-first superqode.yaml.
    """
    try:
        config_path, harness_paths = _scaffold_project_config(force=force)
    except click.ClickException as exc:
        click.echo(f"✓ {exc.message}")
        return

    click.echo(f"✓ Created {config_path} with harness defaults")
    for path in harness_paths:
        click.echo(f"✓ Created {path}")

    click.echo("")
    click.echo("  Quick start:")
    click.echo("    superqode               # Launch TUI")
    click.echo("    superqode harness list-templates")
    click.echo("    superqode harness validate .superqode/harnesses/coding.yaml")


from superqode.commands.agents import agents
cli_main.add_command(agents, name="agents")


from superqode.commands.connect import connect
cli_main.add_command(connect, name="connect")


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

# LLM provider management
from superqode.providers.manager import ProviderManager

# Register new BYOK provider and agent commands
from superqode.commands.providers import providers as providers_cmd
from superqode.commands.auth import auth as auth_cmd
from superqode.commands.serve import serve as serve_cmd


@providers_cmd.command("models")
@click.argument("provider_id")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def providers_models(provider_id, json_output):
    """List current models for a provider."""
    from superqode.providers.registry import PROVIDERS
    from superqode.providers.models import get_models_for_provider

    provider_def = PROVIDERS.get(provider_id)
    if not provider_def:
        raise click.ClickException(f"Provider not found: {provider_id}")

    models = list(get_models_for_provider(provider_id).keys())
    if not models:
        models = list(provider_def.example_models)

    payload = {
        "provider": provider_id,
        "name": provider_def.name,
        "models": models,
        "recommended_models": models,
        "env_vars": provider_def.env_vars,
    }
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"{provider_def.name} ({provider_id})")
    for model in models:
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
    from superqode.providers.models import get_models_for_provider

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
        current_models = list(get_models_for_provider(pid))
        if not current_models:
            current_models = provider_def.example_models[:5]
        item = {
            "provider": pid,
            "name": provider_def.name,
            "configured": bool(configured_vars) or not provider_def.env_vars,
            "configured_env_vars": configured_vars,
            "required_env_vars": provider_def.env_vars,
            "base_url_env": provider_def.base_url_env,
            "example_models": current_models[:5],
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


@cli_main.command("help")
def help_command():
    """Show categorized help for all SuperQode CLI commands."""
    from rich.table import Table
    from rich.console import Console

    console = Console()

    click.echo("")
    console.print("[bold white]SuperQode CLI Reference[/bold white]")
    console.print(
        "[dim]Categorized overview of all commands — use [bold]--help[/bold] on any subcommand for details.[/dim]\n"
    )

    categories = [
        (
            "🚀  Getting Started",
            [
                ("superqode", "Launch the TUI (no subcommand)"),
                ("superqode tui", "Launch the TUI explicitly"),
                ("superqode doctor", "Check basic setup and provider readiness"),
                ("superqode init", "Initialize superqode.yaml in current directory"),
                ("superqode help", "Show this help overview"),
            ],
        ),
        (
            "🤖  ACP Agents",
            [
                ("superqode agents list", "List all available ACP agents"),
                ("superqode agents install <name>", "Install an ACP agent"),
                ("superqode agents show <name>", "Show detailed agent info"),
                ("superqode agents doctor [name]", "Check agent install and protocol health"),
                ("superqode agents free-models", "List free-tier models from installed agents"),
                ("superqode agents connect <name>", "Connect to an ACP agent (deprecated)"),
            ],
        ),
        (
            "🔌  Connect",
            [
                ("superqode connect acp <name>", "Connect to an ACP coding agent"),
                ("superqode connect byok [provider] [model]", "Connect to a BYOK provider/model"),
                (
                    "superqode connect local [provider] [model]",
                    "Connect to a local/self-hosted provider",
                ),
                ("superqode connect setup <provider>", "Show provider setup: env vars, URL, docs"),
            ],
        ),
        (
            "⚡  Models & Providers",
            [
                ("superqode models [options]", "Browse 5000+ models from 130+ providers"),
                ("superqode providers list", "List all configured providers"),
                ("superqode providers show <provider>", "Show provider details"),
                ("superqode providers doctor [provider]", "Show provider config status and hints"),
                ("superqode providers recommend [task]", "Get model recommendations by task"),
                ("superqode providers guide [provider]", "Show quality labels and setup help"),
                ("superqode providers smoke <provider>", "Test a local provider's reachability"),
            ],
        ),
        (
            "🧰  Harness",
            [
                ("superqode harness init [name]", "Scaffold a harness spec from template"),
                ("superqode harness list-templates", "List built-in harness templates"),
                ("superqode harness list-backends", "List available runtime backends"),
                ("superqode harness validate <file>", "Validate a harness spec file"),
                ("superqode harness run <file>", "Run a harness spec (headless)"),
                ("superqode harness doctor [name]", "Check spec readiness and blockers"),
                ("superqode harness graph [run_id]", "Show planned or persisted run graph"),
                ("superqode harness events <run_id>", "Show persisted event timeline"),
                ("superqode harness fork <run_id>", "Fork a persisted run"),
                ("superqode harness replay <run_id>", "Show replay readiness"),
            ],
        ),
        (
            "📋  Sessions",
            [
                ("superqode sessions list", "List stored sessions"),
                ("superqode sessions show <id>", "Show session details"),
                ("superqode sessions tree", "Show session branches and forks"),
                ("superqode sessions export <id>", "Export session as markdown or JSON"),
                ("superqode sessions delete <id>", "Delete a stored session"),
            ],
        ),
        (
            "💾  Memory",
            [
                ("superqode memory status", "Show memory provider status"),
                ("superqode memory providers", "List built-in memory providers"),
                ("superqode memory remember <text>", "Store a memory"),
                ("superqode memory search <query>", "Search memory"),
                ("superqode memory forget <id>", "Delete a memory"),
            ],
        ),
        (
            "🔐  Trust & Plugins",
            [
                ("superqode trust status", "Show project trust status"),
                ("superqode trust doctor", "Show trust-sensitive project files"),
                ("superqode trust yes|no", "Trust or distrust the current project"),
                ("superqode plugins list", "List discoverable plugins"),
                ("superqode plugins show <id>", "Show one plugin manifest"),
                ("superqode plugins validate <path>", "Validate a plugin manifest"),
                ("superqode plugins doctor [path]", "Validate all plugin manifests"),
                ("superqode plugins add <source>", "Install a local plugin"),
                ("superqode plugins enable|disable <id>", "Toggle a plugin"),
            ],
        ),
        (
            "📦  Share",
            [
                ("superqode share create <session_id>", "Create a portable share artifact"),
                ("superqode share export <session_id>", "Export session as markdown/JSON"),
                ("superqode share import <file>", "Import a share artifact"),
                ("superqode share list", "List managed share artifacts"),
                ("superqode share revoke <artifact>", "Delete a share artifact"),
            ],
        ),
        (
            "🔧  Configuration & System",
            [
                ("superqode config show", "Show current configuration"),
                ("superqode config validate", "Validate configuration file"),
                ("superqode sandbox doctor [backend]", "Check sandbox backend readiness"),
                ("superqode tools list", "List tools for a harness profile"),
                ("superqode profiles list", "List built-in harness profiles"),
                ("superqode runtime list", "List available runtime backends"),
                ("superqode runtime doctor", "Check runtime backend readiness"),
                ("superqode benchmark run <tasks>", "Run coding harness benchmarks"),
            ],
        ),
    ]

    for title, cmds in categories:
        console.print(f"\n  [bold]{title}[/bold]")
        for cmd, desc in cmds:
            console.print(f"    [cyan]{cmd:<40}[/cyan] [dim]{desc}[/dim]")

    console.print("\n  [bold]📖  Headless Mode[/bold]")
    console.print(
        '    [cyan]superqode -p "<prompt>"[/cyan]         [dim]Run once and print response[/dim]'
    )
    console.print(
        '    [cyan]superqode -p --json "<prompt>"[/cyan]  [dim]Run once with JSON output[/dim]'
    )
    console.print(
        "    [cyan]superqode --resume <id>[/cyan]         [dim]Resume a stored session[/dim]"
    )
    console.print(
        "    [cyan]superqode --fork <id>[/cyan]           [dim]Fork a stored session[/dim]"
    )

    console.print(
        "\n  [dim]Use [bold]superqode <command> --help[/bold] for detailed options on any command.[/dim]\n"
    )


# Add provider commands (superqode providers list, superqode providers show, etc.)
cli_main.add_command(providers_cmd, name="providers")

# Add auth commands (superqode auth info, superqode auth check, etc.)
cli_main.add_command(auth_cmd, name="auth")

# Add Server commands (superqode serve lsp, superqode serve web, etc.)
cli_main.add_command(serve_cmd, name="serve")

# Add runtime management commands (superqode runtime list, superqode runtime doctor)
from superqode.commands.runtime import runtime_cmd  # noqa: E402

cli_main.add_command(runtime_cmd, name="runtime")

# Add local stack commands (superqode local doctor, superqode local bench)
from superqode.commands.local import local as local_cmd  # noqa: E402

cli_main.add_command(local_cmd, name="local")

# Add the channel daemon (superqode daemon: Telegram/Slack/Discord remote control)
from superqode.commands.daemon import daemon as daemon_cmd  # noqa: E402

cli_main.add_command(daemon_cmd, name="daemon")

# Note: agents command already exists, so we add the new one with a different approach
# The existing agents command handles ACP agents, we'll enhance it


if __name__ == "__main__":
    """Entry point for the SuperQode CLI."""
    cli_main()
