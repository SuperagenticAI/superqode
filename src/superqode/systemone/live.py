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
import os
import hashlib
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

import httpx

from .http_contract import post_decision, validate_api_key
from .client import SystemOneTimeout
from .config import DEFAULT_MODEL, LIVE_API_KEY_ENV
from .types import (
    Answers,
    Question,
    SchemaViolation,
    bind_answers,
    coerce_questions,
    wire_questions,
    ScoreQuestion,
)

DEFAULT_URL = "https://api.typesafe.ai/v1/systemone"
_RETRY_STATUSES = {429, 529}


class LiveSystemOneClient:
    """POST state + questions; bind the answers through the local schema."""

    name = "live"
    provider = "typesafe"

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
        self._attempts: ContextVar[list | None] = ContextVar("decision_attempts", default=None)

    def _headers(self) -> dict[str, str]:
        validate_api_key(self.provider, self.api_key, required=self.require_api_key)
        return {
            **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            "Content-Type": "application/json",
        }

    def _payload(
        self, state: Any, questions: Mapping[str, Question | Mapping[str, Any]]
    ) -> dict[str, Any]:
        bound = coerce_questions(questions)
        if self.url.rstrip("/") == DEFAULT_URL:
            if not bound:
                raise SchemaViolation("TypeSafe requires at least one question")
            if any(
                isinstance(question, ScoreQuestion) and question.levels > 10
                for question in bound.values()
            ):
                raise SchemaViolation("TypeSafe accepts at most 10 rubric levels")
        wire = wire_questions(bound)
        return {"state": state, "model": self.model, "questions": wire}

    async def evaluate(
        self,
        state: Any,
        questions: Mapping[str, Question | Mapping[str, Any]],
    ) -> Answers:
        started = time.monotonic()
        token = self._attempts.set([])
        try:
            return await self._evaluate(state, questions)
        except (Exception, asyncio.CancelledError) as exc:
            if self.record_dir is not None:
                status = (
                    "cancelled"
                    if isinstance(exc, asyncio.CancelledError)
                    else "timeout"
                    if isinstance(exc, SystemOneTimeout)
                    else "refused"
                    if type(exc).__name__ == "DecisionRefused"
                    else ("invalid_response" if self._attempts.get() else "invalid_request")
                    if isinstance(exc, SchemaViolation)
                    else "error"
                )
                try:
                    self._write_record(
                        {
                            "status": status,
                            "model": self.model,
                            "question_ids": list(questions),
                            "evaluation": {
                                "error_type": type(exc).__name__,
                                "latency_ms": round((time.monotonic() - started) * 1000),
                                "http_attempts": list(self._attempts.get() or []),
                            },
                        }
                    )
                except (OSError, ValueError, TypeError):
                    logging.getLogger("superqode.systemone").warning(
                        "System One failure could not be recorded"
                    )
            raise
        finally:
            self._attempts.reset(token)

    async def _evaluate(self, state, questions) -> Answers:
        bound = coerce_questions(questions)
        payload = self._payload(state, bound)
        self.calls.append((state, payload["questions"]))
        started = time.monotonic()
        try:
            body, transport = await asyncio.wait_for(self._post(payload), self.timeout_ms / 1000)
        except asyncio.TimeoutError as exc:
            raise SystemOneTimeout(f"live evaluate timed out after {self.timeout_ms}ms") from exc
        raw_answers = self._decode_answers(body, bound)
        try:
            answers = bind_answers(bound, raw_answers, fill_missing=False)
        except (ValueError, TypeError) as exc:
            raise SchemaViolation("live response did not match the question schema") from exc
        answers.metadata = {
            **transport,
            "provider": self.provider,
            "adapter_version": 1,
            "requested_model": self.model,
            "resolved_model": body.get("model"),
            "model": body.get("model", self.model),
            "usage": self._usage(body),
            "latency_ms": round((time.monotonic() - started) * 1000),
            "http_attempts": list(self._attempts.get() or []),
            "question_count": len(bound),
            "questions_hash": "sha256:"
            + hashlib.sha256(
                json.dumps(wire_questions(bound), sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest(),
        }
        try:
            self._record_evaluation(payload, body, answers, bound, state)
        except OSError:
            answers.metadata["recording_error"] = True
            logging.getLogger("superqode.systemone").warning(
                "System One response could not be recorded"
            )
        return answers

    def _decode_answers(self, body, questions):
        raw = _answers_from_response(body)
        for qid, answer in raw.items():
            # Legacy SystemOne-compatible endpoints may omit the type. When
            # supplied, it must agree with the requested primitive.
            if qid in questions and "type" in answer and answer["type"] != questions[qid].type:
                raise SchemaViolation("SystemOne returned the wrong decision type")
        return raw

    def _usage(self, body):
        return body.get("usage", {})

    def _record_evaluation(self, payload, body, answers, questions, state):
        typed = {key: answer.model_dump(mode="json") for key, answer in answers.answers.items()}
        self._record(payload, {**body, "answers": typed, "metadata": answers.metadata})

    def _begin_attempt(self):
        attempts = self._attempts.get()
        attempt = {"attempt": len(attempts or []) + 1, "http_status": None}
        if attempts is not None:
            attempts.append(attempt)
        return attempt

    async def _post(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        return await post_decision(self, payload, retry_statuses=_RETRY_STATUSES)

    def _record(self, request: dict[str, Any], response: dict[str, Any]) -> None:
        self._write_record(
            {
                "status": "success",
                "request": request,
                "response": response,
                "evaluation": response.get("metadata", {}),
            },
            typed_answers=response.get("answers"),
        )

    def _write_record(self, record, *, typed_answers=None):
        if self.record_dir is None:
            return
        from urllib.parse import urlsplit
        from .state import redact_evidence

        endpoint = urlsplit(self.url)
        authority = endpoint.hostname or ""
        if endpoint.port:
            authority += f":{endpoint.port}"
        record = {
            "record_version": 1,
            "provider": self.provider,
            "adapter_version": 1,
            "endpoint": f"{endpoint.scheme}://{authority}{endpoint.path}",
            **record,
        }
        self.record_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        safe = redact_evidence(record)
        if typed_answers is not None and isinstance(safe.get("response"), dict):
            # Question/option IDs such as "has_token" are identifiers, not
            # credential fields. These values have already passed typed binding.
            safe["response"]["answers"] = {
                qid: {
                    field: redact_evidence(value) if field in {"choice", "legend"} else value
                    for field, value in answer.items()
                }
                for qid, answer in typed_answers.items()
            }
        # Token counters are telemetry, not credentials. Restore only known,
        # typed usage fields; never restore arbitrary provider dictionaries.
        for parent, name in (
            ("evaluation", "usage"),
            ("evaluation", "raw_usage"),
            ("response", "usage"),
        ):
            original = (record.get(parent) or {}).get(name)
            if isinstance(original, dict) and isinstance(safe.get(parent), dict):
                safe[parent][name] = _safe_usage(original)
        path = self.record_dir / f"{int(time.time() * 1000)}-{uuid4().hex[:8]}.json"
        with os.fdopen(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8"
        ) as stream:
            encoded = json.dumps(safe, ensure_ascii=False, indent=2)
            if self.api_key:
                encoded = encoded.replace(self.api_key, "[redacted]")
            stream.write(encoded)


def _safe_usage(usage):
    counts = {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "total_input_tokens",
        "total_output_tokens",
        "cached_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "tokens",
    }
    result = {
        key: value
        for key, value in usage.items()
        if key in counts and (value is None or (type(value) is int and value >= 0))
    }
    for key in ("input_tokens_details", "output_tokens_details"):
        if isinstance(usage.get(key), dict):
            result[key] = _safe_usage(usage[key])
    if isinstance(usage.get("input_tokens_by_modality"), list):
        result["input_tokens_by_modality"] = [
            {"modality": row["modality"], **_safe_usage(row)}
            for row in usage["input_tokens_by_modality"]
            if isinstance(row, dict)
            and row.get("modality") in {"text", "image", "audio", "video", "document"}
        ]
    return result


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


__all__ = ["DEFAULT_URL", "LiveSystemOneClient"]
