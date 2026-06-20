"""Managed-agent harness backends.

These adapters model remote managed agent platforms as explicit, opt-in
execution backends. Direct model APIs need credentials, while deployed managed
agent runtimes may also need tenant-specific endpoints. When required
configuration is absent the backend fails closed instead of silently running
locally.
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from ...agent.loop import AgentResponse
from ..events import HarnessEvent
from .base import HarnessBackendCapabilities, HarnessBackendRequest, HarnessBackendResult


@dataclass(frozen=True)
class ManagedBackendConfig:
    """Resolved provider-managed backend endpoint configuration."""

    endpoint: str
    api_base: str
    mode: str
    base_agent: str
    api_key_env: str
    access_token_env: str
    api_key: str
    access_token: str
    auth_type: str
    agent_id: str
    provider: str
    headers: dict[str, str]
    api_revision: str
    system_instruction: str
    stream: bool
    background: bool
    store: bool
    environment: dict[str, Any] | None
    tools: list[Any]

    @property
    def configured(self) -> bool:
        credential = self.access_token if self.auth_type == "bearer" else self.api_key
        return bool(_request_endpoint(self) and (credential or not self.api_key_env))


class ManagedAgentHarnessBackend:
    """Remote managed-agent backend over a configured HTTPS endpoint."""

    def __init__(self, name: str):
        self.name = name
        provider_label = (
            "Google Agent Engine"
            if name == "google-agent-engine"
            else "Anthropic Managed Agents"
        )
        self.capabilities = HarnessBackendCapabilities(
            backend=name,
            supports_coding=True,
            supports_no_tool=False,
            supports_streaming=True,
            supports_approvals=False,
            supports_sandbox=True,
            supports_shell=True,
            supports_mcp=False,
            supports_typed_output=False,
            supports_workflow_children=True,
            event_detail="provider-normalized",
            availability="configured" if _has_default_endpoint(name) else "needs-config",
            install_hint=_install_hint(name),
            notes=(
                f"{provider_label} is modeled as a remote execution backend.",
                "Live task submission requires provider credentials and, for deployed agents, an endpoint.",
            ),
        )

    async def run(self, request: HarnessBackendRequest) -> HarnessBackendResult:
        config = _resolve_config(self.name, request)
        if not config.configured:
            return _unconfigured_result(self.name, config)

        endpoint = _request_endpoint(config)
        payload = _request_payload(config, request)
        try:
            raw = await asyncio.to_thread(
                _post_json,
                endpoint,
                payload,
                headers=config.headers,
                timeout=_timeout_seconds(request),
            )
        except Exception as exc:
            response = AgentResponse(
                content="",
                messages=[],
                tool_calls_made=0,
                iterations=0,
                stopped_reason="error",
                error=str(exc),
            )
            return HarnessBackendResult(
                response=response,
                backend=self.name,
                runtime=self.name,
                metadata={
                    "managed_backend": self.name,
                    "configured": True,
                    "endpoint": _redact_endpoint(endpoint),
                    "error_type": type(exc).__name__,
                },
            )

        content = _extract_content(raw)
        response = AgentResponse(
            content=content,
            messages=[],
            tool_calls_made=0,
            iterations=1,
            stopped_reason="complete",
        )
        return HarnessBackendResult(
            response=response,
            backend=self.name,
            runtime=self.name,
            metadata={
                "managed_backend": self.name,
                "configured": True,
                "endpoint": _redact_endpoint(endpoint),
                "agent_id": config.agent_id,
                "mode": config.mode,
                "raw_response": raw if isinstance(raw, dict) else {"value": raw},
                "events": [
                    HarnessEvent(
                        type="managed_agent.request",
                        data={
                            "backend": self.name,
                            "endpoint": _redact_endpoint(endpoint),
                            "agent_id": config.agent_id,
                            "mode": config.mode,
                        },
                    ),
                    HarnessEvent(
                        type="managed_agent.response",
                        data={"backend": self.name, "content_chars": len(content)},
                    ),
                ],
            },
        )

    async def stream(self, request: HarnessBackendRequest) -> AsyncIterator[HarnessEvent]:
        config = _resolve_config(self.name, request)
        if config.configured:
            result = await self.run(request)
            yield HarnessEvent(
                type="managed_agent.response",
                data={
                    "backend": self.name,
                    "content": result.response.content,
                    "endpoint": _redact_endpoint(_request_endpoint(config)),
                },
                session_id=request.session_id or "",
            )
            return
        yield HarnessEvent(
            type="managed_backend_unconfigured",
            data={
                "backend": self.name,
                "message": _unconfigured_message(self.name, config),
            },
            session_id=request.session_id or "",
        )


def _resolve_config(backend: str, request: HarnessBackendRequest) -> ManagedBackendConfig:
    remote = request.spec.remote_harness
    config = {
        **dict(remote.config or {}),
        **dict(request.spec.runtime.config or {}),
        **dict(request.metadata.get("managed_backend") or {}),
    }
    prefix = "GOOGLE_AGENT" if backend == "google-agent-engine" else "ANTHROPIC_MANAGED_AGENT"
    mode = str(
        config.get("mode")
        or ("generate_content" if backend == "google-agent-engine" else "endpoint")
    ).strip()
    api_base = str(
        config.get("api_base")
        or (
            "https://generativelanguage.googleapis.com/v1beta"
            if backend == "google-agent-engine"
            else ""
        )
    ).strip()
    endpoint = str(
        config.get("endpoint")
        or os.getenv(f"SUPERQODE_{prefix}_ENDPOINT")
        or os.getenv(f"{prefix}_ENDPOINT")
        or ""
    ).strip()
    base_agent = str(
        config.get("base_agent")
        or config.get("model")
        or ("gemini-flash-latest" if backend == "google-agent-engine" else "")
    ).strip()
    auth_type = str(
        config.get("auth_type") or ("api_key" if backend == "google-agent-engine" else "api_key")
    ).strip()
    api_key_env = str(
        config.get("api_key_env")
        or (
            "GEMINI_API_KEY"
            if backend == "google-agent-engine"
            else "ANTHROPIC_API_KEY"
        )
    ).strip()
    fallback_api_key_env = "GOOGLE_API_KEY" if backend == "google-agent-engine" else ""
    api_key = str(
        config.get("api_key")
        or os.getenv(api_key_env)
        or (os.getenv(fallback_api_key_env) if fallback_api_key_env else "")
        or ""
    ).strip()
    access_token_env = str(
        config.get("access_token_env")
        or ("GOOGLE_OAUTH_ACCESS_TOKEN" if backend == "google-agent-engine" else "")
    ).strip()
    access_token = str(
        config.get("access_token")
        or (os.getenv(access_token_env) if access_token_env else "")
        or ""
    ).strip()
    agent_id = str(config.get("agent_id") or remote.agent_id or "").strip()
    provider = str(config.get("provider") or remote.provider or backend).strip()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    credential = access_token if auth_type == "bearer" else api_key
    if credential:
        if backend == "anthropic-managed":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = str(
                config.get("anthropic_version") or "2023-06-01"
            )
        elif auth_type == "bearer":
            headers["Authorization"] = f"Bearer {access_token}"
        else:
            headers["x-goog-api-key"] = api_key
    api_revision = str(config.get("api_revision") or "").strip()
    if api_revision:
        headers["Api-Revision"] = api_revision
    extra_headers = config.get("headers")
    if isinstance(extra_headers, dict):
        for key, value in extra_headers.items():
            headers[str(key)] = str(value)
    system_instruction = str(
        config.get("system_instruction")
        or (
            "You are a remote coding agent invoked by SuperQode. Return a concise answer "
            "and include a unified diff when code changes are required."
            if backend == "google-agent-engine"
            else ""
        )
    )
    environment = config.get("environment")
    tools = config.get("tools") if isinstance(config.get("tools"), list) else []
    return ManagedBackendConfig(
        endpoint=endpoint,
        api_base=api_base,
        mode=mode,
        base_agent=base_agent,
        api_key_env=api_key_env,
        access_token_env=access_token_env,
        api_key=api_key,
        access_token=access_token,
        auth_type=auth_type,
        agent_id=agent_id,
        provider=provider,
        headers=headers,
        api_revision=api_revision,
        system_instruction=system_instruction,
        stream=_bool_config(config.get("stream"), default=False),
        background=_bool_config(config.get("background"), default=True),
        store=_bool_config(config.get("store"), default=True),
        environment=environment if isinstance(environment, dict) else None,
        tools=tools,
    )


def _request_payload(config: ManagedBackendConfig, request: HarnessBackendRequest) -> dict[str, Any]:
    if config.provider == "google-agent-engine" and _is_google_generate_content(config):
        return _google_generate_content_payload(config, request)
    if config.provider == "google-agent-engine" and _is_google_interaction(config):
        return _google_interaction_payload(config, request)
    return {
        "agent_id": config.agent_id,
        "input": request.prompt,
        "prompt": request.prompt,
        "session_id": request.session_id,
        "metadata": {
            "harness": request.spec.name,
            "provider": request.provider,
            "model": request.model,
            "runtime": request.runtime,
            "sandbox_backend": request.sandbox_backend,
            "working_directory": str(request.working_directory),
        },
    }


def _request_endpoint(config: ManagedBackendConfig) -> str:
    if config.endpoint:
        return config.endpoint
    if config.provider == "google-agent-engine":
        api_base = config.api_base.rstrip("/")
        if _is_google_generate_content(config):
            model = config.base_agent.removeprefix("models/")
            return f"{api_base}/models/{model}:generateContent"
        if _is_google_interaction(config):
            return f"{api_base}/interactions"
    return config.endpoint


def _is_google_generate_content(config: ManagedBackendConfig) -> bool:
    return config.mode.replace("-", "_") in {"generate_content", "direct"}


def _is_google_interaction(config: ManagedBackendConfig) -> bool:
    return config.mode.replace("-", "_") in {"interaction", "interactions", "persisted", "agent"}


def _google_generate_content_payload(
    config: ManagedBackendConfig, request: HarnessBackendRequest
) -> dict[str, Any]:
    return {
        "systemInstruction": {"parts": [{"text": config.system_instruction}]},
        "contents": [
            {
                "role": "user",
                "parts": [{"text": _render_google_prompt(request)}],
            }
        ],
    }


def _google_interaction_payload(
    config: ManagedBackendConfig, request: HarnessBackendRequest
) -> dict[str, Any]:
    agent = config.agent_id or config.base_agent
    payload: dict[str, Any] = {
        "stream": config.stream,
        "background": config.background,
        "store": config.store,
        "agent": agent,
        "input": [
            {
                "type": "user_input",
                "content": [{"type": "text", "text": request.prompt}],
            }
        ],
    }
    if config.environment:
        payload["environment"] = config.environment
    if config.tools:
        payload["tools"] = config.tools
    return payload


def _render_google_prompt(request: HarnessBackendRequest) -> str:
    return "\n".join(
        [
            request.prompt,
            "",
            "SuperQode harness metadata:",
            f"- harness: {request.spec.name}",
            f"- provider: {request.provider}",
            f"- model: {request.model}",
            f"- runtime: {request.runtime}",
            f"- sandbox_backend: {request.sandbox_backend}",
            f"- working_directory: {request.working_directory}",
        ]
    )


def _post_json(
    endpoint: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    timeout: float,
) -> Any:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"managed backend HTTP {exc.code}: {body[:1000]}") from exc
    if not body.strip():
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"content": body}


def _extract_content(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, dict):
        return str(raw)
    for key in ("content", "output", "outputText", "output_text", "response", "text", "result"):
        value = raw.get(key)
        if isinstance(value, str):
            return value
    messages = raw.get("messages")
    if isinstance(messages, list):
        parts: list[str] = []
        for message in messages:
            if isinstance(message, dict):
                value = message.get("content") or message.get("text")
                if isinstance(value, str):
                    parts.append(value)
        if parts:
            return "\n".join(parts)
    candidates = raw.get("candidates")
    if isinstance(candidates, list):
        parts = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            if not isinstance(content, dict):
                continue
            for part in content.get("parts") or []:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
        if parts:
            return "\n".join(parts)
    return json.dumps(raw, indent=2, sort_keys=True)


def _timeout_seconds(request: HarnessBackendRequest) -> float:
    config = request.spec.remote_harness.config or {}
    return float(config.get("timeout_seconds") or request.metadata.get("timeout_seconds") or 300)


def _unconfigured_result(
    backend: str, config: ManagedBackendConfig
) -> HarnessBackendResult:
    response = AgentResponse(
        content="",
        messages=[],
        tool_calls_made=0,
        iterations=0,
        stopped_reason="error",
        error=_unconfigured_message(backend, config),
    )
    return HarnessBackendResult(
        response=response,
        backend=backend,
        runtime=backend,
        metadata={
            "managed_backend": backend,
            "configured": False,
            "required_endpoint": True,
            "api_key_env": config.api_key_env,
        },
    )


def _unconfigured_message(backend: str, config: ManagedBackendConfig) -> str:
    if backend == "google-agent-engine" and _is_google_generate_content(config):
        return (
            "Managed backend 'google-agent-engine' requires Gemini credentials. "
            f"Set {config.api_key_env} or configure remote_harness.config.api_key."
        )
    return (
        f"Managed backend '{backend}' requires an HTTPS endpoint and credentials. "
        f"Set remote_harness.config.endpoint or SUPERQODE_{_env_prefix(backend)}_ENDPOINT, "
        f"and set {config.api_key_env}."
    )


def _has_default_endpoint(backend: str) -> bool:
    if backend == "google-agent-engine" and (
        os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    ):
        return True
    return bool(
        os.getenv(f"SUPERQODE_{_env_prefix(backend)}_ENDPOINT")
        or os.getenv(f"{_env_prefix(backend)}_ENDPOINT")
    )


def _env_prefix(backend: str) -> str:
    return "GOOGLE_AGENT" if backend == "google-agent-engine" else "ANTHROPIC_MANAGED_AGENT"


def _install_hint(backend: str) -> str:
    if backend == "google-agent-engine":
        return (
            "Set GEMINI_API_KEY for Gemini generateContent mode, or configure a "
            "Gemini Enterprise Agent Platform / Agent Runtime endpoint and credential."
        )
    return "Configure Claude Managed Agents endpoint and ANTHROPIC_API_KEY."


def _redact_endpoint(endpoint: str) -> str:
    if "?" not in endpoint:
        return endpoint
    return endpoint.split("?", 1)[0] + "?..."


def _bool_config(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


__all__ = ["ManagedAgentHarnessBackend"]
