"""Tests for harness typed outputs."""

from pydantic import BaseModel
import pytest

from superqode.harness import (
    RESULT_END,
    RESULT_START,
    TypedOutputError,
    build_typed_output_prompt,
    parse_typed_output,
)


class TriageResult(BaseModel):
    fix_applied: bool
    summary: str


def test_build_typed_output_prompt_adds_delimiters_and_schema():
    prompt = build_typed_output_prompt("Return triage", TriageResult)

    assert prompt.startswith("Return triage")
    assert RESULT_START in prompt
    assert RESULT_END in prompt
    assert "fix_applied" in prompt
    assert "summary" in prompt


def test_parse_typed_output_from_delimiters():
    parsed = parse_typed_output(
        f'done\n{RESULT_START}\n{{"fix_applied": true, "summary": "ok"}}\n{RESULT_END}',
        TriageResult,
    )

    assert isinstance(parsed, TriageResult)
    assert parsed.fix_applied is True
    assert parsed.summary == "ok"


def test_parse_typed_output_accepts_raw_json():
    parsed = parse_typed_output('{"fix_applied": false, "summary": "none"}', TriageResult)

    assert parsed.fix_applied is False


def test_parse_typed_output_reports_missing_delimiter():
    with pytest.raises(TypedOutputError, match="missing ---RESULT_START---"):
        parse_typed_output("plain text", TriageResult)


def test_parse_typed_output_reports_validation_error():
    with pytest.raises(TypedOutputError, match="failed validation"):
        parse_typed_output(f'{RESULT_START}\n{{"fix_applied": "bad"}}\n{RESULT_END}', TriageResult)
