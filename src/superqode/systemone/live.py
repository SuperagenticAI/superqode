"""Live System One client over HTTP.

Uses ``httpx.AsyncClient`` so tests can inject ``MockTransport``. Pins
``jev-1.13.0``. Does not run unless an API key is present. Optional
``record_dir`` writes each evaluate to disk for later replay.
"""

from __future__ import annotations

import asyncio
import logging
import json
import time
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

import httpx

from .client import SystemOneError, SystemOneTimeout
from .config import DEFAULT_MODEL, LIVE_API_KEY_ENV
from .types import (
    Answers,
    Question,
    SchemaViolation,
    bind_answers,
    coerce_questions,
    wire_questions,
)

DEFAULT_URL = "https://api.typesafe.ai/v1/systemone"
_RETRY_STATUSES = {429, 529}


class LiveSystemOneClient:
    """POST state + questions; bind the answers through the local schema."""

    name = "live"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        url: str = DEFAULT_URL,
        timeout_ms: int = 5000,
        record_dir: str | Path | None = None,
        http: httpx.AsyncClient | None = None,
        require_api_key: bool = True,
    ) -> None:
        import os

        self.api_key = (
            api_key if api_key is not None else os.environ.get(LIVE_API_KEY_ENV) or ""
        ).strip()
        self.require_api_key = require_api_key
        self.model = model or DEFAULT_MODEL
        self.url = url
        self.timeout_ms = max(int(timeout_ms), 1)
        self.record_dir = Path(record_dir) if record_dir else None
        self._http = http
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    def _headers(self) -> dict[str, str]:
        if not self.api_key and self.require_api_key:
            raise SystemOneError("live client has no API key")
        return {
            **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            "Content-Type": "application/json",
        }

    def _payload(
        self, state: Any, questions: Mapping[str, Question | Mapping[str, Any]]
    ) -> dict[str, Any]:
        bound = coerce_questions(questions)
        wire = wire_questions(bound)
        return {"state": state, "model": self.model, "questions": wire}

    async def evaluate(
        self,
        state: Any,
        questions: Mapping[str, Question | Mapping[str, Any]],
    ) -> Answers:
        bound = coerce_questions(questions)
        payload = self._payload(state, bound)
        self.calls.append((state, payload["questions"]))
        started = time.monotonic()
        try:
            body, transport = await asyncio.wait_for(self._post(payload), self.timeout_ms / 1000)
        except asyncio.TimeoutError as exc:
            raise SystemOneTimeout(f"live evaluate timed out after {self.timeout_ms}ms") from exc
        raw_answers = _answers_from_response(body)
        try:
            answers = bind_answers(bound, raw_answers, fill_missing=False)
        except (ValueError, TypeError) as exc:
            raise SchemaViolation("live response did not match the question schema") from exc
        answers.metadata = {
            **transport,
            "model": body.get("model", self.model),
            "usage": body.get("usage", {}),
            "latency_ms": round((time.monotonic() - started) * 1000),
        }
        try:
            self._record(payload, body)
        except OSError:
            answers.metadata["recording_error"] = True
            logging.getLogger("superqode.systemone").warning(
                "System One response could not be recorded"
            )
        return answers

    async def _post(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        timeout = self.timeout_ms / 1000.0
        owns_client = self._http is None
        client = self._http or httpx.AsyncClient(timeout=timeout)
        try:
            delay = 0.2
            last_error: Exception | None = None
            for _attempt in range(3):
                try:
                    response = await client.post(self.url, headers=self._headers(), json=payload)
                except httpx.TimeoutException as exc:
                    raise SystemOneTimeout(
                        f"live evaluate timed out after {self.timeout_ms}ms"
                    ) from exc
                except httpx.HTTPError as exc:
                    raise SystemOneError("live evaluate transport failure") from exc
                if response.status_code in _RETRY_STATUSES:
                    last_error = SystemOneError(f"live evaluate HTTP {response.status_code}")
                    await _sleep(delay)
                    delay *= 2
                    continue
                if response.status_code in {401, 422}:
                    raise SystemOneError(f"live evaluate HTTP {response.status_code}")
                if response.status_code >= 400:
                    raise SystemOneError(f"live evaluate HTTP {response.status_code}")
                try:
                    body = response.json()
                except ValueError as exc:
                    raise SystemOneError("live evaluate returned non-JSON") from exc
                if not isinstance(body, dict):
                    raise SystemOneError("live evaluate returned a non-object")
                return body, {
                    "http_status": response.status_code,
                    "request_id": response.headers.get("x-request-id")
                    or response.headers.get("request-id", ""),
                }
            raise last_error or SystemOneError("live evaluate failed")
        finally:
            if owns_client:
                await client.aclose()

    def _record(self, request: dict[str, Any], response: dict[str, Any]) -> None:
        if self.record_dir is None:
            return
        self.record_dir.mkdir(parents=True, exist_ok=True)
        path = self.record_dir / f"{int(time.time() * 1000)}-{uuid4().hex[:8]}.json"
        path.write_text(
            json.dumps({"request": request, "response": response}, indent=2) + "\n",
            encoding="utf-8",
        )


def _answers_from_response(body: dict[str, Any]) -> dict[str, Mapping[str, Any]]:
    answers = body.get("answers")
    if not isinstance(answers, dict):
        raise SchemaViolation("live response missing answers object")
    out: dict[str, Mapping[str, Any]] = {}
    for qid, item in answers.items():
        if not isinstance(item, dict):
            raise SchemaViolation(f"live answer {qid!r} is not an object")
        out[str(qid)] = item
    return out


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


__all__ = ["DEFAULT_URL", "LiveSystemOneClient"]
