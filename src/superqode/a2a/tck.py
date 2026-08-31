"""Fixture replies for the official A2A Technology Compatibility Kit.

The TCK at https://github.com/a2aproject/a2a-tck drives a System Under Test
through behaviours the A2A specification does not describe. Its
``docs/SUT_REQUIREMENTS.md`` calls these "testing-specific requirements beyond
the core A2A specification": a task whose message id starts with
``test-resubscribe-message-id`` has to stay active long enough to resubscribe
to, and several checks assert on artifact text and filenames the reference SUT
returns verbatim.

A real agent fails those checks by doing real work. Running SuperQode against
the kit returned an artifact describing an actual repository search where the
kit expected the literal string ``Generated text content``. So certification
needs a mode that answers the kit on its own terms, which is what this module
is. It is selected by message id prefix and only when
``A2AServerConfig.conformance_mode`` is on.

Nothing here should ever run for a real caller. The routing lives in its own
module so that is easy to see and easy to keep out of the harness path.
"""

from __future__ import annotations

import asyncio
from typing import Any

#: How long a resubscribe fixture task stays active.
#:
#: ``SUT_REQUIREMENTS.md`` requires at least ``2 x TCK_STREAMING_TIMEOUT``, and
#: the kit defaults that timeout to 2 seconds. Four seconds is the reference
#: SUT's own answer.
RESUBSCRIBE_HOLD_SECONDS = 4.0

#: Message id prefixes the kit routes on, longest first so that
#: ``tck-stream-artifact-file`` is not claimed by ``tck-stream-artifact``.
CONFORMANCE_PREFIXES: tuple[str, ...] = (
    "tck-stream-artifact-chunked",
    "tck-stream-artifact-text",
    "tck-stream-artifact-file",
    "tck-stream-ordering-001",
    "test-resubscribe-message-id",
    "tck-artifact-file-url",
    "tck-message-response",
    "tck-input-required",
    "tck-complete-task",
    "tck-artifact-text",
    "tck-artifact-file",
    "tck-artifact-data",
    "tck-reject-task",
    "tck-stream-001",
    "tck-stream-002",
    "tck-stream-003",
)


def conformance_message_id(context: Any) -> str:
    """Return the incoming message id, or an empty string when there is none."""
    message = getattr(context, "message", None)
    for attribute in ("message_id", "messageId"):
        value = getattr(message, attribute, None)
        if isinstance(value, str) and value:
            return value
    return ""


def wants_conformance(message_id: str) -> bool:
    """Whether this message id is one of the kit's fixtures."""
    return any(message_id.startswith(prefix) for prefix in CONFORMANCE_PREFIXES)


async def answer_conformance(
    updater: Any, event_queue: Any, sdk: dict[str, Any], message_id: str
) -> bool:
    """Reply to one kit fixture. Always answers while conformance mode is on.

    Mirrors the reference SUT in ``sut/a2a-python/sut_agent.py``. Kept as a
    flat sequence of prefix checks in the same order the reference uses, so the
    two can be read side by side when the kit changes.

    Unrecognised ids get the reference SUT's echo rather than falling through
    to the harness. The kit sends ids it never declares as fixtures, such as the
    one behind its extensions-header check, and letting those reach a real
    harness made them hang on a model call until the client timed out. A
    certification run must not need a model at all.
    """
    part = sdk["Part"]

    if message_id.startswith("tck-stream-artifact-chunked"):
        await updater.start_work()
        await updater.add_artifact([part(text="chunk-1 ")], append=True)
        await updater.add_artifact([part(text="chunk-2")], append=True, last_chunk=True)
        await updater.complete()
        return True

    if message_id.startswith("test-resubscribe-message-id"):
        # The kit needs the task still running when it resubscribes.
        await updater.start_work()
        await asyncio.sleep(RESUBSCRIBE_HOLD_SECONDS)
        await updater.complete()
        return True

    if message_id.startswith("tck-stream-artifact-text"):
        await updater.start_work()
        await updater.add_artifact([part(text="Streamed text content")])
        await updater.complete()
        return True

    if message_id.startswith("tck-stream-artifact-file"):
        await updater.start_work()
        await updater.add_artifact(
            [part(raw=b"tck", media_type="text/plain", filename="output.txt")]
        )
        await updater.complete()
        return True

    if message_id.startswith("tck-stream-ordering-001"):
        await updater.start_work()
        await updater.add_artifact([part(text="Ordered output")])
        await updater.complete()
        return True

    if message_id.startswith("tck-artifact-file-url"):
        await updater.add_artifact(
            [
                part(
                    url="https://example.com/output.txt",
                    media_type="text/plain",
                    filename="output.txt",
                )
            ]
        )
        await updater.complete()
        return True

    if message_id.startswith("tck-message-response"):
        # A bare message rather than a task, which is what this check asserts.
        await event_queue.enqueue_event(
            updater.new_agent_message([part(text="Direct message response")])
        )
        return True

    if message_id.startswith("tck-input-required"):
        await updater.requires_input()
        return True

    if message_id.startswith("tck-complete-task"):
        await updater.complete(updater.new_agent_message([part(text="Hello from TCK")]))
        return True

    if message_id.startswith("tck-artifact-text"):
        await updater.add_artifact([part(text="Generated text content")])
        await updater.complete()
        return True

    if message_id.startswith("tck-artifact-file"):
        await updater.add_artifact(
            [part(raw=b"tck", media_type="text/plain", filename="output.txt")]
        )
        await updater.complete()
        return True

    if message_id.startswith("tck-artifact-data"):
        await updater.add_artifact([part(data={"key": "value", "count": 42})])
        await updater.complete()
        return True

    if message_id.startswith("tck-reject-task"):
        from a2a.utils.errors import A2AError

        raise A2AError("rejected")

    if message_id.startswith("tck-stream-001"):
        await updater.start_work()
        await updater.add_artifact([part(text="Stream hello from TCK")])
        await updater.complete()
        return True

    if message_id.startswith("tck-stream-002"):
        await updater.complete()
        return True

    if message_id.startswith("tck-stream-003"):
        await updater.start_work()
        await updater.add_artifact([part(text="Stream task lifecycle")])
        await updater.complete()
        return True

    # The reference SUT's default branch. Reached by kit requests that carry no
    # fixture prefix, which still expect a well-formed completed task.
    await updater.complete(
        updater.new_agent_message([part(text=f"Unhandled messageId prefix: {message_id}")])
    )
    return True


__all__ = [
    "CONFORMANCE_PREFIXES",
    "RESUBSCRIBE_HOLD_SECONDS",
    "answer_conformance",
    "conformance_message_id",
    "wants_conformance",
]
