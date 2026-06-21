"""Software Factory orchestration over the durable session switchboard.

The factory layer records how work moves across models, providers, harnesses,
and runtime policies without binding the session graph to one vendor or one
orchestration style.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from superqode.session.switchboard import SessionSwitchboard


FACTORY_ROUTES: dict[str, dict[str, Any]] = {
    "private": {
        "description": "Prefer local OSS models and local harnesses; block cloud handoff by default.",
        "policy": "local-first",
        "tags": ["LOCAL", "PRIVATE", "NO_SUBSCRIPTION"],
    },
    "local": {
        "description": "Run on local model providers where possible.",
        "policy": "local-first",
        "tags": ["LOCAL", "OSS"],
    },
    "cheap": {
        "description": "Prefer local or low-cost BYOK models for routine work.",
        "policy": "cost-first",
        "tags": ["CHEAP", "BYOK_OK", "LOCAL_OK"],
    },
    "best": {
        "description": "Allow the strongest configured model or runtime for hard tasks.",
        "policy": "quality-first",
        "tags": ["FRONTIER_OK", "BYOK_OK", "CLOUD_OK"],
    },
    "review": {
        "description": "Prefer reviewer/critic harnesses and high-reasoning models.",
        "policy": "review",
        "tags": ["REVIEW", "QUALITY"],
    },
    "long-context": {
        "description": "Prefer models and harnesses suitable for large repositories or transcripts.",
        "policy": "context-first",
        "tags": ["LONG_CONTEXT"],
    },
    "no-subscription": {
        "description": "Use local OSS or BYOK paths; avoid subscription-only runtimes.",
        "policy": "no-subscription",
        "tags": ["NO_SUBSCRIPTION", "LOCAL_OK", "BYOK_OK"],
    },
}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _safe_id(value: str) -> str:
    return (
        "".join(ch if ch.isalnum() or ch in "._:-" else "-" for ch in value).strip("-") or "factory"
    )


def classify_model_ref(model_ref: str) -> dict[str, Any]:
    """Return provider/model/runtime tags for a factory model reference."""
    from superqode.providers.model_specs import split_provider_model_ref

    raw = (model_ref or "").strip()
    parsed = split_provider_model_ref(raw)
    provider = parsed.provider
    model = parsed.model or raw
    provider_lower = provider.lower()
    tags: list[str] = []
    if provider_lower in {
        "local",
        "ollama",
        "lmstudio",
        "lm-studio",
        "vllm",
        "llamacpp",
        "llama.cpp",
    }:
        tags.extend(["LOCAL", "OSS", "PRIVATE"])
    elif provider_lower in {
        "byok",
        "openai",
        "anthropic",
        "google",
        "gemini",
        "openrouter",
        "huggingface",
    }:
        tags.extend(["BYOK", "CLOUD"])
    elif provider_lower in {"codex", "claude", "gemini-cli", "acp"}:
        tags.extend(["RUNTIME", "CLOUD_OR_LOCAL"])
    else:
        tags.append("MODEL")
    return {
        "raw": raw,
        "provider": provider,
        "model": model,
        "tags": tags,
    }


def default_policy() -> dict[str, Any]:
    """Default user-owned factory policy."""
    return {
        "default_route": "no-subscription",
        "routes": {
            "no-subscription": {
                "allow_cloud": False,
                "allow_subscription_runtimes": False,
                "prefer": ["ollama/qwen3-coder", "local/deepseek-coder"],
            },
            "private": {
                "allow_cloud": False,
                "prefer": ["ollama/qwen3-coder", "local/deepseek-coder"],
            },
            "cheap": {
                "allow_cloud": True,
                "prefer": ["local/deepseek-coder", "byok/openrouter/auto"],
            },
            "best": {
                "allow_cloud": True,
                "prefer": ["byok/openai/gpt-5", "byok/anthropic/claude-sonnet"],
            },
            "review": {
                "allow_cloud": True,
                "prefer": ["byok/openai/gpt-5", "ollama/qwen3-coder"],
                "harness": "review",
            },
        },
    }


@dataclass(frozen=True)
class FactoryEvent:
    id: str
    kind: str
    created_at: str
    session_id: str
    previous: dict[str, Any]
    new: dict[str, Any]
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "created_at": self.created_at,
            "session_id": self.session_id,
            "previous": dict(self.previous),
            "new": dict(self.new),
            "reason": self.reason,
        }


class SoftwareFactory:
    """Local-first factory operations over SuperQode sessions."""

    def __init__(self, storage_dir: str | Path = ".superqode/sessions") -> None:
        self.switchboard = SessionSwitchboard(storage_dir=storage_dir)
        self.policy_path = self._policy_path_for_storage(storage_dir)

    def policy(self) -> dict[str, Any]:
        if not self.policy_path.exists():
            return default_policy()
        loaded = yaml.safe_load(self.policy_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            return default_policy()
        policy = default_policy()
        policy.update(loaded)
        routes = dict(policy.get("routes") or {})
        merged_routes = dict(default_policy()["routes"])
        for name, route in routes.items():
            if isinstance(route, dict):
                merged = dict(merged_routes.get(name, {}))
                merged.update(route)
                merged_routes[name] = merged
        policy["routes"] = merged_routes
        return policy

    def init_policy(self, *, force: bool = False) -> Path:
        if self.policy_path.exists() and not force:
            return self.policy_path
        self.policy_path.parent.mkdir(parents=True, exist_ok=True)
        self.policy_path.write_text(
            yaml.safe_dump(default_policy(), sort_keys=False),
            encoding="utf-8",
        )
        return self.policy_path

    def status(self, session_id: str = "") -> dict[str, Any]:
        resolved = self.switchboard.resolve_session_id(session_id)
        info = self.switchboard.info(resolved)
        factory = dict((info.get("metadata") or {}).get("factory") or {})
        return {
            "session_id": resolved,
            "factory": factory,
            "lineage": list(factory.get("lineage") or []),
            "routes": self.routes(),
            "policy_path": str(self.policy_path),
            "policy": self.policy(),
        }

    def routes(self) -> dict[str, dict[str, Any]]:
        configured = self.policy().get("routes") or {}
        routes = {name: dict(value) for name, value in FACTORY_ROUTES.items()}
        for name, route in configured.items():
            if not isinstance(route, dict):
                continue
            merged = dict(routes.get(name, {}))
            merged.update({"config": route})
            routes[name] = merged
        return routes

    def resolve_route(self, route: str) -> dict[str, Any]:
        normalized = route.strip().lower() or str(
            self.policy().get("default_route") or "no-subscription"
        )
        routes = self.routes()
        if normalized not in routes:
            raise KeyError(f"Unknown factory route: {route}")
        payload = dict(routes[normalized])
        payload["name"] = normalized
        return payload

    def set_mode(self, mode: str, *, session_id: str = "", reason: str = "") -> dict[str, Any]:
        normalized = mode.strip().lower()
        routes = self.routes()
        if normalized not in routes:
            raise KeyError(f"Unknown factory mode/route: {mode}")
        resolved = self.switchboard.resolve_session_id(session_id)
        record = self.switchboard.info(resolved)
        factory = self._factory_metadata(record)
        previous = {"mode": factory.get("mode"), "route": factory.get("route")}
        factory["mode"] = normalized
        factory["route"] = normalized
        factory["route_policy"] = routes[normalized]
        factory["next_turn"] = self._next_turn_intent(factory)
        event = self._event(
            "mode",
            resolved,
            previous=previous,
            new={"mode": normalized, "route_policy": routes[normalized]},
            reason=reason,
        )
        self._save_factory(resolved, factory, event)
        return self.status(resolved)

    def switch_model(
        self,
        model_ref: str,
        *,
        session_id: str = "",
        runtime: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        resolved = self.switchboard.resolve_session_id(session_id)
        record = self.switchboard.info(resolved)
        factory = self._factory_metadata(record)
        parsed = classify_model_ref(model_ref)
        warnings = self.privacy_warnings(record, parsed)
        previous = {
            "provider": record.get("provider"),
            "model": record.get("model"),
            "runtime": factory.get("runtime"),
            "model_ref": factory.get("model_ref"),
        }
        new = {
            "provider": parsed["provider"],
            "model": parsed["model"],
            "runtime": runtime or factory.get("runtime") or parsed["provider"],
            "model_ref": parsed["raw"],
            "tags": parsed["tags"],
        }
        factory.update(new)
        factory["privacy_warnings"] = warnings
        factory["next_turn"] = self._next_turn_intent(factory)
        event = self._event("model", resolved, previous=previous, new=new, reason=reason)
        graph_record = self.switchboard.graph.upsert(
            resolved,
            provider=parsed["provider"] or record.get("provider") or "",
            model=parsed["model"] or record.get("model") or "",
            backend=runtime or record.get("backend") or "",
            record_metadata={"factory": self._with_event(factory, event)},
        )
        return {
            "session": graph_record.to_dict(),
            "event": event.to_dict(),
            "factory": self.status(resolved)["factory"],
            "privacy_warnings": warnings,
        }

    def switch_harness(
        self,
        harness: str,
        *,
        session_id: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        resolved = self.switchboard.resolve_session_id(session_id)
        record = self.switchboard.info(resolved)
        factory = self._factory_metadata(record)
        previous = {"harness": factory.get("harness")}
        new = {"harness": harness.strip()}
        factory.update(new)
        factory["next_turn"] = self._next_turn_intent(factory)
        event = self._event("harness", resolved, previous=previous, new=new, reason=reason)
        graph_record = self.switchboard.graph.upsert(
            resolved,
            record_metadata={"factory": self._with_event(factory, event)},
        )
        return {
            "session": graph_record.to_dict(),
            "event": event.to_dict(),
            "factory": self.status(resolved)["factory"],
        }

    def fork_model(
        self,
        source_session_id: str,
        *,
        model_ref: str,
        role: str = "",
        title: str = "",
        goal: str = "",
        new_session_id: str = "",
    ) -> dict[str, Any]:
        source = self.switchboard.resolve_session_id(source_session_id)
        parsed = classify_model_ref(model_ref)
        agent = role or parsed["model"] or parsed["provider"] or "model"
        fork_id = new_session_id or f"{_safe_id(source)}-{_safe_id(agent)}-{uuid.uuid4().hex[:4]}"
        payload = self.switchboard.fork_to_agent(
            source,
            agent=agent,
            new_session_id=fork_id,
            title=title or f"{agent} on {parsed['raw']}",
            goal=goal,
        )
        switched = self.switch_model(parsed["raw"], session_id=fork_id, reason="factory fork-model")
        return {"fork": payload, "model": switched}

    def fork_harness(
        self,
        source_session_id: str,
        *,
        harness: str,
        role: str = "",
        title: str = "",
        goal: str = "",
        new_session_id: str = "",
    ) -> dict[str, Any]:
        source = self.switchboard.resolve_session_id(source_session_id)
        agent = role or harness
        fork_id = new_session_id or f"{_safe_id(source)}-{_safe_id(agent)}-{uuid.uuid4().hex[:4]}"
        payload = self.switchboard.fork_to_agent(
            source,
            agent=agent,
            new_session_id=fork_id,
            title=title or f"{agent} using {harness}",
            goal=goal,
        )
        switched = self.switch_harness(harness, session_id=fork_id, reason="factory fork-harness")
        return {"fork": payload, "harness": switched}

    def lineage(self, session_id: str = "") -> list[dict[str, Any]]:
        return self.status(session_id)["lineage"]

    def privacy_warnings(self, record: dict[str, Any], parsed_model: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        old_factory = dict((record.get("metadata") or {}).get("factory") or {})
        previous_tags = set(old_factory.get("tags") or [])
        new_tags = set(parsed_model.get("tags") or [])
        route = str(old_factory.get("route") or self.policy().get("default_route") or "")
        route_config = dict((self.policy().get("routes") or {}).get(route) or {})
        moving_to_cloud = "CLOUD" in new_tags or parsed_model.get("provider") in {
            "openai",
            "anthropic",
            "google",
            "gemini",
            "openrouter",
            "byok",
        }
        was_private = bool(previous_tags.intersection({"LOCAL", "PRIVATE", "OSS"})) or route in {
            "private",
            "no-subscription",
        }
        if moving_to_cloud and was_private:
            warnings.append("Moving work from local/private route to a cloud-capable model.")
        if moving_to_cloud and route_config.get("allow_cloud") is False:
            warnings.append(f"Route '{route}' does not allow cloud models by policy.")
        warnings.extend(self._workspace_privacy_signals() if moving_to_cloud else [])
        return list(dict.fromkeys(warnings))

    def _factory_metadata(self, record: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(record.get("metadata") or {})
        factory = dict(metadata.get("factory") or {})
        factory.setdefault("lineage", [])
        return factory

    def _next_turn_intent(self, factory: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider": factory.get("provider") or "",
            "model": factory.get("model") or "",
            "model_ref": factory.get("model_ref") or "",
            "runtime": factory.get("runtime") or "",
            "harness": factory.get("harness") or "",
            "route": factory.get("route") or "",
            "mode": factory.get("mode") or "",
            "updated_at": _now(),
        }

    def _save_factory(self, session_id: str, factory: dict[str, Any], event: FactoryEvent) -> None:
        self.switchboard.graph.upsert(
            session_id,
            record_metadata={"factory": self._with_event(factory, event)},
        )

    def _with_event(self, factory: dict[str, Any], event: FactoryEvent) -> dict[str, Any]:
        updated = dict(factory)
        lineage = list(updated.get("lineage") or [])
        lineage.append(event.to_dict())
        updated["lineage"] = lineage[-100:]
        updated["updated_at"] = _now()
        return updated

    def _event(
        self,
        kind: str,
        session_id: str,
        *,
        previous: dict[str, Any],
        new: dict[str, Any],
        reason: str = "",
    ) -> FactoryEvent:
        return FactoryEvent(
            id=f"factory-{kind}-{uuid.uuid4().hex[:8]}",
            kind=kind,
            created_at=_now(),
            session_id=session_id,
            previous=previous,
            new=new,
            reason=reason,
        )

    def _workspace_privacy_signals(self) -> list[str]:
        signals: list[str] = []
        cwd = Path.cwd()
        for name in (".env", ".env.local", ".env.production", "secrets.yaml", "secrets.yml"):
            if (cwd / name).exists():
                signals.append(f"Sensitive-looking file present: {name}")
        if (cwd / ".git").exists():
            signals.append(
                "Git repository detected; review private/uncommitted content before cloud handoff."
            )
        return signals

    @staticmethod
    def _policy_path_for_storage(storage_dir: str | Path) -> Path:
        base = Path(storage_dir)
        if base.name == "sessions":
            return base.parent / "factory.yaml"
        return base / "factory.yaml"
