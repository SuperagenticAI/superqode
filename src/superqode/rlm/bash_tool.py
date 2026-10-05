"""A second tool surface over the same kernel-owned command broker."""

import json
import ast

from superqode.pipy.messages import TextContent
from superqode.pipy.tools.base import AgentTool, AgentToolResult


def command_code(payload):
    # Data is serialized, never interpolated as executable shell/Python source.
    return (
        "import json as __sq_json\n__sq_json.dumps(commands.dispatch(__sq_json.loads("
        + repr(json.dumps(payload))
        + ")))"
    )


async def dispatch_command(execute_kernel, payload):
    result = await execute_kernel(command_code(payload))
    if result.error:
        raise RuntimeError(result.error)
    encoded = ast.literal_eval(result.value_repr)
    if not isinstance(encoded, str):
        raise RuntimeError("Command broker returned an invalid receipt")
    return json.loads(encoded)


def create_bash_tool(execute_kernel):
    async def execute(tool_call_id, args, signal=None, on_update=None):
        if signal is not None:
            signal.throw_if_aborted()
        payload = dict(args)
        if payload.get("action", "run") in {"run", "start"}:
            payload.setdefault("request_id", tool_call_id)
        receipt = await dispatch_command(execute_kernel, payload)
        text = json.dumps(receipt, ensure_ascii=False)
        return AgentToolResult(
            content=[TextContent(text)], details={"runtime": "bash", "receipt": receipt}
        )

    return AgentTool(
        name="bash",
        label="Bash",
        execution_mode="sequential",
        description="Run Bash in the selected RLM sandbox. Returns a durable command handle; read bounded stdout/stderr separately.",
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["run", "start", "status", "read", "wait", "cancel", "list"],
                },
                "command": {"type": "string"},
                "job_id": {"type": "string"},
                "request_id": {"type": "string"},
                "read_only": {"type": "boolean"},
                "timeout": {"type": "number", "minimum": 1, "maximum": 3600},
                "wait": {"type": "number", "minimum": 0, "maximum": 60},
                "stream": {"type": "string", "enum": ["stdout", "stderr"]},
                "start": {"type": "integer", "minimum": 0},
                "size": {"type": "integer", "minimum": 1, "maximum": 20000},
            },
            "additionalProperties": False,
        },
        execute_fn=execute,
        prompt_snippet="Bash jobs share the Python workspace and execution boundary",
    )
