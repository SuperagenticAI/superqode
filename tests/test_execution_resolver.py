"""Tests for role execution config resolution."""

from superqode.execution import ExecutionMode
from superqode.execution.modes import BYOKConfig
from superqode.execution.resolver import ExecutionResolver


def test_byok_resolution_infers_huggingface_from_hf_model_ref():
    resolver = ExecutionResolver()

    config = resolver.resolve_role(
        {
            "mode": "byok",
            "model": "hf.zai-org/GLM-5.2:fireworks-ai",
        },
        validate_env=False,
    )

    assert config.mode == ExecutionMode.BYOK
    assert isinstance(config.byok, BYOKConfig)
    assert config.byok.provider == "huggingface"
    assert config.byok.model == "zai-org/GLM-5.2:fireworks-ai"
