"""System One Pydantic primitives: schema-safe, not truth-safe."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from superqode.systemone.types import (
    MAX_CHOICE_OPTIONS,
    ChoiceQuestion,
    NoulQuestion,
    SchemaViolation,
    ScoreQuestion,
    bind_answers,
    coerce_question,
    default_answer,
)


def test_choice_rejects_empty_and_oversized_criteria():
    with pytest.raises(ValidationError):
        ChoiceQuestion(instructions="which?", criteria={})
    too_many = {f"opt{i}": "x" for i in range(MAX_CHOICE_OPTIONS + 1)}
    with pytest.raises(ValidationError):
        ChoiceQuestion(instructions="which?", criteria=too_many)


def test_score_needs_two_levels():
    with pytest.raises(ValidationError):
        ScoreQuestion(instructions="how bad?", criteria=["only-one"])


def test_noul_yaml_bool_keys_become_strings():
    question = coerce_question(
        {
            "type": "noul",
            "instructions": "yes?",
            "criteria": {True: {"what": "yes"}, False: {"what": "no"}},
        }
    )
    assert isinstance(question, NoulQuestion)
    assert set(question.criteria or {}) == {"true", "false"}


def test_noul_has_no_confidence_field():
    question = coerce_question({"type": "noul", "instructions": "Is this true?"})
    assert isinstance(question, NoulQuestion)
    answer = bind_answers({"q": question}, {"q": {"noul": 0.42}})
    assert answer.noul("q") == 0.42
    assert "confidence" not in answer.answers["q"].model_dump()


def test_bind_answers_rejects_unknown_choice():
    question = ChoiceQuestion(
        instructions="act?",
        criteria={"allow": "ok", "deny": "no", "ask": "pause"},
    )
    with pytest.raises(SchemaViolation, match="not in the question options"):
        bind_answers({"disposition": question}, {"disposition": {"choice": "maybe"}})


def test_bind_answers_rejects_unknown_probability_option():
    question = ChoiceQuestion(
        instructions="act?",
        criteria={"allow": "ok", "deny": "no", "ask": "pause"},
    )
    with pytest.raises(SchemaViolation, match="unknown options"):
        bind_answers(
            {"disposition": question},
            {
                "disposition": {
                    "choice": "allow",
                    "probabilities": {"allow": 1.0, "other": 0.0},
                }
            },
        )


def test_bind_answers_rejects_extra_and_missing_ids():
    question = NoulQuestion(instructions="yes?")
    with pytest.raises(SchemaViolation, match="unknown question ids"):
        bind_answers({"q": question}, {"q": {"noul": 0.1}, "extra": {"noul": 0.2}})
    with pytest.raises(SchemaViolation, match="missing answer"):
        bind_answers({"q": question}, {})


def test_noul_out_of_range_is_invalid():
    question = NoulQuestion(instructions="yes?")
    with pytest.raises(ValidationError):
        bind_answers({"q": question}, {"q": {"noul": 1.2}})


def test_score_out_of_range_is_schema_violation():
    question = ScoreQuestion(instructions="how bad?", criteria=["low", "mid", "high"])
    with pytest.raises(SchemaViolation, match="outside"):
        bind_answers({"q": question}, {"q": {"score": 9}})


def test_default_choice_prefers_ask():
    question = ChoiceQuestion(
        instructions="act?",
        criteria={"allow": "ok", "deny": "no", "ask": "pause"},
    )
    default = default_answer(question)
    assert default["choice"] == "ask"
    assert default["confidence"] == 0.0
