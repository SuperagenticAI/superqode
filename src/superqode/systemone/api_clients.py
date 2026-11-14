"""Native Google/OpenAI Decisions adapters. No chat completion or SDK upgrades."""

from __future__ import annotations

import json
import math
import os

from .http_contract import DecisionRefused, post_decision, validate_api_key
from .live import LiveSystemOneClient
from .providers import get_provider
from .state import prepare_decision_state
from .types import ChoiceQuestion, NoulQuestion, SchemaViolation, coerce_questions, wire_questions


def _text(value):
    return (
        value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)
    )


def _number(value, *, probability=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SchemaViolation("Decision contains an invalid number")
    if probability and not 0 <= value <= 1:
        raise SchemaViolation("Decision probability is outside [0, 1]")
    return float(value)


def _distribution(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise SchemaViolation("Decision distribution does not cover the requested outcomes")
    values = {key: _number(number, probability=True) for key, number in value.items()}
    # Vendor examples round each outcome to two decimals. Do not renormalize.
    if abs(sum(values.values()) - 1) > 0.02:
        raise SchemaViolation("Decision distribution does not sum to one")
    return values


class _DecisionAPIClient(LiveSystemOneClient):
    provider: str

    def __init__(self, *, api_key=None, model=None, url=None, **kwargs):
        definition = get_provider(self.provider)
        if url and url.rstrip("/") != definition.endpoint:
            raise ValueError(
                f"{definition.label} requires its documented decision endpoint; use a SystemOne-compatible adapter for custom services"
            )
        if model and model not in definition.models:
            raise ValueError(f"Unsupported {definition.label} decision model")
        super().__init__(
            api_key=api_key if api_key is not None else os.environ.get(definition.api_key_env, ""),
            model=model or definition.model,
            url=url or definition.endpoint,
            **kwargs,
        )

    def _headers(self):
        validate_api_key(self.provider, self.api_key)
        if self.provider == "google":
            return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        for variable, header in (
            ("OPENAI_ORG_ID", "OpenAI-Organization"),
            ("OPENAI_PROJECT_ID", "OpenAI-Project"),
        ):
            if value := os.environ.get(variable):
                headers[header] = value
        return headers

    async def _post(self, payload):
        body, metadata = await post_decision(
            self, payload, retry_statuses={429, 500, 502, 503, 504, 529}
        )
        return body, {**metadata, "vendor_answers": body.get("answers")}

    def _record_evaluation(self, payload, body, answers, questions, state):
        if self.record_dir is None:
            return
        # Normalize recordings so existing replay works for all providers.
        record = {
            "status": "success",
            "provider": self.provider,
            "adapter_version": 1,
            "evaluation": answers.metadata,
            "request": {
                "state": prepare_decision_state(state),
                "questions": wire_questions(questions),
                "model": self.model,
            },
            "response": {
                "answers": {
                    key: value.model_dump(mode="json") for key, value in answers.answers.items()
                },
                "model": body.get("model") or self.model,
                "usage": self._usage(body),
            },
        }
        self._write_record(record, typed_answers=record["response"]["answers"])

    def _validate(self, raw, questions):
        if set(raw) != set(questions):
            raise SchemaViolation("Decision answers do not match the requested questions")
        for key, question in questions.items():
            answer = raw[key]
            if isinstance(question, NoulQuestion):
                _number(answer.get("noul"), probability=True)
                if self.provider == "google":
                    _number(answer.get("confidence"), probability=True)
            else:
                _number(answer.get("confidence"), probability=True)
                keys = (
                    question.options
                    if isinstance(question, ChoiceQuestion)
                    else [str(i) for i in range(question.levels)]
                )
                _distribution(answer.get("probabilities"), keys)
                if isinstance(question, ChoiceQuestion):
                    choice = answer.get("choice")
                    if choice not in question.options or answer["probabilities"][
                        choice
                    ] + 0.02 < max(answer["probabilities"].values()):
                        raise SchemaViolation(
                            "Decision choice does not match its outcome distribution"
                        )
                if not isinstance(question, ChoiceQuestion):
                    score = _number(answer.get("score"))
                    expected = sum(
                        int(index) * probability
                        for index, probability in answer["probabilities"].items()
                    )
                    if (
                        not 0 <= score <= question.levels - 1
                        or abs(score - expected) > 0.02 * question.levels
                    ):
                        raise SchemaViolation(
                            "Decision score does not match its rubric distribution"
                        )
        return raw


class GoogleDecisionClient(_DecisionAPIClient):
    provider = "google"
    name = "google-decisions"

    def _payload(self, state, questions):
        bound = coerce_questions(questions)
        if not 1 <= len(bound) <= 1000:
            raise SchemaViolation("Google Decisions accepts 1–1000 questions")
        wire = wire_questions(bound)
        mapped = {}
        for index, (key, question) in enumerate(bound.items()):
            value = wire[key]
            value["instructions"] = _text(value["instructions"])
            if isinstance(question, NoulQuestion):
                criteria = value.get("criteria")
                if criteria:
                    if set(criteria) - {"true", "false"}:
                        raise SchemaViolation(
                            "Google binary criteria must use true/false outcome keys"
                        )
                    value["criteria"] = {
                        f"{name}_description": text or ""
                        for name, text in criteria.items()
                        if name in {"true", "false"}
                    }
            elif isinstance(question, ChoiceQuestion):
                if len(question.options) < 2 or any(
                    not option
                    or option != option.strip()
                    or len(option) > 128
                    or len(option.encode()) > 512
                    or any(
                        ord(c) < 32 or 127 <= ord(c) <= 159 or (c.isspace() and c != " ")
                        for c in option
                    )
                    for option in question.options
                ):
                    raise SchemaViolation(
                        "Google choice keys must be 1–128 characters without surrounding/control spaces, with 2–255 options"
                    )
                value["criteria"] = {
                    option: text or "" for option, text in value["criteria"].items()
                }
            elif not 2 <= question.levels <= 255:
                raise SchemaViolation("Google Decisions accepts 2–255 rubric levels")
            else:
                value["criteria"] = [_text(level) for level in value["criteria"]]
                if any(not level.strip() for level in value["criteria"]):
                    raise SchemaViolation("Google rubric levels cannot be empty")
            mapped[f"q{index}"] = value
        evidence = prepare_decision_state(state)
        return {
            "model": self.model,
            "input": evidence
            if isinstance(evidence, str)
            else json.dumps(evidence, ensure_ascii=False),
            "questions": mapped,
        }

    def _decode_answers(self, body, questions):
        answers = body.get("answers")
        ids = {f"q{index}": key for index, key in enumerate(questions)}
        if not isinstance(answers, dict) or set(answers) != set(ids):
            raise SchemaViolation("Google decision response is incomplete")
        raw = {}
        for qid, key in ids.items():
            answer = answers[qid]
            if not isinstance(answer, dict) or answer.get("type") != questions[key].type:
                raise SchemaViolation("Google returned the wrong decision type")
            question = questions[key]
            if (
                not isinstance(question, (ChoiceQuestion, NoulQuestion))
                and answer.get("legend") is not None
            ):
                expected = {str(i): _text(level) for i, level in enumerate(question.criteria)}
                if answer["legend"] != expected:
                    raise SchemaViolation("Google returned a mismatched rubric legend")
            raw[key] = answer
        return self._validate(raw, questions)

    def _usage(self, body):
        usage = body.get("usage") or {}
        return {
            "input_tokens": usage.get("total_input_tokens"),
            "output_tokens": usage.get("total_output_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }


class OpenAIDecisionClient(_DecisionAPIClient):
    provider = "openai"
    name = "openai-decisions"

    def _payload(self, state, questions):
        bound = coerce_questions(questions)
        if not 1 <= len(bound) <= 400:
            raise SchemaViolation("OpenAI Decisions accepts 1–400 questions")
        wire = wire_questions(bound)
        mapped = []
        for index, (key, question) in enumerate(bound.items()):
            value = wire[key]
            item = {
                "type": question.type,
                "name": f"q{index}",
                "instructions": _text(value["instructions"]),
            }
            if isinstance(question, NoulQuestion):
                item["type"] = "predicate"
                if value.get("criteria"):
                    item["instructions"] += "\nOutcome definitions: " + json.dumps(
                        value["criteria"], ensure_ascii=False
                    )
            elif isinstance(question, ChoiceQuestion):
                if len(question.options) < 2:
                    raise SchemaViolation("OpenAI Decisions needs at least two choices")
                item["choices"] = [
                    {"value": option, "description": text or ""}
                    for option, text in value["criteria"].items()
                ]
            else:
                if not 2 <= question.levels <= 10:
                    raise SchemaViolation("OpenAI Decisions accepts 2–10 rubric levels")
                item["levels"] = [
                    {"label": str(i), "description": _text(text)}
                    for i, text in enumerate(value["criteria"])
                ]
            mapped.append(item)
        evidence = prepare_decision_state(state)
        return {
            "model": self.model,
            "input": evidence
            if isinstance(evidence, str)
            else json.dumps(evidence, ensure_ascii=False),
            "questions": mapped,
        }

    def _decode_answers(self, body, questions):
        answers = body.get("answers")
        ids = {f"q{index}": key for index, key in enumerate(questions)}
        if not isinstance(answers, list) or len(answers) != len(ids):
            raise SchemaViolation("OpenAI decision response is incomplete")
        raw = {}
        for answer in answers:
            if not isinstance(answer, dict) or answer.get("name") not in ids:
                raise SchemaViolation("OpenAI returned an unknown question")
            key = ids[answer["name"]]
            if key in raw:
                raise SchemaViolation("OpenAI returned a duplicate question")
            if answer.get("type") == "refusal":
                raise DecisionRefused(
                    "OpenAI refused a required decision; existing policy remains in force"
                )
            question = questions[key]
            if isinstance(question, NoulQuestion):
                if answer.get("type") != "predicate":
                    raise SchemaViolation("OpenAI returned the wrong decision type")
                raw[key] = {"noul": answer.get("probability")}
            else:
                if answer.get("type") != question.type or not isinstance(
                    answer.get("probabilities"), list
                ):
                    raise SchemaViolation("OpenAI returned the wrong decision type")
                probabilities = {}
                for entry in answer["probabilities"]:
                    if not isinstance(entry, dict):
                        raise SchemaViolation("OpenAI returned invalid probabilities")
                    value = entry.get("value")
                    if isinstance(question, ChoiceQuestion):
                        if not isinstance(value, str):
                            raise SchemaViolation("OpenAI returned an invalid choice")
                    else:
                        number = _number(value)
                        if not number.is_integer():
                            raise SchemaViolation("OpenAI returned an invalid rubric index")
                        value = int(number)
                        if "label" in entry and entry["label"] != str(value):
                            raise SchemaViolation("OpenAI returned a mismatched rubric label")
                    value = str(value)
                    if value in probabilities:
                        raise SchemaViolation("OpenAI returned a duplicate outcome")
                    probabilities[value] = entry.get("probability")
                raw[key] = {**answer, "probabilities": probabilities}
        return self._validate(raw, questions)
