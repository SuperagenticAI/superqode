"""Tool-calling capability detection and testing for local models.

This module provides utilities for detecting and testing whether local
models support function/tool calling, which is critical for coding assistants.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from superqode.providers.local.base import (
    LocalModel,
    ToolTestResult,
    detect_model_family,
)


# Models known to support tool calling well (by family and version)
TOOL_CAPABLE_MODELS: Dict[str, Dict[str, Any]] = {
    # Llama family
    "llama3.1": {
        "supports_tools": True,
        "parallel_tools": True,
        "tool_choice": ["auto", "required", "none"],
        "notes": "Native tool support in Llama 3.1+",
    },
    "llama3.2": {
        "supports_tools": True,
        "parallel_tools": True,
        "tool_choice": ["auto", "required", "none"],
        "notes": "Native tool support",
    },
    "llama3.3": {
        "supports_tools": True,
        "parallel_tools": True,
        "tool_choice": ["auto", "required", "none"],
        "notes": "Latest Llama with improved tool support",
    },
    # Qwen family
    "qwen2.5": {
        "supports_tools": True,
        "parallel_tools": True,
        "tool_choice": ["auto", "required", "none"],
        "notes": "Excellent tool support in Qwen 2.5",
        "recommended_params": {"num_ctx": 16384},
    },
    "qwen2.5-coder": {
        "supports_tools": True,
        "parallel_tools": True,
        "tool_choice": ["auto", "required", "none"],
        "notes": "Optimized for code, great tool support",
        "recommended_params": {"num_ctx": 32768},
    },
    # Mistral family
    "mistral": {
        "supports_tools": True,
        "parallel_tools": False,
        "tool_choice": ["auto", "none"],
        "notes": "Good tool support",
    },
    "mixtral": {
        "supports_tools": True,
        "parallel_tools": True,
        "tool_choice": ["auto", "required", "none"],
        "notes": "MoE with tool support",
    },
    # DeepSeek
    "deepseek-coder": {
        "supports_tools": True,
        "parallel_tools": False,
        "tool_choice": ["auto"],
        "notes": "Code-focused with tool support",
    },
    "deepseek-coder-v2": {
        "supports_tools": True,
        "parallel_tools": True,
        "tool_choice": ["auto", "required"],
        "notes": "Improved tool support in v2",
    },
    # Command-R
    "command-r": {
        "supports_tools": True,
        "parallel_tools": True,
        "tool_choice": ["auto", "required", "none"],
        "notes": "Cohere's tool-focused model",
    },
    # Hermes (fine-tuned for tools)
    "hermes": {
        "supports_tools": True,
        "parallel_tools": True,
        "tool_choice": ["auto", "required"],
        "notes": "Fine-tuned specifically for function calling",
    },
    "nous-hermes": {
        "supports_tools": True,
        "parallel_tools": True,
        "tool_choice": ["auto", "required"],
        "notes": "NousResearch fine-tune for tools",
    },
    # Functionary (specialized for function calling)
    "functionary": {
        "supports_tools": True,
        "parallel_tools": True,
        "tool_choice": ["auto", "required", "none"],
        "notes": "Specialized for OpenAI-compatible function calling",
    },
}

# Models that need special handling or have quirks
TOOL_QUIRKS: Dict[str, Dict[str, Any]] = {
    "qwen2.5-coder": {
        "needs_num_ctx": 16384,  # Needs larger context for tools
        "json_mode_helps": True,
    },
    "llama3.1": {
        "supports_parallel_tools": True,
        "native_tool_format": True,
    },
    "mistral": {
        "tool_use_special_tokens": True,
        "max_tools_per_call": 1,  # Single tool per response
    },
}

# Models that definitely do NOT support tools
NO_TOOL_SUPPORT: Set[str] = {
    "tinyllama",
    "phi-2",
    "gemma",  # Base Gemma doesn't support tools
    "stablelm",
    "falcon",
    "mpt",
    "dolly",
    "vicuna",
    "alpaca",
}

# Test tool definition for capability testing
TEST_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "The city name"},
                "unit": {
                    "type": "string",
                    "enum": ["celsius", "fahrenheit"],
                    "description": "Temperature unit",
                },
            },
            "required": ["city"],
        },
    },
}

# Test message that should trigger tool use
TEST_MESSAGE = {"role": "user", "content": "What's the weather like in Paris?"}


@dataclass
class ToolCapabilityInfo:
    """Detailed tool capability information for a model.

    Attributes:
        model_id: Model identifier
        supports_tools: Whether tool calling is supported
        parallel_tools: Whether parallel tool calls are supported
        tool_choice_modes: Supported tool_choice modes
        recommended_params: Recommended parameters for tool use
        quirks: Known quirks and workarounds
        verified: Whether capability was verified by testing
        confidence: Confidence level (heuristic, tested, confirmed)
        notes: Additional notes
    """

    model_id: str
    supports_tools: bool = False
    parallel_tools: bool = False
    tool_choice_modes: List[str] = field(default_factory=list)
    recommended_params: Dict[str, Any] = field(default_factory=dict)
    quirks: Dict[str, Any] = field(default_factory=dict)
    verified: bool = False
    confidence: str = "unknown"  # unknown, heuristic, tested, confirmed
    notes: str = ""


def get_tool_capability_info(model_id: str) -> ToolCapabilityInfo:
    """Get tool capability information for a model based on heuristics.

    This provides a quick assessment without actually testing the model.

    Args:
        model_id: Model identifier (e.g., "llama3.2:8b-instruct-q4_K_M")

    Returns:
        ToolCapabilityInfo with heuristic-based assessment.
    """
    model_lower = model_id.lower()

    # Check if definitely not supported
    for pattern in NO_TOOL_SUPPORT:
        if pattern in model_lower:
            return ToolCapabilityInfo(
                model_id=model_id,
                supports_tools=False,
                confidence="heuristic",
                notes=f"Model family '{pattern}' does not support tools",
            )

    # Check known capable models
    for pattern, info in TOOL_CAPABLE_MODELS.items():
        if pattern in model_lower:
            quirks = TOOL_QUIRKS.get(pattern, {})
            return ToolCapabilityInfo(
                model_id=model_id,
                supports_tools=info.get("supports_tools", False),
                parallel_tools=info.get("parallel_tools", False),
                tool_choice_modes=info.get("tool_choice", []),
                recommended_params=info.get("recommended_params", {}),
                quirks=quirks,
                confidence="heuristic",
                notes=info.get("notes", ""),
            )

    # Unknown - check for instruct variant which might support tools
    if any(x in model_lower for x in ["instruct", "chat", "assistant"]):
        return ToolCapabilityInfo(
            model_id=model_id,
            supports_tools=False,  # Assume no until tested
            confidence="unknown",
            notes="Instruct model, may support tools. Test to confirm.",
        )

    return ToolCapabilityInfo(
        model_id=model_id,
        supports_tools=False,
        confidence="unknown",
        notes="Unknown model, tool support uncertain",
    )


async def test_tool_calling(
    model_id: str, provider_host: str = "http://localhost:11434", timeout: float = 60.0
) -> ToolTestResult:
    """Test if a model can execute tool calls.

    Performs an actual API call to test tool calling capability.

    Args:
        model_id: Model identifier
        provider_host: Provider host URL (default: Ollama)
        timeout: Request timeout in seconds

    Returns:
        ToolTestResult with actual test results.
    """
    from urllib.request import Request, urlopen
    from urllib.error import URLError, HTTPError

    start_time = time.time()

    # First check heuristics
    info = get_tool_capability_info(model_id)
    if info.confidence == "heuristic" and not info.supports_tools:
        return ToolTestResult(model_id=model_id, supports_tools=False, notes=info.notes)

    # Prepare test request
    endpoint = f"{provider_host}/api/chat"

    payload = {
        "model": model_id,
        "messages": [TEST_MESSAGE],
        "tools": [TEST_TOOL],
        "stream": False,
    }

    # Add recommended params if any
    if info.recommended_params:
        payload["options"] = info.recommended_params

    loop = asyncio.get_event_loop()

    def do_test():
        try:
            headers = {"Content-Type": "application/json"}
            body = json.dumps(payload).encode("utf-8")
            request = Request(endpoint, data=body, headers=headers, method="POST")

            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))

        except HTTPError as e:
            if e.code == 400:
                # Model might not support tools parameter
                return {"error": "tools_not_supported", "code": 400}
            return {"error": str(e), "code": e.code}
        except URLError as e:
            return {"error": str(e.reason)}
        except Exception as e:
            return {"error": str(e)}

    try:
        response = await loop.run_in_executor(None, do_test)
        latency = (time.time() - start_time) * 1000

        # Check for errors
        if "error" in response:
            error_msg = response.get("error", "")
            if "tools_not_supported" in str(error_msg) or response.get("code") == 400:
                return ToolTestResult(
                    model_id=model_id,
                    supports_tools=False,
                    latency_ms=latency,
                    notes="Model returned error for tools parameter",
                )
            return ToolTestResult(
                model_id=model_id,
                supports_tools=False,
                error=str(error_msg),
                latency_ms=latency,
            )

        # Check for tool calls in response
        message = response.get("message", {})
        tool_calls = message.get("tool_calls", [])

        if tool_calls:
            # Verify tool call structure
            valid_call = False
            parallel = len(tool_calls) > 1

            for call in tool_calls:
                func = call.get("function", {})
                if func.get("name") == "get_weather":
                    valid_call = True
                    break

            return ToolTestResult(
                model_id=model_id,
                supports_tools=valid_call,
                parallel_tools=parallel,
                tool_choice=info.tool_choice_modes or ["auto"],
                latency_ms=latency,
                notes="Tool calling verified by test"
                if valid_call
                else "Response had tool_calls but wrong function",
            )
        else:
            # Model responded but didn't use tools
            content = message.get("content", "")
            if content:
                return ToolTestResult(
                    model_id=model_id,
                    supports_tools=False,
                    latency_ms=latency,
                    notes="Model responded with text instead of tool call",
                )

            return ToolTestResult(
                model_id=model_id,
                supports_tools=False,
                latency_ms=latency,
                notes="Empty response, tool calling may not be supported",
            )

    except Exception as e:
        return ToolTestResult(
            model_id=model_id,
            supports_tools=False,
            error=str(e),
            notes="Test failed with exception",
        )


def get_recommended_coding_models() -> List[Dict[str, Any]]:
    """Get list of models recommended for coding with tool support.

    Returns:
        List of model recommendations with capability info.
    """
    recommendations = [
        {
            "model": "qwen2.5-coder:32b",
            "family": "qwen",
            "params": "32B",
            "tool_support": "excellent",
            "coding_quality": "excellent",
            "context": "32K",
            "notes": "Best for coding with tools, requires ~20GB VRAM",
        },
        {
            "model": "qwen2.5-coder:7b",
            "family": "qwen",
            "params": "7B",
            "tool_support": "excellent",
            "coding_quality": "very good",
            "context": "32K",
            "notes": "Good balance of quality and resources",
        },
        {
            "model": "llama3.3:70b",
            "family": "llama",
            "params": "70B",
            "tool_support": "excellent",
            "coding_quality": "excellent",
            "context": "128K",
            "notes": "Latest Llama, excellent overall",
        },
        {
            "model": "llama3.2:8b",
            "family": "llama",
            "params": "8B",
            "tool_support": "excellent",
            "coding_quality": "good",
            "context": "128K",
            "notes": "Efficient with native tool support",
        },
        {
            "model": "deepseek-coder-v2:16b",
            "family": "deepseek",
            "params": "16B",
            "tool_support": "good",
            "coding_quality": "excellent",
            "context": "128K",
            "notes": "Specialized for code generation",
        },
        {
            "model": "mistral:7b",
            "family": "mistral",
            "params": "7B",
            "tool_support": "good",
            "coding_quality": "good",
            "context": "32K",
            "notes": "Reliable tool support, efficient",
        },
        {
            "model": "functionary:latest",
            "family": "functionary",
            "params": "varies",
            "tool_support": "excellent",
            "coding_quality": "good",
            "context": "8K",
            "notes": "Specialized for function calling",
        },
    ]

    return recommendations


def estimate_tool_support(model: LocalModel) -> str:
    """Estimate tool support level for a model.

    Args:
        model: LocalModel instance

    Returns:
        Support level: "excellent", "good", "limited", "none", "unknown"
    """
    info = get_tool_capability_info(model.id)

    if not info.supports_tools:
        if info.confidence == "heuristic":
            return "none"
        return "unknown"

    if info.parallel_tools and len(info.tool_choice_modes) >= 3:
        return "excellent"

    if info.supports_tools:
        return "good"

    return "limited"
