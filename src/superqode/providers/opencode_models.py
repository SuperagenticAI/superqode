"""
OpenCode Model Discovery - Dynamically fetch available models from OpenCode.

This module provides functionality to dynamically discover available models
from OpenCode's CLI, so we don't have to manually update the model list.
"""

import asyncio
import json
import logging
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_cached_models: Optional[List[Dict]] = None
_cache_time: Optional[datetime] = None
CACHE_TTL_SECONDS = 300

_FALLBACK_FREE_MODELS = [
    {
        "id": "opencode/big-pickle",
        "name": "Big Pickle",
        "context": 200000,
        "description": "OpenCode free model fallback",
    },
    {
        "id": "opencode/deepseek-v4-flash-free",
        "name": "DeepSeek V4 Flash Free",
        "context": 1000000,
        "description": "OpenCode free model fallback",
    },
    {
        "id": "opencode/minimax-m2.5-free",
        "name": "MiniMax M2.5 Free",
        "context": 204800,
        "description": "OpenCode free model fallback",
    },
    {
        "id": "opencode/nemotron-3-super-free",
        "name": "Nemotron 3 Super Free",
        "context": 1000000,
        "description": "OpenCode free model fallback",
    },
    {
        "id": "opencode/qwen3.6-plus-free",
        "name": "Qwen 3.6 Plus Free",
        "context": 262144,
        "description": "OpenCode free model fallback",
    },
]


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
            error = stderr.decode(errors="replace").strip()
            logger.warning(f"opencode models failed: {error}")
            return _opencode_fallback_models(error)

        output = stdout.decode()
        models = _parse_opencode_models(output)
        if not models:
            models = _opencode_fallback_models("OpenCode model catalog returned no models")

        _cached_models = models
        _cache_time = datetime.now()

        logger.info(f"Found {len(models)} models from OpenCode")
        return models

    except Exception as e:
        logger.error(f"Error fetching OpenCode models: {e}")
        return _opencode_fallback_models(str(e))


