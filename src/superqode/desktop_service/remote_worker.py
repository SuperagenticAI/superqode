"""Streaming remote turns with exact continuity and acknowledged cancellation."""

from __future__ import annotations

import asyncio
import signal
import uuid
from dataclasses import asdict, is_dataclass
from enum import Enum


def plain(value):
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value.value if isinstance(value, Enum) else value


def payload(event):
    data = plain(event.data)
    data = data if isinstance(data, dict) else {}
    data = data.get("result", data)
    for key in ("artifactUpdate", "statusUpdate", "task", "artifact_update", "status_update"):
        if isinstance(data.get(key), dict):
            return data[key]
    return data


def text_parts(node):
    if not isinstance(node, dict):
        return []
    output = [node["text"]] if isinstance(node.get("text"), str) else []
    for key in ("parts", "artifacts"):
        for part in node.get(key) or []:
            output.extend(text_parts(part))
    for key in ("artifact", "message", "status"):
        output.extend(text_parts(node.get(key)))
    return output


async def run_remote(request, route, config, emit, secrets=None):
    loop = asyncio.get_running_loop()
    current = asyncio.current_task()
    loop.add_signal_handler(signal.SIGTERM, current.cancel)
    previous = request.get("_remote_previous") or {}
    try:
        if route["kind"] == "uhp":
            return await run_uhp(request, route, config, previous, emit)
        return await run_a2a(
            request, route, config, previous, emit, secrets if secrets is not None else []
        )
    finally:
        loop.remove_signal_handler(signal.SIGTERM)


def completed(route, session, state):
    return {
        "status": "completed",
        "session_id": session,
        "remote_continuity": bool(state),
        "remote_state": state,
        "harness_digest": route["digest"],
        "native_continuity": False,
    }


async def cancel_remote(operation, emit):
    try:
        result = await asyncio.wait_for(operation(), timeout=10)
        state = getattr(getattr(result, "status", None), "state", None)
        state = getattr(state, "value", state) or getattr(result, "status", None)
        if state not in {"cancelled", "canceled", "completed"}:
            raise RuntimeError("Server did not acknowledge cancellation")
        emit("remote_cancel", {"acknowledged": True, "server_status": state})
        emit("result", {"status": "cancelled", "remote_cancel_acknowledged": True})
    except Exception as exc:
        emit("remote_cancel", {"acknowledged": False, "error": str(exc)})
        raise RuntimeError(
            "Remote cancellation could not be confirmed; check the server. " + str(exc)
        ) from None


async def run_uhp(request, route, config, previous, emit):
    from superqode.harness.uhp_client import UHPClient
    from superqode.harness.uhp_adapter import _translate

    response_id = ""
    final = None
    chunks = []
    async with UHPClient(route["url"], api_key=config.get("token") or None) as client:
        try:
            async for event in client.stream_response(
                request["prompt"],
                harness_id=route["remote_harness"],
                previous_response_id=previous.get("response_id") or None,
                max_output_tokens=route.get("max_output_tokens"),
            ):
                if event.response:
                    response_id = event.response.id or response_id
                emit("remote_state", {"protocol": "uhp", "response_id": response_id})
                for normalized in _translate(event, chunks, {}):
                    emit("harness_event", {"event": normalized.type, "payload": normalized.data})
                if event.is_terminal:
                    final = event.response
            if final is None:
                raise RuntimeError(
                    "UHP stream ended without a terminal response; it was not replayed"
                )
            final.raise_for_error()
            if final.status != "completed":
                raise RuntimeError("UHP task ended with " + final.status)
            if not chunks:
                emit("answer", {"text": final.output_text})
            state = {"response_id": final.id, "session_id": final.session_id}
            emit(
                "result",
                completed(
                    route, final.session_id or request.get("session_id") or uuid.uuid4().hex, state
                ),
            )
        except asyncio.CancelledError:
            if not response_id:
                raise RuntimeError(
                    "Stopped before the server supplied a response ID; remote cancellation is unconfirmed"
                ) from None
            await cancel_remote(lambda: client.cancel_response(response_id), emit)
        except Exception:
            if response_id and final is None:
                try:
                    await asyncio.wait_for(client.cancel_response(response_id), timeout=5)
                except Exception:
                    emit("remote_cancel", {"acknowledged": False, "response_id": response_id})
            raise


