"""Explicit synthetic connectivity probe, shared by native setup and smoke tests."""

from .pack import load_pack

SYNTHETIC_STATE = {"message": "Please review this code change."}


async def check_connection(client):
    pack = load_pack("provider_check")
    answers = await client.evaluate(dict(SYNTHETIC_STATE), pack.questions)
    return {
        "status": "connected",
        "provider": answers.metadata["provider"],
        "model": answers.metadata["requested_model"],
        "resolved_model": answers.metadata.get("resolved_model"),
        "checked_primitives": ["noul", "choice", "score"],
        "latency_ms": answers.metadata.get("latency_ms"),
        "usage": answers.metadata.get("usage"),
        "note": "API connectivity and answer schema only; this does not certify decision quality.",
    }
