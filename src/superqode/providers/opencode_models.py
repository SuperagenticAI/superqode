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


def _run_opencode(args: List[str], timeout: int = 15) -> subprocess.CompletedProcess:
    """Run an OpenCode CLI command. PATH is the only locator."""
    binary = shutil.which("opencode")
    if not binary:
        raise FileNotFoundError("opencode")
    return subprocess.run(
        [binary, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _cli_model_list() -> List[Dict]:
    """Models OpenCode currently prints (`opencode models`)."""
    verbose = _run_opencode(["models", "--verbose"])
    if verbose.returncode == 0:
        parsed = _parse_opencode_models(verbose.stdout or "")
        if parsed:
            return parsed
    plain = _run_opencode(["models"])
    if plain.returncode != 0:
        return []
    models: List[Dict] = []
    for line in (plain.stdout or "").splitlines():
        model_id = line.strip()
        if not _MODEL_ID_LINE.match(model_id) or model_id.startswith(("{", "}", '"', "[")):
            continue
        models.append(
            {
                "id": model_id,
                "name": model_id.split("/", 1)[-1],
                "provider": model_id.split("/", 1)[0],
                "is_free": _model_has_free_pricing({}, model_id=model_id),
                "context": 128000,
                "source": "opencode",
            }
        )
    return models


def _cache_catalog_path(debug_paths: str) -> Optional[str]:
    """Resolve OpenCode's models.dev cache from `opencode debug paths`."""
    from pathlib import Path

    for line in debug_paths.splitlines():
        key, _, rest = line.strip().partition(" ")
        if key != "cache" or not rest.strip():
            continue
        path = Path(rest.strip()) / "models.json"
        if path.is_file():
            return str(path)
    return None


def _configured_provider_ids(debug_v2: str) -> set[str]:
    """Provider ids OpenCode itself reports as built-in/configured."""
    text = debug_v2.strip()
    if not text:
        return set()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return set()
    providers = data.get("providers") if isinstance(data, dict) else None
    if not isinstance(providers, list):
        return set()
    ids: set[str] = set()
    for item in providers:
        if isinstance(item, dict) and item.get("id"):
            ids.add(str(item["id"]))
    return ids


def _models_from_cache_file(path: str) -> List[Dict]:
    """Read every provider/model pair from OpenCode's live models.dev cache."""
    from pathlib import Path

    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    models: List[Dict] = []
    for provider_id, provider in data.items():
        if not isinstance(provider, dict):
            continue
        raw = provider.get("models") or {}
        if isinstance(raw, dict):
            entries = raw.values()
        elif isinstance(raw, list):
            entries = raw
        else:
            continue
        for item in entries:
            if not isinstance(item, dict):
                continue
            raw_id = str(item.get("id") or "")
            if not raw_id:
                continue
            model_id = raw_id if "/" in raw_id else f"{provider_id}/{raw_id}"
            limit = item.get("limit") if isinstance(item.get("limit"), dict) else {}
            models.append(
                {
                    "id": model_id,
                    "name": item.get("name") or raw_id.split("/")[-1],
                    "provider": model_id.split("/", 1)[0],
                    "is_free": _model_has_free_pricing(
                        item, model_id=model_id, model_name=str(item.get("name") or "")
                    ),
                    "context": item.get("context")
                    or item.get("context_window")
                    or limit.get("context")
                    or 128000,
                    "source": "opencode",
                }
            )
    return models


def _enrich_cli_with_cache(cli_models: List[Dict], cache_models: List[Dict]) -> List[Dict]:
    """Fill in metadata for the models OpenCode actually offers.

    `opencode models` is authoritative about which models this install can
    route: the free Zen tier rotates, so the models.dev cache still lists
    plenty of ids that OpenCode will refuse. Only names, context windows and
    pricing come from the cache, so a model the CLI did not offer can never
    reach the picker.
    """
    by_id = {model["id"]: model for model in cache_models}
    enriched: List[Dict] = []
    for model in cli_models:
        extra = by_id.get(model["id"])
        if not extra:
            enriched.append(model)
            continue
        enriched.append(
            {
                **model,
                "name": extra.get("name") or model.get("name"),
                "context": extra.get("context") or model.get("context"),
                "is_free": bool(model.get("is_free") or extra.get("is_free")),
            }
        )
    return enriched


def _opencode_default_model(reason: str = "") -> Dict:
    """A row that defers to whatever model OpenCode is configured to use.

    Discovery can come up empty when OpenCode is installed but not signed in.
    Without this the picker has nothing to select and the session is stuck.
    """
    return {
        "id": "opencode/auto",
        "name": "OpenCode Default",
        "provider": "opencode",
        "is_free": True,
        "context": 128000,
        "source": "opencode default",
        "description": "Use OpenCode's configured default model"
        + (f" (catalog unavailable: {reason})" if reason else ""),
        "catalog_unavailable": True,
    }


def _discover_opencode_models() -> List[Dict]:
    """CLI list + OpenCode's own cache. No hardcoded model names."""
    if not shutil.which("opencode"):
        logger.warning("OpenCode not found in PATH")
        return []
    try:
        cli_models = _cli_model_list()
    except Exception as exc:  # noqa: BLE001
        logger.warning("opencode models failed: %s", exc)
        cli_models = []
    extra_providers: set[str] = set()
    cache_models: List[Dict] = []
    try:
        paths = _run_opencode(["debug", "paths"])
        cache_path = _cache_catalog_path(paths.stdout or "") if paths.returncode == 0 else None
        if cache_path:
            cache_models = _models_from_cache_file(cache_path)
    except Exception as exc:  # noqa: BLE001
        logger.debug("OpenCode models cache unavailable: %s", exc)
    try:
        v2 = _run_opencode(["debug", "v2"])
        if v2.returncode == 0:
            extra_providers = _configured_provider_ids(v2.stdout or "")
    except Exception as exc:  # noqa: BLE001
        logger.debug("OpenCode provider list unavailable: %s", exc)
    if extra_providers:
        logger.debug("OpenCode providers configured: %s", sorted(extra_providers))
    models = _enrich_cli_with_cache(cli_models, cache_models)
    if not models:
        logger.warning("OpenCode listed no models; offering its configured default")
        return [_opencode_default_model("opencode models returned nothing")]
    logger.info("Found %s models from OpenCode", len(models))
    return models


async def get_opencode_models(force_refresh: bool = False) -> List[Dict]:
    """Dynamically fetch available models from OpenCode."""
    global _cached_models, _cache_time

    if not force_refresh and _cached_models and _cache_time:
        if datetime.now() - _cache_time < timedelta(seconds=CACHE_TTL_SECONDS):
            logger.debug("Using cached OpenCode models")
            return _cached_models

    models = await asyncio.to_thread(_discover_opencode_models)
    _cached_models = models
    _cache_time = datetime.now()
    return models


def get_opencode_models_sync(force_refresh: bool = False) -> List[Dict]:
    """Synchronously fetch OpenCode models for TUI code already running an event loop."""
    global _cached_models, _cache_time

    if not force_refresh and _cached_models and _cache_time:
        if datetime.now() - _cache_time < timedelta(seconds=CACHE_TTL_SECONDS):
            logger.debug("Using cached OpenCode models")
            return _cached_models

    models = _discover_opencode_models()
    _cached_models = models
    _cache_time = datetime.now()
    return models


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
            data = json.loads(json_text)

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
