"""Exercise the bundled Apple SDK on eligible Macs, with no host tool effects.

Unavailable CI runners explicitly report generation_tested=false. Add
--require-available on a physical Mac to make that condition fail validation.
"""

import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time


def check(helper, require_available=False):
    environment = {
        k: v
        for k, v in os.environ.items()
        if k
        in {
            "PATH",
            "HOME",
            "TMPDIR",
            "LANG",
            "LC_ALL",
            "__CF_USER_TEXT_ENCODING",
        }
    }
    status = json.loads(
        subprocess.check_output([helper, "--status"], text=True, timeout=20, env=environment)
    )
    assert type(status.get("available")) is bool and status.get("on_device") is True, status
    assert status.get("model") == "system-on-device" and status.get("guidance"), status
    report = {"availability": status, "generation_tested": False, "checks": []}
    if not status["available"]:
        report["passed"] = not require_available
        return report
    assert status.get("supports_tools") and status.get("supports_structured_output"), status
    child = subprocess.Popen(
        [helper, "--stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        env=environment,
    )
    events = queue.Queue()

    def read():
        for line in child.stdout:
            events.put(line)
        events.put(None)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()

    def turn(request):
        tick = time.monotonic()
        child.stdin.write(json.dumps(request) + "\n")
        child.stdin.flush()
        output, first = [], None
        while True:
            line = events.get(timeout=max(0.1, 180 - (time.monotonic() - tick)))
            assert line is not None, "Apple bridge closed without completion"
            event = json.loads(line)
            output.append(event)
            assert event["event"] != "error", event
            if event["event"] == "text" and first is None:
                first = time.monotonic() - tick
            if event["event"] == "done":
                return output, {
                    "first_text_seconds": first,
                    "duration_seconds": time.monotonic() - tick,
                }

    def content(output):
        return "".join(e["text"] for e in output if e["event"] == "text")

    try:
        messages = [{"role": "user", "content": "Reply with exactly: ok"}]
        output, timing = turn(
            {
                "session_id": "apple-sdk-check",
                "messages": messages,
                "max_tokens": 16,
                "temperature": 0,
            }
        )
        assert output[-1]["finish_reason"] == "stop" and content(output).strip(), output
        report["checks"].append({"name": "streaming text", **timing})
        messages.extend(
            [
                {"role": "assistant", "content": content(output)},
                {"role": "user", "content": "Reply with exactly: ready"},
            ]
        )
        output, timing = turn(
            {
                "session_id": "apple-sdk-check",
                "messages": messages,
                "max_tokens": 16,
                "temperature": 0,
            }
        )
        assert any(e.get("session_reused") is True for e in output), output
        report["checks"].append({"name": "continuing native session", **timing})
        output, timing = turn(
            {
                "messages": [{"role": "user", "content": "Set answer to local."}],
                "schema": {
                    "type": "object",
                    "properties": {"answer": {"type": "string", "enum": ["local"]}},
                    "required": ["answer"],
                },
                "max_tokens": 64,
                "temperature": 0,
            }
        )
        assert json.loads(content(output)) == {"answer": "local"}, output
        report["checks"].append({"name": "guided structured output", **timing})
        tools = [
            {
                "name": "read",
                "description": "Read the requested text file; returns its content.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            }
        ]
        messages = [
            {
                "role": "user",
                "content": "Use read to read sq_apple_fixture.txt. Return the marker in its contents. Do not guess.",
            }
        ]
        output, timing = turn(
            {"messages": messages, "tools": tools, "max_tokens": 128, "temperature": 0}
        )
        assert output[-1]["finish_reason"] == "tool_calls", output
        calls = next(e["calls"] for e in output if e["event"] == "tool_calls")
        assert calls and all(c["function"]["name"] == "read" for c in calls), output
        assert all(
            json.loads(c["function"]["arguments"])["path"] == "sq_apple_fixture.txt" for c in calls
        ), output
        report["checks"].append({"name": "native tool request without execution", **timing})
        messages.append({"role": "assistant", "content": content(output), "tool_calls": calls})
        messages.extend(
            {"role": "tool", "tool_call_id": c["id"], "content": "APPLE_CHECK_MARKER_7B2"}
            for c in calls
        )
        output, timing = turn(
            {"messages": messages, "tools": tools, "max_tokens": 128, "temperature": 0}
        )
        assert output[-1]["finish_reason"] == "stop" and "APPLE_CHECK_MARKER_7B2" in content(
            output
        ), output
        report["checks"].append({"name": "native tool-result transcript", **timing})
        report.update(passed=True, generation_tested=True)
        return report
    finally:
        child.stdin.close()
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        reader.join(timeout=2)
        child.stdout.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--helper", default="/Applications/SuperQode.app/Contents/MacOS/SuperQodeAppleModel"
    )
    parser.add_argument("--require-available", action="store_true")
    args = parser.parse_args()
    result = check(str(Path(args.helper).resolve(strict=True)), args.require_available)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
