"""A bounded Core read-tool roundtrip over generated, disposable test data."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import uuid


async def run(provider, model, endpoint, directory, emit):
    from superqode.harness import init_harness
    from superqode.harness.kernel import HarnessRunRequest
    from superqode.harness.loader import harness_spec_to_dict
    from superqode.harness.spec import ContextSpec, ExecutionPolicySpec
    from superqode.harness.templates import core_template
    from superqode.providers.registry import PROVIDERS

    definition = PROVIDERS[provider]
    if not definition.base_url_env:
        raise ValueError("This provider does not expose a local endpoint binding")
    # This function runs only in a disposable operation worker, never the UI engine.
    os.environ[definition.base_url_env] = (
        endpoint.removesuffix("/v1") if provider == "ollama" else endpoint
    )
    if provider == "ollama":
        os.environ["OLLAMA_HOST"] = endpoint.removesuffix("/v1")
    with tempfile.TemporaryDirectory(prefix="core-read-check-", dir=directory) as temporary:
        root = Path(temporary)
        os.environ["SUPERQODE_SEARCH_ROOTS"] = ""
        os.environ["SUPERQODE_TOOL_OUTPUT_DIR"] = str(root / "tool-output")
        marker = "SUPERQODE_READ_CHECK_" + uuid.uuid4().hex
        (root / "verification.txt").write_text(marker + "\n")
        base = core_template(name="local-core-read-check")
        spec = replace(
            base,
            agents=(replace(base.agents[0], tools=("read",), max_iterations=3),),
            model_policy=replace(
                base.model_policy, config={**base.model_policy.config, "max_iterations": 3}
            ),
            execution_policy=ExecutionPolicySpec(
                allow_read=True, allow_write=False, allow_shell=False, allow_network=False
            ),
            context=ContextSpec(instruction_files=(), session_storage=str(root / "sessions")),
        )
        digest = hashlib.sha256(
            json.dumps(harness_spec_to_dict(spec), sort_keys=True).encode()
        ).hexdigest()
        kernel = await init_harness(spec)
        session = await kernel.session()
        emit(
            "stage",
            {
                "message": "Executing a Core read-tool roundtrip on generated test data; writes, shell, MCP and delegation are excluded."
            },
        )
        result = await asyncio.wait_for(
            session.run(
                HarnessRunRequest(
                    prompt="Use the read tool to read verification.txt. Then reply with only the marker in that file. Do not guess the marker.",
                    provider=provider,
                    model=model,
                    working_directory=root,
                    metadata={
                        "agent_tools": ["read"],
                        "agent_max_iterations": 3,
                        # Reasoning models (Qwen3 etc.) may spend hundreds of
                        # tokens thinking before the final marker reply.
                        "agent_max_tokens": 1024,
                    },
                )
            ),
            timeout=90,
        )
        read = any(
            event.type == "tool_result"
            and event.data.get("tool_name") == "read"
            and event.data.get("success") is True
            and marker in str(event.data.get("output") or "")
            for event in result.events
        )
        answer = result.content.strip() == marker
        # A successful Core read of the generated marker already proves the
        # tool loop. Empty final prose usually means the model burned the
        # remaining output budget on reasoning rather than echoing the marker.
        marker_proven = answer or (read and not result.content.strip())
        response = result.response
        execution_complete = (
            response.stopped_reason == "complete"
            and not response.error
            and not response.schema_errors
        )
        return {
            "status": "passed" if read and marker_proven and execution_complete else "failed",
            "execution_complete": execution_complete,
            "stopped_reason": response.stopped_reason,
            "backend": "builtin",
            "profile": "Core read-only test profile",
            "profile_digest": digest,
            "endpoint": endpoint,
            "model": model,
            "checks": [
                {"name": "read executed successfully", "ok": read},
                {"name": "generated marker observed in tool result or reply", "ok": marker_proven},
            ],
            "final_reply_matches_marker": answer,
            "final_reply_empty": not result.content.strip(),
            "iterations": result.iterations,
            "tool_calls": result.tool_calls_made,
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
            "note": "Actual Core tool execution on disposable data. This checks the reduced read-only profile; other harnesses, project editing, shell execution and full coding quality remain unverified.",
        }
