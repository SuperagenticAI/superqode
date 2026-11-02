"""Repeatable, bounded read/edit checks through real harness backends."""

from __future__ import annotations

import asyncio
from dataclasses import replace, fields
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
import uuid

SUPPORTED_CHECK_BACKENDS = {"builtin", "pipy", "adk", "openai-agents", "pydanticai"}


def scoped_pipy_tools(tools, root):
    """A verification-only file boundary; PiPy's ordinary host permissions stay intact."""
    from superqode.pipy.tools.base import AgentTool, AgentToolResult
    from superqode.pipy.messages import TextContent

    result = []
    for tool in tools:

        async def execute(call_id, args, signal=None, on_update=None, selected=tool):
            path = (root / str(args.get("path") or "")).resolve()
            if not path.is_relative_to(root) or path == root:
                return AgentToolResult(
                    content=[
                        TextContent("Verification tool path is outside its disposable workspace")
                    ],
                    details={"verification_denied": True},
                )
            return await selected.execute(call_id, args, signal, on_update)

        data = {field.name: getattr(tool, field.name) for field in fields(tool)}
        data["execute_fn"] = execute
        result.append(AgentTool(**data))
    return result


def test_spec(source, root, kind):
    from .spec import ContextSpec, ExecutionPolicySpec, RuntimeSpec
    from .templates import core_template

    if source.runtime.backend not in SUPPORTED_CHECK_BACKENDS:
        raise ValueError(
            "This backend needs its own verification adapter; use the normal evaluation workflow"
        )
    base = core_template(name="studio-verification", backend=source.runtime.backend)
    tools = ("read", "edit") if kind == "edit" else ("read",)
    return replace(
        base,
        runtime=RuntimeSpec(
            backend=source.runtime.backend,
            config={"context_files": False, "system_prompt_files": False},
        ),
        agents=(replace(base.agents[0], tools=tools, max_iterations=6),),
        model_policy=replace(
            base.model_policy,
            temperature=source.model_policy.temperature,
            tool_call_format=source.model_policy.tool_call_format,
            config={**base.model_policy.config, "max_iterations": 6},
        ),
        execution_policy=ExecutionPolicySpec(
            sandbox="local",
            approval_profile="yolo",
            allow_read=True,
            allow_write=kind == "edit",
            allow_shell=False,
            allow_network=False,
        ),
        context=ContextSpec(instruction_files=(), session_storage=str(root / "sessions")),
    )


async def attempt(source, provider, model, directory, kind, emit):
    from . import init_harness
    from .kernel import HarnessRunRequest
    from .loader import harness_spec_to_dict

    with tempfile.TemporaryDirectory(prefix="studio-check-", dir=directory) as temporary:
        root = Path(temporary).resolve()
        os.environ["SUPERQODE_SEARCH_ROOTS"] = ""
        os.environ["SUPERQODE_TOOL_OUTPUT_DIR"] = str(root / "tool-output")
        token = "STUDIO_MARKER_" + uuid.uuid4().hex
        (root / "verification.txt").write_text(token + "\n")
        before, expected = "def answer():\n    return 1\n", "def answer():\n    return 2\n"
        (root / "sample.py").write_text(before)
        spec = test_spec(source, root, kind)
        # The experiment identity excludes its disposable storage location.
        identity = harness_spec_to_dict(
            replace(spec, context=replace(spec.context, session_storage="<verification-session>"))
        )
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        kernel = await init_harness(spec)
        session = await kernel.session()
        tools = ["read", "edit"] if kind == "edit" else ["read"]
        prompt = "Use read to inspect verification.txt. Return only the marker from that file."
        if kind == "edit":
            prompt = "Use read to inspect verification.txt and sample.py. Use edit to change sample.py to return 2 instead of 1, preserving its other text. Finish with only the marker from verification.txt."
        result = await asyncio.wait_for(
            session.run(
                HarnessRunRequest(
                    prompt=prompt,
                    provider=provider,
                    model=model,
                    working_directory=root,
                    metadata={
                        "agent_tools": tools,
                        "tools": tools,
                        "agent_max_iterations": 6,
                        "agent_max_tokens": 768,
                        "verification_root": str(root),
                    },
                )
            ),
            timeout=120,
        )
        events = result.events
        read = any(
            e.type == "tool_result"
            and e.data.get("tool_name") == "read"
            and e.data.get("success") is True
            and token in str(e.data.get("output") or "")
            for e in events
        )
        answer = result.content.strip() == token
        checks = [
            {"name": "Read generated marker through tool", "ok": read},
            {"name": "Returned marker after tool result", "ok": answer},
        ]
        if kind == "edit":
            edited = any(
                e.type == "tool_result"
                and e.data.get("tool_name") == "edit"
                and e.data.get("success") is True
                for e in events
            )
            path = root / "sample.py"
            content = path.read_text() if path.is_file() and path.stat().st_size < 100_000 else ""
            syntax = False
            try:
                compile(content, "sample.py", "exec")
                syntax = bool(content)
            except SyntaxError:
                pass
            checks += [
                {"name": "Executed edit tool", "ok": edited},
                {"name": "Exact expected code change", "ok": content == expected},
                {"name": "Python syntax check (code not executed)", "ok": syntax},
            ]
        trace = [
            {"event": e.type, "data": dict(e.data)}
            for e in events
            if e.type in {"tool_call", "tool_result", "model_result", "run_end"}
        ]
        return {
            "status": "passed" if all(c["ok"] for c in checks) else "failed",
            "checks": checks,
            "profile_digest": digest,
            "backend": source.runtime.backend,
            "error": result.response.error,
            "trace": trace,
            "iterations": result.iterations,
            "tool_calls": result.tool_calls_made,
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
            "cost_usd": result.cost_usd,
        }


