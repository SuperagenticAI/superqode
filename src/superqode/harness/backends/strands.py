"""Isolated Strands harness with SuperQode-owned tool execution."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import hashlib
import json
import math
import os
from pathlib import Path
from collections.abc import AsyncIterator
from typing import Any

from ...agent.loop import AgentResponse
from ...tools.base import ToolContext, ToolRegistry, ToolResult
from ...tools.governed import execute_governed_tool
from ...tools.permissions import Permission, PermissionManager
from ..compiler import compile_to_headless_profile
from ..events import HarnessEvent
from ..loader import harness_spec_to_dict
from ..permissions import evaluate_permission_rules
from ..sandbox import apply_backend_permissions, require_shell, SandboxPolicy
from ..spec import HarnessFlavor
from .base import HarnessBackendCapabilities, HarnessBackendRequest, HarnessBackendResult
from .strands_environment import worker_environment, redact_error

MAX_PACKET = 1_000_000
SUPPORTED_TOOLS = {"read", "write", "edit", "bash"}
CONFIG_KEYS = {
    "effort",
    "context_manager",
    "caching",
    "max_turns",
    "total_tokens",
    "output_tokens",
    "timeout_seconds",
    "wall_timeout_seconds",
    "session",
}
INSTALL_HINT = "Run `superqode harness strands setup`, then `superqode harness strands doctor`."


def strands_python() -> Path:
    configured = os.environ.get("SUPERQODE_STRANDS_PYTHON")
    if configured:
        return Path(configured).expanduser().absolute()
    return (
        Path.home()
        / ".superqode"
        / "runtimes"
        / "strands"
        / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )


def strands_installation_status() -> tuple[bool, str]:
    interpreter = strands_python()
    ready = interpreter.is_file() and os.access(interpreter, os.X_OK)
    return ready, "" if ready else INSTALL_HINT


def _worker_command() -> list[str]:
    return [str(strands_python()), "-I", "-u", str(Path(__file__).with_name("strands_worker.py"))]


def _settings(request: HarnessBackendRequest) -> dict:
    raw = dict(request.spec.runtime.config)
    if unknown := set(raw) - CONFIG_KEYS:
        raise ValueError("Unsupported Strands configuration: " + ", ".join(sorted(unknown)))
    for key, default, maximum in [
        ("max_turns", 20, 200),
        ("total_tokens", 100000, 2000000),
        ("output_tokens", 32000, 1000000),
    ]:
        value = raw.get(key, default)
        if type(value) is not int or not 0 < value <= maximum:
            raise ValueError(f"Strands {key} must be an integer from 1 to {maximum}")
        raw[key] = value
    for cap in (
        request.metadata.get("agent_max_iterations"),
        request.spec.model_policy.config.get("max_iterations"),
        *(agent.max_iterations for agent in request.spec.agents),
    ):
        if type(cap) is int and cap > 0:
            raw["max_turns"] = min(raw["max_turns"], cap)
    output_cap = request.metadata.get("agent_max_tokens")
    if type(output_cap) is int and output_cap > 0:
        raw["output_tokens"] = min(raw["output_tokens"], output_cap)
    timeout = raw.get("timeout_seconds", 300)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
        raise ValueError("Strands timeout_seconds must be between 0 and 3600")
    raw["timeout_seconds"] = timeout
    wall_timeout = raw.get("wall_timeout_seconds", 3600)
    if (
        type(wall_timeout) not in (int, float)
        or not math.isfinite(wall_timeout)
        or not 0 < wall_timeout <= 3600
    ):
        raise ValueError("Strands wall_timeout_seconds must be between 0 and 3600")
    raw["wall_timeout_seconds"] = wall_timeout
    if raw.get("effort", "auto") not in {
        "auto",
        "off",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    }:
        raise ValueError("Unsupported Strands effort")
    if raw.get("context_manager", "auto") not in {"auto", "agentic", False}:
        raise ValueError("Strands context_manager must be auto, agentic or false")
    if raw.get("caching", "auto") not in ("auto", True, False):
        raise ValueError("Strands caching must be auto, true or false")
    if type(raw.get("session", True)) is not bool:
        raise ValueError("Strands session must be true or false")
    return raw


def _model(request: HarnessBackendRequest) -> str:
    provider = {"gemini": "google"}.get(request.provider, request.provider)
    if provider not in {"bedrock", "anthropic", "openai", "google", "ollama", "litellm"}:
        raise ValueError(
            f"Strands does not support provider {provider!r}; choose Bedrock, Anthropic, OpenAI, Google, Ollama or LiteLLM"
        )
    if not request.model.strip():
        raise ValueError("Choose an explicit model for Strands")
    model = request.model.strip()
    prefix = model.split("/", 1)[0]
    if prefix in {"bedrock", "anthropic", "openai", "google", "ollama", "litellm"}:
        if prefix != provider:
            raise ValueError("Strands model prefix differs from the selected provider")
        return model
    return f"{provider}/{model}"


def _tools(request: HarnessBackendRequest) -> ToolRegistry:
    spec = request.spec
    if spec.flavor == HarnessFlavor.DECISION:
        raise ValueError("Strands decision harnesses are not supported")
    if (
        spec.workflow.mode.value != "single"
        or spec.recursion.enabled
        or spec.remote_harness.enabled
    ):
        raise ValueError("Strands currently supports single-agent local harnesses only")
    if request.images:
        raise ValueError("Strands image input is not yet supported by this adapter")
    if request.sandbox_backend not in {"local", "read-only", "no-shell"}:
        raise ValueError("Strands supports local, read-only and no-shell capability profiles only")
    if spec.hooks.rules or any(
        agent.delegates_to or agent.skills or agent.output_schema for agent in spec.agents
    ):
        raise ValueError(
            "Strands does not yet support custom hooks, delegation, skills or typed output"
        )
    if spec.execution_policy.blocked_categories:
        raise ValueError("Strands blocked_categories policy is not yet supported")
    if spec.model_policy.fallbacks or spec.model_policy.temperature is not None:
        raise ValueError("Strands fallback chains and temperature policy are not yet supported")
    if spec.model_policy.reasoning:
        raise ValueError("Set Strands reasoning with runtime.config.effort")
    if spec.flavor == HarnessFlavor.NO_TOOL:
        return ToolRegistry.empty()
    selected = request.metadata.get("agent_tools") or (
        spec.agents[0].tools if spec.agents else ("read",)
    )
    if spec.agents and spec.agents[0].tools and set(selected) - set(spec.agents[0].tools):
        raise ValueError("Strands agent tools cannot widen the HarnessSpec tool declaration")
    if set(selected) - SUPPORTED_TOOLS:
        raise ValueError("Strands supports only the governed read, write, edit and bash tools")
    policy = spec.execution_policy
    enabled = set(selected)
    if not policy.allow_read:
        enabled.discard("read")
    if not policy.allow_write or request.sandbox_backend == "read-only":
        enabled.difference_update({"write", "edit"})
    if not policy.allow_shell or request.sandbox_backend in {"read-only", "no-shell"}:
        enabled.discard("bash")
    return ToolRegistry.core().filtered([name for name in selected if name in enabled])


class StrandsHarnessBackend:
    name = "strands"
    capabilities = HarnessBackendCapabilities(
        backend=name,
        supports_coding=True,
        supports_no_tool=True,
        supports_streaming=True,
        supports_approvals=False,
        supports_sandbox=False,
        supports_shell=True,
        supports_mcp=False,
        supports_typed_output=False,
        supports_workflow_children=False,
        event_detail="rich",
        notes=(
            "Isolated Python runtime; SuperQode executes the four governed core tools.",
            "ASK blocks execution; interactive approval/resume is not implemented.",
            "Memory, skills, delegation and Strands-owned tools are disabled.",
            "Local/read-only/no-shell profiles are capability controls, not OS isolation.",
        ),
    )

    def __init__(self):
        self._tasks: dict[str | None, asyncio.Task] = {}

    async def cancel(self, session_id=None):
        task = self._tasks.get(session_id)
        if task and task is not asyncio.current_task():
            task.cancel()

    async def run(self, request: HarnessBackendRequest) -> HarnessBackendResult:
        events = [event async for event in self.stream(request)]
        result = next(event.data for event in reversed(events) if event.type == "model_result")
        response = AgentResponse(
            content=result["content"],
            messages=[],
            tool_calls_made=result["tool_calls_made"],
            iterations=result["iterations"],
            stopped_reason=result["stopped_reason"],
            input_tokens=result.get("input_tokens"),
            output_tokens=result.get("output_tokens"),
            total_tokens=result.get("total_tokens"),
        )
        return HarnessBackendResult(
            response=response, backend=self.name, runtime=self.name, metadata={"events": events}
        )

    async def stream(self, request: HarnessBackendRequest) -> AsyncIterator[HarnessEvent]:
        settings = _settings(request)
        tools = _tools(request)
        model = _model(request)
        identity = hashlib.sha256(
            json.dumps(
                {
                    "cwd": str(request.working_directory.resolve()),
                    "spec": harness_spec_to_dict(request.spec),
                    "model": model,
                    "tools": [tool.name for tool in tools.list()],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        session_id = hashlib.sha256(f"{identity}:{request.session_id}".encode()).hexdigest()
        session_dir = Path.home() / ".superqode" / "strands" / "sessions" / identity
        if request.session_id and settings.get("session", True):
            session_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            session_dir.chmod(0o700)
        payload = {
            "model": model,
            "prompt": request.prompt,
            "settings": settings,
            "instructions": compile_to_headless_profile(request.spec).job_description,
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": {"json": tool.parameters},
                }
                for tool in tools.list()
            ],
            "session": {"id": session_id, "dir": str(session_dir)}
            if request.session_id and settings.get("session", True)
            else False,
        }
        environment = worker_environment(request.provider, strands_python())
        budget = _ActiveBudget(settings["timeout_seconds"], settings["wall_timeout_seconds"])
        self._tasks[request.session_id] = asyncio.current_task()
        process = None
        watchdog = None
        if observer := getattr(self, "_runtime_observer", None):
            observer(self)
        try:
            process = await budget.wait(
                asyncio.create_subprocess_exec(
                    *_worker_command(),
                    cwd=request.working_directory,
                    env=environment,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    limit=MAX_PACKET + 1,
                )
            )
            watchdog = asyncio.create_task(_expire_worker(process, budget.deadline))
            await budget.wait(_send(process, payload))
            terminal = None
            ready = False
            while line := await budget.wait(process.stdout.readline()):
                if len(line) > MAX_PACKET:
                    raise ValueError("Strands worker packet exceeds size limit")
                packet = json.loads(line)
                if not isinstance(packet, dict) or terminal is not None:
                    raise ValueError("Invalid Strands worker protocol")
                kind = packet.get("type")
                if kind == "ready" and not ready:
                    ready = True
                    yield HarnessEvent(
                        type="model_request",
                        data={
                            "backend": self.name,
                            "model": model,
                            "versions": packet["versions"],
                        },
                    )
                elif kind == "tool_request" and ready:
                    name, args = packet.get("name"), packet.get("arguments")
                    if not isinstance(args, dict) or not isinstance(packet.get("id"), str):
                        raise ValueError("Invalid Strands tool request")
                    yield HarnessEvent(
                        type="tool_call",
                        data={
                            "tool_name": name,
                            "arguments": args,
                            "tool_call_id": packet["id"],
                        },
                    )
                    result = await budget.wait(execute_tool(request, tools, name, args))
                    yield HarnessEvent(
                        type="tool_result",
                        data={
                            "tool_name": name,
                            "success": result.success,
                            "output": result.output,
                            "error": result.error,
                        },
                    )
                    await budget.wait(
                        _send(
                            process,
                            {
                                "id": packet["id"],
                                "success": result.success,
                                "output": result.output,
                                "error": result.error,
                            },
                        )
                    )
                elif kind == "delta" and ready and isinstance(packet.get("text"), str):
                    yield HarnessEvent(type="model_delta", data={"text": packet["text"]})
                elif kind == "result" and ready:
                    terminal = _validate_result(packet)
                elif kind == "error":
                    raise RuntimeError(
                        redact_error(
                            str(packet.get("message") or "Strands worker failed"), environment
                        )
                    )
                else:
                    raise ValueError("Unexpected Strands worker packet")
            code = await budget.wait(process.wait())
            if code != 0 or terminal is None:
                raise RuntimeError("Strands worker exited without a successful terminal result")
            yield HarnessEvent(type="model_result", data=terminal)
            yield HarnessEvent(type="end", data={"backend": self.name})
        except (FileNotFoundError, PermissionError) as exc:
            if process is None:
                raise RuntimeError(
                    "Strands runtime is missing or cannot be started. " + INSTALL_HINT
                ) from exc
            raise
        finally:
            self._tasks.pop(request.session_id, None)
            if watchdog:
                watchdog.cancel()
                with suppress(asyncio.CancelledError):
                    await watchdog
            if process:
                await _close(process)


class _ActiveBudget:
    """Time awaited work; never leave a cancellation timer armed across yield."""

    def __init__(self, seconds, wall_seconds=3600):
        self.seconds = seconds
        self.remaining = seconds
        self.wall_seconds = wall_seconds
        self.deadline = asyncio.get_running_loop().time() + wall_seconds

    async def wait(self, operation):
        started = asyncio.get_running_loop().time()
        try:
            return await asyncio.wait_for(
                operation, max(0, min(self.remaining, self.deadline - started))
            )
        except TimeoutError as exc:
            if asyncio.get_running_loop().time() >= self.deadline:
                raise TimeoutError(
                    f"Strands exceeded its {self.wall_seconds:g}s wall-clock timeout"
                ) from exc
            raise TimeoutError(
                f"Strands exceeded its {self.seconds:g}s active execution timeout"
            ) from exc
        finally:
            self.remaining -= asyncio.get_running_loop().time() - started


async def _expire_worker(process, deadline):
    # Reap the worker even while the async generator is suspended in a UI yield.
    # Do not cancel the consumer task, which may be processing unrelated UI work.
    await asyncio.sleep(max(0, deadline - asyncio.get_running_loop().time()))
    await _close(process)


async def _send(process, packet):
    raw = (json.dumps(packet, allow_nan=False) + "\n").encode()
    if len(raw) > MAX_PACKET:
        raise ValueError("Strands worker request exceeds size limit")
    process.stdin.write(raw)
    await process.stdin.drain()


async def _close(process):
    if process.stdin:
        process.stdin.close()
    if process.returncode is None:
        with suppress(ProcessLookupError):
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 2)
        except asyncio.TimeoutError:
            with suppress(ProcessLookupError):
                process.kill()
    await process.wait()
    if process.stdin:
        with suppress(BrokenPipeError, ConnectionResetError):
            await process.stdin.wait_closed()


def _validate_result(packet):
    if not isinstance(packet.get("content"), str) or packet.get("stopped_reason") not in {
        "complete",
        "max_iterations",
        "max_tokens",
        "cancelled",
    }:
        raise ValueError("Invalid Strands terminal result")
    for key in ("iterations", "tool_calls_made", "input_tokens", "output_tokens", "total_tokens"):
        value = packet.get(key)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("Invalid Strands terminal usage")
    if packet.get("iterations") is None or packet.get("tool_calls_made") is None:
        raise ValueError("Missing Strands terminal counts")
    if packet["stopped_reason"] != "complete":
        raise RuntimeError("Strands run did not complete: " + packet["stopped_reason"])
    return {key: value for key, value in packet.items() if key != "type"}


async def execute_tool(request, tools, name, arguments) -> ToolResult:
    tool = tools.get(name) if isinstance(name, str) else None
    policy = request.spec.execution_policy
    denied = (
        not tool
        or (name == "read" and not policy.allow_read)
        or (
            name in {"write", "edit"}
            and (not policy.allow_write or request.sandbox_backend == "read-only")
        )
        or (
            name == "bash"
            and (not policy.allow_shell or request.sandbox_backend in {"read-only", "no-shell"})
        )
    )
    if denied:
        return ToolResult(False, "", "Tool denied by Strands harness capabilities")
    from jsonschema import validate, ValidationError

    try:
        validate(arguments, tool.parameters)
    except ValidationError:
        return ToolResult(False, "", "Invalid tool arguments")
    rule = evaluate_permission_rules(policy.permission_rules, name, arguments)
    if rule and rule.action in {"deny", "ask"}:
        return ToolResult(
            False,
            "",
            "Tool denied or requires approval; Strands interactive approvals are not implemented",
        )
    profile = compile_to_headless_profile(request.spec)
    manager = PermissionManager(
        apply_backend_permissions(profile.permissions, request.sandbox_backend)
    )
    if manager.check_permission(name, arguments) != Permission.ALLOW:
        return ToolResult(False, "", "Tool denied or requires approval")
    # Declared command allowlists must not be ignored by a shell-capable adapter.
    if name == "bash":
        try:
            require_shell(
                SandboxPolicy(allow_shell=True, allowed_commands=policy.allowed_commands),
                arguments.get("command", ""),
            )
        except (PermissionError, ValueError):
            return ToolResult(False, "", "Shell command denied by harness policy")
    if name in {"read", "write", "edit"}:
        target = (request.working_directory / str(arguments.get("path", ""))).resolve()
        if not target.is_relative_to(request.working_directory.resolve()):
            return ToolResult(False, "", "File access is outside the project")
    ctx = ToolContext(
        session_id=request.session_id or "strands",
        working_directory=request.working_directory,
        permission_manager=manager,
        harness_spec=request.spec,
        harness_store=request.metadata.get("_harness_store"),
        harness_run_id=str(request.metadata.get("_harness_run_id") or ""),
        harness_runtime="strands",
        harness_provider=request.provider,
        harness_model=request.model,
        harness_sandbox_backend=request.sandbox_backend,
    )
    return await execute_governed_tool(tool, arguments, ctx)
