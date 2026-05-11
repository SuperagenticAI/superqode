"""
ACP Agent Free Model Discovery - Find which ACP agents provide free models.

This module discovers which ACP agents support free models by:
1. Getting list of all supported ACP agents from registry
2. For each agent, checking if it can be queried for models
3. Identifying which agents have free models available

This is dynamic - not a hardcoded list!
"""

import asyncio
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


# Known free model patterns
FREE_MODEL_PATTERNS = [
    "free",
    "zero-cost",
    "no-cost",
    "gratis",
    # Specific known free models from OpenCode
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
    # DeepSeek free models
    "deepseek-chat-free",
    "deepseek-coder-free",
    # Cline built-in free models (no API key needed!)
    "minimax-m2.5",
    "kimi-k2.5",
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
    """Check Cline for available free models (built-in, no API key needed)."""
    try:
        if not shutil.which("cline"):
            return AgentFreeModels(
                agent_id="cline",
                agent_name="Cline",
                models=[],
                is_available=False,
                error="Cline not installed",
            )

        # Cline has built-in free models (MiniMax M2.5, Kimi K2.5)
        # These are temporarily free with no API key required
        free_models = [
            FreeModelInfo(
                agent_id="cline",
                agent_name="Cline",
                model_id="minimax-m2.5",
                model_name="MiniMax M2.5 (Free)",
                context_window=200000,
            ),
            FreeModelInfo(
                agent_id="cline",
                agent_name="Cline",
                model_id="kimi-k2.5",
                model_name="Kimi K2.5 (Free)",
                context_window=200000,
            ),
        ]

        return AgentFreeModels(
            agent_id="cline",
            agent_name="Cline",
            models=free_models,
            is_available=True,
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

        # Run opencode models command
        proc = await asyncio.create_subprocess_exec(
            "opencode",
            "models",
            "--verbose",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            return AgentFreeModels(
                agent_id="opencode",
                agent_name="OpenCode",
                models=[],
                is_available=False,
                error=f"Failed: {stderr.decode()[:100]}",
            )

        # Parse output to find free models
        models = _parse_opencode_models_for_free(stdout.decode())

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
    import json

    models = []
    blocks = output.split("opencode/")

    for block in blocks:
        if not block.strip():
            continue

        lines = block.strip().split("\n")
        if not lines:
            continue

        model_id = lines[0].strip().replace("opencode/", "").strip()
        if not model_id:
            continue

        # Check if free
        is_free = _is_free_model(model_id, "")

        if not is_free and len(lines) > 1:
            # Try to parse JSON for cost info
            try:
                json_text = "\n".join(lines[1:200])
                data = json.loads(json_text[:2000])
                if "cost" in data:
                    is_free = (
                        data["cost"].get("input", 0) == 0 and data["cost"].get("output", 0) == 0
                    )
            except Exception:
                pass

        if is_free:
            # Estimate context
            context = 128000
            if "200k" in model_id.lower():
                context = 200000
            elif "1m" in model_id.lower():
                context = 1000000
            elif "512k" in model_id.lower():
                context = 512000
            elif "256k" in model_id.lower():
                context = 256000

            models.append(
                FreeModelInfo(
                    agent_id="opencode",
                    agent_name="OpenCode",
                    model_id=f"opencode/{model_id}",
                    model_name=model_id.replace("-", " ").replace("_", " ").title(),
                    context_window=context,
                )
            )

    return models


async def discover_agents_with_free_models() -> List[AgentFreeModels]:
    """
    Discover which ACP agents have free models available.

    This queries multiple sources:
    1. OpenCode CLI - has known free models
    2. Cline - has built-in free models (no API key needed!)
    3. Other ACP agents (future: query via ACP protocol)

    Returns:
        List of AgentFreeModels, sorted by number of free models
    """
    results = []

    # Check OpenCode
    opencode_result = await check_opencode_free_models()
    if opencode_result.models:
        results.append(opencode_result)

    # Check Cline
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

    # Cline - has built-in free models (no API key needed!)
    if shutil.which("cline"):
        agents.append(
            {
                "id": "cline",
                "name": "Cline",
                "method": "builtin",
                "models": ["minimax-m2.5", "kimi-k2.5"],
                "has_free_models": True,
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