def get_opencode_models_sync(force_refresh: bool = False) -> List[Dict]:
    """Synchronously fetch OpenCode models for TUI code already running an event loop."""
    global _cached_models, _cache_time

    if not force_refresh and _cached_models and _cache_time:
        if datetime.now() - _cache_time < timedelta(seconds=CACHE_TTL_SECONDS):
            logger.debug("Using cached OpenCode models")
            return _cached_models

    if not shutil.which("opencode"):
        logger.warning("OpenCode not found in PATH")
        return []

    try:
        proc = subprocess.run(
            ["opencode", "models", "--verbose"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if proc.returncode != 0:
            error = (proc.stderr or proc.stdout or "").strip()
            logger.warning(f"opencode models failed: {error}")
            models = _opencode_fallback_models(error)
        else:
            models = _parse_opencode_models(proc.stdout)
            if not models:
                models = _opencode_fallback_models("OpenCode model catalog returned no models")

        _cached_models = models
        _cache_time = datetime.now()
        return models
    except Exception as e:
        logger.error(f"Error fetching OpenCode models: {e}")
        models = _opencode_fallback_models(str(e))
        _cached_models = models
        _cache_time = datetime.now()
        return models


def _opencode_fallback_models(reason: str = "") -> List[Dict]:
    """Return usable OpenCode options when catalog discovery fails."""
    fallback_models = [
        {
            **model,
            "provider": "opencode",
            "is_free": True,
            "source": "opencode fallback",
            "catalog_unavailable": True,
            "description": model["description"]
            + (f" (catalog unavailable: {reason})" if reason else ""),
        }
        for model in _FALLBACK_FREE_MODELS
    ]
    fallback_models.append(
        {
            "id": "opencode/auto",
            "name": "OpenCode Default",
            "provider": "opencode",
            "is_free": False,
            "context": 128000,
            "source": "opencode default",
            "description": "Use OpenCode's configured default model"
            + (f" (catalog unavailable: {reason})" if reason else ""),
            "catalog_unavailable": True,
        }
    )
    return fallback_models


def _parse_opencode_models(output: str) -> List[Dict]:
    """Parse OpenCode models output."""
    json_models = _parse_json_models(output)
    if json_models:
        return json_models

    models = []
    for raw_model_id, json_text in _iter_cli_model_blocks(output):
        model_id = raw_model_id.strip()
        if not model_id:
            continue

        try:
            data = json.loads(json_text[:2000])

            is_free = False
            is_free = _model_has_free_pricing(data, model_id=model_id)

            context = 128000
            if "limit" in data and "context" in data["limit"]:
                context = data["limit"]["context"]
            elif "context" in data:
                context = data["context"]
            elif "context_window" in data:
                context = data["context_window"]

            name = data.get("name", model_id.replace("-", " ").replace("_", " ").title())

            models.append(
                {
                    "id": model_id,
                    "name": name,
                    "provider": model_id.split("/", 1)[0],
                    "is_free": is_free,
                    "context": context,
                    "source": "opencode",
                }
            )
        except Exception:
            is_free = "-free" in model_id.lower() or "free" in model_id.lower()
            models.append(
                {
                    "id": model_id,
                    "name": model_id.replace("-", " ").replace("_", " ").title(),
                    "provider": model_id.split("/", 1)[0],
                    "is_free": is_free,
                    "context": _estimate_context(model_id),
                    "source": "opencode",
                }
            )

    return models


_MODEL_ID_LINE = re.compile(r"^[A-Za-z0-9_.-]+/.+")


def _iter_cli_model_blocks(output: str) -> List[tuple[str, str]]:
    """Split ``opencode models --verbose`` output into ``provider/model`` blocks."""
    blocks: List[tuple[str, str]] = []
    current_id: Optional[str] = None
    current_lines: List[str] = []

    def flush() -> None:
        nonlocal current_id, current_lines
        if current_id:
            blocks.append((current_id, "\n".join(current_lines).strip()))
        current_id = None
        current_lines = []

    for line in output.splitlines():
        stripped = line.strip()
        if _MODEL_ID_LINE.match(stripped) and not stripped.startswith(("{", "}", '"')):
            flush()
            current_id = stripped
            continue
        if current_id is not None:
            current_lines.append(line)

    flush()
    return blocks


def _parse_json_models(output: str) -> List[Dict]:
    """Parse JSON output if the OpenCode CLI emits structured models."""
    text = output.strip()
    if not text:
        return []

    try:
        data = json.loads(text)
    except Exception:
        return []

    if isinstance(data, dict):
        raw_models = data.get("models") or data.get("data") or []
    elif isinstance(data, list):
        raw_models = data
    else:
        return []

    models = []
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id") or item.get("model") or item.get("name") or ""
        if not raw_id:
            continue
        raw_id = str(raw_id)
        model_id = raw_id if "/" in raw_id else f"opencode/{raw_id}"
        models.append(
            {
                "id": model_id,
                "name": item.get("name") or str(raw_id).split("/")[-1],
                "provider": item.get("provider") or model_id.split("/", 1)[0],
                "is_free": _model_has_free_pricing(item, model_id=str(raw_id)),
                "context": item.get("context")
                or item.get("context_window")
                or item.get("limit", {}).get("context", 128000),
                "source": "opencode",
            }
        )

    return models


def _model_has_free_pricing(data: Dict, model_id: str = "", model_name: str = "") -> bool:
    """Return True when model metadata or naming indicates zero-cost use."""
    lower_id = model_id.lower()
    lower_name = model_name.lower()
    if any(
        pattern in lower_id or pattern in lower_name
        for pattern in ("free", "zero-cost", "no-cost", "gratis")
    ):
        return True

    cost = data.get("cost") or data.get("pricing") or data.get("price")
    if isinstance(cost, dict):
        input_cost = cost.get("input", cost.get("prompt", cost.get("input_cost")))
        output_cost = cost.get("output", cost.get("completion", cost.get("output_cost")))
        if input_cost is not None and output_cost is not None:
            return _is_zero_price(input_cost) and _is_zero_price(output_cost)

    if data.get("free") is True or data.get("is_free") is True:
        return True

    return False


def _is_zero_price(value) -> bool:
    try:
        return float(value) == 0
    except (TypeError, ValueError):
        return str(value).strip().lower() in {"free", "$0", "$0.00", "0"}


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


async def get_free_opencode_models(force_refresh: bool = False) -> List[Dict]:
    """Get only free models from OpenCode."""
    all_models = await get_opencode_models(force_refresh=force_refresh)
    return [m for m in all_models if m.get("is_free", False)]


async def is_opencode_available() -> bool:
    """Check if OpenCode is installed and available."""
    return shutil.which("opencode") is not None


def clear_cache():
    """Clear the model cache to force refresh on next call."""
    global _cached_models, _cache_time
    _cached_models = None
    _cache_time = None


async def get_opencode_models_with_fallback(force_refresh: bool = False) -> List[Dict]:
    """Get OpenCode models dynamically.

    Kept for compatibility with older callers; it no longer falls back to a
    static model list because OpenCode's catalog changes independently.
    """
    return await get_opencode_models(force_refresh=force_refresh)
