"""Core message adapter for host-owned evidence projections."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace

from .context_artifacts import ContextArtifactStore
from .context_policy import ContextItem, ContextPolicy, ContextPolicyEngine


def configured_context_client(policy, *, spec=None, explicit=None):
    if policy is None or policy.selector != "jev":
        return None
    from superqode.execution_recovery import active_recovery
    from superqode.systemone.config import resolve_systemone, build_client

    recovery = active_recovery()
    if recovery:
        budget = recovery.store.get(recovery.work_order_id).budget
        if budget.max_cost_usd is not None or budget.max_tokens is not None:
            # Unknown selector spend cannot escape a capped WorkOrder ledger.
            return None
    settings = resolve_systemone(spec=spec, explicit=explicit)
    return build_client(settings) if settings.enabled and not settings.skip_client else None


def configured_context_policy(config=None):
    values = dict(config or {})
    mode = values.pop("mode", os.environ.get("SUPERQODE_CONTEXT_MODE", "off"))
    selector = values.pop("selector", os.environ.get("SUPERQODE_CONTEXT_SELECTOR", "rules"))
    if mode == "off":
        return None
    # Persistence/reader availability is inseparable from applying a projection.
    values.pop("store_path", None)
    values.pop("conditional_instructions", None)
    return ContextPolicy(mode=mode, selector=selector, **values)


def core_items(messages):
    calls = {}
    items = []
    for index, message in enumerate(messages):
        for call in getattr(message, "tool_calls", None) or ():
            fn = call.get("function") or {}
            arguments = fn.get("arguments") or {}
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    arguments = {}
            calls[call.get("id")] = (
                fn.get("name", ""),
                arguments if isinstance(arguments, dict) else {},
            )
        text = message.content if isinstance(message.content, str) else ""
        call_id = getattr(message, "tool_call_id", "") or ""
        tool, arguments = calls.get(call_id, (getattr(message, "name", "") or "", {}))
        if message.role == "tool" and call_id not in calls:
            call_id = ""
        identity = f"{index}:{call_id}:{hashlib.sha256(text.encode()).hexdigest()}"
        if message.role == "assistant" and getattr(message, "tool_calls", None):
            arguments = {"tool_calls": message.tool_calls}
        items.append(
            ContextItem(
                identity,
                message.role,
                text,
                tool,
                call_id,
                arguments,
                text.startswith("Error:") or "Traceback (most recent call last)" in text,
            )
        )
    return items


async def prepare_core_context(loop, messages):
    spec = getattr(loop.config, "harness_spec", None)
    config = (getattr(getattr(spec, "runtime", None), "config", None) or {}).get("context", {})
    policy = configured_context_policy(config)
    if any(
        isinstance(m.content, str)
        and ("[context chunk " in m.content or "[context artifact " in m.content)
        for m in messages
    ):
        loop._ensure_context_chunk_tool()
    if policy is None:
        from superqode.execution_recovery import active_recovery
        from superqode.workorders.evidence import evidence_config

        recovery = active_recovery()
        if (
            recovery
            and evidence_config(recovery.store.get(recovery.work_order_id)).get("enabled") is True
        ):
            loop._ensure_context_chunk_tool()
        return messages
    try:
        store = ContextArtifactStore(config.get("store_path"))
        engine = ContextPolicyEngine(
            store,
            loop.session_id,
            policy,
            client=(
                getattr(loop, "_systemone_client", None)
                or configured_context_client(policy, spec=spec)
            ),
        )
        loop._context_artifact_store = store
        loop._ensure_context_chunk_tool()
        plan = await engine.prepare(
            core_items(messages), run_key=str(getattr(loop.config, "harness_run_id", ""))
        )
        loop.last_context_selection = plan.trace
        await loop.hooks.fire("context_selection", loop._lifecycle_context(), plan.trace)
        if plan.trace["candidate_count"] and loop.on_thinking:
            await loop.on_thinking(
                f"Context {policy.mode}: {plan.trace['candidate_count']} evidence references; "
                f"{plan.trace['chars_before']} -> {plan.trace['proposed_chars_after']} proposed characters"
            )
        # Project a copy. The session archive and subsequent iterations retain originals.
        return [
            replace(message, content=plan.replacements.get(i, message.content))
            for i, message in enumerate(messages)
        ]
    except Exception as exc:
        loop.last_context_selection = {
            "kind": "context_selection",
            "fallback": type(exc).__name__,
            "mode": policy.mode,
            "applied": False,
        }
        return messages
