"""Headless SuperQode runner for scripting and CI."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .agent.loop import AgentConfig, AgentResponse
from .runtime import create_runtime, resolve_runtime_name
from .agent.session_manager import SessionManager, SessionMessage, SessionMetadata
from .agent.system_prompts import SystemPromptLevel
from .providers.gateway.litellm_gateway import LiteLLMGateway
from .sandbox import apply_backend_permissions
from .tools.base import ToolRegistry
from .tools.permissions import Permission, PermissionConfig, PermissionManager, ToolGroup


def _env_flag(name: str, default: bool = False) -> bool:
    import os

    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class HarnessProfile:
    """A built-in harness profile."""

    name: str
    description: str
    system_level: SystemPromptLevel
    tools: Optional[List[str]]
    permissions: PermissionConfig
    job_description: str = ""


READ_ONLY_TOOLS = [
    "read_file",
    "list_directory",
    "grep",
    "glob",
    "repo_search",
    "code_search",
    "diagnostics",
    "todo_read",
]


def get_harness_profiles() -> Dict[str, HarnessProfile]:
    """Return built-in profiles for common harness modes."""
    read_only_permissions = PermissionConfig(
        default=Permission.DENY,
        groups={
            ToolGroup.READ: Permission.ALLOW,
            ToolGroup.SEARCH: Permission.ALLOW,
            ToolGroup.DIAGNOSTICS: Permission.ALLOW,
        },
        tools={
            "todo_read": Permission.ALLOW,
        },
    )

    build_permissions = PermissionConfig(default=Permission.ALLOW)

    plan_permissions = PermissionConfig(
        default=Permission.DENY,
        groups={
            ToolGroup.READ: Permission.ALLOW,
            ToolGroup.SEARCH: Permission.ALLOW,
            ToolGroup.DIAGNOSTICS: Permission.ALLOW,
            ToolGroup.SHELL: Permission.ASK,
        },
        tools={
            "todo_read": Permission.ALLOW,
        },
    )

    qe_permissions = PermissionConfig(
        default=Permission.ALLOW,
        groups={
            ToolGroup.SHELL: Permission.ASK,
            ToolGroup.NETWORK: Permission.ASK,
        },
    )

    return {
        "no-tool": HarnessProfile(
            name="no-tool",
            description="Model-only reasoning profile with no tools or repository access.",
            system_level=SystemPromptLevel.NO_TOOL,
            tools=[],
            permissions=PermissionConfig(default=Permission.DENY),
        ),
        "build": HarnessProfile(
            name="build",
            description="Full-access coding profile for implementation work.",
            system_level=SystemPromptLevel.FULL,
            tools=None,
            permissions=build_permissions,
        ),
        "plan": HarnessProfile(
            name="plan",
            description="Read-only planning profile; shell requires approval and is denied headlessly.",
            system_level=SystemPromptLevel.STANDARD,
            tools=[*READ_ONLY_TOOLS, "bash"],
            permissions=plan_permissions,
            job_description=(
                "Analyze the project and produce a concrete implementation plan. "
                "Do not edit files or make changes."
            ),
        ),
        "review": HarnessProfile(
            name="review",
            description="Read-only review profile for bug, risk, and design review.",
            system_level=SystemPromptLevel.FULL,
            tools=READ_ONLY_TOOLS,
            permissions=read_only_permissions,
            job_description=(
                "Review the codebase for correctness, security, maintainability, and missing tests. "
                "Return prioritized findings with file references."
            ),
        ),
        "qe": HarnessProfile(
            name="qe",
            description="Quality-engineering profile for adversarial validation.",
            system_level=SystemPromptLevel.EXPERT,
            tools=None,
            permissions=qe_permissions,
            job_description=(
                "Act as a quality engineer. Stress assumptions, seek reproducible failures, "
                "and report evidence. Ask before shell or network actions."
            ),
        ),
    }


def create_tool_registry(profile: HarnessProfile) -> ToolRegistry:
    """Create a tool registry for a profile."""
    registry = ToolRegistry.full()
    if profile.tools is not None:
        return registry.filtered(profile.tools)
    return registry


async def run_headless(
    prompt: str,
    provider: str,
    model: str,
    profile_name: str = "build",
    working_directory: Optional[Path] = None,
    system_level: Optional[SystemPromptLevel] = None,
    session_id: Optional[str] = None,
    fork_from: Optional[str] = None,
    sandbox_backend: str = "local",
    runtime: Optional[str] = None,
) -> AgentResponse:
    """Run a single non-interactive SuperQode request."""
    profiles = get_harness_profiles()
    if profile_name not in profiles:
        valid = ", ".join(sorted(profiles))
        raise ValueError(f"Unknown profile '{profile_name}'. Valid profiles: {valid}")

    profile = profiles[profile_name]
    storage_dir = ".superqode/sessions"
    requested_working_directory = working_directory or Path.cwd()
    active_working_directory = requested_working_directory
    worktree_info = None

    if fork_from:
        manager = SessionManager(storage_dir=storage_dir)
        fork_id = session_id or f"{fork_from}-fork-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        manager.start_session(session_id=fork_from)
        session_id = manager.fork_current_session(fork_id)

    if sandbox_backend == "git-worktree":
        from .workspace.worktree import GitWorktreeManager

        worktree_session_id = session_id or f"headless-{uuid.uuid4().hex[:8]}"
        manager = GitWorktreeManager(requested_working_directory)
        worktree_info = await manager.create_qe_worktree(
            session_id=worktree_session_id,
            copy_uncommitted=True,
            keep_gitignored=True,
        )
        active_working_directory = worktree_info.path
        storage_dir = str((requested_working_directory / ".superqode" / "sessions").resolve())
        session_id = session_id or worktree_session_id

    config = AgentConfig(
        provider=provider,
        model=model,
        system_prompt_level=system_level or profile.system_level,
        working_directory=active_working_directory,
        job_description=profile.job_description,
        plan_mode=profile.name == "plan",
        enable_session_storage=True,
        session_storage_dir=storage_dir,
        session_id=session_id,
    )

    runtime_obj = create_runtime(
        resolve_runtime_name(cli=runtime),
        gateway=LiteLLMGateway(),
        tools=create_tool_registry(profile),
        config=config,
        parallel_tools=True,
        include_mcp=_env_flag("SUPERQODE_MCP_SEARCH"),
        permission_manager=PermissionManager(
            apply_backend_permissions(profile.permissions, sandbox_backend)
        ),
    )
    try:
        return await runtime_obj.run(prompt)
    finally:
        if worktree_info:
            from .workspace.worktree import GitWorktreeManager

            await GitWorktreeManager(requested_working_directory).remove_worktree(
                worktree_info, force=True
            )


def resolve_session_id(session_id_or_prefix: str, storage_dir: str = ".superqode/sessions") -> str:
    """Resolve a full session id from an exact id or unique prefix."""
    manager = SessionManager(storage_dir=storage_dir)
    sessions = manager.list_all_sessions()
    exact = [s.session_id for s in sessions if s.session_id == session_id_or_prefix]
    if exact:
        return exact[0]
    matches = [s.session_id for s in sessions if s.session_id.startswith(session_id_or_prefix)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(f"Session not found: {session_id_or_prefix}")
    raise ValueError(f"Ambiguous session prefix: {session_id_or_prefix}")


def list_sessions(
    limit: int = 20, storage_dir: str = ".superqode/sessions"
) -> List[SessionMetadata]:
    """List stored headless/local sessions."""
    return SessionManager(storage_dir=storage_dir).list_all_sessions()[:limit]


def session_tree(storage_dir: str = ".superqode/sessions") -> List[Dict[str, Any]]:
    """Return sessions with parent/child relationships."""
    sessions = SessionManager(storage_dir=storage_dir).list_all_sessions()
    children: Dict[Optional[str], List[SessionMetadata]] = {}
    for session in sessions:
        children.setdefault(session.parent_session_id, []).append(session)

    def build_node(session: SessionMetadata) -> Dict[str, Any]:
        return {
            "session_id": session.session_id,
            "parent_session_id": session.parent_session_id,
            "provider": session.provider,
            "model": session.model,
            "message_count": session.message_count,
            "updated_at": session.updated_at,
            "children": [build_node(child) for child in children.get(session.session_id, [])],
        }

    return [build_node(session) for session in children.get(None, [])]


def get_session_messages(
    session_id_or_prefix: str,
    storage_dir: str = ".superqode/sessions",
) -> tuple[SessionMetadata, List[SessionMessage]]:
    """Load session metadata and messages."""
    session_id = resolve_session_id(session_id_or_prefix, storage_dir)
    manager = SessionManager(storage_dir=storage_dir)
    metadata = manager.get_session_info(session_id)
    if not metadata:
        raise ValueError(f"Session not found: {session_id_or_prefix}")
    manager.start_session(session_id=session_id)
    return metadata, manager.get_messages()


def export_session(
    session_id_or_prefix: str,
    fmt: str = "markdown",
    storage_dir: str = ".superqode/sessions",
) -> str:
    """Export a stored session as markdown or JSON."""
    metadata, messages = get_session_messages(session_id_or_prefix, storage_dir)
    if fmt == "json":
        return json.dumps(
            {
                "session_id": metadata.session_id,
                "created_at": metadata.created_at,
                "updated_at": metadata.updated_at,
                "provider": metadata.provider,
                "model": metadata.model,
                "parent_session_id": metadata.parent_session_id,
                "title": metadata.title,
                "messages": [message.__dict__ for message in messages],
            },
            ensure_ascii=False,
            indent=2,
        )
    if fmt != "markdown":
        raise ValueError("format must be markdown or json")

    lines = [
        f"# SuperQode Session {metadata.session_id}",
        "",
        f"- Provider: {metadata.provider or 'unknown'}",
        f"- Model: {metadata.model or 'unknown'}",
        f"- Parent: {metadata.parent_session_id or 'none'}",
        f"- Created: {metadata.created_at}",
        f"- Updated: {metadata.updated_at}",
        "",
    ]
    for message in messages:
        title = message.role.title()
        if message.tool_name:
            title += f" ({message.tool_name})"
        lines.extend([f"## {title}", "", message.content, ""])
    return "\n".join(lines).rstrip() + "\n"


def response_to_json(
    response: AgentResponse,
    provider: str,
    model: str,
    profile: str,
    change_summary: Optional[Dict[str, Any]] = None,
) -> str:
    """Serialize a headless response as stable JSON."""
    payload: Dict[str, Any] = {
        "type": "superqode.result",
        "profile": profile,
        "provider": provider,
        "model": model,
        "content": response.content,
        "tool_calls_made": response.tool_calls_made,
        "iterations": response.iterations,
        "stopped_reason": response.stopped_reason,
        "success": response.stopped_reason == "complete" and not response.error,
    }
    if response.error:
        payload["error"] = response.error
    if change_summary is not None:
        payload["changes"] = change_summary
    return json.dumps(payload, ensure_ascii=False)
