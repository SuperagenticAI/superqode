"""Automatic memory extraction (codex memories pattern, opt-in).

After a completed run, a small extraction call distills durable,
non-obvious facts from the conversation — user preferences ("use pnpm,
never npm"), project facts ("tests need DS4 running"), decisions made —
and stores them in the local memory provider, where ``:memory search`` and
SpecMem-aware flows already look.

Strictly opt-in (``SUPERQODE_AUTO_MEMORY=1``): it spends an extra model
call per qualifying run. Extraction runs as a background task so the user
never waits on it; failures are silent by design (memory is best-effort).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, List, Optional

AUTO_MEMORY_ENV = "SUPERQODE_AUTO_MEMORY"
# Don't bother extracting from trivial exchanges.
MIN_MESSAGES = 6
MAX_MEMORIES_PER_RUN = 5
_TRANSCRIPT_MESSAGE_CHARS = 400
_TRANSCRIPT_MESSAGES = 30

_EXTRACTION_PROMPT = """Review the conversation transcript and extract durable memories worth keeping for future sessions in this project.

Extract ONLY:
- explicit user preferences about how to work ("always X", "never Y")
- non-obvious project facts discovered during the work (setup quirks, constraints)
- decisions made and their reasons

Do NOT extract: task progress, code contents, anything obvious from the repo itself, or one-off details.

Respond with a JSON array (and nothing else). Each item: {"kind": "preference"|"fact"|"decision", "content": "<one concise sentence>"}. Respond with [] if nothing qualifies."""


def auto_memory_enabled() -> bool:
    return os.environ.get(AUTO_MEMORY_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _transcript(messages: List[Any]) -> str:
    lines: List[str] = []
    for m in messages[-_TRANSCRIPT_MESSAGES:]:
        role = getattr(m, "role", "?")
        if role == "system":
            continue
        content = getattr(m, "content", "")
        if not isinstance(content, str):
            continue  # skip multimodal parts
        text = content.strip()
        if not text:
            continue
        if len(text) > _TRANSCRIPT_MESSAGE_CHARS:
            text = text[:_TRANSCRIPT_MESSAGE_CHARS] + "…"
        lines.append(f"{role}: {text}")
    return "\n".join(lines)


def _parse_memory_array(raw: str) -> List[dict]:
    text = (raw or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*\n|\n```\s*$", "", text)
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data[:MAX_MEMORIES_PER_RUN]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        kind = str(item.get("kind", "fact")).strip().lower()
        if kind not in ("preference", "fact", "decision"):
            kind = "fact"
        if 10 <= len(content) <= 500:
            out.append({"kind": kind, "content": content})
    return out


async def extract_session_memories(
    messages: List[Any],
    gateway: Any,
    provider: str,
    model: str,
    project_root: Path,
    store: Optional[Any] = None,
) -> int:
    """Extract and store memories from a finished run. Returns stored count.

    Never raises - memory is best-effort and must not break a run.
    """
    try:
        if len(messages) < MIN_MESSAGES:
            return 0
        transcript = _transcript(messages)
        if len(transcript) < 200:
            return 0

        from ..providers.gateway.base import Message

        response = await gateway.chat_completion(
            messages=[
                Message(role="system", content=_EXTRACTION_PROMPT),
                Message(role="user", content=f"<transcript>\n{transcript}\n</transcript>"),
            ],
            model=model,
            provider=provider,
            temperature=0.0,
            max_tokens=600,
        )
        memories = _parse_memory_array(getattr(response, "content", "") or "")
        if not memories:
            return 0

        if store is None:
            from ..memory.providers import LocalAgentMemoryProvider

            store = LocalAgentMemoryProvider(project_root)

        stored = 0
        for memory in memories:
            try:
                # Skip near-duplicates already in the store.
                existing = store.search(memory["content"], limit=1)
                if existing and existing[0].score >= 0.99:
                    continue
                store.remember(memory["content"], kind=memory["kind"], tags=("auto",))
                stored += 1
            except Exception:
                continue
        return stored
    except Exception:
        return 0


__all__ = [
    "AUTO_MEMORY_ENV",
    "MIN_MESSAGES",
    "auto_memory_enabled",
    "extract_session_memories",
]
