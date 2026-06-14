"""Benchmarks for local OpenAI-compatible endpoints.

Measures the two numbers that decide whether a local model is pleasant in an
agent loop: time to first token (prefill speed) and decode tokens/second.
The optional agentic mode adds cheap probes for the control signals a coding
agent needs: tool calls, edit format, shell command calls, and context recall.
Stdlib only (urllib + SSE parsing), so it works against any running engine
with no extra dependencies.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_PROMPT = (
    "You are a coding agent. Read this function and explain the bug in two "
    "sentences, then show the one-line fix.\n\n"
    "def median(values):\n"
    "    values.sort()\n"
    "    return values[len(values) // 2]\n"
)

AGENTIC_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the repository.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Apply an exact text replacement to a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                },
                "required": ["path", "old", "new"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
]

TOOL_CALL_PROBE = (
    "You are a coding agent benchmark. Do not answer in prose. Call exactly one "
    "tool: read_file with path 'pyproject.toml'."
)

EDIT_FORMAT_PROBE = (
    "You are a coding agent benchmark. Return only a unified diff that changes "
    "this function to return 2 instead of 1:\n\n"
    "def answer():\n"
    "    return 1\n"
)

SHELL_TOOL_PROBE = (
    "You are a coding agent benchmark. Do not answer in prose. Call exactly one "
    "tool: bash with command 'pytest -q'."
)

CONTEXT_SENTINEL = "SUPERQODE_SENTINEL_4f9c8b2a"
CONTEXT_PROBE = (
    "You are a coding agent benchmark. The following repository notes are long "
    "on purpose.\n\n"
    + "\n".join(f"note {i}: keep scanning for the sentinel." for i in range(220))
    + f"\n\nFinal important token: {CONTEXT_SENTINEL}\n"
    + "Reply with only the final important token."
)

CONNECT_TIMEOUT = 10.0
STREAM_TIMEOUT = 180.0


@dataclass
class BenchResult:
    endpoint: str
    model: str
    ok: bool = False
    ttft_s: Optional[float] = None  # time to first content token
    decode_tps: Optional[float] = None  # tokens/second after first token
    total_s: Optional[float] = None
    completion_tokens: int = 0
    error: str = ""
    mode: str = "speed"
    tool_call_success: Optional[bool] = None
    edit_format_success: Optional[bool] = None
    shell_call_success: Optional[bool] = None
    context_recall_success: Optional[bool] = None
    agentic_score: Optional[float] = None
    agentic_notes: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.agentic_notes is None:
            self.agentic_notes = []


@dataclass
class StreamResult:
    content: str = ""
    tool_calls: List[dict[str, Any]] = None  # type: ignore[assignment]
    chunks: int = 0
    ttft_s: Optional[float] = None
    total_s: Optional[float] = None
    decode_tps: Optional[float] = None

    def __post_init__(self) -> None:
        if self.tool_calls is None:
            self.tool_calls = []


def endpoint_reachable(endpoint: str, timeout: float = CONNECT_TIMEOUT) -> bool:
    """True if the endpoint's /models route answers at all (any HTTP reply)."""
    url = endpoint.rstrip("/") + "/models"
    try:
        request = Request(url, headers={"User-Agent": "SuperQode"}, method="GET")
        with urlopen(request, timeout=timeout):  # noqa: S310
            return True
    except HTTPError:
        # A 4xx/5xx still means the server is up and listening.
        return True
    except (URLError, OSError):
        return False


def list_endpoint_models(endpoint: str, timeout: float = CONNECT_TIMEOUT) -> List[str]:
    """Model ids served by an OpenAI-compatible endpoint."""
    url = endpoint.rstrip("/") + "/models"
    try:
        request = Request(url, headers={"User-Agent": "SuperQode"}, method="GET")
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError):
        return []
    items = payload.get("data", []) if isinstance(payload, dict) else []
    return [str(m.get("id")) for m in items if isinstance(m, dict) and m.get("id")]


def run_bench(
    endpoint: str,
    model: str,
    prompt: str = DEFAULT_PROMPT,
    max_tokens: int = 256,
    api_key: str = "",
) -> BenchResult:
    """Stream one chat completion and time first-token and decode rate."""
    result = BenchResult(endpoint=endpoint, model=model)
    try:
        stream = _stream_chat(
            endpoint,
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "stream": True,
                "temperature": 0,
            },
            api_key=api_key,
        )
    except (HTTPError, URLError, OSError, ValueError) as exc:
        result.error = str(exc)
        return result

    if stream.ttft_s is None:
        result.error = "stream produced no content"
        return result

    result.ok = True
    result.ttft_s = stream.ttft_s
    result.total_s = stream.total_s
    result.completion_tokens = stream.chunks
    result.decode_tps = stream.decode_tps
    return result


