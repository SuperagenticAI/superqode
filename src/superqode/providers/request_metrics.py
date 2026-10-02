"""Content-free measurements of the payload actually passed to a gateway."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from typing import Any


def measure_request_payload(messages: list[Any], tools: list[Any] | None) -> dict[str, Any]:
    def wire(value):
        if is_dataclass(value):
            return asdict(value)
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        return value

    schema = json.dumps(
        [wire(tool) for tool in tools or []], sort_keys=True, default=str, ensure_ascii=False
    ).encode()
    transcript = json.dumps(
        [wire(message) for message in messages], default=str, ensure_ascii=False
    ).encode()
    system_bytes = sum(
        len(json.dumps(wire(message).get("content", ""), ensure_ascii=False).encode())
        for message in messages
        if wire(message).get("role") == "system"
    )
    return {
        "measurement": "gateway payload UTF-8 bytes",
        "message_count": len(messages),
        "tool_count": len(tools or []),
        "tool_schema_bytes": len(schema),
        "messages_bytes": len(transcript),
        "system_content_bytes": system_bytes,
        "tool_schema_sha256": hashlib.sha256(schema).hexdigest(),
        "provider_input_tokens": None,
    }
