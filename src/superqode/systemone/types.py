"""Pydantic shapes for System One questions and answers.

Schema-safe, not truth-safe: a Choice cannot name an option the question
did not list; a Noul is only a 0-1 probability.
"""

from __future__ import annotations

import json

from typing import Annotated, Any, Literal, Mapping, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

MAX_CHOICE_OPTIONS = 255


class SchemaViolation(ValueError):
    """An answer named a value the question did not allow."""


class ChoiceQuestion(BaseModel):
    """Pick one option from a closed set."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["choice"] = "choice"
    instructions: str | dict[str, Any]
    criteria: dict[str, Any]

    @field_validator("criteria", mode="before")
    @classmethod
    def _closed_set(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("Choice criteria must be a map of option to description")
        value = {
            "true" if key is True else "false" if key is False else str(key): item
            for key, item in value.items()
        }
        if not value:
            raise ValueError("Choice criteria must list at least one option")
        if len(value) > MAX_CHOICE_OPTIONS:
            raise ValueError(f"Choice criteria cannot exceed {MAX_CHOICE_OPTIONS} options")
        return value

    @property
    def options(self) -> tuple[str, ...]:
        return tuple(self.criteria.keys())


class ScoreQuestion(BaseModel):
    """Rate the state along ordered levels."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["score"] = "score"
    instructions: str | dict[str, Any]
    criteria: list[Any]

    @field_validator("criteria")
    @classmethod
    def _ordered_levels(cls, value: list[Any]) -> list[Any]:
        if len(value) < 2:
            raise ValueError("Score criteria must list at least two levels")
        return value

    @property
    def levels(self) -> int:
        return len(self.criteria)


class NoulQuestion(BaseModel):
    """Yes/no probability. Near 0.5 is the uncertainty signal; there is no
    separate confidence field."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["noul"] = "noul"
    instructions: str | dict[str, Any]
    criteria: dict[str, Any] | None = None

    @field_validator("criteria", mode="before")
    @classmethod
    def _stringify_keys(cls, value: Any) -> Any:
        # YAML `true:` / `false:` become booleans; TypeSafe uses string keys.
        if not isinstance(value, dict):
            return value
        return {
            "true" if key is True else "false" if key is False else str(key): item
            for key, item in value.items()
        }


Question = Annotated[
    Union[ChoiceQuestion, ScoreQuestion, NoulQuestion],
    Field(discriminator="type"),
]

_QUESTION_ADAPTER = TypeAdapter(Question)


def coerce_question(
    value: Question | Mapping[str, Any],
) -> ChoiceQuestion | ScoreQuestion | NoulQuestion:
    """Accept a model or a wire dict."""
    if isinstance(value, (ChoiceQuestion, ScoreQuestion, NoulQuestion)):
        return value
    return _QUESTION_ADAPTER.validate_python(value)


def coerce_questions(
    questions: Mapping[str, Question | Mapping[str, Any]],
) -> dict[str, ChoiceQuestion | ScoreQuestion | NoulQuestion]:
    return {qid: coerce_question(question) for qid, question in questions.items()}


def wire_questions(questions: Mapping[str, Question | Mapping[str, Any]]) -> dict[str, Any]:
    """Serialize structured local criteria into the API's string descriptions."""
    result = {}
    for qid, question in coerce_questions(questions).items():
        payload = question.model_dump(mode="json", exclude_none=True)
        if isinstance(question, (ChoiceQuestion, NoulQuestion)) and question.criteria:
            payload["criteria"] = {
                key: value
                if isinstance(value, str) or value is None
                else json.dumps(value, sort_keys=True)
                for key, value in question.criteria.items()
            }
        result[qid] = payload
    return result


class ChoiceAnswer(BaseModel):
    """Selected option plus the full distribution and a confidence summary."""

    model_config = ConfigDict(extra="ignore")

    choice: str
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("probabilities")
    @classmethod
    def _unit_interval(cls, value: dict[str, float]) -> dict[str, float]:
        for option, probability in value.items():
            if not 0.0 <= probability <= 1.0:
                raise ValueError(f"probability for {option!r} is not in [0, 1]")
        return value


class ScoreAnswer(BaseModel):
    """Position along the question's levels, possibly between two of them."""

    model_config = ConfigDict(extra="ignore")

    score: float
    probabilities: dict[str, float] | list[float] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    legend: dict[str, Any] | None = None


class NoulAnswer(BaseModel):
    """Probability that the statement is true. No separate confidence."""

    model_config = ConfigDict(extra="ignore")

    noul: float = Field(ge=0.0, le=1.0)


Answer = ChoiceAnswer | ScoreAnswer | NoulAnswer


