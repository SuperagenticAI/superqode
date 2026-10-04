"""Validated, opt-in outbound routes. Secrets are resolved only by the host."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


def positive(value: Any, name: str, default: int, maximum: int) -> int:
    value = default if value is None else value
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be an integer between 0 and {maximum}")
    return value


@dataclass(frozen=True)
class DelegationPeer:
    name: str
    url: str
    description: str = ""
    credential_env: str = ""
    hosted: bool = False
    credits: int = 0
    skill: str = ""
    subscription_method: str = "GET"

    @classmethod
    def parse(cls, value: dict) -> DelegationPeer:
        if not isinstance(value, dict):
            raise ValueError("Each A2A peer must be an object")
        extra = set(value) - set(cls.__dataclass_fields__)
        if extra:
            raise ValueError(
                f"Unknown A2A peer fields: {sorted(extra)}; use credential_env for secrets"
            )
        try:
            peer = cls(**value)
        except TypeError as error:
            raise ValueError("A2A peer requires name and url") from error
        if any(
            not isinstance(getattr(peer, name), str)
            for name in (
                "name",
                "url",
                "description",
                "credential_env",
                "skill",
                "subscription_method",
            )
        ):
            raise ValueError("A2A peer names, URLs and credential references must be strings")
        parsed = urlsplit(peer.url)
        if (
            not peer.name
            or len(peer.name) > 128
            or parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "A2A peer needs a name and an HTTP(S) URL without credentials/query/fragment"
            )
        if not isinstance(peer.hosted, bool) or peer.subscription_method not in {"GET", "POST"}:
            raise ValueError("Invalid A2A peer hosting/subscription policy")
        positive(peer.credits, "peer credits", 0, 1_000_000_000)
        if peer.hosted and (not peer.credential_env or not peer.credits or not peer.skill):
            raise ValueError(
                "Hosted A2A peers require credential_env, skill and a bounded credit tariff"
            )
        return peer


@dataclass(frozen=True)
class DelegationPolicy:
    enabled: bool = False
    hosted_enabled: bool = False
    max_hosted_credits: int = 0
    max_tasks: int = 8
    max_parallel: int = 2
    max_payload_bytes: int = 128_000
    max_result_bytes: int = 1_000_000
    request_timeout: int = 30
    deadline_seconds: int = 300
    poll_seconds: int = 2
    peers: tuple[DelegationPeer, ...] = field(default_factory=tuple)

    @classmethod
    def from_config(cls, config: dict | None) -> DelegationPolicy:
        raw = dict(config or {})
        extra = set(raw) - set(cls.__dataclass_fields__) - {"paid_fallback"}
        if extra:
            raise ValueError(f"Unknown RLM A2A configuration: {sorted(extra)}")
        for name in ("enabled", "hosted_enabled", "paid_fallback"):
            if name in raw and not isinstance(raw[name], bool):
                raise ValueError(f"a2a.{name} must be a boolean")
        if raw.pop("paid_fallback", False):
            raise ValueError(
                "Automatic paid fallback is unsupported; select an enabled hosted peer explicitly"
            )
        peers = tuple(DelegationPeer.parse(p) for p in raw.pop("peers", []))
        if len({p.name for p in peers}) != len(peers):
            raise ValueError("A2A peer aliases must be unique")
        defaults = cls()
        bounds = {
            "max_hosted_credits": 1_000_000_000,
            "max_tasks": 1000,
            "max_parallel": 64,
            "max_payload_bytes": 4_000_000,
            "max_result_bytes": 16_000_000,
            "request_timeout": 300,
            "deadline_seconds": 86400,
            "poll_seconds": 60,
        }
        for name, maximum in bounds.items():
            raw[name] = positive(raw.get(name), name, getattr(defaults, name), maximum)
            if name != "max_hosted_credits" and raw[name] == 0:
                raise ValueError(f"{name} must be positive")
        return cls(peers=peers, **raw)

    def peer(self, name: str) -> DelegationPeer:
        if not self.enabled:
            raise PermissionError("A2A routing is disabled; a stored key does not enable it")
        peer = next((p for p in self.peers if p.name == name), None)
        if peer is None:
            raise PermissionError(f"A2A peer {name!r} is not configured")
        if peer.hosted and (not self.hosted_enabled or not self.max_hosted_credits):
            raise PermissionError(
                "Hosted A2A routing requires explicit opt-in and a credit allowance"
            )
        return peer

    def inventory(self) -> list[dict]:
        if not self.enabled:
            return []
        return [
            {
                "name": p.name,
                "description": p.description,
                "skill": p.skill,
                "hosted": p.hosted,
                "credits": p.credits,
            }
            for p in self.peers
            if not p.hosted or (self.hosted_enabled and self.max_hosted_credits)
        ]
