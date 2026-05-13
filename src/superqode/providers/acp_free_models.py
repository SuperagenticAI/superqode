"""
ACP Agent Free Model Discovery - Find which ACP agents provide free models.

This module discovers which ACP agents support free models by:
1. Getting list of all supported ACP agents from registry
2. For each agent, checking if it can be queried for models
3. Identifying which agents have free models available

This is dynamic - not a hardcoded list!
"""

import logging
import shutil
from typing import Dict, List, Optional, Set
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FreeModelInfo:
    """Information about a free model from an ACP agent."""

    agent_id: str
    agent_name: str
    model_id: str
    model_name: str
    context_window: int = 128000


@dataclass
class AgentFreeModels:
    """Free models available from an ACP agent."""

    agent_id: str
    agent_name: str
    models: List[FreeModelInfo]
    is_available: bool = False
    error: Optional[str] = None


# Generic free model patterns. Specific model ids are intentionally excluded
# because agent catalogs change independently.
FREE_MODEL_PATTERNS = [
    "free",
    "zero-cost",
    "no-cost",
    "gratis",
]


def _is_free_model(model_id: str, model_name: str) -> bool:
    """Check if a model is free based on its ID or name."""
    lower_id = model_id.lower()
    lower_name = model_name.lower()

    for pattern in FREE_MODEL_PATTERNS:
        if pattern in lower_id or pattern in lower_name:
            return True
    return False


async def check_pi_free_models() -> AgentFreeModels:
    """Check if Pi can use free models (via DeepSeek free tier)."""
    try:
        # Pi supports multiple providers - DeepSeek has a free tier
        # But requires API key setup, so not truly "free" like Cline
        # Let's check if pi-acp is installed
        if not shutil.which("pi-acp") and not shutil.which("pi"):
            return AgentFreeModels(
                agent_id="pi",
                agent_name="Pi",
                models=[],
                is_available=False,
                error="Pi not installed (npm install -g @earendil-works/pi-coding-agent pi-acp)",
            )

        # Pi uses external providers - DeepSeek has free tier but needs API key
        # Not truly free without setup
        return AgentFreeModels(
            agent_id="pi",
            agent_name="Pi",
            models=[],
            is_available=True,
            error="Uses external providers (OpenAI, Anthropic, Google, DeepSeek) - DeepSeek has free tier",
        )

    except Exception as e:
        return AgentFreeModels(
            agent_id="pi",
            agent_name="Pi",
            models=[],
            is_available=False,
            error=str(e),
        )


async def check_cline_free_models() -> AgentFreeModels:
    """Check Cline for available free models.

    Cline's available/free model catalog is not exposed through a stable CLI
    discovery command here, so SuperQode does not synthesize a static list.
    """
    try:
        if not shutil.which("cline"):
            return AgentFreeModels(
                agent_id="cline",
                agent_name="Cline",
                models=[],
                is_available=False,
                error="Cline not installed",
            )

        return AgentFreeModels(
            agent_id="cline",
            agent_name="Cline",
            models=[],
            is_available=True,
            error="Cline free model catalog is not dynamically discoverable",
        )

    except Exception as e:
        return AgentFreeModels(
            agent_id="cline",
            agent_name="Cline",
            models=[],
            is_available=False,
            error=str(e),
        )


async def check_opencode_free_models() -> AgentFreeModels:
    """Check OpenCode for available free models via CLI."""
    try:
        # Check if opencode is installed
        if not shutil.which("opencode"):
            return AgentFreeModels(
                agent_id="opencode",
                agent_name="OpenCode",
                models=[],
                is_available=False,
                error="OpenCode not installed",
            )

        from superqode.providers.opencode_models import get_free_opencode_models

        dynamic_models = await get_free_opencode_models(force_refresh=True)
        models = [
            FreeModelInfo(
                agent_id="opencode",
                agent_name="OpenCode",
                model_id=model["id"],
                model_name=model.get("name", model["id"].split("/")[-1]),
                context_window=model.get("context", 128000),
            )
            for model in dynamic_models
        ]

        return AgentFreeModels(
            agent_id="opencode",
            agent_name="OpenCode",
            models=models,
            is_available=True,
        )

    except Exception as e:
        return AgentFreeModels(
            agent_id="opencode",
            agent_name="OpenCode",
            models=[],
            is_available=False,
            error=str(e),
        )


def _parse_opencode_models_for_free(output: str) -> List[FreeModelInfo]:
    """Parse OpenCode models output and extract free models."""
    from superqode.providers.opencode_models import _parse_opencode_models

    return [
        FreeModelInfo(
            agent_id="opencode",
            agent_name="OpenCode",
            model_id=model["id"],
            model_name=model.get("name", model["id"].split("/")[-1]),
            context_window=model.get("context", 128000),
        )
        for model in _parse_opencode_models(output)
        if model.get("is_free", False)
    ]


