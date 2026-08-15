import pytest

from superqode.harness import (
    DEFAULT_HARNESS_ID,
    get_model_family_route,
    list_harnesses,
    optional_harnesses,
    recommended_harnesses,
    resolve_harness,
)


def test_catalogue_has_core_default_and_preserved_workbench(tmp_path):
    entries = {entry.id: entry for entry in list_harnesses(tmp_path)}

    assert DEFAULT_HARNESS_ID == "core"
    assert entries["core"].default is True
    assert entries["core"].tools == ("read", "write", "edit", "bash")
    assert entries["workbench"].default is False
    assert "patch" in entries["workbench"].tools
    assert len(entries["workbench"].tools) > len(entries["core"].tools)


def test_catalogue_resolves_compatibility_aliases(tmp_path):
    assert resolve_harness("minimal", root=tmp_path).id == "core"
    assert resolve_harness("native", root=tmp_path).id == "workbench"
    assert resolve_harness("coding", root=tmp_path).id == "workbench"


def test_catalogue_exposes_templates_as_directly_runnable_harnesses(tmp_path):
    entries = {entry.id: entry for entry in list_harnesses(tmp_path)}

    assert entries["kimi-coding"].category == "model-family"
    assert entries["kimi-coding"].provider == "moonshot"
    assert entries["kimi-coding"].model == "kimi-k3"
    assert entries["kimi-coding"].deprecated is False
    assert entries["kimi-k3-coding"].deprecated is True
    assert entries["qwen-coding"].source == "built-in-template"


def test_recommended_catalogue_hides_pinned_and_specialized_presets(tmp_path):
    complete = {entry.id: entry for entry in list_harnesses(tmp_path)}
    recommended = {entry.id: entry for entry in recommended_harnesses(tmp_path)}

    assert complete["core"].catalog_tier == "recommended"
    assert complete["kimi-coding"].catalog_tier == "recommended"
    assert complete["kimi-k3-coding"].catalog_tier == "compatibility"
    assert complete["benchmark-coding"].catalog_tier == "specialized"
    assert {"core", "workbench", "no-tool", "kimi-coding"} <= recommended.keys()
    assert "kimi-k3-coding" not in recommended
    assert "gemma4-coding" not in recommended
    assert "benchmark-coding" not in recommended

    # Visibility never changes direct resolution for reproducible configurations.
    assert resolve_harness("kimi-k3-coding", root=tmp_path).id == "kimi-k3-coding"


def test_optional_catalogue_contains_tau_without_main_or_acp_harnesses(tmp_path):
    optional = {entry.id: entry for entry in optional_harnesses(tmp_path)}

    assert list(optional) == ["tau", "deepseek-harness", "deepagents"]
    assert optional["tau"].source == "optional:tau"
    assert optional["deepseek-harness"].source == "optional:deepseek-harness"
    assert optional["deepagents"].source == "optional:deepagents"
    assert "core" not in optional
    assert "copilot" not in optional


def test_kimi_family_route_is_curated_and_versioned_preset_stays_pinned(tmp_path):
    route = get_model_family_route("kimi")
    maintained = resolve_harness("kimi-coding", root=tmp_path)
    pinned = resolve_harness("kimi-k3-coding", root=tmp_path)

    assert route.target() == "moonshot/kimi-k3"
    assert route.target("fast") == "moonshot/kimi-k2.7-code-highspeed"
    assert maintained.spec.metadata["route"] == "kimi"
    assert maintained.spec.metadata["channel"] == "stable"
    assert pinned.spec.model_policy.primary == "moonshot/kimi-k3"


def test_unknown_harness_suggests_close_catalogue_match(tmp_path):
    with pytest.raises(ValueError, match="Did you mean.*kimi-k3-coding"):
        resolve_harness("kmi-k3-coding", root=tmp_path)


def test_deepagents_resolves_by_id_and_alias_without_the_package_installed(tmp_path):
    """A missing optional dependency is a setup hint, never a resolution error.

    The entry has to stay browsable so the Hub can tell the user how to get it.
    """
    entry = resolve_harness("deepagents", root=tmp_path)

    assert entry.id == "deepagents"
    assert entry.runtime == "deepagents"
    assert entry.source == "optional:deepagents"
    assert resolve_harness("deep-agents", root=tmp_path).id == "deepagents"
    assert resolve_harness("langchain-deepagents", root=tmp_path).id == "deepagents"
    if not entry.available:
        assert entry.issue
