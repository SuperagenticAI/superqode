"""Deterministic subprocess used to exercise the Prime RPC wire protocol."""

from __future__ import annotations

import json
import os
import sys
from typing import Any


def emit(payload: dict[str, Any]) -> None:
    wire = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.buffer.write(wire.encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


if "--version" in sys.argv:
    print("prime-agent 0.7.1")
    raise SystemExit(0)


waiting_for_ui = False
for line in sys.stdin.buffer:
    request = json.loads(line)
    request_id = request.get("id")
    command = request.get("type")

    if command == "extension_ui_response" and waiting_for_ui:
        waiting_for_ui = False
        emit({"type": "ui_result", "rawResponse": request})
        emit({"type": "agent_end"})
        continue
    if command == "hang":
        continue
    if command == "exit":
        sys.stderr.write("intentional fake crash\n")
        sys.stderr.flush()
        os._exit(7)
    if command == "fail":
        emit(
            {
                "id": request_id,
                "type": "response",
                "command": command,
                "success": False,
                "error": "deliberate failure",
            }
        )
        continue

    data: Any = {}
    if command == "get_state":
        data = {"sessionId": "fake-session", "isStreaming": False}
    elif command == "get_messages":
        data = {"messages": [{"role": "assistant", "content": "done"}]}
    elif command == "get_session_stats":
        data = {"tokens": {"input": 30, "output": 12, "total": 42}, "cost": 0.01}
    elif command == "get_last_assistant_text":
        data = {"text": "done"}
    elif command == "get_available_models":
        data = {"models": [{"provider": "prime", "id": "fake-model"}]}
    elif command == "echo":
        data = request.get("value")

    emit(
        {
            "id": request_id,
            "type": "response",
            "command": command,
            "success": True,
            "data": data,
        }
    )

    if command == "prompt":
        if request.get("message") == "stall":
            continue
        if request.get("message") == "ui":
            waiting_for_ui = True
            emit({"type": "extension_ui_request", "id": "ui-1", "method": "confirm"})
        else:
            emit({"type": "agent_start"})
            emit({"type": "turn_start"})
            emit(
                {
                    "type": "message_update",
                    "message": {"role": "assistant"},
                    "assistantMessageEvent": {
                        "type": "text_delta",
                        "contentIndex": 0,
                        "delta": "done",
                    },
                }
            )
            emit(
                {
                    "type": "future_prime_event",
                    "text": "left\u2028right\u2029done",
                    "extra": {"preserved": True},
                }
            )
            emit({"type": "turn_end", "message": {}, "toolResults": []})
            emit({"type": "agent_end"})
    elif command == "malformed":
        sys.stdout.buffer.write(b"{not-json}\n")
        sys.stdout.buffer.flush()
        emit({"type": "after_malformed"})