async def discover_agents_with_free_models() -> List[AgentFreeModels]:
    """
    Discover which ACP agents have free models available.

    This queries multiple sources:
    1. OpenCode CLI - dynamic model catalog and pricing metadata
    2. Other ACP agents (future: query via ACP protocol)

    Returns:
        List of AgentFreeModels, sorted by number of free models
    """
    results = []

    # Check OpenCode
    opencode_result = await check_opencode_free_models()
    if opencode_result.models:
        results.append(opencode_result)

    # Check Cline only if it exposes a dynamic free-model source in the future.
    cline_result = await check_cline_free_models()
    if cline_result.models:
        results.append(cline_result)

    logger.info(
        f"Discovered {len(results)} agents with free models: {[r.agent_id for r in results]}"
    )
    return results


async def get_all_free_models() -> List[FreeModelInfo]:
    """
    Get list of all free models from all available ACP agents.

    Returns:
        Consolidated list of free models from all sources
    """
    all_models = []

    agents = await discover_agents_with_free_models()

    for agent in agents:
        if agent.is_available:
            all_models.extend(agent.models)

    # Sort by agent then by name
    all_models.sort(key=lambda x: (x.agent_id, x.model_name))

    return all_models


# ============================================================================
# PROVIDER DISCOVERY - Which providers have free models?
# ============================================================================


async def check_provider_free_models(provider_id: str) -> Optional[AgentFreeModels]:
    """
    Check a BYOK provider for free models.

    Uses the models.dev API to find providers with free models.
    """
    try:
        from superqode.providers.models_dev import get_models_dev

        client = get_models_dev()
        await client.load()

        models = client.get_models_for_provider(provider_id)

        free_models = []
        for model_id, model_info in models.items():
            # Check if model has zero price (free)
            if model_info.input_price == 0 and model_info.output_price == 0:
                free_models.append(
                    FreeModelInfo(
                        agent_id=provider_id,
                        agent_name=client.get_provider(provider_id).name
                        if client.get_provider(provider_id)
                        else provider_id,
                        model_id=model_id,
                        model_name=model_info.name,
                        context_window=model_info.context_window,
                    )
                )

        return AgentFreeModels(
            agent_id=provider_id,
            agent_name=provider_id.title(),
            models=free_models,
            is_available=len(free_models) > 0,
        )

    except Exception as e:
        logger.debug(f"Error checking provider {provider_id}: {e}")
        return None


async def discover_all_free_sources() -> Dict[str, List[AgentFreeModels]]:
    """
    Discover all sources that have free models.

    Returns:
        Dictionary with 'agents' and 'providers' keys containing free model sources
    """
    all_sources = {
        "agents": [],  # ACP agents (OpenCode, etc.)
        "providers": [],  # BYOK providers (OpenRouter, Groq, etc.)
    }

    # Discover from ACP agents
    agent_results = await discover_agents_with_free_models()
    all_sources["agents"] = agent_results

    # Discover from providers that have free models
    # Known providers with free tiers: groq, openrouter, opencode
    free_provider_ids = ["groq", "openrouter", "opencode"]

    for pid in free_provider_ids:
        result = await check_provider_free_models(pid)
        if result and result.is_available:
            # Avoid duplicates - already in agents
            if result.agent_id not in [a.agent_id for a in all_sources["agents"]]:
                all_sources["providers"].append(result)

    return all_sources


# ============================================================================
# AGENT DISCOVERY - Which agents can we query?
# ============================================================================


async def get_discoverable_agents() -> List[Dict]:
    """
    Get list of agents where we can discover free models dynamically.

    Returns:
        List of agents with their discovery method
    """
    agents = []

    # OpenCode - can query via CLI
    if shutil.which("opencode"):
        agents.append(
            {
                "id": "opencode",
                "name": "OpenCode",
                "method": "cli",
                "command": "opencode models --verbose",
                "has_free_models": True,
            }
        )

    # Cline - installed, but no dynamic free-model catalog available here
    if shutil.which("cline"):
        agents.append(
            {
                "id": "cline",
                "name": "Cline",
                "method": "unavailable",
                "has_free_models": False,
                "note": "Free model catalog is not dynamically discoverable",
            }
        )

    # Pi - requires setup but can use DeepSeek free tier
    if shutil.which("pi-acp") or shutil.which("pi"):
        agents.append(
            {
                "id": "pi",
                "name": "Pi",
                "method": "external_provider",
                "providers": ["deepseek", "anthropic", "openai", "google"],
                "has_free_models": False,  # Requires API key setup
                "note": "DeepSeek has free tier",
            }
        )

    return agents


# Export for easy use
__all__ = [
    "FreeModelInfo",
    "AgentFreeModels",
    "discover_agents_with_free_models",
    "get_all_free_models",
    "get_discoverable_agents",
]
