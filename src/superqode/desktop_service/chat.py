"""Direct model chat: explicit messages/images, no project instructions or tools."""

from dataclasses import asdict
import json

from superqode.providers.gateway.base import Message
from superqode.providers.gateway.litellm_gateway import LiteLLMGateway
from superqode.image_input import image_message
from .images import load_snapshots


async def run_chat(request, emit):
    if request.get("expected_digest") not in {None, "direct-chat-v1"}:
        raise ValueError("The previous task is not a direct chat session")
    history = list(request.get("_chat_history") or [])
    history.append(
        {
            "role": "user",
            "text": request["prompt"],
            "image_snapshots": request.get("image_snapshots") or [],
        }
    )
    if len(json.dumps(history)) > 500_000:
        raise ValueError("Chat history exceeds 500 KB; start a new conversation")
    messages = [
        Message(role=item["role"], content=image_message(item["text"], list(load_snapshots(item))))
        for item in history
    ]
    parts, terminal, usage = [], False, None
    async for chunk in LiteLLMGateway().stream_completion(
        messages=messages, provider=request["provider"], model=request["model"], tools=None
    ):
        if chunk.content:
            parts.append(chunk.content)
            emit("harness_event", {"event": "model_delta", "payload": {"text": chunk.content}})
        if chunk.thinking_content:
            emit(
                "harness_event", {"event": "thinking", "payload": {"text": chunk.thinking_content}}
            )
        if chunk.usage:
            usage = asdict(chunk.usage)
        terminal = terminal or bool(chunk.finish_reason)
    if not terminal:
        raise RuntimeError("Chat stream ended without a finish reason; it was not replayed")
    history.append({"role": "assistant", "text": "".join(parts)})
    emit(
        "result",
        {
            "status": "completed",
            "session_id": request.get("session_id") or request["job_id"],
            "harness_digest": "direct-chat-v1",
            "native_continuity": True,
            "chat_history": history,
            "usage": usage,
            "interaction_mode": "chat",
        },
    )
