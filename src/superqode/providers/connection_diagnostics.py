"""Bounded connection checks that distinguish configuration from live access.

Normal checks never generate text. Inference is an explicit, isolated opt-in:
it sends no project context, executes no tools and does not change a session.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from urllib.error import URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .credentials import provider_api_key
from .dynamic import resolve_provider_def, resolve_base_url
from .registry import ProviderCategory


@dataclass(frozen=True)
class ConnectionCheck:
    status: str
    message: str
    provider: str
    model: str
    endpoint: str = ""
    context_window: int | None = None
    inference_verified: bool = False
    tools_verified: bool = False


def public_endpoint(value: str) -> str:
    """Display an endpoint without URL credentials, query strings or fragments."""
    try:
        parts = urlsplit(value)
        return urlunsplit((parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", ""))
    except ValueError:
        return "Invalid endpoint"


def failure_message(error: Exception) -> tuple[str, str]:
    """Never echo SDK/server exception text, which can contain credentials."""
    from .gateway.base import AuthenticationError, ModelNotFoundError, RateLimitError

    code = getattr(error, "status_code", None) or getattr(error, "code", None)
    if isinstance(error, AuthenticationError) or code in {401, 403}:
        return (
            "auth_error",
            "Authentication was rejected. Sign in again or check this route's credential.",
        )
    if isinstance(error, ModelNotFoundError) or code == 404:
        return (
            "model_missing",
            "The model or endpoint was not found. Check the server URL and model selection.",
        )
    if isinstance(error, RateLimitError) or code == 429:
        return (
            "rate_limited",
            "The account is rate limited or out of quota. Check your plan and retry later.",
        )
    if isinstance(error, (TimeoutError, asyncio.TimeoutError)):
        return "timeout", "The check timed out. Check the server and network, then retry."
    if isinstance(error, (URLError, ConnectionError, OSError)):
        return (
            "unreachable",
            "The server could not be reached. Start it or check its URL and network.",
        )
    return "error", "The connection check failed. Check the route's setup and retry."


def _read_models(url: str, api_key: str | None = None) -> dict:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=4) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Model response exceeds diagnostic limit")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Invalid model response")
    return data


async def check_model_connection(
    provider: str, model: str, *, infer: bool = False, tools: bool = False, gateway=None
) -> ConnectionCheck:
    definition = resolve_provider_def(provider)
    if definition is None:
        return ConnectionCheck(
            "unconfigured", "Select a supported provider first.", provider, model
        )
    local = definition.category == ProviderCategory.LOCAL
    if tools and not local:
        return ConnectionCheck(
            "unsupported_check",
            "Tool probes are available for local model routes only.",
            provider,
            model,
        )
    endpoint = resolve_base_url(definition) or ""
    if local and not endpoint:
        from .local.context_probe import _candidate_base_urls

        endpoint = next(iter(_candidate_base_urls(provider)), "")
    displayed = public_endpoint(endpoint) if endpoint else ""
    if not local and not provider_api_key(definition):
        return ConnectionCheck(
            "unconfigured",
            f"Configure this account with superqode auth login {provider}.",
            provider,
            model,
            displayed,
        )
    if not model:
        return ConnectionCheck("unconfigured", "Choose a model first.", provider, model, displayed)
    try:
        if infer or tools:
            from .gateway import GatewayFactory, Message, ToolDefinition

            probe = (
                ToolDefinition(
                    name="connection_probe",
                    description="Return the requested echo value. Diagnostic only; never executed.",
                    parameters={
                        "type": "object",
                        "properties": {"echo": {"type": "string"}},
                        "required": ["echo"],
                    },
                )
                if tools
                else None
            )

            client = gateway if gateway is not None else GatewayFactory.create()
            try:
                response = await asyncio.wait_for(
                    client.chat_completion(
                        messages=[
                            Message(
                                role="user",
                                content='Call connection_probe with echo="OK".'
                                if tools
                                else "Reply with OK.",
                            )
                        ],
                        provider=provider,
                        model=model,
                        max_tokens=64 if tools else 8,
                        tools=[probe] if tools else None,
                    ),
                    timeout=20,
                )
            finally:
                close = getattr(client, "close", None) if gateway is None else None
                if close:
                    await close()
            if tools:
                valid = False
                for call in getattr(response, "tool_calls", None) or []:
                    function = call.get("function", {}) if isinstance(call, dict) else {}
                    arguments = function.get("arguments")
                    try:
                        arguments = (
                            json.loads(arguments) if isinstance(arguments, str) else arguments
                        )
                    except ValueError:
                        continue
                    if (
                        function.get("name") == "connection_probe"
                        and isinstance(arguments, dict)
                        and arguments.get("echo") == "OK"
                    ):
                        valid = True
                        break
                return ConnectionCheck(
                    "verified" if valid else "tools_unverified",
                    "Model returned the expected tool call; no tool was executed."
                    if valid
                    else "The request completed without the expected tool call. Check the server's chat template and tool support.",
                    provider,
                    model,
                    displayed,
                    inference_verified=True,
                    tools_verified=valid,
                )
            if not str(getattr(response, "content", "") or "").strip():
                return ConnectionCheck(
                    "empty_response",
                    "The request returned no text. Retry or select another model; generation is not verified.",
                    provider,
                    model,
                    displayed,
                )
            return ConnectionCheck(
                "verified",
                "A minimal inference request succeeded. Account and model access verified.",
                provider,
                model,
                displayed,
                inference_verified=True,
            )
        if not local:
            return ConnectionCheck(
                "configured",
                "Credential configured; sign-in, quota and model access are not verified. "
                "Use :connect test --infer for a minimal request that may consume account usage.",
                provider,
                model,
                displayed,
            )
        base = endpoint.rstrip("/")
        url = base + (
            "/api/tags"
            if provider == "ollama"
            else "/models"
            if base.endswith("/v1")
            else "/v1/models"
        )
        data = await asyncio.wait_for(
            asyncio.to_thread(_read_models, url, provider_api_key(definition)), timeout=5
        )
        rows = data.get("models" if provider == "ollama" else "data")
        if not isinstance(rows, list):
            raise ValueError("Missing model list")
        selected = next(
            (
                row
                for row in rows
                if isinstance(row, dict)
                and (
                    row.get("id") == model
                    or row.get("name") == model
                    or row.get("model") == model
                    or (provider == "ollama" and row.get("name") == model + ":latest")
                )
            ),
            None,
        )
        if selected is None:
            return ConnectionCheck(
                "model_missing",
                "Server reachable, but the selected model is not listed. "
                "Load/download it or choose another model.",
                provider,
                model,
                displayed,
            )
        context = (
            selected.get("loaded_context_length")
            or selected.get("max_model_len")
            or selected.get("context_length")
        )
        context = (
            context
            if isinstance(context, int) and not isinstance(context, bool) and context > 0
            else None
        )
        return ConnectionCheck(
            "reachable",
            "Server reachable and model listed. Generation and tool calling are not yet verified. "
            "Use :connect test --infer for a small generation check.",
            provider,
            model,
            displayed,
            context,
        )
    except Exception as error:
        status, message = failure_message(error)
        return ConnectionCheck(status, message, provider, model, displayed)
