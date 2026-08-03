"""Context compaction and branch summarization.

Ported from ``packages/agent/src/harness/compaction/`` of earendil-works/pi
(MIT). The prompts are reproduced verbatim, because the summary format is what
lets a compacted session continue coherently.

Compaction never deletes anything. It appends a compaction entry that tells the
context builder where to cut, so the full history stays in the tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .messages import (
    AgentMessage,
    AssistantMessage,
    TextContent,
    ToolResultMessage,
    Usage,
    UserMessage,
    default_convert_to_llm,
)
from .provider_events import AssistantDoneEvent, AssistantErrorEvent
from .session.entries import CompactionEntry, MessageEntry, SessionTreeEntry
from .signals import AbortSignal
from .stream import Context, Model, StreamFn, StreamOptions

SUMMARIZATION_SYSTEM_PROMPT = """You are a context summarization assistant. Your task is to read a conversation between a user and an AI assistant, then produce a structured summary following the exact format specified.

Do NOT continue the conversation. Do NOT respond to any questions in the conversation. ONLY output the structured summary."""

SUMMARIZATION_PROMPT = """The messages above are a conversation to summarize. Create a structured context checkpoint summary that another LLM will use to continue the work.

Use this EXACT format:

## Goal
[What is the user trying to accomplish? Can be multiple items if the session covers different tasks.]

## Constraints & Preferences
- [Any constraints, preferences, or requirements mentioned by user]
- [Or "(none)" if none were mentioned]

## Progress
### Done
- [x] [Completed tasks/changes]

### In Progress
- [ ] [Current work]

### Blocked
- [Issues preventing progress, if any]

## Key Decisions
- **[Decision]**: [Brief rationale]

## Next Steps
1. [Ordered list of what should happen next]

## Critical Context
- [Any data, examples, or references needed to continue]
- [Or "(none)" if not applicable]

Keep each section concise. Preserve exact file paths, function names, and error messages."""

UPDATE_SUMMARIZATION_PROMPT = """The messages above are NEW conversation messages to incorporate into the existing summary provided in <previous-summary> tags.

Update the existing structured summary with new information. RULES:
- PRESERVE all existing information from the previous summary
- ADD new progress, decisions, and context from the new messages
- UPDATE the Progress section: move items from "In Progress" to "Done" when completed
- UPDATE "Next Steps" based on what was accomplished
- PRESERVE exact file paths, function names, and error messages
- If something is no longer relevant, you may remove it

Use this EXACT format:

## Goal
[Preserve existing goals, add new ones if the task expanded]

## Constraints & Preferences
- [Preserve existing, add new ones discovered]

## Progress
### Done
- [x] [Include previously done items AND newly completed items]

### In Progress
- [ ] [Current work - update based on progress]

### Blocked
- [Current blockers - remove if resolved]

## Key Decisions
- **[Decision]**: [Brief rationale] (preserve all previous, add new)

## Next Steps
1. [Update based on current state]

## Critical Context
- [Preserve important context, add new if needed]

Keep each section concise. Preserve exact file paths, function names, and error messages."""

BRANCH_SUMMARY_SYSTEM_PROMPT = """You are a conversation summarization assistant. Summarize what happened on a branch of a conversation that is being left behind.

Do NOT continue the conversation. ONLY output the summary."""

BRANCH_SUMMARY_PROMPT = """The messages above are a branch of a conversation that the user is navigating away from. Summarize what was attempted and what was learned, so the main conversation can benefit from it without replaying the whole branch.

Keep it short. Preserve exact file paths, function names, and error messages."""

#: Rough characters-per-token ratio used when no provider usage is available.
CHARS_PER_TOKEN = 4
#: An image costs roughly this many characters of context.
ESTIMATED_IMAGE_CHARS = 4800


@dataclass(slots=True)
class CompactionSettings:
    """Thresholds and retention, defaults matching pi."""

    enabled: bool = True
    #: Held back for the summarization prompt and its output.
    reserve_tokens: int = 16384
    #: Approximate recent context kept verbatim after compaction.
    keep_recent_tokens: int = 20000


DEFAULT_COMPACTION_SETTINGS = CompactionSettings()


class CompactionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(slots=True)
class CompactionPreparation:
    """What a compaction would do, computed before any model call."""

    first_kept_entry_id: str
    messages_to_summarize: list[AgentMessage] = field(default_factory=list)
    retained_tail: list[AgentMessage] = field(default_factory=list)
    previous_summary: str | None = None
    tokens_before: int = 0


@dataclass(slots=True)
class CompactResult:
    summary: str
    first_kept_entry_id: str | None = None
    tokens_before: int = 0
    usage: Usage | None = None


def calculate_context_tokens(usage: Usage) -> int:
    """Total context tokens a turn consumed, per pi's accounting."""
    if usage.total_tokens:
        return usage.total_tokens
    return usage.input + usage.output + usage.cache_read + usage.cache_write


