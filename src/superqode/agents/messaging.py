"""Agent messaging utilities for direct subprocess communication."""

import subprocess
from pathlib import Path
from typing import Tuple, Optional, Dict, Any


def map_model_to_opencode(model_name: str) -> str:
    """Map user-friendly model names to OpenCode model identifiers.

    OpenCode expects just the model name (e.g., "glm-4.7-free"),
    NOT the provider/model format.
    """
    # Map user-friendly names to OpenCode model names
    model_mapping = {
        "glm-4.7": "glm-4.7-free",
        "grok-code": "grok-code",
        "kimi-k2.5": "kimi-k2.5-free",
        "gpt-5-nano": "gpt-5-nano",
        "big-pickle": "big-pickle",
        "minimax-m2.1": "minimax-m2.1-free",
        # Strip provider prefix if present
        "opencode/glm-4.7-free": "glm-4.7-free",
        "opencode/grok-code": "grok-code",
        "opencode/kimi-k2.5-free": "kimi-k2.5-free",
        "opencode/gpt-5-nano": "gpt-5-nano",
        "opencode/big-pickle": "big-pickle",
        "opencode/minimax-m2.1-free": "minimax-m2.1-free",
    }

    mapped = model_mapping.get(model_name, model_name)

    # Ensure the result has the opencode/ prefix
    if not mapped.startswith("opencode/"):
        mapped = f"opencode/{mapped}"

    return mapped


def send_message_to_agent(
    agent: Dict[str, Any], message: str, model: Optional[str] = None, cwd: Optional[Path] = None
) -> Tuple[bool, str, str]:
    """
    Send a message to an agent using subprocess.

    Args:
        agent: Agent data dictionary with 'short_name' and other metadata
        message: The message to send to the agent
        model: Optional model name to use (will be mapped for OpenCode)
        cwd: Optional working directory for subprocess

    Returns:
        Tuple of (success: bool, stdout: str, stderr: str)
    """
    agent_name = agent.get("short_name", "unknown")

    if agent_name == "opencode":
        return _send_to_opencode(message, model, cwd)
    else:
        # For other agents, return not implemented
        error_msg = f"Direct messaging not yet implemented for agent: {agent_name}"
        return (False, "", error_msg)


def _send_to_opencode(
    message: str, model: Optional[str] = None, cwd: Optional[Path] = None
) -> Tuple[bool, str, str]:
    """
    Send a message to OpenCode using subprocess.

    Args:
        message: The message to send
        model: Optional model name (will be mapped to OpenCode format)
        cwd: Optional working directory

    Returns:
        Tuple of (success: bool, stdout: str, stderr: str)
    """
    # Build the command
    cmd = ["opencode", "run", message]

    # Note: Not specifying model for better performance and accuracy
    # OpenCode tends to read config files when model is specified

    # Execute
    try:
        import subprocess as sp

        result = sp.run(cmd, capture_output=True, text=True, cwd=str(cwd) if cwd else None)

        success = result.returncode == 0
        return (success, result.stdout, result.stderr)

    except FileNotFoundError:
        error_msg = "OpenCode not found. Make sure it's installed and in your PATH."
        return (False, "", error_msg)
    except Exception as e:
        error_msg = f"Error running OpenCode: {e}"
        return (False, "", error_msg)


def send_to_role_agent(
    agent_name: str, model: Optional[str], message: str, cwd: Optional[Path] = None
) -> Tuple[bool, str, str]:
    """
    Send a message to an agent configured in a role.

    This is a convenience function for role-based mode where we already know
    the agent name and model from the role configuration.

    Args:
        agent_name: Name of the agent (e.g., "opencode")
        model: Model to use (e.g., "glm-4.7", "grok-code")
        message: The message to send
        cwd: Optional working directory

    Returns:
        Tuple of (success: bool, stdout: str, stderr: str)
    """
    # Create a minimal agent dict
    agent = {"short_name": agent_name}
    return send_message_to_agent(agent, message, model, cwd)


# Import PersonaContext for type hints (lazy import to avoid circular deps)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from superqode.agents.persona import PersonaContext


def wrap_message_with_persona(message: str, persona_context: Optional["PersonaContext"]) -> str:
    """Wrap a user message with persona context.

    This function prepends the persona system prompt to the user's message,
    allowing the AI model to respond with the appropriate role context.

    Args:
        message: The original user message
        persona_context: Optional persona context to prepend. If None or
                        invalid, returns the original message unchanged.

    Returns:
        The wrapped message with persona context, or original if no context.
        The format is: {system_prompt}{user_message}
    """
    # Handle None or invalid context gracefully
    if persona_context is None:
        return message

    # Check if persona_context has required attributes
    try:
        system_prompt = persona_context.system_prompt
        if not system_prompt:
            return message
    except (AttributeError, TypeError):
        # Invalid context object, return original message
        return message

    # Combine persona context with user message
    # The system_prompt already ends with "---\n" separator
    return f"{system_prompt}{message}"
