"""
Generic free-model discovery for ACP agents.

Agents declare how their free-model catalog is discovered via the optional
``[free_models]`` section in their TOML descriptor. The schema is:

    [free_models]
    enabled = true
    discovery.command = "opencode models --verbose"
    discovery.parser = "opencode_models_table"
    discovery.timeout_seconds = 10
    fallback = [
        { id = "opencode/big-pickle", name = "Big Pickle", context = 200000 },
        # ...
    ]

The ``parser`` field names a built-in parser registered via the
``@register_parser`` decorator below. New parsers can be added without
schema changes; community-contributed TOMLs just reference the parser
they need.

Backward compatibility: the original ``providers/acp_free_models.py`` and
``providers/opencode_models.py`` keep working untouched. This module is
additive — callers opt in via ``discover_free_models_for_agent``.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .schema import Agent


CACHE_TTL_SECONDS = 300


@dataclass
class FreeModel:
    """One free model discovered from an agent's catalog."""

    id: str
    name: str
    agent_id: str
    context: int = 0
    provider: str = ""
    description: str = ""
    source: str = "discovery"  # "discovery" | "fallback"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "agent_id": self.agent_id,
            "context": self.context,
            "provider": self.provider,
            "description": self.description,
            "source": self.source,
        }


@dataclass
class FreeModelDiscovery:
    """Result of a free-model discovery probe for one agent."""

    agent_id: str
    models: List[FreeModel] = field(default_factory=list)
    used_fallback: bool = False
    error: Optional[str] = None
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# Parser registry
# ---------------------------------------------------------------------------

ParserFn = Callable[[str, str], List[FreeModel]]
_PARSERS: Dict[str, ParserFn] = {}


def register_parser(name: str) -> Callable[[ParserFn], ParserFn]:
    """Register a stdout parser under ``name``.

    Parsers receive ``(stdout, agent_id)`` and return ``List[FreeModel]``.
    They must not raise — return an empty list on parse failure so the
    caller can fall back cleanly.
    """

    def deco(fn: ParserFn) -> ParserFn:
        _PARSERS[name] = fn
        return fn

    return deco


def get_parser(name: str) -> Optional[ParserFn]:
    return _PARSERS.get(name)


def list_parsers() -> List[str]:
    return sorted(_PARSERS)


# ---------------------------------------------------------------------------
# Built-in parsers
# ---------------------------------------------------------------------------


def _has_free_pricing(data: Dict[str, Any], model_id: str = "") -> bool:
    """Heuristic: a model is free if its pricing fields are all zero or the
    id contains ``-free``. Used by the OpenCode parser; lifted here so
    other parsers can reuse the same rule."""
    if "-free" in (model_id or "").lower():
        return True
    pricing = data.get("pricing") or data.get("cost") or {}
    if not isinstance(pricing, dict):
        return False
    if not pricing:
        return False
    for value in pricing.values():
        try:
            if float(value) > 0:
                return False
        except (TypeError, ValueError):
            return False
    return True


@register_parser("opencode_models_table")
def _parse_opencode_table(stdout: str, agent_id: str) -> List[FreeModel]:
    """Parse OpenCode's ``models --verbose`` output.

    The CLI emits per-model blocks like ``opencode/<id>\\n<json>`` followed
    by the next block. Some versions emit a single JSON document instead;
    we try JSON first and fall back to block parsing.
    """
    text = (stdout or "").strip()
    if not text:
        return []

    # JSON document path
    try:
        data = json.loads(text)
        raw_models = (
            data.get("models") or data.get("data") if isinstance(data, dict) else data
        ) or []
        if isinstance(raw_models, list):
            models: List[FreeModel] = []
            for item in raw_models:
                if not isinstance(item, dict):
                    continue
                raw_id = item.get("id") or item.get("model") or item.get("name") or ""
                if not raw_id:
                    continue
                model_id = raw_id if str(raw_id).startswith("opencode/") else f"opencode/{raw_id}"
                if not _has_free_pricing(item, model_id=model_id):
                    continue
                models.append(
                    FreeModel(
                        id=model_id,
                        name=item.get("name", str(raw_id)),
                        agent_id=agent_id,
                        context=int(
                            (item.get("limit") or {}).get("context")
                            or item.get("context")
                            or item.get("context_window")
                            or 0
                        ),
                        provider="opencode",
                    )
                )
            if models:
                return models
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass

    # Block-parsing fallback (legacy OpenCode output)
    models = []
    for block in text.split("opencode/"):
        if not block.strip():
            continue
        lines = block.strip().split("\n")
        if not lines:
            continue
        model_id = lines[0].strip().replace("opencode/", "")
        if not model_id:
            continue
        json_text = "\n".join(lines[1:])[:2000]
        try:
            data = json.loads(json_text)
        except (json.JSONDecodeError, ValueError):
            # No JSON tail — use id heuristic
            if "-free" not in model_id.lower():
                continue
            models.append(
                FreeModel(
                    id=f"opencode/{model_id}",
                    name=model_id.replace("-", " ").title(),
                    agent_id=agent_id,
                    provider="opencode",
                )
            )
            continue
        if not _has_free_pricing(data, model_id=model_id):
            continue
        context = int(
            (data.get("limit") or {}).get("context")
            or data.get("context")
            or data.get("context_window")
            or 0
        )
        models.append(
            FreeModel(
                id=f"opencode/{model_id}",
                name=data.get("name", model_id.replace("-", " ").title()),
                agent_id=agent_id,
                context=context,
                provider="opencode",
            )
        )
    return models


