"""
ACP Agent Model Discovery - Dynamically fetch available models from any ACP agent.

This module provides functionality to discover available models from any ACP-compatible
coding agent via the Agent Client Protocol. This is dynamic - not hardcoded.

Usage:
    from superqode.providers.acp_models import get_acp_agent_models

    # After connecting to an ACP agent client
    models = await get_acp_agent_models(acp_client)
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ACPModel:
    """An available model from an ACP agent."""

    id: str
    name: str
    provider: Optional[str] = None
    description: Optional[str] = None
    capabilities: Optional[List[str]] = None
    context_window: Optional[int] = None
    max_output_tokens: Optional[int] = None
    is_free: bool = False


async def get_acp_agent_models(acp_client: Any) -> List[ACPModel]:
    """
    Get available models from an ACP agent via the protocol.

    Args:
        acp_client: An instance of ACP client that has get_available_models method

    Returns:
        List of ACPModel objects with free models marked
    """
    try:
        if not hasattr(acp_client, "get_available_models"):
            logger.warning("ACP client doesn't have get_available_models method")
            return []

        # Call the agent's models endpoint
        raw_models = await acp_client.get_available_models()

        models = []
        for m in raw_models:
            model_id = m.get("id", "")
            model_name = m.get("name", model_id)

            # Determine if model is free
            is_free = _is_free_model(model_id, model_name, m.get("provider"))

            # Determine context window
            context = m.get("context_window", 128000)

            models.append(
                ACPModel(
                    id=model_id,
                    name=model_name,
                    provider=m.get("provider"),
                    description=m.get("description"),
                    capabilities=m.get("capabilities"),
                    context_window=context,
                    max_output_tokens=m.get("max_output_tokens"),
                    is_free=is_free,
                )
            )

        logger.info(f"Found {len(models)} models from ACP agent")
        return models

    except Exception as e:
        logger.error(f"Error fetching ACP agent models: {e}")
        return []


def _is_free_model(model_id: str, model_name: str, provider: Optional[str]) -> bool:
    """
    Determine if a model is free based on its name/ID.

    Checks for common free model patterns:
    - Contains "free" in the name
    - Known free model IDs
    """
    lower_id = model_id.lower()
    lower_name = model_name.lower()

    # Free model patterns
    free_patterns = [
        "free",
        "zero-cost",
        "no-cost",
        "gratis",
    ]

    for pattern in free_patterns:
        if pattern in lower_id or pattern in lower_name:
            return True

    # Known free models
    known_free = [
        "big-pickle",
        "minimax-m2.5-free",
        "nemotron-3-super-free",
        "gpt-5-nano",
        "hy3-preview-free",
        "ling-2.6-flash-free",
        "trinity-large-preview-free",
        "qwen3.6-plus-free",
        "mimo-v2-flash-free",
        "trinity-mini-preview-free",
    ]

    for free_model in known_free:
        if free_model in lower_id:
            return True

    return False


async def get_free_acp_models(acp_client: Any) -> List[ACPModel]:
    """Get only free models from an ACP agent."""
    all_models = await get_acp_agent_models(acp_client)
    return [m for m in all_models if m.is_free]


def models_to_dict(models: List[ACPModel]) -> List[Dict]:
    """Convert ACPModel objects to dictionary format for UI."""
    return [
        {
            "id": m.id,
            "name": m.name,
            "provider": m.provider,
            "description": m.description,
            "context": m.context_window or 128000,
            "is_free": m.is_free,
        }
        for m in models
    ]
