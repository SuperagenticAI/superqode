#!/usr/bin/env python3
"""System Under Test for the official A2A Technology Compatibility Kit.

The kit at https://github.com/a2aproject/a2a-tck drives an agent through
behaviours the A2A specification does not describe. Its
``docs/SUT_REQUIREMENTS.md`` calls these "testing-specific requirements beyond
the core A2A specification": a task whose message id begins
``test-resubscribe-message-id`` has to stay active long enough to resubscribe
to, and several checks assert on artifact text and filenames the reference SUT
returns verbatim. A working agent fails them by doing real work.

This lives outside the package on purpose. Answering the kit means changing
behaviour according to a client-supplied message id, and a published agent must
never do that. A flag on the shipped server would be one misconfiguration away
from doing it in production; a separate script cannot be switched on by
accident because it is not installed.

The consequence is that two numbers exist and both are worth having. This
script measures conformance of the protocol layer. Running the kit against
``superqode serve a2a`` measures the agent people actually call, and the gap
between them is where real defects hide.

Usage:

    python scripts/a2a_tck_sut.py --port 9999
    ./run_tck.py --sut-host http://127.0.0.1:9999
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

import superqode.a2a.server as server_module


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


def _patch_executor() -> None:
    """Route every request to a fixture instead of the harness.

    Patched on the class before any server is built, so there is no path
    through this process that reaches real execution. That is the point: a
    certification run must not call a model or touch a repository.
    """

    async def execute(self: Any, context: Any, event_queue: Any) -> None:
        sdk = server_module._a2a_sdk()
        task_id = server_module._required_id(context.task_id, "task")
        context_id = server_module._required_id(context.context_id, "context")
        updater = sdk["TaskUpdater"](event_queue, task_id, context_id)

        if context.current_task is None:
            await event_queue.enqueue_event(
                sdk["Task"](
                    id=task_id,
                    context_id=context_id,
                    status=sdk["TaskStatus"](state=sdk["TaskState"].TASK_STATE_SUBMITTED),
                )
            )
        await answer_conformance(updater, event_queue, sdk, conformance_message_id(context))

    server_module.SuperQodeA2AExecutor.execute = execute


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--provider", default="ollama")
    parser.add_argument("--model", default="none")
    args = parser.parse_args()

    _patch_executor()

    # The kit sends several hundred requests. The shipped ceilings would
    # throttle it after ten, so a run would measure the limiter instead.
    from superqode.a2a import create_a2a_server

    server = asyncio.run(
        create_a2a_server(
            server_url=f"http://{args.host}:{args.port}",
            provider=args.provider,
            model=args.model,
            store_path="/tmp/superqode-tck-store.sqlite3",
            task_store_path="/tmp/superqode-tck-tasks.sqlite3",
            anonymous_per_minute=0,
            keyed_per_minute=0,
            global_per_day=0,
        )
    )
    print(f"A2A TCK SUT on http://{args.host}:{args.port} (fixtures only, no harness)")
    server.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