@register_parser("openai_models_endpoint")
def _parse_openai_models(stdout: str, agent_id: str) -> List[FreeModel]:
    """Parse an OpenAI-style ``GET /v1/models`` JSON response.

    Useful for agents that expose a models endpoint via a local CLI flag.
    Free filtering is heuristic — if the agent's catalog has no pricing
    info, every model is treated as free (the caller's discovery command
    is expected to be the agent's *free* catalog endpoint, not the full
    paid one).
    """
    try:
        data = json.loads(stdout or "")
    except (json.JSONDecodeError, ValueError):
        return []
    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return [
        FreeModel(
            id=str(item.get("id") or item.get("name") or ""),
            name=str(item.get("name") or item.get("id") or ""),
            agent_id=agent_id,
            context=int(item.get("context_window") or item.get("context") or 0),
            provider=str(item.get("owned_by") or item.get("provider") or ""),
        )
        for item in items
        if isinstance(item, dict) and (item.get("id") or item.get("name"))
    ]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

# (agent_id, command) -> (timestamp, result)
_CACHE: Dict[str, tuple[float, FreeModelDiscovery]] = {}


def _fallback_models(agent: "Agent", reason: str) -> FreeModelDiscovery:
    """Build a discovery result from the agent's ``fallback`` list."""
    free_cfg = (agent.get("free_models") or {}) if isinstance(agent, dict) else {}
    fallback = free_cfg.get("fallback") or []
    models = [
        FreeModel(
            id=str(item.get("id", "")),
            name=str(item.get("name", item.get("id", ""))),
            agent_id=agent["identity"],
            context=int(item.get("context") or 0),
            provider=str(item.get("provider") or ""),
            description=str(item.get("description") or ""),
            source="fallback",
        )
        for item in fallback
        if isinstance(item, dict) and item.get("id")
    ]
    return FreeModelDiscovery(
        agent_id=agent["identity"],
        models=models,
        used_fallback=True,
        error=reason,
    )


async def discover_free_models_for_agent(
    agent: "Agent", force_refresh: bool = False
) -> FreeModelDiscovery:
    """Run the agent's declared free-model discovery probe.

    Returns a ``FreeModelDiscovery`` with the parsed models, or the
    fallback list if the discovery command is missing, the executable
    isn't on PATH, the command times out, or the parser returns nothing.
    """
    agent_id = agent.get("identity", "")
    free_cfg = agent.get("free_models") or {}
    if not free_cfg or not free_cfg.get("enabled", True):
        return FreeModelDiscovery(agent_id=agent_id)

    discovery = free_cfg.get("discovery") or {}
    command = discovery.get("command")
    parser_name = discovery.get("parser")
    timeout = float(discovery.get("timeout_seconds") or 10.0)

    cache_key = f"{agent_id}::{command}"
    if not force_refresh:
        cached = _CACHE.get(cache_key)
        if cached and (time.monotonic() - cached[0]) < CACHE_TTL_SECONDS:
            return cached[1]

    if not command or not parser_name:
        result = _fallback_models(agent, reason="no discovery configured")
        _CACHE[cache_key] = (time.monotonic(), result)
        return result

    parser = get_parser(parser_name)
    if not parser:
        result = _fallback_models(agent, reason=f"unknown parser '{parser_name}'")
        _CACHE[cache_key] = (time.monotonic(), result)
        return result

    # Quick reject: if the first word of the command isn't on PATH, skip
    # the subprocess and use the fallback. This is the same shortcut
    # `acp_discovery` uses; it's the difference between a 10s timeout and
    # an instant return when the agent isn't installed.
    head = command.split()[0]
    if head != "npx" and not shutil.which(head):
        result = _fallback_models(agent, reason="not installed")
        _CACHE[cache_key] = (time.monotonic(), result)
        return result

    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        result = _fallback_models(agent, reason=f"timeout after {timeout}s")
        _CACHE[cache_key] = (time.monotonic(), result)
        return result
    except Exception as e:
        result = _fallback_models(agent, reason=str(e))
        _CACHE[cache_key] = (time.monotonic(), result)
        return result

    duration_ms = (time.monotonic() - start) * 1000.0

    if proc.returncode != 0:
        result = _fallback_models(
            agent,
            reason=f"exit {proc.returncode}: {stderr.decode(errors='replace').strip()[:200]}",
        )
        result.duration_ms = duration_ms
        _CACHE[cache_key] = (time.monotonic(), result)
        return result

    try:
        models = parser(stdout.decode(errors="replace"), agent_id)
    except Exception as e:
        result = _fallback_models(agent, reason=f"parser error: {e}")
        result.duration_ms = duration_ms
        _CACHE[cache_key] = (time.monotonic(), result)
        return result

    if not models:
        result = _fallback_models(agent, reason="parser returned no models")
        result.duration_ms = duration_ms
        _CACHE[cache_key] = (time.monotonic(), result)
        return result

    result = FreeModelDiscovery(
        agent_id=agent_id,
        models=models,
        used_fallback=False,
        duration_ms=duration_ms,
    )
    _CACHE[cache_key] = (time.monotonic(), result)
    return result


async def discover_all_free_models(
    agents: List["Agent"], force_refresh: bool = False
) -> List[FreeModelDiscovery]:
    """Probe every agent's free-model catalog concurrently.

    Agents without a ``[free_models]`` section are skipped (empty result).
    Results are returned in the same order as ``agents``.
    """
    tasks = [discover_free_models_for_agent(a, force_refresh=force_refresh) for a in agents]
    return await asyncio.gather(*tasks)


def clear_cache() -> None:
    """Drop the discovery TTL cache. Useful in tests and after install/uninstall."""
    _CACHE.clear()