def run_agentic_bench(
    endpoint: str,
    model: str,
    max_tokens: int = 384,
    api_key: str = "",
) -> BenchResult:
    """Run lightweight agent-control probes against a local model endpoint.

    The probes are intentionally non-mutating. They measure whether a model can
    emit the shapes SuperQode needs before it is allowed near real tools.
    """
    speed = run_bench(endpoint, model, max_tokens=max_tokens, api_key=api_key)
    result = BenchResult(
        endpoint=endpoint,
        model=model,
        ok=speed.ok,
        ttft_s=speed.ttft_s,
        decode_tps=speed.decode_tps,
        total_s=speed.total_s,
        completion_tokens=speed.completion_tokens,
        error=speed.error,
        mode="agentic",
    )
    if not speed.ok:
        return result

    try:
        tool_probe = _stream_chat(
            endpoint,
            _tool_probe_body(model, TOOL_CALL_PROBE, max_tokens=max_tokens),
            api_key=api_key,
        )
        tool_calls = _all_tool_calls(tool_probe)
        result.tool_call_success = _has_tool_call(
            tool_calls,
            "read_file",
            lambda args: args.get("path") == "pyproject.toml",
        )
        if not result.tool_call_success:
            result.agentic_notes.append("read_file tool call missing or wrong arguments")

        edit_probe = _stream_chat(
            endpoint,
            {
                "model": model,
                "messages": [{"role": "user", "content": EDIT_FORMAT_PROBE}],
                "max_tokens": max_tokens,
                "stream": True,
                "temperature": 0,
            },
            api_key=api_key,
        )
        result.edit_format_success = _looks_like_edit(edit_probe.content)
        if not result.edit_format_success:
            result.agentic_notes.append("edit-format probe did not produce a usable patch/diff")

        shell_probe = _stream_chat(
            endpoint,
            _tool_probe_body(model, SHELL_TOOL_PROBE, max_tokens=max_tokens),
            api_key=api_key,
        )
        shell_calls = _all_tool_calls(shell_probe)
        result.shell_call_success = _has_tool_call(
            shell_calls,
            "bash",
            lambda args: args.get("command") == "pytest -q"
            or args.get("cmd") == "pytest -q",
        )
        if not result.shell_call_success:
            result.agentic_notes.append("bash tool call missing or wrong command")

        context_probe = _stream_chat(
            endpoint,
            {
                "model": model,
                "messages": [{"role": "user", "content": CONTEXT_PROBE}],
                "max_tokens": 64,
                "stream": True,
                "temperature": 0,
            },
            api_key=api_key,
        )
        result.context_recall_success = CONTEXT_SENTINEL in context_probe.content
        if not result.context_recall_success:
            result.agentic_notes.append("long-context sentinel was not recalled")
    except (HTTPError, URLError, OSError, ValueError) as exc:
        result.error = str(exc)
        result.ok = False
        return result

    checks = [
        result.tool_call_success,
        result.edit_format_success,
        result.shell_call_success,
        result.context_recall_success,
    ]
    passed = sum(1 for item in checks if item is True)
    result.agentic_score = round((passed / len(checks)) * 100, 1)
    return result


def _tool_probe_body(model: str, prompt: str, *, max_tokens: int) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "tools": AGENTIC_TOOLS,
        "tool_choice": "auto",
        "max_tokens": max_tokens,
        "stream": True,
        "temperature": 0,
    }


