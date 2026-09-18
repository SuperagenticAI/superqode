"""Evaluate general decision packs independently of the coding loop."""

from __future__ import annotations

import json
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .client import SystemOneClient, SystemOneError
from .pack import QuestionPack
from .state import prepare_decision_state
from .types import ChoiceAnswer, NoulAnswer, ScoreAnswer, bind_answers


class DecisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["decided", "abstain"]
    outputs: dict[str, str | bool | float | None]
    answers: dict[str, Any]
    abstained: list[str]
    metadata: dict[str, Any]


def parse_state(prompt: str, pack: QuestionPack) -> Any:
    text = prompt.strip()
    if not text:
        raise ValueError("Decision state cannot be empty")
    try:
        state = json.loads(text)
    except json.JSONDecodeError:
        if text.startswith(("{", "[")):
            raise ValueError("Decision state contains invalid JSON") from None
        state = text
    if isinstance(state, str) and pack.input_key:
        state = {pack.input_key: state}
    return state


async def evaluate_decision(
    client: SystemOneClient, state: Any, pack: QuestionPack
) -> DecisionResult:
    """Retain typed answers; abstain from low-confidence output values."""
    payload = prepare_decision_state(state, pack.state_schema)
    questions = pack.wire_questions()
    started = time.monotonic()
    try:
        response = await client.evaluate(payload, questions)
        answers = bind_answers(
            pack.questions,
            {qid: answer.model_dump(mode="json") for qid, answer in response.answers.items()},
        )
        answers.metadata = dict(response.metadata)
    except SystemOneError:
        raise
    except Exception as exc:
        raise SystemOneError("Decision evaluation failed; no decision was produced") from exc
    outputs: dict[str, Any] = {}
    abstained = []
    policy = pack.decision_policy
    for qid, answer in answers.answers.items():
        value = None
        if isinstance(answer, (ChoiceAnswer, ScoreAnswer)):
            if answer.confidence >= policy.min_confidence:
                value = answer.choice if isinstance(answer, ChoiceAnswer) else answer.score
        elif isinstance(answer, NoulAnswer):
            if answer.noul <= policy.noul_false_max:
                value = False
            elif answer.noul >= policy.noul_true_min:
                value = True
        outputs[qid] = value
        if value is None:
            abstained.append(qid)
    return DecisionResult(
        status="abstain" if abstained else "decided",
        outputs=outputs,
        answers={qid: answer.model_dump(mode="json") for qid, answer in answers.answers.items()},
        abstained=abstained,
        metadata={
            "pack": f"{pack.id}@{pack.version}",
            "pack_hash": pack.content_hash(),
            "client": client.name,
            "evaluation": {
                "status": "success",
                "latency_ms": round((time.monotonic() - started) * 1000),
                **answers.metadata,
            },
        },
    )
