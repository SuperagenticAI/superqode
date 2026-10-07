"""Observed built-in runtime boundaries with a deterministic, offline gateway.

These probes execute the real runtime and file tools in disposable directories.
They do not certify a provider, an MCP transport, or vendor-native behavior.
"""

from __future__ import annotations

import asyncio
import json
import hashlib
import inspect
import tempfile
from dataclasses import dataclass
from pathlib import Path

from superqode import __version__
from superqode.agent.loop import AgentConfig, AgentLoop
from superqode.governance import (
    ContextualPolicyEngine,
    ContextualPolicyRule,
    CredentialBroker,
    GovernanceBundle,
    PolicyLayer,
    governance_scope,
)
from superqode.providers.gateway.base import (
    GatewayInterface,
    GatewayResponse,
    StreamChunk,
    Usage,
    Cost,
)
from superqode.runtime import create_runtime
from superqode.runtime.builtin import BuiltinRuntime
from superqode.tools.base import ToolRegistry, ToolResult
from superqode.tools.file_tools import ReadFileTool, WriteFileTool
from superqode.tools.permissions import Permission, PermissionConfig, PermissionManager
from superqode.tools.governed import execute_governed_tool


@dataclass(frozen=True)
class CertificationCheck:
    name: str
    verdict: str
    detail: str


@dataclass(frozen=True)
class BuiltinCertificationReport:
    checks: tuple[CertificationCheck, ...]

    @property
    def has_drift(self) -> bool:
        return any(check.verdict == "drift" for check in self.checks)

    @property
    def complete(self) -> bool:
        return all(check.verdict == "supported" for check in self.checks)

    @property
    def local_complete(self) -> bool:
        local = [check for check in self.checks if check.name != "live-provider-behavior"]
        return bool(local) and all(check.verdict == "supported" for check in local)

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "superqode_version": __version__,
            "integration": "builtin",
            "scope": "offline-runtime-boundaries",
            "gateway": "deterministic-fixture",
            "status": "failed" if self.has_drift else "passed" if self.complete else "incomplete",
            "complete": self.complete,
            "local_complete": self.local_complete,
            "has_drift": self.has_drift,
            "source_digests": {
                name: "sha256:"
                + hashlib.sha256(Path(inspect.getfile(obj)).read_bytes()).hexdigest()
                for name, obj in (
                    ("agent_loop", AgentLoop),
                    ("builtin_runtime", BuiltinRuntime),
                    ("file_tools", WriteFileTool),
                    ("governed_tools", execute_governed_tool),
                    ("certification_suite", BuiltinCertificationReport),
                )
            },
            "checks": [vars(check) for check in self.checks],
        }


class _FixtureGateway(GatewayInterface):
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.requests = []
        self.stream_closed = False

    async def chat_completion(self, messages, model, provider=None, **kwargs):
        self.requests.append({"messages": list(messages), "model": model, "provider": provider})
        return self.responses.pop(0) if self.responses else GatewayResponse(content="fixture done")

    async def stream_completion(self, messages, model, provider=None, **kwargs):
        self.requests.append({"messages": list(messages), "model": model, "provider": provider})
        try:
            yield StreamChunk(content="first", finish_reason=None)
            await asyncio.sleep(0)
            yield StreamChunk(content="second", finish_reason="stop")
        finally:
            self.stream_closed = True

    async def test_connection(self, provider, model=None):
        return {"ok": False, "reason": "Offline fixture has no provider connection"}

    def get_model_string(self, provider, model):
        return f"{provider}/{model}"


def _tool_call(name="write_file", arguments=None):
    return GatewayResponse(
        content="",
        tool_calls=[
            {
                "id": "fixture-call",
                "function": {
                    "name": name,
                    "arguments": json.dumps(
                        arguments or {"path": "probe.txt", "content": "evidence"}
                    ),
                },
            }
        ],
    )


def _runtime(root, gateway, *, storage=False, mcp_executor=None):
    tools = ToolRegistry.empty()
    tools.register(WriteFileTool())
    tools.register(ReadFileTool())
    return create_runtime(
        "builtin",
        gateway=gateway,
        tools=tools,
        config=AgentConfig(
            "fixture",
            "fixture-model",
            working_directory=root,
            max_iterations=6,
            enable_session_storage=storage,
            session_storage_dir=str(root / "sessions"),
            session_id="certification-session" if storage else None,
        ),
        include_mcp=False,
        allow_peer_agents=False,
        parallel_tools=False,
        permission_manager=PermissionManager(PermissionConfig(default=Permission.ALLOW)),
        mcp_executor=mcp_executor,
    )