def summary(attempts):
    total = len(attempts)
    passed = sum(row["status"] == "passed" for row in attempts)
    rate = passed / total
    z = 1.96
    center = (rate + z * z / (2 * total)) / (1 + z * z / total)
    half = (
        z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    )
    metrics = {}
    for key in ("tokens_in", "tokens_out", "cost_usd"):
        values = [row.get(key) for row in attempts]
        known = [v for v in values if type(v) in {int, float} and math.isfinite(v) and v >= 0]
        metrics[key] = sum(known) if len(known) == total else None
        metrics[key + "_known_attempts"] = len(known)
    return {
        "attempts": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": rate,
        "wilson_95": [max(0, center - half), min(1, center + half)],
        **metrics,
    }


def run(plan, directory, emit):
    from .loader import harness_spec_from_dict
    from superqode.providers.registry import PROVIDERS

    selected = plan["route"]
    if selected.get("endpoint"):
        definition = PROVIDERS[selected["provider"]]
        os.environ[definition.base_url_env] = (
            selected["endpoint"].removesuffix("/v1")
            if definition.id == "ollama"
            else selected["endpoint"]
        )
        if definition.id == "ollama":
            os.environ["OLLAMA_API_BASE"] = selected["endpoint"].removesuffix("/v1")
    source = harness_spec_from_dict(plan["spec"])
    reports = []
    for index in range(plan["repeats"]):
        emit(
            "stage",
            {"message": f"Harness check {index + 1}/{plan['repeats']} · {source.runtime.backend}"},
        )
        started = time.monotonic()
        try:
            row = asyncio.run(
                attempt(
                    source, selected["provider"], selected["model"], directory, plan["check"], emit
                )
            )
        except Exception as exc:
            row = {"status": "error", "error": str(exc), "checks": [], "trace": []}
        row["elapsed_seconds"] = time.monotonic() - started
        reports.append(row)
        emit("attempt", {"index": index + 1, **row})
    result = {
        "scope": "restricted-harness-profile",
        "source_digest": plan["source_digest"],
        "source_name": source.name,
        "backend": source.runtime.backend,
        "route": selected,
        "check": plan["check"],
        "attempts": reports,
        "summary": summary(reports),
        "engine_version": plan["engine_version"],
        "checked_at": time.time(),
        "note": "Reduced read/edit profile; source hooks, MCP, delegates, fallbacks and shell are excluded. This does not certify the complete saved harness or authorize adoption.",
    }
    emit("result", result)
    return result
