"""Rubric self-grading.

A rubric declares *what done looks like*. When set on
:class:`~superqode.agent.loop.AgentConfig`, every time the agent would
otherwise finish, a separate grader call judges the work against the
rubric. ``needs_revision`` feeds the grader's feedback back in and the loop
resumes; ``satisfied`` (or ``failed``, or hitting the round cap) lets the
run end. Two extra model calls at most by default — the grader is cheap
insurance on long unattended runs.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, List, Tuple

VERDICTS = ("satisfied", "needs_revision", "failed")

GRADER_SYSTEM_PROMPT = """You are a strict reviewer. Judge whether the assistant's work satisfies the rubric.

Respond with ONLY a JSON object: {"verdict": "satisfied"|"needs_revision"|"failed", "feedback": "<specific, actionable feedback when needs_revision; otherwise brief reason>"}

Rules:
- "satisfied": every rubric requirement is verifiably met.
- "needs_revision": fixable gaps remain; feedback must say exactly what to fix.
- "failed": the rubric cannot be satisfied from here (wrong direction, impossible requirement).
- Judge only against the rubric. Do not invent new requirements."""

_TRANSCRIPT_MESSAGE_CHARS = 600
_TRANSCRIPT_MESSAGES = 20


def _transcript_tail(messages: List[Any], final_content: str) -> str:
    lines: List[str] = []
    for m in messages[-_TRANSCRIPT_MESSAGES:]:
        role = getattr(m, "role", "?")
        if role == "system":
            continue
        content = getattr(m, "content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        text = content.strip()
        if len(text) > _TRANSCRIPT_MESSAGE_CHARS:
            text = text[:_TRANSCRIPT_MESSAGE_CHARS] + "…"
        lines.append(f"{role}: {text}")
    lines.append(f"assistant (final): {final_content.strip()[:2000]}")
    return "\n".join(lines)


def parse_grader_response(raw: str) -> Tuple[str, str]:
    """Parse a verdict; malformed output is explicitly ungraded."""
    text = (raw or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*\n|\n```\s*$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return "ungraded", "Rubric grader did not return a valid verdict"
    try:
        data = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return "ungraded", "Rubric grader did not return a valid verdict"
    if not isinstance(data, dict):
        return "ungraded", "Rubric grader did not return an object"
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in VERDICTS:
        return "ungraded", "Rubric grader did not return a valid verdict"
    return verdict, str(data.get("feedback", "")).strip()


async def grade_against_rubric(
    messages: List[Any],
    final_content: str,
    rubric: str,
    gateway: Any,
    provider: str,
    model: str,
    *,
    spec: Any = None,
    on_result: Any = None,
) -> Tuple[str, str]:
    """Grade with the utility model or opt-in Jev; uncertainty stays ungraded.

    Grading is a utility call: SUPERQODE_UTILITY_PROVIDER can route it to a
    cheaper model (including the on-device apple-fm) instead of the session model.
    """
    if os.environ.get("SUPERQODE_RUBRIC_GRADER", "").lower() == "systemone":
        result = await evaluate_jev_rubric(
            rubric, _transcript_tail(messages, final_content), spec=spec
        )
        if on_result:
            on_result(result)
        verdict = result["verdict"]
        if verdict == "needs_revision":
            return (
                verdict,
                f"Re-check each requirement and supply missing evidence. Rubric: {rubric}",
            )
        return verdict, result["reason"]
    try:
        from .utility_model import utility_completion

        raw = await utility_completion(
            gateway,
            provider,
            model,
            system=GRADER_SYSTEM_PROMPT,
            user=(
                f"<rubric>\n{rubric}\n</rubric>\n\n"
                f"<work>\n{_transcript_tail(messages, final_content)}\n</work>"
            ),
            max_tokens=400,
        )
        return parse_grader_response(raw)
    except Exception:
        return "ungraded", "Rubric grader did not return a valid verdict"


__all__ = ["GRADER_SYSTEM_PROMPT", "VERDICTS", "grade_against_rubric", "parse_grader_response"]


async def evaluate_jev_rubric(rubric: str, work: str, *, spec=None, client=None) -> dict[str, Any]:
    """One bounded decision; never turn abstention or client failure into success."""
    from dataclasses import replace

    from superqode.systemone.config import build_client, resolve_systemone
    from superqode.systemone.decision import evaluate_decision
    from superqode.systemone.pack import load_pack

    try:
        # Inherit endpoint, model, deadline and offline policy. A separate opt-in
        # enables grading without enabling the permission sidecar.
        from types import SimpleNamespace

        declared = getattr(spec, "systemone", None)
        if declared is None or not getattr(declared, "enabled", False):
            declared = SimpleNamespace(enabled=True, client="live")
        else:
            declared = SimpleNamespace(**{**vars(declared), "enabled": True})
        settings = resolve_systemone(spec=spec, explicit=declared)
        settings = replace(settings, pack="rubric")
        active = build_client(settings, injected=client)
        if active is None:
            return {
                "verdict": "ungraded",
                "reason": "Rubric client unavailable: " + (settings.skip_reason or "disabled"),
            }
        decision = await evaluate_decision(
            active, {"rubric": rubric, "work": work}, load_pack("rubric")
        )
        verdict = decision.outputs.get("verdict") if decision.status == "decided" else "ungraded"
        return {
            "verdict": verdict or "ungraded",
            "reason": "Jev rubric: " + str(verdict or "ungraded"),
            "decision": decision.model_dump(mode="json"),
        }
    except Exception:
        return {"verdict": "ungraded", "reason": "Rubric evaluation unavailable"}