def _bundle(action, *, phase="tool_call", tool="write_file", revision="fixture"):
    return GovernanceBundle(
        ContextualPolicyEngine(
            (
                PolicyLayer(
                    "project",
                    "fixture",
                    rules=(ContextualPolicyRule(revision, action, phases=(phase,), tools=(tool,)),),
                ),
            )
        ),
        CredentialBroker(),
    )


def _require(condition, message):
    if not condition:
        raise _ProbeMismatch(message)


class _ProbeMismatch(Exception):
    pass


async def _file_tools(root):
    gateway = _FixtureGateway(
        [
            _tool_call(),
            _tool_call("read_file", {"path": "probe.txt"}),
            GatewayResponse(content="fixture done"),
        ]
    )
    response = await _runtime(root, gateway).run("Write probe.txt, then read it using tools.")
    _require(
        not response.error and response.stopped_reason == "complete", "Tool run did not complete"
    )
    _require(
        (root / "probe.txt").is_file() and (root / "probe.txt").read_text() == "evidence",
        "Write did not reach the fixture",
    )
    results = [m.content for m in gateway.requests[-1]["messages"] if m.role == "tool"]
    _require(
        any("evidence" in str(text) for text in results),
        "Read result did not reach the model request",
    )
    return "Observed real write/read execution and tool-result feedback."


async def _deny(root):
    gateway = _FixtureGateway([_tool_call()])
    runtime = _runtime(root, gateway)
    with governance_scope(_bundle("deny")):
        await runtime.run("Write probe.txt using the tool.")
    _require(not (root / "probe.txt").exists(), "Denied tool mutated the fixture")
    feedback = [
        message.content
        for request in gateway.requests
        for message in request["messages"]
        if message.role == "tool"
    ]
    _require(
        any(
            "policy" in str(content).lower()
            and any(word in str(content).lower() for word in ("denied", "blocked"))
            for content in feedback
        ),
        "Denial was not observed in tool feedback",
    )
    return "Contextual DENY prevented the real file write."


async def _approval(root):
    runtime = _runtime(root, _FixtureGateway([_tool_call()]))
    with governance_scope(_bundle("ask")):
        response = await runtime.run("Write probe.txt using the tool.")
        _require(response.stopped_reason == "needs_approval", "ASK did not pause")
        _require(not (root / "probe.txt").exists(), "ASK executed before consent")
        request = runtime.get_pending_approvals()[0]
        _require(request["arguments"]["path"] == "probe.txt", "Pending request lost its arguments")
        resumed = await runtime.approve_and_resume()
        _require(
            not resumed.error
            and (root / "probe.txt").is_file()
            and (root / "probe.txt").read_text() == "evidence",
            "Approved write failed",
        )
        timestamp = (root / "probe.txt").stat().st_mtime_ns
        try:
            await runtime.approve_and_resume()
        except RuntimeError:
            pass
        else:
            raise _ProbeMismatch("The same approval could be resumed twice")
        _require(
            (root / "probe.txt").stat().st_mtime_ns == timestamp,
            "Duplicate approval repeated the write",
        )
    return "ASK paused, approved once, and rejected duplicate resumption."


async def _changed_policy(root):
    runtime = _runtime(root, _FixtureGateway([_tool_call()]))
    with governance_scope(_bundle("ask", revision="old")):
        response = await runtime.run("Write probe.txt using the tool.")
        _require(response.stopped_reason == "needs_approval", "ASK did not pause")
    with governance_scope(_bundle("deny", revision="new")):
        response = await runtime.approve_and_resume()
    _require(
        response.error and not (root / "probe.txt").exists(), "New DENY did not invalidate approval"
    )
    return "A new DENY prevented a previously pending invocation."


