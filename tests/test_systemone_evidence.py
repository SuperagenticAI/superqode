"""Evidence metadata must never include supplied content or credentials."""

import json
import httpx
from systemone_evidence import request_metadata


def test_evidence_contains_only_known_models_endpoints_and_structural_metadata():
    request = httpx.Request(
        "POST",
        "https://api.openai.com/v1/decisions?api_key=PRIVATE_QUERY",
        headers={"Authorization": "Bearer PRIVATE_HEADER"},
        json={
            "model": "gpt-6-luna",
            "input": "PRIVATE_PROMPT",
            "questions": [{"instructions": "PRIVATE_QUESTION"}],
        },
    )
    result = request_metadata(request)
    assert result["model"] == "gpt-6-luna" and result["question_count"] == 1
    assert result["endpoint"] == "https://api.openai.com/v1/decisions"
    assert "PRIVATE" not in json.dumps(result)


def test_unknown_models_are_not_copied_into_evidence():
    request = httpx.Request(
        "POST",
        "https://api.openai.com/v1/decisions",
        json={"model": "PRIVATE_MODEL", "input": "PRIVATE_PROMPT"},
    )
    assert request_metadata(request)["model"] == "custom-or-fixture"
    assert request_metadata(httpx.Request("GET", "https://private.invalid/no-api")) is None