def _stream_chat(endpoint: str, body: dict[str, Any], api_key: str = "") -> StreamResult:
    """Stream one chat completion and collect text plus tool-call deltas."""
    url = endpoint.rstrip("/") + "/chat/completions"
    encoded = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "SuperQode"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    start = time.monotonic()
    first_token_at: Optional[float] = None
    chunks = 0
    content_parts: list[str] = []
    tool_chunks: dict[int, dict[str, Any]] = {}
    request = Request(url, data=encoded, headers=headers, method="POST")
    with urlopen(request, timeout=STREAM_TIMEOUT) as response:  # noqa: S310
        for raw in response:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:") :].strip()
            if payload == "[DONE]":
                break
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            choices = event.get("choices") or []
            delta = (choices[0].get("delta") or {}) if choices else {}
            content = delta.get("content") or delta.get("reasoning_content")
            if content:
                if first_token_at is None:
                    first_token_at = time.monotonic()
                content_parts.append(str(content))
                chunks += 1
            for tool_delta in delta.get("tool_calls") or []:
                if first_token_at is None:
                    first_token_at = time.monotonic()
                chunks += 1
                index = int(tool_delta.get("index") or 0)
                merged = tool_chunks.setdefault(
                    index,
                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                )
                if tool_delta.get("id"):
                    merged["id"] += str(tool_delta["id"])
                function = tool_delta.get("function") or {}
                if function.get("name"):
                    merged["function"]["name"] += str(function["name"])
                if function.get("arguments"):
                    merged["function"]["arguments"] += str(function["arguments"])

    end = time.monotonic()
    output = StreamResult(
        content="".join(content_parts),
        tool_calls=[tool_chunks[i] for i in sorted(tool_chunks)],
        chunks=chunks,
        ttft_s=round(first_token_at - start, 2) if first_token_at is not None else None,
        total_s=round(end - start, 2),
    )
    decode_window = end - first_token_at if first_token_at is not None else 0
    if decode_window > 0 and chunks > 1:
        output.decode_tps = round((chunks - 1) / decode_window, 1)
    return output


def _all_tool_calls(stream: StreamResult) -> list[dict[str, Any]]:
    calls = list(stream.tool_calls)
    if stream.content:
        try:
            from ..agent.text_tool_calls import extract_text_tool_calls

            _cleaned, extracted = extract_text_tool_calls(stream.content)
            calls.extend(extracted)
        except Exception:
            pass
    return calls


def _tool_name(call: dict[str, Any]) -> str:
    function = call.get("function") if isinstance(call, dict) else None
    if isinstance(function, dict) and function.get("name"):
        return str(function["name"])
    if call.get("name"):
        return str(call["name"])
    return ""


def _tool_args(call: dict[str, Any]) -> dict[str, Any]:
    raw: Any = {}
    function = call.get("function") if isinstance(call, dict) else None
    if isinstance(function, dict):
        raw = function.get("arguments", {})
    elif isinstance(call, dict):
        raw = call.get("arguments", {})
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _has_tool_call(
    calls: list[dict[str, Any]],
    name: str,
    predicate,
) -> bool:
    for call in calls:
        if _tool_name(call) == name and predicate(_tool_args(call)):
            return True
    return False


def _looks_like_edit(content: str) -> bool:
    text = content.strip()
    if "*** Begin Patch" in text and "*** End Patch" in text:
        return True
    return "---" in text and "+++" in text and "@@" in text and "+    return 2" in text


def render_bench(results: List[BenchResult]) -> str:
    agentic = any(r.mode == "agentic" for r in results)
    title = (
        "SuperQode local bench (agent-control probes, streamed)"
        if agentic
        else "SuperQode local bench (agentic-shaped prompt, streamed)"
    )
    lines = [title, ""]
    if agentic:
        lines.append(
            f"{'model':<36} {'TTFT':>7} {'decode':>12} {'score':>7} "
            f"{'tool':>5} {'edit':>5} {'shell':>6} {'ctx':>4}"
        )
    else:
        lines.append(f"{'model':<44} {'TTFT':>8} {'decode':>12} {'total':>8}")
    for r in results:
        if r.ok and agentic:
            tps = f"{r.decode_tps} tok/s" if r.decode_tps is not None else "n/a"
            score = f"{r.agentic_score:.0f}%" if r.agentic_score is not None else "n/a"
            lines.append(
                f"{r.model:<36} {r.ttft_s:>6}s {tps:>12} {score:>7} "
                f"{_mark(r.tool_call_success):>5} {_mark(r.edit_format_success):>5} "
                f"{_mark(r.shell_call_success):>6} {_mark(r.context_recall_success):>4}"
            )
            for note in r.agentic_notes[:3]:
                lines.append(f"  - {r.model}: {note}")
        elif r.ok:
            tps = f"{r.decode_tps} tok/s" if r.decode_tps is not None else "n/a"
            lines.append(f"{r.model:<44} {r.ttft_s:>7}s {tps:>12} {r.total_s:>7}s")
        else:
            lines.append(f"{r.model:<44} failed: {r.error[:60]}")
    lines.append("")
    if agentic:
        lines.append("Agentic score covers tool call, edit format, shell call, and context recall.")
    lines.append("TTFT tracks prefill speed; agent loops are prefill-dominated.")
    return "\n".join(lines)


def _mark(value: Optional[bool]) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "-"


__all__ = [
    "BenchResult",
    "list_endpoint_models",
    "render_bench",
    "run_agentic_bench",
    "run_bench",
]
