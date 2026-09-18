"""Tool discovery changes schemas, not execution or permission grants."""

from dataclasses import replace
import json

import pytest

from superqode.harness.catalog import resolve_harness, recommended_harnesses
from superqode.harness.loader import harness_spec_to_dict, harness_spec_from_dict
from superqode.harness.spec import HarnessSpec, SystemOneSpec
from superqode.harness.compiler import compile_to_headless_profile
from superqode.systemone.client import StubSystemOneClient
from superqode.tools.base import ToolContext
from superqode.tools.tool_search import ToolSearchTool, apply_deferred_tool_policy
from test_deferred_tools import _registry


@pytest.fixture(autouse=True)
def isolate_systemone_environment(monkeypatch):
    for name in (
        "SUPERQODE_SYSTEMONE",
        "SUPERQODE_SYSTEMONE_MODE",
        "SUPERQODE_SYSTEMONE_TRACE_DIR",
        "SUPERQODE_SYSTEMONE_TOOL_SEARCH",
        "SUPERQODE_DEFERRED_TOOLS",
        "TYPESAFE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_systemone_is_selectable_coding_harness_with_shadow_defaults(tmp_path):
    harness = resolve_harness("systemone", root=tmp_path)
    assert harness.runtime == "builtin"
    assert harness.spec.systemone.client == "live"
    assert harness.spec.systemone.mode == "shadow"
    assert harness.spec.systemone.tool_search_mode == "shadow"
    assert harness.spec.model_policy.primary is None
    assert compile_to_headless_profile(harness.spec).tools is None
    assert "web_fetch" in harness.tools
    assert harness.id in {entry.id for entry in recommended_harnesses(tmp_path)}
    restored = harness_spec_from_dict(harness_spec_to_dict(harness.spec))
    assert restored.systemone == harness.spec.systemone
    registry = _registry()
    apply_deferred_tool_policy(registry, policy="all")
    assert registry.get("tool_search") is not None
    assert "web_fetch" in registry.deferred_names()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["shadow", "rerank"])
async def test_semantic_selection_and_shadow_activation(mode, tmp_path):
    registry = _registry()
    registry.defer("web_fetch", "shell_session")
    client = StubSystemOneClient(
        {
            "tool": {
                "choice": "candidate_1",
                "confidence": 0.95,
                "probabilities": {"candidate_0": 0.02, "candidate_1": 0.96, "none": 0.02},
            },
            "necessary": {"noul": 0.95},
        }
    )
    ctx = ToolContext(
        session_id="test",
        working_directory=tmp_path,
        tool_registry=registry,
        harness_spec=HarnessSpec(
            name="test",
            systemone=SystemOneSpec(
                enabled=True, tool_search_mode=mode, trace_dir=str(tmp_path / "traces")
            ),
        ),
        systemone_client=client,
    )
    # Neither description includes "internet": small-catalog semantic fallback.
    result = await ToolSearchTool().execute({"query": "internet"}, ctx)
    assert result.metadata["activated"] == (["web_fetch"] if mode == "rerank" else [])
    assert result.metadata["systemone"]["selectedTool"] == "web_fetch"
    assert registry.get("web_fetch") is not None
    event = json.loads(next((tmp_path / "traces" / "tool-search").glob("*.json")).read_text())
    assert event["baselineTools"] == []
    assert event["activatedTools"] == result.metadata["activated"]
    assert len(client.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case", ["low_confidence", "tie", "not_necessary", "none", "invalid", "error", "offline"]
)
async def test_reranking_abstains_or_falls_back(case, tmp_path):
    registry = _registry()
    registry.defer("web_fetch", "shell_session")
    answer = {
        "choice": "candidate_0",
        "confidence": 0.95,
        "probabilities": {"candidate_0": 0.95, "none": 0.05},
    }
    necessary = 0.95
    if case == "low_confidence":
        answer["confidence"] = 0.4
    elif case == "tie":
        answer["probabilities"] = {"candidate_0": 0.51, "none": 0.49}
    elif case == "not_necessary":
        necessary = 0.5
    elif case == "none":
        answer.update(choice="none", probabilities={"none": 0.95, "candidate_0": 0.05})
    elif case == "invalid":
        answer["choice"] = "made_up_tool"
    client = StubSystemOneClient(
        {"tool": answer, "necessary": {"noul": necessary}},
        error=RuntimeError("transport") if case == "error" else None,
    )
    spec = HarnessSpec(
        name="test", systemone=SystemOneSpec(enabled=True, tool_search_mode="rerank")
    )
    if case == "offline":
        spec = replace(spec, metadata={"airplane_mode": True})
    ctx = ToolContext(
        session_id="t",
        working_directory=tmp_path,
        tool_registry=registry,
        harness_spec=spec,
        systemone_client=client,
    )
    result = await ToolSearchTool().execute({"query": "fetch web page"}, ctx)
    assert result.metadata["activated"] == (
        ["web_fetch"] if case in {"invalid", "error", "offline"} else []
    )
    if case == "offline":
        assert client.calls == []


def test_explicit_deferred_off_overrides_harness_default(monkeypatch):
    monkeypatch.setenv("SUPERQODE_DEFERRED_TOOLS", "off")
    registry = _registry()
    assert apply_deferred_tool_policy(registry, policy="all") == 0


@pytest.mark.asyncio
async def test_large_catalog_without_retrieval_match_skips_model(tmp_path):
    from test_deferred_tools import _NamedTool

    registry = _registry()
    for i in range(10):
        registry.register(_NamedTool(f"extra_{i}", "Additional capability"))
        registry.defer(f"extra_{i}")
    client = StubSystemOneClient()
    ctx = ToolContext(
        session_id="t",
        working_directory=tmp_path,
        tool_registry=registry,
        systemone=SystemOneSpec(enabled=True, tool_search_mode="rerank"),
        systemone_client=client,
    )
    result = await ToolSearchTool().execute({"query": "unmatchedzz"}, ctx)
    assert result.metadata["activated"] == []
    assert result.metadata["systemone"]["reason"] == "no_candidates"
    assert client.calls == []


@pytest.mark.asyncio
async def test_missing_live_key_retains_lexical_search(tmp_path):
    registry = _registry()
    registry.defer("web_fetch")
    client = StubSystemOneClient()
    ctx = ToolContext(
        session_id="t",
        working_directory=tmp_path,
        tool_registry=registry,
        systemone=SystemOneSpec(enabled=True, client="live", tool_search_mode="rerank"),
        systemone_client=client,
    )
    result = await ToolSearchTool().execute({"query": "web page"}, ctx)
    assert result.metadata["activated"] == ["web_fetch"]
    assert result.metadata["systemone"]["reason"] == "live_unavailable"
    assert client.calls == []


@pytest.mark.asyncio
async def test_timeout_retains_lexical_search(tmp_path):
    import asyncio

    class SlowClient:
        async def evaluate(self, state, questions):
            await asyncio.sleep(10)

    registry = _registry()
    registry.defer("web_fetch")
    ctx = ToolContext(
        session_id="t",
        working_directory=tmp_path,
        tool_registry=registry,
        systemone=SystemOneSpec(enabled=True, tool_search_mode="rerank", timeout_ms=1),
        systemone_client=SlowClient(),
    )
    result = await ToolSearchTool().execute({"query": "web page"}, ctx)
    assert result.metadata["activated"] == ["web_fetch"]
    assert result.metadata["systemone"]["status"] == "error"
