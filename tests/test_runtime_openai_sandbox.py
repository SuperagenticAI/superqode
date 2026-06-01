"""Phase 7 tests: SandboxAgent integration inside OpenAIAgentsRuntime."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from superqode.agent.loop import AgentConfig
from superqode.runtime.errors import RuntimeNotInstalledError
from superqode.tools.base import Tool, ToolContext, ToolRegistry, ToolResult

pytest.importorskip("agents", reason="openai-agents not installed")
pytest.importorskip("agents.sandbox", reason="openai-agents sandbox support not installed")

from superqode.runtime.openai_agents import OpenAIAgentsRuntime  # noqa: E402
from superqode.runtime.openai_sandbox import (  # noqa: E402
    build_manifest,
    build_sandbox_client,
    is_sandbox_backend_available,
    supported_sandbox_backends,
)


class _EchoTool(Tool):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "echo"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ToolResult(success=True, output="")


def _registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(_EchoTool())
    return r


def _config(tmp_path: Path) -> AgentConfig:
    return AgentConfig(
        provider="openai",
        model="gpt-4o-mini",
        working_directory=tmp_path,
        enable_session_storage=False,
        session_id="sandbox-test",
    )


# ---------------------------------------------------------------------------
# Backend registry / helpers
# ---------------------------------------------------------------------------


def test_supported_backends_includes_all_announced_clients():
    """The v0.14 announcement lists 8 sandbox providers + local; we recognize all."""
    expected = {
        "local",
        "docker",
        "e2b",
        "daytona",
        "modal",
        "vercel",
        "runloop",
        "blaxel",
        "cloudflare",
    }
    assert set(supported_sandbox_backends()) == expected


def test_local_backend_is_available():
    assert is_sandbox_backend_available("local") is True


def test_third_party_backends_raise_install_hint_when_missing():
    """e2b/daytona/modal/vercel/runloop/blaxel/cloudflare ship as separate packages."""
    for name in ("e2b", "daytona", "modal", "vercel", "runloop", "blaxel", "cloudflare"):
        with pytest.raises(RuntimeNotInstalledError) as exc:
            build_sandbox_client(name)
        # The hint must include the expected pip package.
        assert f"agents-{name}" in str(exc.value)


def test_unknown_backend_raises_value_error():
    with pytest.raises(ValueError):
        build_sandbox_client("not-a-backend")


def test_build_sandbox_client_local_returns_unix_local():
    from agents.sandbox.sandboxes.unix_local import UnixLocalSandboxClient

    client = build_sandbox_client("local")
    assert isinstance(client, UnixLocalSandboxClient)


# ---------------------------------------------------------------------------
# Manifest construction
# ---------------------------------------------------------------------------


def test_build_manifest_includes_working_directory_as_localdir(tmp_path):
    from agents.sandbox.entries import LocalDir

    manifest = build_manifest(_config(tmp_path))
    assert "repo" in manifest.entries
    entry = manifest.entries["repo"]
    assert isinstance(entry, LocalDir)
    assert entry.src == tmp_path


# ---------------------------------------------------------------------------
# Runtime wiring
# ---------------------------------------------------------------------------


def test_runtime_without_sandbox_uses_regular_agent(tmp_path):
    runtime = OpenAIAgentsRuntime(tools=_registry(), config=_config(tmp_path))
    assert runtime.sandbox_backend is None
    assert runtime._sandbox_client is None
    # When sandbox is off, the RunConfig has no sandbox set.
    assert getattr(runtime._run_config, "sandbox", None) is None


def test_runtime_with_local_sandbox_upgrades_to_sandbox_agent(tmp_path):
    from agents.sandbox import SandboxAgent

    runtime = OpenAIAgentsRuntime(
        tools=_registry(),
        config=_config(tmp_path),
        sandbox_backend="local",
    )
    assert runtime.sandbox_backend == "local"
    assert runtime._sandbox_client is not None
    assert isinstance(runtime._agent, SandboxAgent)
    # SandboxAgent carries a default Manifest.
    assert runtime._agent.default_manifest is not None
    # RunConfig has a sandbox configured.
    assert getattr(runtime._run_config, "sandbox", None) is not None


def test_runtime_with_unrecognized_backend_falls_back_to_regular_agent(tmp_path, caplog):
    """If sandbox_backend isn't a known name, log a warning and use regular Agent."""
    runtime = OpenAIAgentsRuntime(
        tools=_registry(),
        config=_config(tmp_path),
        sandbox_backend="never-heard-of-it",
    )
    # Fell back — sandbox_backend was cleared.
    assert runtime.sandbox_backend is None
    assert runtime._sandbox_client is None


def test_runtime_with_missing_third_party_backend_raises(tmp_path):
    """Asking for e2b without `agents-e2b` installed must raise the install hint."""
    with pytest.raises(RuntimeNotInstalledError) as exc:
        OpenAIAgentsRuntime(
            tools=_registry(),
            config=_config(tmp_path),
            sandbox_backend="e2b",
        )
    assert "agents-e2b" in str(exc.value)


def test_runtime_tracing_stays_disabled_with_sandbox(tmp_path):
    """Switching to sandbox must not flip tracing on."""
    runtime = OpenAIAgentsRuntime(
        tools=_registry(),
        config=_config(tmp_path),
        sandbox_backend="local",
    )
    assert runtime._run_config.tracing_disabled is True
