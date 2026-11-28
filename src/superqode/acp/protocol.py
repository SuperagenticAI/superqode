"""Version-specific ACP contracts shared by clients and the stdio router."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
import json
import os
from pathlib import Path
import shutil
from typing import Any

SUPPORTED_VERSIONS = (1, 2)
PROTOCOL_POLICIES = ("auto", "v1", "v2")
SCHEMA_VERSION = "schema-v2.0.0-beta.4"


class ProtocolError(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = self.acp_code = code
        self.data = data

    def wire(self) -> dict:
        return {
            "code": self.code,
            "message": str(self),
            **({"data": self.data} if self.data is not None else {}),
        }


def requested_version(value: Any = None) -> int:
    value = os.environ.get("SUPERQODE_ACP_PROTOCOL_VERSION", "1") if value is None else value
    if value in ("1", "2"):
        value = int(value)
    if type(value) is not int or value not in SUPPORTED_VERSIONS:
        raise ValueError("ACP protocol version must be 1 or 2")
    return value


def protocol_policy(value: Any = None, version: Any = None) -> tuple[str, int]:
    """New policy names distinguish strict v2 from the older v2-with-fallback flag."""
    if value is None:
        selected = requested_version(version)
        return ("auto" if selected == 2 else "v1"), selected
    if value not in PROTOCOL_POLICIES:
        raise ValueError("ACP protocol policy must be auto, v1 or v2")
    selected = 1 if value == "v1" else 2
    if version is not None and requested_version(version) != selected:
        raise ValueError("ACP protocol policy and requested version disagree")
    return value, selected


def select_version(value: Any, supported=SUPPORTED_VERSIONS) -> int:
    if type(value) is not int or not 0 <= value <= 65535:
        raise ProtocolError(-32602, "protocolVersion must be an integer from 0 to 65535")
    candidates = [v for v in supported if v <= value]
    if not candidates:
        raise ProtocolError(
            -32022,
            "Unsupported protocol version",
            {"requested": value, "supported": list(supported)},
        )
    return max(candidates)


def capability(capabilities: dict | None, *path: str) -> bool:
    node: Any = capabilities
    for part in path:
        if not isinstance(node, dict):
            return False
        node = node.get(part)
    return isinstance(node, dict)


def validate_envelope(message: Any) -> None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        raise ProtocolError(-32600, "Expected one JSON-RPC 2.0 object")
    if "method" in message:
        if not isinstance(message["method"], str) or any(k in message for k in ("result", "error")):
            raise ProtocolError(-32600, "Invalid request")
        if "id" in message and type(message["id"]) not in (str, int):
            raise ProtocolError(-32600, "Request id must be a string or integer")
        if "params" in message and not isinstance(message["params"], dict):
            raise ProtocolError(-32602, "Expected object parameters")
    elif "id" not in message or (("result" in message) == ("error" in message)):
        raise ProtocolError(-32600, "Invalid response")
    elif message["id"] is not None and type(message["id"]) not in (str, int):
        raise ProtocolError(-32600, "Invalid response id")
    elif "error" in message:
        error = message["error"]
        if (
            not isinstance(error, dict)
            or type(error.get("code")) is not int
            or not isinstance(error.get("message"), str)
        ):
            raise ProtocolError(-32600, "Invalid response error")


@lru_cache
def v2_schema() -> dict:
    return json.loads(files("superqode.acp.schema").joinpath("v2.json").read_text())


@lru_cache(maxsize=64)
def _validator(definition: str):
    from jsonschema import Draft202012Validator

    schema = v2_schema()
    return Draft202012Validator(
        {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": f"#/$defs/{definition}"}
    )


def validate_v2(definition: str, value: Any) -> None:
    error = next(_validator(definition).iter_errors(value), None)
    if error is not None:
        # Validation errors can contain credentials and prompt contents.
        path = ".".join(str(p) for p in error.absolute_path)
        raise ProtocolError(-32602, f"Invalid {definition}" + (f" at {path}" if path else ""))


def mcp_servers_v2(servers: list[dict], capabilities: dict, *, cwd: Path) -> list[dict]:
    result = []
    for server in servers:
        transport = server.get("type", "stdio")
        if not capability(capabilities, "session", "mcp", transport):
            continue
        item = {**server, "type": transport}
        if transport == "stdio":
            command = str(item.get("command", ""))
            executable = shutil.which(command)
            if executable is None and (cwd / command).is_file():
                executable = str((cwd / command).resolve())
            if not executable:
                raise ValueError(f"MCP executable is not available: {command}")
            item["command"] = str(Path(executable).resolve())
        result.append(item)
    return result


def redact_protocol(value: Any) -> Any:
    """Do not put MCP/auth secrets or submission keys in traffic logs."""
    if isinstance(value, list):
        return [redact_protocol(v) for v in value]
    if isinstance(value, dict):
        return {
            k: "[redacted]"
            if k in {"env", "headers", "token", "accessToken", "refreshToken", "idempotencyKey"}
            else redact_protocol(v)
            for k, v in value.items()
        }
    return value
