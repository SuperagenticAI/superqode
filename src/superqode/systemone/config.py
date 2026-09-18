"""Resolve the opt-in System One gate from spec, AgentConfig, and env.

Disabled by default. ``SUPERQODE_SYSTEMONE=stub`` turns it on without a
harness edit. Spec ``airplane_mode`` and ``client: live`` without an API
key skip the client instead of calling the network.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

SYSTEMONE_ENV = "SUPERQODE_SYSTEMONE"
LIVE_API_KEY_ENV = "TYPESAFE_API_KEY"
DEFAULT_MODEL = "jev-1.13.0"
_FALSE = {"0", "false", "off", "no", "disabled"}
_CLIENTS = {"stub", "replay", "live"}


@dataclass(frozen=True)
class SystemOneSettings:
    """Resolved runtime settings for one AgentLoop."""

    enabled: bool = False
    client: str = "stub"
    pack: str = "tool_gate"
    endpoint: str = "https://api.typesafe.ai/v1/systemone"
    api_key_env: str = "TYPESAFE_API_KEY"
    model: str = DEFAULT_MODEL
    replay_path: str = ""
    replay_trace: str = ""
    record_dir: str = ""
    timeout_ms: int = 5000
    airplane: str = "skip"
    skip_reason: str = ""

    @property
    def skip_client(self) -> bool:
        return bool(self.skip_reason)


def _truthy_env(raw: str | None) -> bool | None:
    if raw is None or not str(raw).strip():
        return None
    value = str(raw).strip().lower()
    if value in _FALSE:
        return False
    return True


def _client_from_env(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip().lower()
    if value in _CLIENTS:
        return value
    return None


def _spec_systemone(spec: Any) -> Any | None:
    if spec is None:
        return None
    return getattr(spec, "systemone", None)


def is_airplane(spec: Any = None, environ: Mapping[str, str] | None = None) -> bool:
    """True when the harness spec asked to stay offline."""
    if spec is None:
        return False
    metadata = getattr(spec, "metadata", None) or {}
    if isinstance(metadata, dict) and metadata.get("airplane_mode"):
        return True
    execution = getattr(spec, "execution_policy", None)
    config = getattr(execution, "config", None) or {}
    if isinstance(config, dict) and (config.get("airplane_mode") or config.get("strict_network")):
        return True
    return False


def resolve_systemone(
    *,
    spec: Any = None,
    explicit: Any = None,
    environ: Mapping[str, str] | None = None,
) -> SystemOneSettings:
    """Merge harness spec, AgentConfig.systemone, and env. Env wins on enable."""
    env = environ if environ is not None else os.environ
    declared = explicit if explicit is not None else _spec_systemone(spec)
    enabled = bool(getattr(declared, "enabled", False))
    client = str(getattr(declared, "client", None) or "stub").strip().lower() or "stub"
    pack = str(getattr(declared, "pack", None) or "tool_gate").strip() or "tool_gate"
    model = str(getattr(declared, "model", None) or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    endpoint = str(getattr(declared, "endpoint", "https://api.typesafe.ai/v1/systemone"))
    api_key_env = str(getattr(declared, "api_key_env", LIVE_API_KEY_ENV))
    replay_path = str(getattr(declared, "replay_path", None) or "")
    replay_trace = str(getattr(declared, "replay_trace", None) or "")
    record_dir = str(getattr(declared, "record_dir", None) or "")
    timeout_ms = int(getattr(declared, "timeout_ms", None) or 5000)
    airplane = str(getattr(declared, "airplane", None) or "skip").strip().lower() or "skip"

    env_flag = _truthy_env(env.get(SYSTEMONE_ENV))
    if env_flag is False:
        enabled = False
    elif env_flag is True:
        enabled = True
    env_client = _client_from_env(env.get(SYSTEMONE_ENV))
    if env_client:
        client = env_client
    if client not in _CLIENTS:
        client = "stub"

    skip_reason = ""
    if enabled and is_airplane(spec, env) and airplane == "skip":
        skip_reason = "airplane"
    elif (
        enabled and client == "live" and api_key_env and not str(env.get(api_key_env) or "").strip()
    ):
        skip_reason = "live_unavailable"

    return SystemOneSettings(
        enabled=enabled,
        client=client,
        pack=pack,
        model=model,
        endpoint=endpoint,
        api_key_env=api_key_env,
        replay_path=replay_path,
        replay_trace=replay_trace,
        record_dir=record_dir,
        timeout_ms=max(timeout_ms, 1),
        airplane=airplane,
        skip_reason=skip_reason,
    )


def build_client(settings: SystemOneSettings, injected: Any = None) -> Any | None:
    """Return a System One client, or None when the gate should stay silent."""
    if injected is not None:
        return injected
    if not settings.enabled or settings.skip_client:
        return None
    from .client import ReplaySystemOneClient, StubSystemOneClient

    if settings.client == "replay":
        if not settings.replay_path:
            return None
        return ReplaySystemOneClient(settings.replay_path, trace_id=settings.replay_trace or None)
    if settings.client == "live":
        from .live import LiveSystemOneClient

        return LiveSystemOneClient(
            model=settings.model,
            url=settings.endpoint,
            api_key=os.environ.get(settings.api_key_env, "") if settings.api_key_env else "",
            require_api_key=bool(settings.api_key_env),
            timeout_ms=settings.timeout_ms,
            record_dir=settings.record_dir or None,
        )
    return StubSystemOneClient()


__all__ = [
    "DEFAULT_MODEL",
    "LIVE_API_KEY_ENV",
    "SYSTEMONE_ENV",
    "SystemOneSettings",
    "build_client",
    "is_airplane",
    "resolve_systemone",
]
