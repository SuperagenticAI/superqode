"""
OpenCode Model Discovery - Dynamically fetch available models from OpenCode.

This module provides functionality to dynamically discover available models
from OpenCode's CLI, so we don't have to manually update the model list.
"""

import asyncio
import json
import logging
import shutil
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_cached_models: Optional[List[Dict]] = None
_cache_time: Optional[datetime] = None
CACHE_TTL_SECONDS = 300


async def get_opencode_models(force_refresh: bool = False) -> List[Dict]:
    """Dynamically fetch available models from OpenCode CLI."""
    global _cached_models, _cache_time

    if not force_refresh and _cached_models and _cache_time:
        if datetime.now() - _cache_time < timedelta(seconds=CACHE_TTL_SECONDS):
            logger.debug("Using cached OpenCode models")
            return _cached_models

    opencode_path = shutil.which("opencode")
    if not opencode_path:
        logger.warning("OpenCode not found in PATH")
        return []

    try:
        cmd = ["opencode", "models", "--verbose"]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.warning(f"opencode models failed: {stderr.decode()}")
            return []

        output = stdout.decode()
        models = _parse_opencode_models(output)

        _cached_models = models
        _cache_time = datetime.now()

        logger.info(f"Found {len(models)} models from OpenCode")
        return models

    except Exception as e:
        logger.error(f"Error fetching OpenCode models: {e}")
        return []


def _parse_opencode_models(output: str) -> List[Dict]:
    """Parse OpenCode models output."""
    models = []
    blocks = output.split("opencode/")

    for block in blocks:
        if not block.strip():
            continue
        lines = block.strip().split("\n")
        if not lines:
            continue

        model_id = lines[0].strip()
        if not model_id:
            continue

        model_id = model_id.replace("opencode/", "").strip()
        json_text = "\n".join(lines[1:])

        try:
            data = json.loads(json_text[:2000])

            is_free = False
            if "cost" in data:
                is_free = data["cost"].get("input", 0) == 0 and data["cost"].get("output", 0) == 0

            context = 128000
            if "limit" in data and "context" in data["limit"]:
                context = data["limit"]["context"]

            name = data.get("name", model_id.replace("-", " ").replace("_", " ").title())

            models.append(
                {
                    "id": f"opencode/{model_id}",
                    "name": name,
                    "provider": "opencode",
                    "is_free": is_free,
                    "context": context,
                    "source": "opencode",
                }
            )
        except Exception:
            is_free = "-free" in model_id.lower() or "free" in model_id.lower()
            models.append(
                {
                    "id": f"opencode/{model_id}",
                    "name": model_id.replace("-", " ").replace("_", " ").title(),
                    "provider": "opencode",
                    "is_free": is_free,
                    "context": _estimate_context(model_id),
                    "source": "opencode",
                }
            )

    return models


def _estimate_context(model_id: str) -> int:
    """Estimate context window based on model name."""
    model_lower = model_id.lower()

    if "200k" in model_lower:
        return 200000
    elif "1m" in model_lower or "1000k" in model_lower:
        return 1000000
    elif "512k" in model_lower:
        return 512000
    elif "256k" in model_lower:
        return 256000
    elif "128k" in model_lower:
        return 128000
    elif "32k" in model_lower:
        return 32000
    return 128000


async def get_free_opencode_models() -> List[Dict]:
    """Get only free models from OpenCode."""
    all_models = await get_opencode_models()
    return [m for m in all_models if m.get("is_free", False)]


async def is_opencode_available() -> bool:
    """Check if OpenCode is installed and available."""
    return shutil.which("opencode") is not None


FALLBACK_OPENCODE_MODELS = [
    {"id": "opencode/big-pickle", "name": "Big Pickle", "is_free": True, "context": 200000},
    {
        "id": "opencode/minimax-m2.5-free",
        "name": "MiniMax M2.5 (Free)",
        "is_free": True,
        "context": 200000,
    },
    {
        "id": "opencode/nemotron-3-super-free",
        "name": "Nemotron 3 Super (Free)",
        "is_free": True,
        "context": 1000000,
    },
    {"id": "opencode/gpt-5-nano", "name": "GPT-5 Nano", "is_free": True, "context": 400000},
    {
        "id": "opencode/hy3-preview-free",
        "name": "HY3 Preview (Free)",
        "is_free": True,
        "context": 128000,
    },
    {
        "id": "opencode/ling-2.6-flash-free",
        "name": "Ling 2.6 Flash (Free)",
        "is_free": True,
        "context": 128000,
    },
    {
        "id": "opencode/trinity-large-preview-free",
        "name": "Trinity Large (Free)",
        "is_free": True,
        "context": 128000,
    },
    {
        "id": "opencode/qwen3.6-plus-free",
        "name": "Qwen 3.6 Plus (Free)",
        "is_free": True,
        "context": 128000,
    },
]


def clear_cache():
    """Clear the model cache to force refresh on next call."""
    global _cached_models, _cache_time
    _cached_models = None
    _cache_time = None


async def get_opencode_models_with_fallback() -> List[Dict]:
    """Get OpenCode models with fallback to static list."""
    models = await get_opencode_models()

    if not models:
        logger.info("Using fallback static OpenCode models")
        return FALLBACK_OPENCODE_MODELS

    return models
