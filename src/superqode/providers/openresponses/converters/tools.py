"""
Tool Definition Conversion.

Converts between Gateway ToolDefinition and Open Responses tool formats.

Gateway Format:
    ToolDefinition(
        name="read_file",
        description="Read a file",
        parameters={"type": "object", "properties": {...}}
    )

Open Responses Format:
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {...}}
        }
    }
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ...gateway.base import ToolDefinition


def convert_tools_to_openresponses(tools: Optional[List[ToolDefinition]]) -> List[Dict[str, Any]]:
    """
    Convert Gateway tool definitions to Open Responses format.

    Args:
        tools: List of ToolDefinition objects

    Returns:
        List of Open Responses tool dicts
    """
    if not tools:
        return []

    result = []
    for tool in tools:
        result.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
        )

    return result


def convert_tools_from_openresponses(tools: Optional[List[Dict[str, Any]]]) -> List[ToolDefinition]:
    """
    Convert Open Responses tools to Gateway ToolDefinition objects.

    Args:
        tools: List of Open Responses tool dicts

    Returns:
        List of ToolDefinition objects
    """
    if not tools:
        return []

    result = []
    for tool in tools:
        tool_type = tool.get("type", "")

        if tool_type == "function":
            func = tool.get("function", {})
            result.append(
                ToolDefinition(
                    name=func.get("name", ""),
                    description=func.get("description", ""),
                    parameters=func.get("parameters", {}),
                )
            )

        elif tool_type == "code_interpreter":
            # Built-in tool - create a placeholder definition
            result.append(
                ToolDefinition(
                    name="code_interpreter",
                    description="Execute code in a sandboxed environment",
                    parameters={
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "The code to execute",
                            },
                        },
                        "required": ["code"],
                    },
                )
            )

        elif tool_type == "file_search":
            # Built-in tool
            result.append(
                ToolDefinition(
                    name="file_search",
                    description="Search files in vector stores",
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query",
                            },
                        },
                        "required": ["query"],
                    },
                )
            )

        elif tool_type == "apply_patch":
            # Built-in tool
            result.append(
                ToolDefinition(
                    name="apply_patch",
                    description="Apply a patch to files",
                    parameters={
                        "type": "object",
                        "properties": {
                            "patch": {
                                "type": "string",
                                "description": "The patch to apply in unified diff format",
                            },
                        },
                        "required": ["patch"],
                    },
                )
            )

        elif tool_type == "web_search":
            # Built-in tool
            result.append(
                ToolDefinition(
                    name="web_search",
                    description="Search the web for information",
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query",
                            },
                        },
                        "required": ["query"],
                    },
                )
            )

    return result


def create_openresponses_function_tool(
    name: str,
    description: str,
    parameters: Dict[str, Any],
    strict: bool = False,
) -> Dict[str, Any]:
    """
    Create an Open Responses function tool definition.

    Args:
        name: Tool name
        description: Tool description
        parameters: JSON Schema for parameters
        strict: Enable strict mode for structured outputs

    Returns:
        Open Responses tool dict
    """
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
            "strict": strict,
        },
    }


def create_code_interpreter_tool(container: Optional[str] = None) -> Dict[str, Any]:
    """
    Create an Open Responses code interpreter tool.

    Args:
        container: Optional container configuration

    Returns:
        Open Responses tool dict
    """
    tool = {"type": "code_interpreter"}
    if container:
        tool["container"] = container
    return tool


def create_file_search_tool(
    vector_store_ids: Optional[List[str]] = None,
    max_num_results: int = 20,
    ranking_options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create an Open Responses file search tool.

    Args:
        vector_store_ids: List of vector store IDs to search
        max_num_results: Maximum number of results
        ranking_options: Ranking configuration

    Returns:
        Open Responses tool dict
    """
    tool: Dict[str, Any] = {
        "type": "file_search",
        "max_num_results": max_num_results,
    }
    if vector_store_ids:
        tool["vector_store_ids"] = vector_store_ids
    if ranking_options:
        tool["ranking_options"] = ranking_options
    return tool


def create_apply_patch_tool() -> Dict[str, Any]:
    """
    Create an Open Responses apply patch tool.

    Returns:
        Open Responses tool dict
    """
    return {"type": "apply_patch"}


def create_web_search_tool(
    search_context_size: str = "medium",
    user_location: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create an Open Responses web search tool.

    Args:
        search_context_size: Size of search context ("low", "medium", "high")
        user_location: Optional user location for localized results

    Returns:
        Open Responses tool dict
    """
    tool: Dict[str, Any] = {
        "type": "web_search",
        "search_context_size": search_context_size,
    }
    if user_location:
        tool["user_location"] = user_location
    return tool