class Answers(BaseModel):
    """Typed answers keyed by the question ids the caller sent."""

    model_config = ConfigDict(extra="forbid")

    answers: dict[str, Answer]
    metadata: dict[str, Any] = Field(default_factory=dict)

    def get(self, question_id: str) -> Answer | None:
        return self.answers.get(question_id)

    def noul(self, question_id: str) -> float:
        answer = self.answers[question_id]
        if not isinstance(answer, NoulAnswer):
            raise TypeError(f"{question_id!r} is not a Noul answer")
        return answer.noul

    def choice(self, question_id: str) -> ChoiceAnswer:
        answer = self.answers[question_id]
        if not isinstance(answer, ChoiceAnswer):
            raise TypeError(f"{question_id!r} is not a Choice answer")
        return answer

    def score(self, question_id: str) -> ScoreAnswer:
        answer = self.answers[question_id]
        if not isinstance(answer, ScoreAnswer):
            raise TypeError(f"{question_id!r} is not a Score answer")
        return answer

    def noul_map(self) -> dict[str, float]:
        return {
            qid: answer.noul
            for qid, answer in self.answers.items()
            if isinstance(answer, NoulAnswer)
        }


def default_answer(question: ChoiceQuestion | ScoreQuestion | NoulQuestion) -> dict[str, Any]:
    """Schema-legal uncertain default. Compose fail-opens to ASK on these."""
    if isinstance(question, NoulQuestion):
        return {"noul": 0.5}
    if isinstance(question, ScoreQuestion):
        midpoint = (question.levels - 1) / 2
        return {"score": midpoint, "confidence": 0.0}
    options = question.options
    choice = "ask" if "ask" in question.criteria else options[0]
    probabilities = {option: 0.0 for option in options}
    probabilities[choice] = 1.0
    return {"choice": choice, "probabilities": probabilities, "confidence": 0.0}


def _validate_choice(question: ChoiceQuestion, raw: Mapping[str, Any]) -> ChoiceAnswer:
    payload = dict(raw)
    choice = str(payload.get("choice", ""))
    if choice not in question.criteria:
        raise SchemaViolation(
            f"choice {choice!r} is not in the question options {list(question.criteria)}"
        )
    probabilities = payload.get("probabilities") or {}
    if not isinstance(probabilities, dict):
        raise SchemaViolation("choice probabilities must be a map of option to probability")
    unknown = set(probabilities) - set(question.criteria)
    if unknown:
        raise SchemaViolation(f"probabilities name unknown options {sorted(unknown)}")
    filled = {option: 0.0 for option in question.options}
    filled.update({key: float(value) for key, value in probabilities.items()})
    if not probabilities:
        filled[choice] = 1.0
    payload["choice"] = choice
    payload["probabilities"] = filled
    return ChoiceAnswer.model_validate(payload)


def _validate_score(question: ScoreQuestion, raw: Mapping[str, Any]) -> ScoreAnswer:
    answer = ScoreAnswer.model_validate(raw)
    upper = question.levels - 1
    if not 0.0 <= answer.score <= upper:
        raise SchemaViolation(f"score {answer.score} is outside [0, {upper}]")
    return answer


def bind_answers(
    questions: Mapping[str, ChoiceQuestion | ScoreQuestion | NoulQuestion],
    raw: Mapping[str, Mapping[str, Any]],
    *,
    fill_missing: bool = False,
) -> Answers:
    """Bind raw answer dicts to the questions. Rejects off-schema values.

    Extra answer ids are always an error. Missing ids raise unless
    ``fill_missing`` is true, in which case each gap gets a schema-legal
    uncertain default.
    """
    extra = set(raw) - set(questions)
    if extra:
        raise SchemaViolation(f"answers include unknown question ids {sorted(extra)}")
    bound: dict[str, Answer] = {}
    for qid, question in questions.items():
        if qid in raw:
            payload = raw[qid]
        elif fill_missing:
            payload = default_answer(question)
        else:
            raise SchemaViolation(f"missing answer for {qid!r}")
        if not isinstance(payload, Mapping):
            raise SchemaViolation(f"answer for {qid!r} must be an object")
        if isinstance(question, ChoiceQuestion):
            bound[qid] = _validate_choice(question, payload)
        elif isinstance(question, ScoreQuestion):
            bound[qid] = _validate_score(question, payload)
        else:
            bound[qid] = NoulAnswer.model_validate(payload)
    return Answers(answers=bound)


__all__ = [
    "MAX_CHOICE_OPTIONS",
    "Answer",
    "Answers",
    "ChoiceAnswer",
    "ChoiceQuestion",
    "NoulAnswer",
    "NoulQuestion",
    "Question",
    "SchemaViolation",
    "ScoreAnswer",
    "ScoreQuestion",
    "bind_answers",
    "coerce_question",
    "coerce_questions",
    "default_answer",
]
