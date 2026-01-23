"""Session state management for SuperQode."""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any


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
    """Manages the current session state and agent connections."""

    def __init__(self):
        self.state = "superqode"  # "superqode" | "agent_connected" | "role_mode"
        self.connected_agent = None  # Agent data when in agent_connected state
        self.agent_role_info = None  # Role info when connected via role
        self.current_context = SessionContext()  # Current work context
        self.handoff_workflow = HandoffWorkflow()  # Handoff management
        self.acp_manager = None  # ACP agent manager for real connections
        self.selected_model = None  # Selected model for agent
        self.current_mode = "home"  # Current mode name (for TUI/non-TUI compatibility)

    def connect_to_agent(self, agent_data, role_info=None, model=None):
        """Connect to an agent directly (bypassing roles)"""
        self.state = "agent_connected"
        self.connected_agent = agent_data
        self.agent_role_info = role_info
        self.selected_model = model  # Store selected model for direct connections

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
        self.current_mode = "home"

    def switch_to_role_mode(self, mode):
        """Switch to role-based mode"""
        self.state = "role_mode"
        self.current_mode = mode

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
            return f"🔗 {agent_name.upper()}"
        elif self.state == "role_mode":
            return self.current_mode.replace(".", "/").upper()
        else:  # superqode
            if self.current_mode == "home":
                return "🏠 HOME"
            else:
                return self.current_mode.replace(".", "/").upper()

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
            return self.current_mode
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
