"""Local-only ACP fixture: edit through host APIs, request permission, resume."""

import json
import os
from pathlib import Path
import sys

sequence = 100
controls = {"model": "model-a", "mode": "code", "effort": "low"}


def send(value):
    print(json.dumps({"jsonrpc": "2.0", **value}), flush=True)


def host(method, params):
    global sequence
    sequence += 1
    identity = sequence
    send({"id": identity, "method": method, "params": params})
    while line := sys.stdin.readline():
        response = json.loads(line)
        if response.get("id") == identity:
            return response
    raise RuntimeError("Host disconnected")


for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    identity = request.get("id")
    params = request.get("params", {})
    if method == "initialize":
        result = {
            "protocolVersion": 1,
            "agentCapabilities": {"loadSession": True, "promptCapabilities": {"image": True}},
        }
    elif method == "session/new":
        result = {
            "sessionId": "desktop-acp-fixture-session",
            "models": {
                "availableModels": [
                    {"modelId": "model-a", "name": "Model A"},
                    {"modelId": "model-b", "name": "Model B"},
                ],
                "currentModelId": "model-a",
            },
            "modes": {
                "availableModes": [{"id": "code", "name": "Code"}, {"id": "plan", "name": "Plan"}],
                "currentModeId": "code",
            },
        }
    elif method == "session/load":
        result = {}
        send(
            {
                "method": "session/update",
                "params": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "Resumed ACP session. "},
                },
            }
        )
    elif method in {"session/set_model", "session/set_mode", "session/set_config_option"}:
        if method == "session/set_model":
            controls["model"] = params["modelId"]
        elif method == "session/set_mode":
            controls["mode"] = params["modeId"]
        else:
            controls[params["configId"]] = params["value"]
        result = {}
    elif method == "session/prompt":
        prompt = params["prompt"][0]["text"]
        if prompt == "image":
            text = "Image parts received: " + str(
                sum(part.get("type") == "image" for part in params["prompt"])
            )
        elif prompt == "controls":
            text = "Agent controls: " + json.dumps(controls, sort_keys=True)
        elif prompt == "escape":
            response = host("fs/write_text_file", {"path": "../outside.txt", "content": "escaped"})
            text = "Scope blocked" if "error" in response else "Unexpected escape"
        elif prompt == "environment":
            text = (
                "Agent auth preserved"
                if os.environ.get("OPENAI_API_KEY") == "existing-agent-fixture-key"
                else "Unexpected agent credential"
            )
        elif prompt == "terminal":
            response = host(
                "terminal/create",
                {"command": sys.executable, "args": ["-c", "print('ACP terminal with spaces')"]},
            )
            terminal = response["result"]["terminalId"]
            host("terminal/wait_for_exit", {"terminalId": terminal})
            output = host("terminal/output", {"terminalId": terminal})
            text = output["result"]["output"]
            host("terminal/release", {"terminalId": terminal})
        elif prompt == "permission":
            response = host(
                "session/request_permission",
                {
                    "options": [
                        {"kind": "allow_always", "optionId": "unsafe-always"},
                        {"kind": "reject_once", "optionId": "reject"},
                    ],
                    "toolCall": {"title": "Always-only permission"},
                },
            )
            text = (
                "Permission refused"
                if "error" in response
                else "Always permission granted: " + json.dumps(response["result"])
            )
        else:
            response = host(
                "fs/write_text_file",
                {"path": "main.py", "content": "print('Hello from desktop ACP')\n"},
            )
            text = "Write denied" if "error" in response else "Updated main.py through ACP."
        send(
            {
                "method": "session/update",
                "params": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": text},
                },
            }
        )
        result = {"stopReason": "end_turn"}
    elif identity is None:
        continue
    else:
        result = {}
    if identity is not None:
        send({"id": identity, "result": result})
