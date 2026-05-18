"""Bridge SuperQode tools into ADK BaseTool instances.

Strategy: subclass ADK's BaseTool directly so we preserve SuperQode's
JSON-Schema parameter declarations (FunctionTool would re-derive them from
Python type hints, which our Tool subclasses don't carry).

Permissions are enforced *inside* the bridged tool's run_async, so HITL and
DENY behavior is consistent with the builtin runtime.

ADK is imported lazily — this module is safe to load even when google-adk
isn't installed; calls into the bridge raise RuntimeNotInstalledError.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, Iterable, List, Optional

from ..tools.base import Tool, ToolContext, ToolRegistry, ToolResult
from ..tools.permissions import Permission, PermissionManager
from .errors import RuntimeNotInstalledError


def _require_adk():
    """Import ADK lazily; raise with install hint if missing."""
    try:
        from google.adk.tools.base_tool import BaseTool  # noqa: F401
        from google.genai import types  # noqa: F401
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "google-adk is required for the ADK tool bridge. "
            "Install with: pip install superqode[adk]"
        ) from exc


def _format_tool_result(result: ToolResult) -> Dict[str, Any]:
    """Coerce a ToolResult into a JSON-serializable dict for the model.

    Output strings stay strings (wrapped under "output") so the model sees
    them verbatim. Structured output is returned as-is when already a mapping.
    """
    if not result.success:
        return {"success": False, "error": result.error or "tool error"}
    output = result.output
    if isinstance(output, (dict, list)):
        payload = output
    else:
        payload = {"output": "" if output is None else str(output)}
    if isinstance(payload, dict):
        return {"success": True, **payload}
    return {"success": True, "output": payload}


def _check_permission(
    permission_manager: PermissionManager, tool_name: str, args: Dict[str, Any]
) -> Optional[ToolResult]:
    """Return None when allowed; a ToolResult(success=False, ...) when denied/ask.

    ADK doesn't expose an interactive HITL hook from inside a tool body, so we
    treat ASK as DENY for v1 (matches builtin behavior when no UI is wired in).
    The Phase-2 doc page notes this gap; ADK's `tool_confirmation` is the v2 path.
    """
    perm = permission_manager.check_permission(tool_name, args)
    if perm == Permission.DENY:
        return ToolResult(
            success=False, output="", error=f"Permission denied for tool: {tool_name}"
        )
    if perm == Permission.ASK:
        return ToolResult(
            success=False,
            output="",
            error=(
                f"Permission required for tool: {tool_name}. "
                "ADK runtime cannot prompt; configure permissions or use the builtin runtime."
            ),
        )
    return None


def make_bridged_tool_class():
    """Return a ``BridgedSuperQodeTool`` class bound to the live ADK BaseTool.

    Defined inside a function so importing this module never imports ADK.
    """
    _require_adk()
    from google.adk.tools.base_tool import BaseTool
    from google.adk.tools.tool_context import ToolContext as ADKToolContext
    from google.genai import types

    class BridgedSuperQodeTool(BaseTool):
        """ADK tool that delegates to a SuperQode Tool, with permission enforcement."""

        def __init__(
            self,
            sq_tool: Tool,
            ctx_factory: Callable[[], ToolContext],
            permission_manager: PermissionManager,
        ):
            super().__init__(name=sq_tool.name, description=sq_tool.description)
            self._sq_tool = sq_tool
            self._ctx_factory = ctx_factory
            self._permission_manager = permission_manager

        def _get_declaration(self):  # type: ignore[override]
            # SuperQode parameters are already JSON Schema. ADK's Schema is a
            # pydantic model that accepts the same shape.
            schema = self._sq_tool.parameters or {"type": "object", "properties": {}}
            return types.FunctionDeclaration(
                name=self.name,
                description=self.description,
                parameters=types.Schema.model_validate(schema),
            )

        async def run_async(  # type: ignore[override]
            self,
            *,
            args: Dict[str, Any],
            tool_context: ADKToolContext,
        ) -> Any:
            denial = _check_permission(self._permission_manager, self.name, args)
            if denial is not None:
                return _format_tool_result(denial)
            ctx = self._ctx_factory()
            result = await self._sq_tool.execute(args, ctx)
            return _format_tool_result(result)

    return BridgedSuperQodeTool


def to_adk_tools(
    registry: ToolRegistry,
    ctx_factory: Callable[[], ToolContext],
    permission_manager: PermissionManager,
    excluded: Optional[Iterable[str]] = None,
) -> List[Any]:
    """Bridge every tool in ``registry`` into an ADK BaseTool instance.

    Args:
        registry: SuperQode tool registry whose tools will be exposed to ADK.
        ctx_factory: Zero-arg callable returning a fresh ToolContext per call.
        permission_manager: Used to enforce permissions inside each bridged tool.
        excluded: Tool names to skip (e.g. from model profile excluded_tools).

    Returns:
        A list of ADK BaseTool instances ready to pass to LlmAgent(tools=...).
    """
    BridgedSuperQodeTool = make_bridged_tool_class()
    excluded_set = set(excluded or ())
    bridged: List[Any] = []
    for tool in registry.list():
        if tool.name in excluded_set:
            continue
        bridged.append(BridgedSuperQodeTool(tool, ctx_factory, permission_manager))
    return bridged
