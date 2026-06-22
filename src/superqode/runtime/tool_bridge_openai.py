"""Bridge SuperQode tools into openai-agents FunctionTools.

Each SuperQode Tool becomes a FunctionTool(name, description, params_json_schema,
on_invoke_tool, needs_approval). The needs_approval callable consults
PermissionManager.check_permission — ASK becomes needs_approval=True (the SDK
interrupts the run for HITL), DENY returns an error string immediately, ALLOW
runs the tool.

The SDK is imported lazily; this module is safe to load without
``uv tool install 'superqode[openai-agents]'``.
"""

from __future__ import annotations

import inspect
import json
import logging
from typing import Any, Callable, Dict, Iterable, List, Optional

from ..tools.base import Tool, ToolContext, ToolRegistry, ToolResult
from ..tools.permissions import Permission, PermissionManager
from .errors import RuntimeNotInstalledError

logger = logging.getLogger(__name__)


def construct_function_tool(
    FunctionToolCls: Any,
    *,
    needs_approval: Optional[Callable[..., Any]] = None,
    **kwargs: Any,
) -> Any:
    """Construct an openai-agents FunctionTool across SDK versions.

    Current SDKs accept ``needs_approval`` in the constructor. Some older
    installed versions do not, but the rest of our bridge is still useful for
    non-HITL tests and direct invocation. In that case, attach the predicate as
    a normal instance attribute so SuperQode callers can still inspect/use it.
    The old SDK will not auto-interrupt on that attribute, but permission DENY
    remains enforced in ``on_invoke_tool``.
    """
    try:
        accepts_needs_approval = "needs_approval" in inspect.signature(FunctionToolCls).parameters
    except (TypeError, ValueError):
        accepts_needs_approval = False

    if needs_approval is not None and accepts_needs_approval:
        return FunctionToolCls(needs_approval=needs_approval, **kwargs)

    tool = FunctionToolCls(**kwargs)
    if needs_approval is not None:
        try:
            tool.needs_approval = needs_approval
        except Exception:  # noqa: BLE001 - third-party SDK object may be immutable
            logger.debug("FunctionTool does not expose needs_approval on this SDK version")
    return tool


def _require_sdk():
    try:
        from agents.tool import FunctionTool  # noqa: F401
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "openai-agents is required for the OpenAI Agents tool bridge. "
            "Install with: uv tool install 'superqode[openai-agents]'"
        ) from exc


def _format_output(result: ToolResult) -> str:
    """Coerce a ToolResult into a string the model can consume.

    The SDK accepts strings, structured outputs, or anything with ``str()``;
    we keep it simple and return a JSON string for structured output, plain
    string otherwise. Error returns a model-visible error string (the SDK
    treats that as a tool failure the model can recover from).
    """
    if not result.success:
        return f"ERROR: {result.error or 'tool error'}"
    output = result.output
    if output is None:
        return ""
    if isinstance(output, (dict, list)):
        return json.dumps(output, default=str)
    return str(output)


def to_openai_function_tools(
    registry: ToolRegistry,
    ctx_factory: Callable[[], ToolContext],
    permission_manager: PermissionManager,
    excluded: Optional[Iterable[str]] = None,
) -> List[Any]:
    """Bridge every tool in ``registry`` to an openai-agents FunctionTool.

    Args:
        registry: SuperQode tool registry whose tools will be exposed.
        ctx_factory: Zero-arg callable that builds a fresh ToolContext per
            invocation.
        permission_manager: Used by both ``needs_approval`` and the
            ``on_invoke_tool`` wrapper to enforce permissions consistently.
        excluded: Tool names to skip (e.g. from model-profile excluded_tools).

    Returns:
        A list of ``FunctionTool`` instances ready to pass to
        ``Agent(tools=...)``.
    """
    _require_sdk()
    from agents.tool import FunctionTool

    excluded_set = set(excluded or ())
    tools_out: List[Any] = []

    for tool in registry.list():
        if tool.name in excluded_set:
            continue

        tools_out.append(_bridge_one(tool, ctx_factory, permission_manager, FunctionTool))

    return tools_out


def _bridge_one(
    sq_tool: Tool,
    ctx_factory: Callable[[], ToolContext],
    permission_manager: PermissionManager,
    FunctionToolCls: Any,
) -> Any:
    """Build one FunctionTool. Pulled out so closures bind to the right tool."""

    async def _needs_approval(_ctx: Any, params: Dict[str, Any], _call_id: str) -> bool:
        perm = permission_manager.check_permission(sq_tool.name, params)
        return perm == Permission.ASK

    async def _on_invoke(_tool_context: Any, args_json: str) -> str:
        try:
            args = json.loads(args_json) if args_json else {}
        except json.JSONDecodeError:
            return "ERROR: invalid JSON arguments"

        perm = permission_manager.check_permission(sq_tool.name, args)
        if perm == Permission.DENY:
            return f"ERROR: Permission denied for tool: {sq_tool.name}"

        ctx = ctx_factory()
        try:
            result = await sq_tool.execute(args, ctx)
        except Exception as exc:  # noqa: BLE001 — surface as tool error
            logger.exception("Tool %s raised", sq_tool.name)
            return f"ERROR: {type(exc).__name__}: {exc}"

        return _format_output(result)

    return construct_function_tool(
        FunctionToolCls,
        name=sq_tool.name,
        description=sq_tool.description,
        params_json_schema=sq_tool.parameters or {"type": "object", "properties": {}},
        on_invoke_tool=_on_invoke,
        needs_approval=_needs_approval,
        strict_json_schema=False,  # superqode tools don't all conform to strict schema
    )
