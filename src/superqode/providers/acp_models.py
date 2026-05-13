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

            # Determine if model is free. Prefer dynamic pricing/capability metadata
            # when the ACP agent exposes it, then fall back to conservative naming
            # patterns for agents that only return ids/names.
            is_free = _is_free_model(model_id, model_name, m.get("provider"), m)

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


def _is_free_model(
    model_id: str,
    model_name: str,
    provider: Optional[str],
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Determine if a model is free based on its name/ID.

    Checks dynamic model metadata first and only falls back to generic
    naming patterns such as "free" when pricing is not exposed.
    """
    lower_id = model_id.lower()
    lower_name = model_name.lower()
    metadata = metadata or {}

    if metadata.get("free") is True or metadata.get("is_free") is True:
        return True

    cost = metadata.get("cost") or metadata.get("pricing") or metadata.get("price")
    if isinstance(cost, dict):
        input_cost = cost.get("input", cost.get("prompt", cost.get("input_cost")))
        output_cost = cost.get("output", cost.get("completion", cost.get("output_cost")))
        if input_cost is not None and output_cost is not None:
            return _is_zero_price(input_cost) and _is_zero_price(output_cost)

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

    return False


def _is_zero_price(value: Any) -> bool:
    try:
        return float(value) == 0
    except (TypeError, ValueError):
        return str(value).strip().lower() in {"free", "$0", "$0.00", "0"}


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