def get_last_assistant_usage(entries: list[SessionTreeEntry]) -> Usage | None:
    """Usage from the last assistant turn that actually completed."""
    for entry in reversed(entries):
        if not isinstance(entry, MessageEntry):
            continue
        message = entry.message
        if not isinstance(message, AssistantMessage):
            continue
        if message.stop_reason in ("error", "aborted"):
            continue
        if calculate_context_tokens(message.usage) > 0:
            return message.usage
    return None


def estimate_message_tokens(message: AgentMessage) -> int:
    """Character-based estimate, used where no provider usage exists."""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return max(1, len(content) // CHARS_PER_TOKEN)
    chars = 0
    for block in content or []:
        if isinstance(block, TextContent):
            chars += len(block.text)
        elif getattr(block, "type", "") == "image":
            chars += ESTIMATED_IMAGE_CHARS
        elif getattr(block, "type", "") == "thinking":
            chars += len(getattr(block, "thinking", ""))
        elif getattr(block, "type", "") == "toolCall":
            chars += len(str(getattr(block, "arguments", "")))
    summary = getattr(message, "summary", None)
    if isinstance(summary, str):
        chars += len(summary)
    return max(1, chars // CHARS_PER_TOKEN)


def estimate_context_tokens(messages: list[AgentMessage]) -> int:
    return sum(estimate_message_tokens(message) for message in messages)


def should_compact(context_tokens: int, context_window: int, settings: CompactionSettings) -> bool:
    """Whether the next turn would run too close to the context limit."""
    if not settings.enabled:
        return False
    return context_tokens > context_window - settings.reserve_tokens


def _entry_message(entry: SessionTreeEntry) -> AgentMessage | None:
    return entry.message if isinstance(entry, MessageEntry) else None


def prepare_compaction(
    path_entries: list[SessionTreeEntry],
    settings: CompactionSettings = DEFAULT_COMPACTION_SETTINGS,
) -> CompactionPreparation | None:
    """Choose the cut point. Returns None when there is nothing to compact."""
    if not path_entries or isinstance(path_entries[-1], CompactionEntry):
        return None

    previous_index = -1
    for index in range(len(path_entries) - 1, -1, -1):
        if isinstance(path_entries[index], CompactionEntry):
            previous_index = index
            break

    previous_summary: str | None = None
    boundary_start = 0
    if previous_index >= 0:
        previous = path_entries[previous_index]
        assert isinstance(previous, CompactionEntry)
        previous_summary = previous.summary
        first_kept_index = -1
        if previous.first_kept_entry_id:
            first_kept_index = next(
                (
                    i
                    for i, entry in enumerate(path_entries)
                    if entry.id == previous.first_kept_entry_id
                ),
                -1,
            )
        boundary_start = first_kept_index if first_kept_index >= 0 else previous_index + 1

    candidates = list(range(boundary_start, len(path_entries)))
    if not candidates:
        return None

    # Walk back from the newest entry until the retained tail is about
    # keep_recent_tokens, then cut there.
    kept_tokens = 0
    cut_index = len(path_entries)
    for index in reversed(candidates):
        message = _entry_message(path_entries[index])
        if message is not None:
            kept_tokens += estimate_message_tokens(message)
        cut_index = index
        if kept_tokens >= settings.keep_recent_tokens:
            break

    if cut_index <= boundary_start:
        # Everything is recent. Nothing older is left to summarize.
        return None

    first_kept = path_entries[cut_index]
    if not first_kept.id:
        raise CompactionError("invalid_session", "First kept entry has no id")

    messages_to_summarize = [
        message
        for entry in path_entries[boundary_start:cut_index]
        if (message := _entry_message(entry)) is not None
    ]
    retained_tail = [
        message
        for entry in path_entries[cut_index:]
        if (message := _entry_message(entry)) is not None
    ]
    if not messages_to_summarize:
        return None

    return CompactionPreparation(
        first_kept_entry_id=first_kept.id,
        messages_to_summarize=messages_to_summarize,
        retained_tail=retained_tail,
        previous_summary=previous_summary,
        tokens_before=estimate_context_tokens(messages_to_summarize + retained_tail),
    )


async def _run_summary(
    *,
    stream_fn: StreamFn,
    model: Model,
    system_prompt: str,
    messages: list[AgentMessage],
    instruction: str,
    signal: AbortSignal | None,
    error_code: str,
) -> tuple[str, Usage | None]:
    context = Context(
        system_prompt=system_prompt,
        messages=default_convert_to_llm([*messages, UserMessage(content=instruction)]),
        tools=None,
    )
    response = stream_fn(model, context, StreamOptions(signal=signal))
    if hasattr(response, "__await__"):
        response = await response  # type: ignore[misc]

    final: AssistantMessage | None = None
    async for event in response:  # type: ignore[union-attr]
        if isinstance(event, AssistantDoneEvent):
            final = event.message
            break
        if isinstance(event, AssistantErrorEvent):
            final = event.error
            break

    if final is None:
        raise CompactionError(error_code, "Summarization produced no assistant message")
    if final.stop_reason in ("error", "aborted"):
        raise CompactionError(error_code, final.error_message or "Summarization failed")
    text = final.text.strip()
    if not text:
        raise CompactionError(error_code, "Summarization produced an empty summary")
    return text, final.usage


async def generate_summary(
    preparation: CompactionPreparation,
    *,
    stream_fn: StreamFn,
    model: Model,
    custom_instructions: str | None = None,
    signal: AbortSignal | None = None,
) -> tuple[str, Usage | None]:
    """Summarize the messages a compaction is about to drop from context."""
    if preparation.previous_summary:
        instruction = (
            f"<previous-summary>\n{preparation.previous_summary}\n</previous-summary>\n\n"
            f"{UPDATE_SUMMARIZATION_PROMPT}"
        )
    else:
        instruction = SUMMARIZATION_PROMPT
    if custom_instructions:
        instruction = f"{instruction}\n\nAdditional instructions:\n{custom_instructions}"

    return await _run_summary(
        stream_fn=stream_fn,
        model=model,
        system_prompt=SUMMARIZATION_SYSTEM_PROMPT,
        messages=preparation.messages_to_summarize,
        instruction=instruction,
        signal=signal,
        error_code="summarization_failed",
    )


async def generate_branch_summary(
    entries: list[SessionTreeEntry],
    *,
    stream_fn: StreamFn,
    model: Model,
    signal: AbortSignal | None = None,
) -> tuple[str, Usage | None]:
    """Summarize a branch that is being navigated away from."""
    messages = [message for entry in entries if (message := _entry_message(entry)) is not None]
    if not messages:
        raise CompactionError("branch_summary_failed", "Branch has no messages to summarize")
    return await _run_summary(
        stream_fn=stream_fn,
        model=model,
        system_prompt=BRANCH_SUMMARY_SYSTEM_PROMPT,
        messages=messages,
        instruction=BRANCH_SUMMARY_PROMPT,
        signal=signal,
        error_code="branch_summary_failed",
    )


__all__ = [
    "BRANCH_SUMMARY_PROMPT",
    "BRANCH_SUMMARY_SYSTEM_PROMPT",
    "DEFAULT_COMPACTION_SETTINGS",
    "SUMMARIZATION_PROMPT",
    "SUMMARIZATION_SYSTEM_PROMPT",
    "UPDATE_SUMMARIZATION_PROMPT",
    "CompactResult",
    "CompactionError",
    "CompactionPreparation",
    "CompactionSettings",
    "calculate_context_tokens",
    "estimate_context_tokens",
    "estimate_message_tokens",
    "generate_branch_summary",
    "generate_summary",
    "get_last_assistant_usage",
    "prepare_compaction",
    "should_compact",
]
