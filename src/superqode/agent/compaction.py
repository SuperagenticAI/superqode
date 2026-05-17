"""
Structured conversation compaction.

When a session outgrows the model's context window, we replace the bulk of
the transcript with a single structured Markdown summary plus a short
tail of recent turns. The 9-section template is ported from opencode's
``session/compaction.ts`` so summaries are predictable enough for the
next assistant turn to reason against.

This is opt-in via ``AgentConfig.enable_summarization`` and currently
runs once per turn when the token estimate crosses the limit. If the
summarization call fails or returns nothing, the caller falls back to
mechanical pruning.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, TYPE_CHECKING

from ..providers.gateway.base import GatewayInterface, Message

if TYPE_CHECKING:
    from .loop import AgentMessage


COMPACTION_PROMPT = """Summarize the conversation so far into a structured Markdown report.

Output exactly the Markdown structure shown inside <template> and keep the section order unchanged. Do not include the <template> tags in your response.

<template>
## Goal
- [single-sentence task summary]

## Constraints & Preferences
- [user constraints, preferences, specs, or "(none)"]

## Progress
### Done
- [completed work or "(none)"]

### In Progress
- [current work or "(none)"]

### Blocked
- [blockers or "(none)"]

## Key Decisions
- [decision and why, or "(none)"]

## Next Steps
- [ordered next actions or "(none)"]

## Critical Context
- [important technical facts, errors, open questions, or "(none)"]

## Relevant Files
- [file or directory path: why it matters, or "(none)"]
</template>

Rules:
- Keep every section, even when empty.
- Use terse bullets, not prose paragraphs.
- Preserve exact file paths, commands, error strings, and identifiers when known.
- Do not mention the summary process or that context was compacted."""


def serialize_for_compaction(messages: Iterable["AgentMessage"]) -> str:
    """Render a transcript fragment for the summarizer.

    Tool-call assistant turns include a one-line summary of which tools
    were invoked; tool results keep their content. Empty messages are
    skipped because they would otherwise inflate the transcript without
    carrying information.
    """
    parts: List[str] = []
    for m in messages:
        role = m.role
        content = (m.content or "").strip()
        if m.tool_calls:
            names = ", ".join(tc.get("function", {}).get("name", "?") for tc in m.tool_calls)
            tool_line = f"[tool calls: {names}]"
            content = (content + "\n" + tool_line).strip() if content else tool_line
        if not content:
            continue
        parts.append(f"--- {role} ---\n{content}")
    return "\n\n".join(parts)


async def compact_history(
    messages: List["AgentMessage"],
    gateway: GatewayInterface,
    provider: str,
    model: str,
) -> Optional[str]:
    """Ask the model to produce a structured summary of ``messages``.

    Returns the summary text, or ``None`` if the call fails, the
    transcript is empty, or the model returns nothing. Callers should
    fall back to mechanical pruning on ``None``.
    """
    if not messages:
        return None
    transcript = serialize_for_compaction(messages)
    if not transcript:
        return None

    request_messages = [
        Message(role="system", content=COMPACTION_PROMPT),
        Message(role="user", content=transcript),
    ]
    try:
        response = await gateway.chat_completion(
            messages=request_messages,
            model=model,
            provider=provider,
            temperature=0.0,
        )
    except Exception:
        return None

    summary = (response.content or "").strip()
    return summary or None
