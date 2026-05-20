"""Bridge SuperQode tools into PydanticAI toolsets.

PydanticAI's high-level function tools are typed-function first, but its
``AbstractToolset`` API accepts raw ``ToolDefinition.parameters_json_schema``.
That lower-level path is the right fit for SuperQode because our tools already
own JSON Schema parameter declarations.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from ..tools.base import Tool, ToolContext, ToolRegistry, ToolResult
from ..tools.permissions import Permission, PermissionManager
from .errors import RuntimeNotInstalledError


def _require_pydanticai():
    try:
        from pydantic_ai.toolsets import AbstractToolset  # noqa: F401
        from pydantic_ai.toolsets.abstract import ToolsetTool  # noqa: F401
        from pydantic_ai.tools import ToolDefinition  # noqa: F401
        from pydantic_core import SchemaValidator, core_schema  # noqa: F401
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "PydanticAI runtime requires the 'pydanticai' extra. "
            "Install with: pip install superqode[pydanticai]"
        ) from exc


def _format_tool_result(result: ToolResult) -> Any:
    if result.success:
        return result.output
    if result.output:
        return f"Error: {result.error}\n{result.output}"
    return f"Error: {result.error or 'tool error'}"


def _permission_denial_or_approval(
    permission_manager: PermissionManager,
    tool_name: str,
    args: dict[str, Any],
    *,
    tool_call_approved: bool,
) -> ToolResult | None:
    permission = permission_manager.check_permission(tool_name, args)
    if permission == Permission.DENY:
        return ToolResult(
            success=False,
            output="",
            error=f"Permission denied for tool: {tool_name}",
        )
    if permission == Permission.ASK:
        if tool_call_approved:
            return None
        from pydantic_ai.exceptions import ApprovalRequired

        raise ApprovalRequired
    return None


def make_superqode_toolset_class():
    """Return a PydanticAI toolset class without importing PydanticAI at module load."""

    _require_pydanticai()
    from pydantic_ai.toolsets import AbstractToolset
    from pydantic_ai.toolsets.abstract import ToolsetTool
    from pydantic_ai.tools import RunContext, ToolDefinition
    from pydantic_core import SchemaValidator, core_schema

    args_validator = SchemaValidator(
        core_schema.dict_schema(core_schema.str_schema(), core_schema.any_schema())
    )

    class SuperQodePydanticAIToolset(AbstractToolset[Any]):
        """PydanticAI toolset backed by SuperQode's ToolRegistry."""

        def __init__(
            self,
            registry: ToolRegistry,
            ctx_factory: Callable[[], ToolContext],
            permission_manager: PermissionManager,
            excluded: Iterable[str] | None = None,
            on_tool_call: Callable[[str, dict[str, Any]], None] | None = None,
            on_tool_result: Callable[[str, ToolResult], None] | None = None,
        ) -> None:
            self._registry = registry
            self._ctx_factory = ctx_factory
            self._permission_manager = permission_manager
            self._on_tool_call = on_tool_call
            self._on_tool_result = on_tool_result
            self._excluded = set(excluded or ())
            self._tools: dict[str, Tool] = {
                tool.name: tool for tool in registry.list() if tool.name not in self._excluded
            }

        @property
        def id(self) -> str:
            return "superqode"

        async def get_tools(self, ctx: RunContext[Any]) -> dict[str, ToolsetTool[Any]]:
            return {
                name: ToolsetTool(
                    toolset=self,
                    tool_def=ToolDefinition(
                        name=name,
                        description=tool.description,
                        parameters_json_schema=tool.parameters
                        or {"type": "object", "properties": {}},
                    ),
                    max_retries=ctx.max_retries,
                    args_validator=args_validator,
                )
                for name, tool in self._tools.items()
            }

        async def call_tool(
            self,
            name: str,
            tool_args: dict[str, Any],
            ctx: RunContext[Any],
            tool: ToolsetTool[Any],
        ) -> Any:
            sq_tool = self._tools[name]
            if self._on_tool_call is not None:
                self._on_tool_call(name, tool_args)
            denial = _permission_denial_or_approval(
                self._permission_manager,
                name,
                tool_args,
                tool_call_approved=bool(getattr(ctx, "tool_call_approved", False)),
            )
            if denial is not None:
                if self._on_tool_result is not None:
                    self._on_tool_result(name, denial)
                return _format_tool_result(denial)
            result = await sq_tool.execute(tool_args, self._ctx_factory())
            if self._on_tool_result is not None:
                self._on_tool_result(name, result)
            return _format_tool_result(result)

    return SuperQodePydanticAIToolset


def to_pydanticai_toolsets(
    registry: ToolRegistry,
    ctx_factory: Callable[[], ToolContext],
    permission_manager: PermissionManager,
    excluded: Iterable[str] | None = None,
    on_tool_call: Callable[[str, dict[str, Any]], None] | None = None,
    on_tool_result: Callable[[str, ToolResult], None] | None = None,
) -> list[Any]:
    """Return PydanticAI toolsets that expose SuperQode tools."""

    if not registry.list():
        return []
    toolset_cls = make_superqode_toolset_class()
    return [
        toolset_cls(
            registry,
            ctx_factory,
            permission_manager,
            excluded,
            on_tool_call=on_tool_call,
            on_tool_result=on_tool_result,
        )
    ]
