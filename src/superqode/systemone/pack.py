"""Frozen, human-reviewed System One question packs.

Put questions and thresholds in one place. Packs ship as YAML, are hashed
for the audit trail, and load without a model.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .types import Question, coerce_questions, wire_questions

PACKS_DIR = Path(__file__).parent / "packs"


class ToolGateThresholds(BaseModel):
    """Compose thresholds. Change these in the pack, not in prompt text."""

    model_config = ConfigDict(extra="forbid")

    deny_noul: float = Field(default=0.7, ge=0.0, le=1.0)
    allow_noul: float = Field(default=0.8, ge=0.0, le=1.0)
    allow_risk_max: float = Field(default=0.2, ge=0.0, le=1.0)
    allow_confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    noul_uncertain: tuple[float, float] = (0.4, 0.6)

    @field_validator("noul_uncertain")
    @classmethod
    def _band(cls, value: tuple[float, float]) -> tuple[float, float]:
        low, high = float(value[0]), float(value[1])
        if not 0.0 <= low < high <= 1.0:
            raise ValueError("noul_uncertain must be a (low, high) band inside (0, 1]")
        return (low, high)

    @model_validator(mode="after")
    def _risk_order(self):
        if self.allow_risk_max >= self.deny_noul:
            raise ValueError("allow_risk_max must be lower than deny_noul")
        return self

    def uncertain(self, noul: float) -> bool:
        low, high = self.noul_uncertain
        return low < noul < high


class DecisionPolicy(BaseModel):
    """Confidence bounds applied in code to general decision outputs."""

    model_config = ConfigDict(extra="forbid")
    min_confidence: float = Field(default=0.75, ge=0, le=1)
    noul_false_max: float = Field(default=0.2, ge=0, le=1)
    noul_true_min: float = Field(default=0.8, ge=0, le=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.noul_false_max >= self.noul_true_min:
            raise ValueError("Noul false bound must be lower than true bound")
        return self


class QuestionPack(BaseModel):
    """One versioned pack: questions plus optional compose thresholds."""

    model_config = ConfigDict(extra="forbid")

    id: str
    version: str
    description: str = ""
    questions: dict[str, Question]
    thresholds: ToolGateThresholds = Field(default_factory=ToolGateThresholds)
    state_schema: dict[str, Any] | None = None
    input_key: str = ""
    decision_policy: DecisionPolicy = Field(default_factory=DecisionPolicy)

    @field_validator("state_schema")
    @classmethod
    def valid_schema(cls, schema):
        if schema is None:
            return schema
        from jsonschema import Draft202012Validator

        Draft202012Validator.check_schema(schema)

        def check_refs(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"$ref", "$dynamicRef"} and not str(item).startswith("#"):
                        raise ValueError("State schemas only support local references")
                    check_refs(item)
            elif isinstance(value, list):
                for item in value:
                    check_refs(item)

        check_refs(schema)
        return schema

    def content_hash(self) -> str:
        payload = self.model_dump(mode="json")
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        digest = "sha256:" + hashlib.sha256(blob).hexdigest()
        return digest

    def wire_questions(self) -> dict[str, Any]:
        if not self.questions:
            raise ValueError(f"pack {self.id!r} has no questions")
        return wire_questions(self.questions)


def load_pack(source: str | Path) -> QuestionPack:
    """Load a pack by builtin id (``tool_gate``) or from a YAML/JSON path."""
    path = Path(source)
    if not path.suffix and not path.exists():
        path = PACKS_DIR / f"{source}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"System One pack not found: {source}")
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        import yaml

        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"pack {path} must be a mapping")
    questions = coerce_questions(data.get("questions") or {})
    payload = {**data, "questions": questions}
    return QuestionPack.model_validate(payload)


def builtin_pack_ids() -> tuple[str, ...]:
    return tuple(sorted(path.stem for path in PACKS_DIR.glob("*.yaml")))


__all__ = [
    "PACKS_DIR",
    "QuestionPack",
    "ToolGateThresholds",
    "builtin_pack_ids",
    "load_pack",
]
