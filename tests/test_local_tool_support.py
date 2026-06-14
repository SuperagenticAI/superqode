"""Local model tool-support capability labels."""

from superqode.providers.local import LocalModel, estimate_tool_support, likely_supports_tools
from superqode.providers.local.tool_support import (
    get_recommended_coding_models,
    get_tool_capability_info,
)


def test_gemma3_and_gemma4_are_tool_capable():
    for model_id in ("gemma3:27b-it", "gemma4:31b-mlx-bf16", "gemma-4-31b-it"):
        assert likely_supports_tools(model_id) is True
        info = get_tool_capability_info(model_id)
        assert info.supports_tools is True
        assert info.confidence == "heuristic"
        assert estimate_tool_support(LocalModel(id=model_id, name=model_id)) == "good"


def test_glm4_and_glm5_are_tool_capable():
    for model_id in ("glm-4.5-air", "THUDM/GLM-4.6", "zhipuai/glm-5"):
        assert likely_supports_tools(model_id) is True
        info = get_tool_capability_info(model_id)
        assert info.supports_tools is True
        assert info.confidence == "heuristic"
        assert info.recommended_params["num_ctx"] == 32768
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


def test_recommended_coding_models_stay_curated():
    recommendations = get_recommended_coding_models()
    ids = {row["model"] for row in recommendations}

    assert "llama3.2:8b" not in ids
    assert "llama3.3:70b" not in ids
    assert "deepseek-coder-v2:16b" not in ids
    assert {"glm-4.5-air", "qwen3.6:35b-a3b", "deepseek-v4-flash"} <= ids
    assert all("models.dev Labs" in row["notes"] for row in recommendations)
