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
    output_schema: Optional[Path] = None,
    rubric: Optional[str] = None,
) -> AgentResponse:
    """Run a single non-interactive SuperQode request.

    ``output_schema`` pins the final answer to a JSON Schema: the schema is
    embedded in the prompt, the final message is parsed and validated, and
    one corrective retry runs on failure. The outcome lands on
    ``response.structured_output`` / ``response.schema_errors``.

    ``rubric`` enables self-grading: a grader call judges the answer against
    the rubric and "needs_revision" feedback re-enters the loop.
    """
    profiles = get_harness_profiles()
    if profile_name not in profiles:
        valid = ", ".join(sorted(profiles))
        raise ValueError(f"Unknown profile '{profile_name}'. Valid profiles: {valid}")

    schema: Optional[Dict[str, Any]] = None
    if output_schema is not None:
        from .agent.structured_output import load_schema, schema_instruction

        schema = load_schema(Path(output_schema))
        prompt = prompt + schema_instruction(schema)

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
        rubric=rubric,
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
        response = await runtime_obj.run(prompt)
        if schema is not None:
            from .agent.structured_output import check_output, correction_prompt

            payload, errors = check_output(response.content, schema)
            if errors:
                # One corrective retry; session storage keeps the context.
                response = await runtime_obj.run(correction_prompt(errors, schema))
                payload, errors = check_output(response.content, schema)
            response.structured_output = payload
            response.schema_errors = errors
        return response
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
    if fmt == "html":
        return _render_session_html(metadata, messages)
    if fmt != "markdown":
        raise ValueError("format must be markdown, json, or html")

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


_HTML_ROLE_COLORS = {
    "user": "#2563eb",
    "assistant": "#16a34a",
    "tool": "#9333ea",
    "system": "#6b7280",
}


def _render_session_html(metadata, messages) -> str:
    """Self-contained HTML transcript: one shareable file, no external assets."""
    import html as html_mod

    rows = []
    for message in messages:
        role = (message.role or "?").lower()
        color = _HTML_ROLE_COLORS.get(role, "#6b7280")
        title = role.title()
        if getattr(message, "tool_name", None):
            title += f" · {html_mod.escape(message.tool_name)}"
        body = html_mod.escape(message.content or "")
        rows.append(
            f'<section class="msg" style="border-left-color:{color}">'
            f'<header style="color:{color}">{title}</header>'
            f"<pre>{body}</pre></section>"
        )
    title = html_mod.escape(metadata.title or metadata.session_id)
    meta_line = html_mod.escape(
        f"{metadata.provider or 'unknown'}/{metadata.model or 'unknown'} · "
        f"created {metadata.created_at} · updated {metadata.updated_at}"
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SuperQode Session {html_mod.escape(metadata.session_id)}</title>
<style>
  body {{ background:#0b0e14; color:#d6dde6; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
         max-width: 60rem; margin: 2rem auto; padding: 0 1rem; }}
  h1 {{ font-size: 1.2rem; }} .meta {{ color:#8b949e; font-size:.85rem; margin-bottom:1.5rem; }}
  .msg {{ border-left: 3px solid; margin: .8rem 0; padding: .4rem .8rem; background:#11151d; border-radius: 0 6px 6px 0; }}
  .msg header {{ font-weight: 600; font-size:.8rem; text-transform: uppercase; letter-spacing:.06em; }}
  .msg pre {{ white-space: pre-wrap; word-break: break-word; margin:.4rem 0 0; font-size:.85rem; line-height:1.45; }}
</style>
</head>
<body>
<h1>SuperQode Session {title}</h1>
<div class="meta">{meta_line}</div>
{"".join(rows)}
</body>
</html>
"""


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
    if getattr(response, "schema_errors", None) is not None:
        payload["structured_output"] = response.structured_output
        payload["schema_errors"] = response.schema_errors
        payload["schema_valid"] = not response.schema_errors
        if response.schema_errors:
            payload["success"] = False
    return json.dumps(payload, ensure_ascii=False)
