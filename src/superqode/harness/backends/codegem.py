"""CodeGem on the normal HarnessSpec, kernel and TUI execution route."""

from dataclasses import replace
from uuid import uuid4

from .pipy import PiPyHarnessBackend, _session_ref, _safe_session_id
from ..codegem_adapter import CodeGemHarnessProtocolAdapter


class CodeGemHarnessBackend(PiPyHarnessBackend):
    name = "codegem"
    capabilities = replace(
        PiPyHarnessBackend.capabilities,
        backend="codegem",
        supports_mcp=False,
        notes=("Exactly six tools for Gemini/Gemma. Tools run with host process permissions.",),
    )

    def __init__(self, *, adapter=None):
        super().__init__(adapter=adapter or CodeGemHarnessProtocolAdapter())

    async def cancel(self, session_id=None):
        ref = self._active_ref
        if ref is None:
            return
        # The kernel cancels by its public ID, while this backend namespaces
        # storage IDs. The adapter's external ID belongs to the JSONL session.
        if session_id and session_id not in {ref.session_id, ref.external_session_id}:
            if "codegem-" + _safe_session_id(session_id) != ref.session_id:
                return
        await self.adapter.cancel(ref)

    async def _events(self, request):
        # Namespace kernel IDs; requests without an ID always open a fresh session.
        ref = _session_ref(request)
        policy = request.spec.execution_policy
        from superqode.codegem.tools import TOOL_NAMES

        if len(request.spec.agents) != 1 or request.spec.agents[0].tools != TOOL_NAMES:
            raise ValueError(
                "CodeGem requires one agent with exactly read, write, edit, search, python, bash"
            )
        if policy.approval_profile != "none" or request.sandbox_backend not in {"local", "none"}:
            raise ValueError(
                "CodeGem requires approval_profile=none and host execution; it cannot provide an OS sandbox"
            )
        runtime_config = {
            **ref.metadata["runtime_config"],
            "execution_policy": {
                "allow_read": policy.allow_read,
                "allow_write": policy.allow_write,
                "allow_shell": policy.allow_shell,
                "allowed_commands": list(policy.allowed_commands),
                "permission_rules": bool(policy.permission_rules),
            },
        }
        if policy.allowed_commands or policy.permission_rules or policy.blocked_categories:
            raise ValueError(
                "CodeGem cannot enforce command allowlists or approval rules; use Core or Workbench"
            )
        if policy.allow_shell and not policy.allow_network:
            raise ValueError("CodeGem host subprocesses cannot enforce allow_network=False")
        # Explicit HarnessSpec model settings override runtime family defaults.
        model_policy = request.spec.model_policy
        if model_policy.temperature is not None:
            runtime_config["temperature"] = model_policy.temperature
        if model_policy.context_window is not None:
            runtime_config["context_window"] = model_policy.context_window
        if model_policy.reasoning is not None:
            if request.provider in {"ollama", "lmstudio", "llamacpp"}:
                runtime_config["thinking"] = model_policy.reasoning != "off"
            else:
                from superqode.codegem.profiles import gemini_thinking_level, resolve_profile

                profile = resolve_profile(request.model, request.provider)
                runtime_config["thinking_config"] = {
                    "thinkingLevel": gemini_thinking_level(
                        request.model, profile, model_policy.reasoning
                    )
                }
        ref = replace(
            ref,
            harness_id="codegem",
            metadata={**ref.metadata, "runtime_config": runtime_config},
            session_id="codegem-" + (ref.session_id if request.session_id else uuid4().hex),
        )
        from ..protocol import HarnessMessage

        ref = await self.adapter.resume(ref)
        self._active_ref = ref
        try:
            message = HarnessMessage(
                "user",
                request.prompt,
                metadata={
                    "images": [
                        {"data": image.data, "mime_type": image.mime_type}
                        for image in request.images
                    ]
                },
            )
            async for event in self.adapter.send(ref, message):
                yield event
        finally:
            await self.adapter.close(ref)
            self._active_ref = None
