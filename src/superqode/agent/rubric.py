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
    """Parse the grader's JSON; unparseable output counts as satisfied.

    Failing open is deliberate: a flaky grader must never trap a run in
    revision loops.
    """
    text = (raw or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*\n|\n```\s*$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return "satisfied", ""
    try:
        data = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return "satisfied", ""
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in VERDICTS:
        return "satisfied", ""
    return verdict, str(data.get("feedback", "")).strip()


async def grade_against_rubric(
    messages: List[Any],
    final_content: str,
    rubric: str,
    gateway: Any,
    provider: str,
    model: str,
) -> Tuple[str, str]:
    """Run one grader call. Returns (verdict, feedback); fails open to satisfied."""
    try:
        from ..providers.gateway.base import Message

        response = await gateway.chat_completion(
            messages=[
                Message(role="system", content=GRADER_SYSTEM_PROMPT),
                Message(
                    role="user",
                    content=(
                        f"<rubric>\n{rubric}\n</rubric>\n\n"
                        f"<work>\n{_transcript_tail(messages, final_content)}\n</work>"
                    ),
                ),
            ],
            model=model,
            provider=provider,
            temperature=0.0,
            max_tokens=400,
        )
        return parse_grader_response(getattr(response, "content", "") or "")
    except Exception:
        return "satisfied", ""


__all__ = ["GRADER_SYSTEM_PROMPT", "VERDICTS", "grade_against_rubric", "parse_grader_response"]
