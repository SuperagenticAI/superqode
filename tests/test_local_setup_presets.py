"""Memory presets reuse fitting artifacts and retain honest evidence labels."""

from superqode.local.context_contract import choose_contract
from superqode.local.hardware import HardwareProfile
from superqode.local.presets import setup_presets


def choices(hw, installed=False):
    return [
        {
            "id": model,
            "model": model,
            "engine": "ollama",
            "name": model,
            "installed": installed,
            "preset": "running" if installed else "suggested",
            "suggested_context": 8192,
            "evaluation_status": "catalog-verified",
            "fit": choose_contract(model, hw).fit,
        }
        for model in ("qwen3.5:4b", "qwen3.5:9b", "qwen3.6:27b", "qwen3-coder-next:q4_K_M")
    ]


def mac(memory):
    return HardwareProfile(platform="darwin", is_apple_silicon=True, unified_memory_gb=memory)


def test_small_mac_gets_fitting_distinct_contracts_without_oversized_moe():
    presets = setup_presets(choices(mac(16)), mac(16))
    assert len({p["choice"]["id"] for p in presets}) == 3
    assert all(p["choice"]["fit"]["rating"] == "Fits" for p in presets)
    assert all("coder-next" not in p["choice"]["model"] for p in presets)
    assert presets[0]["choice"]["suggested_context"] <= 4096
    assert presets[0]["choice"]["max_tokens"] <= 1024


def test_installed_gemma_is_reused_before_suggesting_a_new_larger_download():
    hw = mac(64)
    rows = choices(hw)
    rows.append(
        {
            "id": "local-gemma",
            "engine": "lmstudio",
            "model": "my-gemma",
            "installed": True,
            "preset": "running",
            "suggested_context": 8192,
            "fit": {"weights_gb": 4.5},
            "metadata": {"size_bytes": int(4.5 * 1024**3)},
        }
    )
    presets = setup_presets(rows, hw)
    assert all(p["choice"]["model"] == "my-gemma" for p in presets)
    assert all(p["choice"]["installed"] for p in presets)


def test_unknown_and_too_large_artifacts_never_become_automatic_presets():
    hw = mac(8)
    rows = choices(hw)
    rows.append(
        {"id": "unknown", "model": "mystery", "engine": "ollama", "fit": {"weights_gb": None}}
    )
    assert all(p["choice"] is None for p in setup_presets(rows, hw))


def test_longer_context_does_not_inherit_short_context_tested_label():
    hw = mac(64)
    row = choices(hw)[0]
    row["evaluation_status"] = "tested"
    presets = setup_presets([row], hw)
    assert presets[0]["choice"]["evaluation_status"] == "tested"
    assert presets[-1]["choice"]["evaluation_status"] == "catalog-verified"
