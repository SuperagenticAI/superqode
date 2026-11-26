"""Exercise the packaged Coder worker with a deterministic streaming model."""

import asyncio
import importlib.util
import json
from pathlib import Path
import sys

from pydantic_ai.messages import RetryPromptPart, ToolReturnPart, UserPromptPart
from pydantic_ai.models.function import DeltaToolCall, FunctionModel


async def stream(messages, info):
    users = [p.content for m in messages for p in m.parts if isinstance(p, UserPromptPart)]
    text = str(users[-1])
    result = next(
        (p for p in messages[-1].parts if isinstance(p, (ToolReturnPart, RetryPromptPart))), None
    )
    if result is not None:
        yield "RESULT: " + str(result.content)
        return
    if "SLOW" in text:
        await asyncio.sleep(30)
        yield "slow result"
        return
    if "READ" in text:
        name, args = "read_file", {"path": "marker.txt"}
    elif "WRITE" in text:
        name, args = "write_file", {"path": "written.txt", "content": "coder-approved"}
    elif "SHELL" in text:
        name, args = "shell", {"command": "printf coder-shell"}
    elif "MCP" in text:
        name, args = "mcp_0_echo", {"message": "coder-mcp"}
    else:
        yield f"USER_TURNS={len(users)}"
        return
    yield {0: DeltaToolCall(name=name, json_args=json.dumps(args))}


spec = importlib.util.spec_from_file_location("coder_worker", sys.argv[1])
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
worker.serve(Path(sys.argv[2]), "openai:fixture", model=FunctionModel(stream_function=stream))
