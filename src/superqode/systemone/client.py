"""System One client protocol and local (no-network) implementations.

The stub is schema-strict so SuperQode composition can be tested without
pretending a model is present. ``evaluate`` is async so a live POST does
not stall the agent loop.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from .types import (
    Answers,
    Question,
    SchemaViolation,
    bind_answers,
    coerce_questions,
    default_answer,
)


class SystemOneError(Exception):
    """Client failed to evaluate. Compose fail-opens to ASK."""


class SystemOneTimeout(SystemOneError):
    """The evaluation exceeded the caller's deadline."""


@runtime_checkable
class SystemOneClient(Protocol):
    """Evaluate typed questions over one state. No generation, no tools."""

    name: str

    async def evaluate(
        self,
        state: Any,
        questions: Mapping[str, Question | Mapping[str, Any]],
    ) -> Answers: ...


class StubSystemOneClient:
    """Return fixture answers keyed by question id.

    Missing ids get a schema-legal uncertain default. An answer that names
    an option the question did not list raises :class:`SchemaViolation`.
    Pass ``error`` to simulate timeout or transport failure.
    """

    name = "stub"

    def __init__(
        self,
        answers: Mapping[str, Mapping[str, Any]] | None = None,
        *,
        error: BaseException | None = None,
        fill_missing: bool = True,
    ) -> None:
        self._answers = {qid: dict(payload) for qid, payload in (answers or {}).items()}
        self._error = error
        self._fill_missing = fill_missing
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    async def evaluate(
        self,
        state: Any,
        questions: Mapping[str, Question | Mapping[str, Any]],
    ) -> Answers:
        bound_questions = coerce_questions(questions)
        self.calls.append(
            (state, {qid: q.model_dump(mode="json") for qid, q in bound_questions.items()})
        )
        if self._error is not None:
            raise self._error
        raw: dict[str, Mapping[str, Any]] = {}
        for qid, question in bound_questions.items():
            if qid in self._answers:
                raw[qid] = self._answers[qid]
            elif self._fill_missing:
                raw[qid] = default_answer(question)
        try:
            return bind_answers(bound_questions, raw, fill_missing=False)
        except SchemaViolation:
            raise
        except Exception as exc:
            raise SchemaViolation(str(exc)) from exc


class ReplaySystemOneClient:
    """Play recorded JSON answers from disk. Still schema-strict."""

    name = "replay"

    def __init__(self, source: str | Path, *, trace_id: str | None = None) -> None:
        self._source = Path(source)
        self._trace_id = trace_id
        self._traces = _load_replay(self._source)
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    async def evaluate(
        self,
        state: Any,
        questions: Mapping[str, Question | Mapping[str, Any]],
    ) -> Answers:
        bound_questions = coerce_questions(questions)
        self.calls.append(
            (state, {qid: q.model_dump(mode="json") for qid, q in bound_questions.items()})
        )
        raw = self._lookup()
        return bind_answers(bound_questions, raw, fill_missing=False)

    def _lookup(self) -> dict[str, Mapping[str, Any]]:
        if self._trace_id:
            if self._trace_id not in self._traces:
                raise SystemOneError(f"replay has no trace {self._trace_id!r}")
            return self._traces[self._trace_id]
        if len(self._traces) == 1:
            return next(iter(self._traces.values()))
        if "" in self._traces:
            return self._traces[""]
        raise SystemOneError("replay has multiple traces; pass trace_id")


def _load_replay(path: Path) -> dict[str, dict[str, Mapping[str, Any]]]:
    if path.is_dir():
        traces: dict[str, dict[str, Mapping[str, Any]]] = {}
        for file in sorted(path.glob("*.json")):
            payload = json.loads(file.read_text(encoding="utf-8"))
            if file.name == "verdict.json" and "action" in payload:
                continue
            answers = _answers_from_payload(payload)
            traces[str(payload.get("id") or file.stem)] = answers
        return traces
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload.get("traces"), dict):
        return {
            str(trace_id): _answers_from_payload(body)
            for trace_id, body in payload["traces"].items()
        }
    return {str(payload.get("id") or ""): _answers_from_payload(payload)}


def _answers_from_payload(payload: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(payload, dict):
        raise SystemOneError("replay payload must be an object")
    if "response" in payload and "request" in payload:
        payload = payload["response"]
        if not isinstance(payload, dict):
            raise SystemOneError("recorded response must be an object")
    answers = payload.get("answers", payload)
    if not isinstance(answers, dict):
        raise SystemOneError("replay answers must be an object")
    return {str(qid): dict(body) for qid, body in answers.items() if isinstance(body, dict)}


__all__ = [
    "ReplaySystemOneClient",
    "StubSystemOneClient",
    "SystemOneClient",
    "SystemOneError",
    "SystemOneTimeout",
]