async def refresh_oauth(client, route, config, secrets):
    if not config.get("oauth"):
        return
    from superqode.a2a.oauth import ensure_access_token
    from superqode.a2a.security import OAuthNeed

    for data in route.get("oauth_needs", []):
        token = await ensure_access_token(route["url"], OAuthNeed(**data), interactive=False)
        if token:
            secrets.append(token)
            client._http.headers["Authorization"] = "Bearer " + token
            return


async def run_a2a(request, route, config, previous, emit, secrets=None):
    from superqode.a2a.client import A2AClient
    from superqode.a2a.reply import task_reply

    context = previous.get("context_id") or ""
    task_id = ""
    terminal = False
    async with A2AClient(
        route["url"],
        bearer_token=config.get("token") or None,
        extra_headers=config.get("headers") or None,
        client_cert=config.get("cert") or None,
        client_key=config.get("key") or None,
        strict_origin=True,
    ) as client:
        client.add_query_params(config.get("query") or {})
        try:
            await refresh_oauth(client, route, config, secrets if secrets is not None else [])
            card = await client.get_agent_card()
            if card.capabilities.streaming:
                visible = ""
                async for event in client.send_message_streaming(
                    request["prompt"], session_id=context or None
                ):
                    if event.type == "error":
                        raise RuntimeError(str(event.data))
                    data = payload(event)
                    context = str(data.get("contextId") or data.get("context_id") or context)
                    task_id = str(
                        data.get("taskId")
                        or data.get("task_id")
                        or (data.get("id") if data.get("kind") == "task" else "")
                        or task_id
                    )
                    emit(
                        "remote_state",
                        {"protocol": "a2a", "task_id": task_id, "context_id": context},
                    )
                    state = (data.get("status") or {}).get("state")
                    if state in {
                        "failed",
                        "canceled",
                        "rejected",
                        "auth-required",
                        "auth_required",
                    }:
                        raise RuntimeError("A2A task ended with " + state)
                    terminal = (
                        bool(data.get("final"))
                        or state in {"completed", "input-required", "input_required"}
                        or terminal
                    )
                    piece = "".join(text_parts(data))
                    appending = data.get("append") is True
                    if piece and (appending or (piece != visible and not visible.endswith(piece))):
                        delta = (
                            piece[len(visible) :]
                            if not appending and visible and piece.startswith(visible)
                            else piece
                        )
                        emit(
                            "harness_event", {"event": "message.delta", "payload": {"text": delta}}
                        )
                        visible = (
                            piece if visible and piece.startswith(visible) else visible + piece
                        )
                    emit("harness_event", {"event": "a2a.update", "payload": data})
                if not terminal:
                    raise RuntimeError(
                        "A2A stream ended without terminal status; the message was not replayed"
                    )
            else:
                result = await client.send_message(
                    request["prompt"], session_id=context or None, nonblocking=True
                )
                task_id = getattr(result, "task_id", "")
                context = getattr(result, "context_id", None) or context
                while hasattr(result, "status"):
                    context = getattr(result, "context_id", None) or context
                    state = getattr(result.status.state, "value", result.status.state)
                    emit(
                        "remote_state",
                        {
                            "protocol": "a2a",
                            "task_id": task_id,
                            "context_id": context,
                            "state": state,
                        },
                    )
                    if state in {"completed", "input_required"}:
                        break
                    if state not in {"working", "submitted"}:
                        raise RuntimeError("A2A task ended with " + state)
                    await asyncio.sleep(0.25)
                    result = await client.get_task(task_id)
                text = (
                    task_reply(result)
                    if hasattr(result, "status")
                    else "\n".join(p.text for p in result.parts if getattr(p, "text", None))
                )
                emit("answer", {"text": text})
            emit(
                "result",
                completed(
                    route, context or uuid.uuid4().hex, {"context_id": context} if context else {}
                ),
            )
        except asyncio.CancelledError:
            if not task_id:
                raise RuntimeError(
                    "Stopped before the server supplied a task ID; remote cancellation is unconfirmed"
                ) from None
            await cancel_remote(lambda: client.cancel_task(task_id), emit)
        except Exception:
            if task_id and not terminal:
                try:
                    await asyncio.wait_for(client.cancel_task(task_id), timeout=5)
                except Exception:
                    emit("remote_cancel", {"acknowledged": False, "task_id": task_id})
            raise