async def _mcp_result(root):
    calls = []

    async def executor(server, tool, arguments):
        calls.append((server, tool))
        return ToolResult(True, "SUPPRESSED_FIXTURE_MARKER")

    gateway = _FixtureGateway([_tool_call("mcp_probe_echo", {"text": "fixture"})])
    runtime = _runtime(root, gateway, mcp_executor=executor)
    with governance_scope(_bundle("deny", phase="tool_result", tool="mcp_probe_echo")):
        await runtime.run("Call mcp_probe_echo using the tool.")
    _require(calls == [("probe", "echo")], "Dynamic MCP dispatch did not execute once")
    results = [
        m.content for request in gateway.requests for m in request["messages"] if m.role == "tool"
    ]
    _require(
        results and all("SUPPRESSED_FIXTURE_MARKER" not in str(text) for text in results),
        "Denied result reached a model request",
    )
    return (
        "Dynamic MCP route suppressed a denied result before model feedback; transport was mocked."
    )


async def _cancel(root):
    gateway = _FixtureGateway()
    runtime = _runtime(root, gateway)
    chunks = []
    async for chunk in runtime.run_streaming("Write an explanation of this fixture."):
        chunks.append(chunk)
        runtime.cancel()
    _require(
        "first" in "".join(chunks) and "second" not in "".join(chunks),
        "Cancellation did not stop further output",
    )
    return "Cancellation during an active stream suppressed subsequent fixture output; blocking I/O was not tested."


async def _model_usage(root):
    gateway = _FixtureGateway(
        [
            GatewayResponse(
                content="fixture done",
                usage=Usage(3, 2, 5),
                cost=Cost(total_cost=0),
            )
        ]
    )
    response = await _runtime(root, gateway).run("Explain this fixture.")
    _require(
        gateway.requests[0]["provider"] == "fixture"
        and gateway.requests[0]["model"] == "fixture-model",
        "Configured model was not forwarded",
    )
    _require(
        response.total_tokens == 5 and response.cost_usd == 0,
        "Reported usage or known zero cost was lost",
    )
    return "Configured model/provider reached the gateway; reported tokens and zero cost survived."


async def _continuity(root):
    first = _runtime(
        root, _FixtureGateway([GatewayResponse(content="retained fixture answer")]), storage=True
    )
    await first.run("Remember fixture continuity.")
    gateway = _FixtureGateway()
    second = _runtime(root, gateway, storage=True)
    await second.run("Continue the fixture task.")
    history = gateway.requests[0]["messages"]
    _require(
        any(m.role == "user" and m.content == "Remember fixture continuity." for m in history),
        "Prior user message was not restored",
    )
    _require(
        any(m.role == "assistant" and m.content == "retained fixture answer" for m in history),
        "Prior assistant message was not restored",
    )
    return (
        "A fresh runtime restored file-backed conversation history using the same session identity."
    )


BUILTIN_PROBES = (
    ("file-tool-calling", _file_tools),
    ("contextual-deny", _deny),
    ("ask-approve-once", _approval),
    ("changed-policy", _changed_policy),
    ("dynamic-mcp-result-policy", _mcp_result),
    ("active-stream-cancellation", _cancel),
    ("model-forwarding-and-usage", _model_usage),
    ("session-restart-continuity", _continuity),
)


async def run_builtin_certification() -> BuiltinCertificationReport:
    checks = []
    with tempfile.TemporaryDirectory(prefix="superqode-builtin-certification-") as directory:
        for name, probe in BUILTIN_PROBES:
            root = Path(directory).resolve() / name
            root.mkdir()
            try:
                detail = await asyncio.wait_for(probe(root), timeout=15)
                checks.append(CertificationCheck(name, "supported", detail))
            except _ProbeMismatch as exc:
                checks.append(CertificationCheck(name, "drift", str(exc)))
            except Exception as exc:
                checks.append(
                    CertificationCheck(
                        name, "unknown", f"Probe could not finish: {type(exc).__name__}"
                    )
                )
    checks.append(
        CertificationCheck(
            "live-provider-behavior",
            "unknown",
            "No external provider was called; provider authentication, effective model identity and coding quality remain unverified.",
        )
    )
    return BuiltinCertificationReport(tuple(checks))


def render_builtin_certification(report: BuiltinCertificationReport) -> str:
    payload = report.to_dict()
    lines = [f"Builtin runtime: {payload['status']} (offline boundary probes)"]
    lines.extend(f"[{check.verdict}] {check.name}: {check.detail}" for check in report.checks)
    return "\n".join(lines)
