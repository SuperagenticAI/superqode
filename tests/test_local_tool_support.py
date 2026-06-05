"""Local model tool-support capability labels."""

from superqode.providers.local import LocalModel, estimate_tool_support, likely_supports_tools
from superqode.providers.local.tool_support import get_tool_capability_info


def test_gemma3_and_gemma4_are_tool_capable():
    for model_id in ("gemma3:27b-it", "gemma4:31b-mlx-bf16", "gemma-4-31b-it"):
        assert likely_supports_tools(model_id) is True
        info = get_tool_capability_info(model_id)
        assert info.supports_tools is True
        assert info.confidence == "heuristic"
        assert estimate_tool_support(LocalModel(id=model_id, name=model_id)) == "good"


def test_gemma2_stays_conservative():
    model_id = "gemma2:9b-it"

    assert likely_supports_tools(model_id) is False
    info = get_tool_capability_info(model_id)
    assert info.supports_tools is False
    assert info.confidence == "heuristic"
    assert estimate_tool_support(LocalModel(id=model_id, name=model_id)) == "none"


def test_base_gemma_is_unknown_not_false_no_tools():
    model_id = "gemma:latest"

    assert likely_supports_tools(model_id) is False
    info = get_tool_capability_info(model_id)
    assert info.supports_tools is False
    assert info.confidence == "unknown"
    assert estimate_tool_support(LocalModel(id=model_id, name=model_id)) == "unknown"


def test_provider_reported_tool_support_wins_for_local_model():
    model = LocalModel(id="custom-local-model", name="custom-local-model", supports_tools=True)

    assert estimate_tool_support(model) == "good"
