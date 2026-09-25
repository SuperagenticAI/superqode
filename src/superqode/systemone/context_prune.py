"""Query-aware keep-or-stub for old tool outputs.

Runs at the compaction boundary. Shadow records the decision and leaves the
prompt unchanged. Enforce stubs an output only when Jev is confidently
finished with it, the cut is large enough, and the result fits the window.
The original bytes stay on the loop. User and assistant text stay verbatim.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .client import ReplaySystemOneClient, StubSystemOneClient
from .config import build_client, is_airplane, resolve_systemone
from .pack import ContextPrunePolicy, load_pack
from .state import prepare_decision_state
from .types import NoulQuestion

logger = logging.getLogger(__name__)

CONTEXT_ENV = "SUPERQODE_JEV_CONTEXT"
CLIENT_ENV = "SUPERQODE_JEV_CONTEXT_CLIENT"
TIMEOUT_ENV = "SUPERQODE_JEV_CONTEXT_TIMEOUT_MS"
_OFF = {"", "0", "off", "false", "no", "disabled"}
_STUB_MARK = "[context chunk "


@dataclass(frozen=True)
class ToolCandidate:
    """One old tool call whose output may be stubbed."""

    chunk_id: str
    index: int
    name: str
    call_id: str
    arguments: str
    output_chars: int


def context_mode(environ: Mapping[str, str] | None = None) -> str:
    """Return ``off``, ``shadow``, or ``enforce``. Unknown values stay off."""
    env = environ if environ is not None else os.environ
    raw = str(env.get(CONTEXT_ENV) or "off").strip().lower()
    if raw in _OFF:
        return "off"
    if raw == "shadow":
        return "shadow"
    if raw == "enforce":
        return "enforce"
    return "off"


def context_original(loop: Any, chunk_id: str) -> str | None:
    """Return tool output retained when a stub replaced it in the live prompt."""
    store = getattr(loop, "_context_originals", None)
    if not isinstance(store, dict):
        return None
    value = store.get(chunk_id)
    return value if isinstance(value, str) else None


def _policy() -> ContextPrunePolicy:
    pack = load_pack("context_prune")
    return pack.context_policy or ContextPrunePolicy()


def _timeout_s(environ: Mapping[str, str], fallback_ms: int) -> float:
    raw = str(environ.get(TIMEOUT_ENV) or "").strip()
    if raw:
        try:
            return max(int(raw), 1) / 1000
        except ValueError:
            pass
    return max(int(fallback_ms), 1) / 1000


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return ""


def _call_parts(tool_call: Any) -> tuple[str, str, str]:
    """Return ``(call_id, name, arguments_text)`` from a dict or SDK object."""
    if isinstance(tool_call, dict):
        call_id = str(tool_call.get("id") or "")
        function = tool_call.get("function") or {}
        if not isinstance(function, dict):
            function = {}
        name = str(function.get("name") or tool_call.get("name") or "")
        arguments = function.get("arguments", "")
    else:
        call_id = str(getattr(tool_call, "id", "") or "")
        function = getattr(tool_call, "function", None)
        name = str(getattr(function, "name", "") or getattr(tool_call, "name", "") or "")
        arguments = getattr(function, "arguments", "") if function is not None else ""
    if not isinstance(arguments, str):
        try:
            arguments = json.dumps(arguments, default=str, sort_keys=True)
        except TypeError:
            arguments = str(arguments)
    return call_id, name, arguments


def _chunk_id(call_id: str, index: int) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in call_id)[:48]
    if safe:
        return f"tool-{safe}"
    return f"tool-i{index}"


def select_candidates(
    messages: list[Any],
    *,
    keep_recent_tokens: int,
    policy: ContextPrunePolicy,
    count_tokens,
) -> list[ToolCandidate]:
    """Old, large tool outputs outside the protected recent tail.

    A single output that crosses the recent-token budget is a candidate. The
    current turn's results, anything after the last assistant message, stay.
    """
    last_assistant = max(
        (
            index
            for index, message in enumerate(messages)
            if getattr(message, "role", "") == "assistant"
        ),
        default=len(messages),
    )
    prunable: set[int] = set()
    accumulated = 0
    for index in range(len(messages) - 1, -1, -1):
        try:
            accumulated += int(count_tokens(messages[index]))
        except (TypeError, ValueError):
            accumulated += max(1, len(_content_text(getattr(messages[index], "content", ""))) // 4)
        if accumulated <= keep_recent_tokens or index >= last_assistant:
            continue
        prunable.add(index)
    found: list[ToolCandidate] = []
    for index, message in enumerate(messages):
        if index not in prunable or getattr(message, "role", "") != "tool":
            continue
        text = _content_text(getattr(message, "content", ""))
        if len(text) < policy.min_output_chars or _STUB_MARK in text:
            continue
        call_id = str(getattr(message, "tool_call_id", "") or "")
        name = str(getattr(message, "name", "") or "tool")
        arguments = ""
        found.append(
            ToolCandidate(
                chunk_id=_chunk_id(call_id, index),
                index=index,
                name=name,
                call_id=call_id,
                arguments=arguments,
                output_chars=len(text),
            )
        )
    # Attach the matching call's arguments when the assistant turn is still present.
    by_id = {item.call_id: item for item in found if item.call_id}
    enriched: list[ToolCandidate] = []
    for message in messages:
        if getattr(message, "role", "") != "assistant" or not getattr(message, "tool_calls", None):
            continue
        for tool_call in message.tool_calls:
            call_id, name, arguments = _call_parts(tool_call)
            current = by_id.get(call_id)
            if current is None:
                continue
            enriched_item = ToolCandidate(
                chunk_id=current.chunk_id,
                index=current.index,
                name=name or current.name or "tool",
                call_id=current.call_id,
                arguments=arguments or current.arguments,
                output_chars=current.output_chars,
            )
            by_id[call_id] = enriched_item
    for item in found:
        enriched.append(by_id.get(item.call_id, item) if item.call_id else item)
    enriched.sort(key=lambda item: item.output_chars, reverse=True)
    return enriched[: policy.max_candidates]


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _user_texts(messages: list[Any]) -> list[str]:
    texts: list[str] = []
    for message in messages:
        if getattr(message, "role", "") == "user":
            text = _content_text(getattr(message, "content", ""))
            if text.strip():
                texts.append(text)
    return texts


def build_state(
    messages: list[Any], candidates: list[ToolCandidate], *, limit: int
) -> tuple[dict[str, Any], bool]:
    """Sketch the transcript. Tool bodies stay out of the decision state."""
    users = _user_texts(messages)
    candidate_ids = {item.chunk_id for item in candidates}
    turns: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        role = getattr(message, "role", "")
        if role == "tool":
            call_id = str(getattr(message, "tool_call_id", "") or "")
            name = str(getattr(message, "name", "") or "tool")
            chunk = _chunk_id(call_id, index)
            text = _content_text(getattr(message, "content", ""))
            if chunk not in candidate_ids and len(text) < 240:
                continue
            turns.append(
                {
                    "role": "tool",
                    "id": chunk,
                    "name": name,
                    "note": f"{name}: {len(text)} chars omitted",
                }
            )
            continue
        if role not in {"user", "assistant"}:
            continue
        text = _clip(_content_text(getattr(message, "content", "")), 180)
        tools: list[str] = []
        if role == "assistant" and getattr(message, "tool_calls", None):
            for tool_call in message.tool_calls:
                _, name, _arguments = _call_parts(tool_call)
                tools.append(name)
        if not text and not tools:
            continue
        turn: dict[str, Any] = {"role": role}
        if text:
            turn["text"] = text
        if tools:
            turn["tools"] = tools[:8]
        turns.append(turn)
    notes = []
    for item in candidates:
        notes.append(
            {
                "id": item.chunk_id,
                "name": item.name,
                "chars": item.output_chars,
                "input": _clip(item.arguments, 160),
            }
        )
    state: dict[str, Any] = {
        "task": _clip(users[0], 500) if users else "",
        "latest_request": _clip(users[-1], 500) if users else "",
        "turns": turns,
        "candidates": notes,
    }
    asked_same_task = len(users) >= 2
    if not asked_same_task:
        state.pop("latest_request", None)
        if users:
            state["latest_request"] = state["task"]
    while len(json.dumps(state, ensure_ascii=False)) > limit and state["turns"]:
        state["turns"].pop(0)
    return state, asked_same_task


def _questions(
    pack_questions: Mapping[str, NoulQuestion],
    candidates: list[ToolCandidate],
    *,
    ask_same_task: bool,
) -> dict[str, NoulQuestion]:
    questions: dict[str, NoulQuestion] = {}
    if ask_same_task and "same_task" in pack_questions:
        template = pack_questions["same_task"]
        questions["same_task"] = NoulQuestion(
            instructions=_question_text(template, "Compare `task` with `latest_request`."),
            criteria=template.criteria,
        )
    keep_call = pack_questions["keep_call"]
    keep_output = pack_questions["keep_output"]
    for offset, candidate in enumerate(candidates):
        suffix = f"Call id `{candidate.chunk_id}` in `candidates`. Tool: {candidate.name}."
        questions[f"keep_call_{offset}"] = NoulQuestion(
            instructions=_question_text(keep_call, suffix),
            criteria=keep_call.criteria,
        )
        questions[f"keep_output_{offset}"] = NoulQuestion(
            instructions=_question_text(keep_output, suffix),
            criteria=keep_output.criteria,
        )
    return questions


def _question_text(template: NoulQuestion, suffix: str) -> str:
    instructions = template.instructions
    if isinstance(instructions, dict):
        base = str(instructions.get("question") or "")
    else:
        base = str(instructions)
    return f"{base} {suffix}".strip()


def stub_text(name: str, content: str, chunk_id: str, head_chars: int) -> str:
    head = content[:head_chars].rstrip()
    return (
        f"{head}\n"
        f"{_STUB_MARK}{chunk_id}: output of '{name}' kept locally, "
        f"{len(content):,} chars. Call read_context_chunk with chunk_id {chunk_id} "
        f"to see the omitted text.]"
    )


def reduction_ratio(before: str, after: str) -> float:
    if not before:
        return 0.0
    saved = max(0, len(before) - len(after))
    return saved / len(before)


def cache_plan(
    *,
    same_task: float | None,
    stub_count: int,
    reprocess_tokens: int,
    applied: bool,
) -> dict[str, Any]:
    """Deterministic cache arithmetic. Jev does not estimate token cost."""
    if same_task is None:
        reason = "single_request"
        changed = False
    elif same_task < 0.4:
        reason = "task_changed"
        changed = True
    elif same_task >= 0.6:
        reason = "same_task"
        changed = False
    else:
        reason = "task_uncertain"
        changed = False
    if stub_count:
        reason = "tool_output_stub"
    recommended = "rebuild" if stub_count or changed else "reuse"
    return {
        "recommended_action": recommended,
        "applied_action": "rebuild" if applied else "reuse",
        "estimated_reprocess_tokens": reprocess_tokens if stub_count else 0,
        "reason_code": reason,
        "same_task": same_task,
    }


def _copy_message(message: Any, content: str) -> Any:
    return type(message)(
        role=message.role,
        content=content,
        tool_calls=getattr(message, "tool_calls", None),
        tool_call_id=getattr(message, "tool_call_id", None),
        name=getattr(message, "name", None),
        reasoning_content=getattr(message, "reasoning_content", None),
    )


def apply_stubs(
    messages: list[Any],
    chosen: list[tuple[ToolCandidate, str]],
    *,
    head_chars: int,
    originals: dict[str, str],
) -> list[Any]:
    """Return a new message list. ``originals`` receives the replaced bodies."""
    updated = list(messages)
    for candidate, _action in chosen:
        current = messages[candidate.index]
        content = _content_text(getattr(current, "content", ""))
        originals[candidate.chunk_id] = content
        updated[candidate.index] = _copy_message(
            current, stub_text(candidate.name, content, candidate.chunk_id, head_chars)
        )
    return updated


def _transcript_chars(messages: list[Any]) -> str:
    return "\n".join(_content_text(getattr(message, "content", "")) for message in messages)


def _token_count(loop: Any, messages: list[Any]) -> int:
    dicts = [
        {
            "role": getattr(message, "role", ""),
            "content": _content_text(getattr(message, "content", "")),
            "tool_calls": getattr(message, "tool_calls", None),
            "tool_result": (
                getattr(message, "content", "") if getattr(message, "role", "") == "tool" else None
            ),
        }
        for message in messages
    ]
    return int(loop.context_manager.count_tokens(dicts))


def _reprocess_tokens(loop: Any, messages: list[Any], first_index: int) -> int:
    if first_index >= len(messages):
        return 0
    return _token_count(loop, messages[first_index:])


def _client_for(loop: Any, environ: Mapping[str, str]) -> tuple[Any | None, str, str]:
    """Return ``(client, client_name, skip_reason)``."""
    injected = getattr(loop, "_systemone_client", None)
    if injected is not None:
        return injected, "injected", ""
    settings = resolve_systemone(
        spec=getattr(getattr(loop, "config", None), "harness_spec", None),
        explicit=getattr(getattr(loop, "config", None), "systemone", None),
        environ=environ,
    )
    requested = str(environ.get(CLIENT_ENV) or "").strip().lower()
    if settings.enabled and not requested:
        if settings.skip_client:
            return None, settings.client, settings.skip_reason or "skipped"
        return build_client(settings), settings.client, ""
    name = requested or "stub"
    if name == "live":
        if is_airplane(getattr(getattr(loop, "config", None), "harness_spec", None), environ):
            return None, "live", "airplane"
        key = str(environ.get("TYPESAFE_API_KEY") or "").strip()
        if not key:
            return None, "live", "live_unavailable"
        from .live import LiveSystemOneClient

        return (
            LiveSystemOneClient(
                model=settings.model,
                url=settings.endpoint,
                api_key=key,
                require_api_key=True,
                timeout_ms=settings.timeout_ms,
                record_dir=settings.record_dir or None,
            ),
            "live",
            "",
        )
    if name == "replay":
        if not settings.replay_path:
            return None, "replay", "missing_replay"
        return (
            ReplaySystemOneClient(settings.replay_path, trace_id=settings.replay_trace or None),
            "replay",
            "",
        )
    if name != "stub":
        return StubSystemOneClient(), "stub", ""
    return StubSystemOneClient(), "stub", ""


def _write_trace(trace_dir: str, event: dict[str, Any]) -> None:
    if not trace_dir:
        return
    try:
        directory = Path(trace_dir) / "context-prune"
        directory.mkdir(parents=True, exist_ok=True)
        event["trace_id"] = uuid4().hex
        payload = prepare_decision_state(event)
        fd = os.open(
            directory / f"{event['trace_id']}.json",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False)
    except (OSError, ValueError):
        logger.warning("System One context-prune trace could not be recorded")


def _base_event(mode: str, settings_model: str) -> dict[str, Any]:
    return {
        "kind": "context_prune",
        "mode": mode,
        "model": settings_model,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "skipped",
        "fallback": "",
        "applied": False,
        "stub_count": 0,
        "candidate_count": 0,
        "reduction": 0.0,
        "chunks": [],
        "cache": cache_plan(same_task=None, stub_count=0, reprocess_tokens=0, applied=False),
    }


async def apply_context_prune(
    loop: Any,
    messages: list[Any],
    *,
    keep_recent: int,
    threshold: int,
) -> tuple[list[Any], dict[str, Any]]:
    """Score old tool outputs. Enforce may return a stubbed copy of ``messages``."""
    environ = os.environ
    mode = context_mode(environ)
    settings = resolve_systemone(
        spec=getattr(getattr(loop, "config", None), "harness_spec", None),
        explicit=getattr(getattr(loop, "config", None), "systemone", None),
        environ=environ,
    )
    event = _base_event(mode, settings.model)
    event["session_id"] = str(getattr(loop, "session_id", "") or "")
    if mode == "off":
        event["fallback"] = "disabled"
        loop.last_context_prune = event
        return messages, event

    try:
        pack = load_pack("context_prune")
        policy = pack.context_policy or ContextPrunePolicy()
    except (OSError, ValueError) as exc:
        event.update(status="error", fallback="pack_unavailable", reason=type(exc).__name__)
        loop.last_context_prune = event
        return messages, event

    event["pack_id"] = pack.id
    event["pack_version"] = pack.version
    event["pack_hash"] = pack.content_hash()
    candidates = select_candidates(
        messages,
        keep_recent_tokens=keep_recent,
        policy=policy,
        count_tokens=lambda message: _token_count(loop, [message]),
    )
    event["candidate_count"] = len(candidates)
    if not candidates:
        event["fallback"] = "no_candidates"
        loop.last_context_prune = event
        _write_trace(settings.trace_dir, event)
        return messages, event

    client, client_name, skip_reason = _client_for(loop, environ)
    event["client"] = client_name
    if client is None:
        event.update(status="skipped", fallback=skip_reason or "no_client")
        loop.last_context_prune = event
        _write_trace(settings.trace_dir, event)
        return messages, event

    state, ask_same_task = build_state(messages, candidates, limit=policy.max_state_chars)
    try:
        state = prepare_decision_state(state)
    except ValueError:
        event.update(status="error", fallback="state_rejected")
        loop.last_context_prune = event
        _write_trace(settings.trace_dir, event)
        return messages, event

    questions = _questions(pack.questions, candidates, ask_same_task=ask_same_task)
    started = time.monotonic()
    try:
        answers = await asyncio.wait_for(
            client.evaluate(state, questions),
            timeout=_timeout_s(environ, settings.timeout_ms),
        )
        latency_ms = round((time.monotonic() - started) * 1000, 2)
        same_task = (
            answers.noul("same_task") if ask_same_task and "same_task" in questions else None
        )
        chosen: list[tuple[ToolCandidate, str]] = []
        chunks: list[dict[str, Any]] = []
        for offset, candidate in enumerate(candidates):
            keep_call = answers.noul(f"keep_call_{offset}")
            keep_output = answers.noul(f"keep_output_{offset}")
            action = "stub" if keep_output < policy.keep_below else "keep"
            chunks.append(
                {
                    "id": candidate.chunk_id,
                    "tool": candidate.name,
                    "keep_call": keep_call,
                    "keep_output": keep_output,
                    "action": action,
                }
            )
            if action == "stub":
                chosen.append((candidate, action))
    except Exception:
        event.update(
            status="error",
            fallback="evaluation_failed",
            latency_ms=round((time.monotonic() - started) * 1000, 2),
        )
        loop.last_context_prune = event
        _write_trace(settings.trace_dir, event)
        return messages, event

    originals: dict[str, str] = {}
    proposed = (
        apply_stubs(messages, chosen, head_chars=policy.stub_head_chars, originals=originals)
        if chosen
        else messages
    )
    before = _transcript_chars(messages)
    after = _transcript_chars(proposed)
    ratio = reduction_ratio(before, after)
    tokens_after = _token_count(loop, proposed) if chosen else _token_count(loop, messages)
    fits = bool(chosen) and tokens_after <= threshold
    enough = ratio + 1e-12 >= policy.min_reduction
    applied = mode == "enforce" and fits and enough
    if not chosen:
        fallback = "nothing_to_stub"
    elif mode == "shadow":
        fallback = ""
    elif not enough:
        fallback = "low_reduction"
    elif not fits:
        fallback = "still_over_budget"
    else:
        fallback = ""
    if applied:
        ensure = getattr(loop, "_ensure_context_chunk_tool", None)
        if callable(ensure):
            ensure()
        store = getattr(loop, "_context_originals", None)
        if not isinstance(store, dict):
            store = {}
            loop._context_originals = store
        store.update(originals)
        result_messages = proposed
    else:
        result_messages = messages
    first_index = min((item.index for item, _action in chosen), default=len(messages))
    event.update(
        status="success",
        fallback=fallback,
        applied=applied,
        stub_count=len(chosen),
        reduction=round(ratio, 4),
        tokens_before=_token_count(loop, messages),
        tokens_after=_token_count(loop, result_messages),
        latency_ms=latency_ms,
        chunks=chunks,
        cache=cache_plan(
            same_task=same_task,
            stub_count=len(chosen),
            reprocess_tokens=_reprocess_tokens(loop, messages, first_index),
            applied=applied,
        ),
    )
    loop.last_context_prune = event
    _write_trace(settings.trace_dir, event)
    return result_messages, event


__all__ = [
    "CLIENT_ENV",
    "CONTEXT_ENV",
    "TIMEOUT_ENV",
    "ToolCandidate",
    "apply_context_prune",
    "apply_stubs",
    "build_state",
    "cache_plan",
    "context_mode",
    "context_original",
    "reduction_ratio",
    "select_candidates",
    "stub_text",
]
