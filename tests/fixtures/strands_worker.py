"""Deterministic process fixture for the isolated harness transport."""

import json
import sys
import time


def send(data):
    print(json.dumps(data), flush=True)


request = json.loads(sys.stdin.readline())
mode = request["prompt"]
send({"type": "ready", "versions": {"fixture": "1"}})
if mode == "hang":
    time.sleep(60)
if mode == "garbage":
    print("not json", flush=True)
    raise SystemExit(0)
if mode == "partial":
    send({"type": "delta", "text": "partial output"})
    raise SystemExit(0)
if mode == "tool":
    send(
        {
            "type": "tool_request",
            "id": "1",
            "name": "write",
            "arguments": {"path": "fixture.txt", "content": "written"},
        }
    )
    reply = json.loads(sys.stdin.readline())
    assert reply["id"] == "1"
    content = "written" if reply["success"] else reply["error"]
else:
    content = "fixture response"
send({"type": "delta", "text": content})
result = {
    "type": "result",
    "content": content,
    "stopped_reason": "complete",
    "tool_calls_made": 1 if mode == "tool" else 0,
    "iterations": 1,
    "input_tokens": 10,
    "output_tokens": 4,
    "total_tokens": 14,
}
if mode == "bad_usage":
    result["total_tokens"] = -1
if mode == "limited":
    result["stopped_reason"] = "max_iterations"
send(result)
if mode == "duplicate":
    send(result)
if mode == "bad_exit":
    raise SystemExit(1)
