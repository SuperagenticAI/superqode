"""Bounded decision REST requests and safe, actionable provider errors."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math

import httpx

from .client import SystemOneError, SystemOneTimeout
from .providers import get_provider
from .types import SchemaViolation

MAX_BODY_BYTES = 4 * 1024 * 1024  # Deliberately below vendor upload limits.


class DecisionRefused(SystemOneError):
    """A required decision was refused or blocked; never an affirmative answer."""


def validate_api_key(provider, value, *, required=True):
    definition = get_provider(provider)
    if not value and required:
        raise SystemOneError(
            f"Set {definition.api_key_env} for {definition.label}. Setup: {definition.docs}"
        )
    if value and any(ord(char) < 33 or ord(char) > 126 for char in value):
        raise SystemOneError(
            f"Paste a valid {definition.label} API key without internal spaces, line breaks or non-ASCII characters. Setup: {definition.docs}"
        )


def json_body(data):
    def nonfinite(_value):
        raise SchemaViolation("Decision response contains a non-finite JSON number")

    def finite(value):
        result = float(value)
        return result if math.isfinite(result) else nonfinite(value)

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise SchemaViolation("Decision response contains a duplicate JSON field")
            result[key] = value
        return result

    return json.loads(data, object_pairs_hook=unique, parse_constant=nonfinite, parse_float=finite)


def retry_delay(headers, attempt, *, now=None):
    """Honor seconds, HTTP dates and OpenAI's millisecond retry header.

    A long server delay is interrupted by the evaluation's total deadline; do
    not retry early by clamping it down to an arbitrary short backoff.
    """
    for name, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        value = headers.get(name)
        if value is None:
            continue
        try:
            delay = float(value) * scale
        except (TypeError, ValueError):
            if name != "retry-after":
                continue
            try:
                date = parsedate_to_datetime(value)
                delay = (date - (now or datetime.now(timezone.utc))).total_seconds()
            except (TypeError, ValueError, OverflowError):
                continue
        if math.isfinite(delay):
            return max(0.0, delay)
    return 0.2 * 2**attempt


def error_code(body):
    """Inspect only machine codes; never display upstream bodies or messages."""
    try:
        error = json.loads(body).get("error", {})
    except (ValueError, AttributeError, UnicodeDecodeError):
        return ""
    if not isinstance(error, dict):
        return ""
    details = error.get("details", [])
    if isinstance(details, list) and any(
        isinstance(item, dict)
        and item.get("reason") in ("API_KEY_INVALID", "API_KEY_EXPIRED", "API_KEY_NOT_FOUND")
        for item in details
    ):
        return "invalid_key"
    for name in ("code", "type", "status"):
        value = error.get(name)
        if value in ("insufficient_quota", "billing_hard_limit_reached", "quota_exceeded"):
            return "quota"
        if value in (
            "safety",
            "prohibited_content",
            "blocklist",
            "image_safety",
            "content_blocked",
        ):
            return "safety"
    return ""


def http_error(provider, status, *, code=""):
    definition = get_provider(provider)
    if status in {401, 403} or code == "invalid_key":
        guidance = f"Check {definition.api_key_env}, API billing, project permissions and decision-model access."
    elif status == 404:
        guidance = "Check decision-model availability for your account and region. A chat-model subscription does not grant decision API access."
    elif code == "quota":
        guidance = "API quota or billing is exhausted. Check the provider's API billing and usage limits before retrying."
    elif status == 429:
        guidance = "The provider's request or token rate limit was reached. Wait and retry, or check API quota and billing."
    elif status in {400, 413, 415, 422}:
        guidance = "Check the input/context size, question criteria and supported request format."
    elif 300 <= status < 400:
        guidance = "The endpoint redirected the request. No credentials were forwarded; check the configured endpoint."
    elif status >= 500:
        guidance = "The provider is temporarily unavailable. Retry later. Existing permission checks remain in force."
    else:
        guidance = "The provider returned an unexpected response. Check the API setup."
    return SystemOneError(f"{definition.label} HTTP {status}: {guidance} Setup: {definition.docs}")


async def post_decision(owner, payload, *, retry_statuses):
    try:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError) as exc:
        raise SchemaViolation("Decision input must be finite JSON") from exc
    if len(encoded) > MAX_BODY_BYTES:
        raise SchemaViolation("Decision request exceeds the size limit (4 MiB)")
    headers = owner._headers()  # Reject missing credentials before opening transport.
    own = owner._http is None
    client = owner._http or httpx.AsyncClient(
        timeout=owner.timeout_ms / 1000, follow_redirects=False
    )
    try:
        for attempt in range(3):
            event = owner._begin_attempt()
            try:
                async with client.stream(
                    "POST", owner.url, headers=headers, content=encoded, follow_redirects=False
                ) as response:
                    event.update(
                        http_status=response.status_code,
                        request_id=response.headers.get("x-request-id")
                        or response.headers.get("request-id", ""),
                    )
                    chunks = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_BODY_BYTES:
                            raise SystemOneError("Decision response exceeds the size limit")
                        chunks.append(chunk)
                    data = b"".join(chunks)
                    code = error_code(data) if response.status_code != 200 else ""
                    if response.status_code in retry_statuses and code != "quota" and attempt < 2:
                        await asyncio.sleep(retry_delay(response.headers, attempt))
                        continue
                    if (
                        response.status_code == 400
                        and owner.provider == "google"
                        and code == "safety"
                    ):
                        raise DecisionRefused(
                            "Google blocked the decision input; existing policy remains in force"
                        )
                    if response.status_code != 200:
                        raise http_error(owner.provider, response.status_code, code=code)
                    try:
                        body = json_body(data)
                    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
                        raise SystemOneError("Decision endpoint returned invalid JSON") from exc
                    if not isinstance(body, dict):
                        raise SystemOneError("Decision endpoint returned a non-object")
                    if "usage" in body and not isinstance(body["usage"], dict):
                        raise SchemaViolation("Decision usage must be an object")
                    return body, {
                        "provider": owner.provider,
                        "adapter_version": 1,
                        "http_status": response.status_code,
                        "request_id": event["request_id"],
                        "raw_usage": body.get("usage", {}),
                    }
            except httpx.TimeoutException as exc:
                raise SystemOneTimeout(
                    f"{owner.name} timed out after {owner.timeout_ms}ms"
                ) from exc
            except httpx.HTTPError as exc:
                raise SystemOneError(
                    f"{owner.name} transport failure; check your network and provider setup"
                ) from exc
        raise SystemOneError("Decision evaluation failed")
    finally:
        if own:
            await client.aclose()
