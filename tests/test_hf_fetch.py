"""Tests for Hugging Face Hub search + download engine (mocked, no network)."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass

import pytest

from superqode.providers.huggingface import fetch


@dataclass
class _FakeModelInfo:
    id: str
    downloads: int = 0
    likes: int = 0
    library_name: str = ""
    gated: bool = False
    tags: list = None
    pipeline_tag: str = ""


@dataclass
class _FakeDryRun:
    file_size: int
    filename: str
    is_cached: bool = False
    will_download: bool = True


class _FakeHfApi:
    """Stand-in for huggingface_hub.HfApi."""

    _models: list = []
    _repo_files: list = []
    last_kwargs: dict = {}

    def list_models(self, **kwargs):
        _FakeHfApi.last_kwargs = kwargs
        return list(_FakeHfApi._models)

    def list_repo_files(self, repo_id, token=None):
        return list(_FakeHfApi._repo_files)


@pytest.fixture
def fake_hub(monkeypatch):
    """Inject a fake huggingface_hub module surface used by fetch.py."""
    mod = types.ModuleType("huggingface_hub")
    mod.HfApi = _FakeHfApi
    mod.snapshot_download = lambda *a, **k: []
    mod.hf_hub_download = lambda *a, **k: "/tmp/fake"
    mod.scan_cache_dir = lambda: None  # tests override via monkeypatch.setattr
    monkeypatch.setitem(sys.modules, "huggingface_hub", mod)
    _FakeHfApi._models = []
    _FakeHfApi._repo_files = []
    return mod


def test_search_hub_maps_fields_and_filters_gguf(fake_hub):
    _FakeHfApi._models = [
        _FakeModelInfo("unsloth/Qwen3-GGUF", downloads=1000, likes=5, library_name="gguf", tags=["gguf"]),
    ]
    out = fetch.search_hub("qwen3", kind="gguf", limit=5)
    assert len(out) == 1
    m = out[0]
    assert m.id == "unsloth/Qwen3-GGUF"
    assert m.downloads == 1000 and m.likes == 5
    assert m.is_gguf is True
    # gguf kind sets the filter; pipeline_tag not used.
    assert _FakeHfApi.last_kwargs.get("filter") == "gguf"


def test_search_hub_mlx_uses_author(fake_hub):
    _FakeHfApi._models = [_FakeModelInfo("mlx-community/Qwen3-4bit", tags=["mlx"])]
    out = fetch.search_hub("qwen", kind="mlx")
    assert out[0].is_mlx is True
    assert _FakeHfApi.last_kwargs.get("author") == "mlx-community"


def test_search_hub_default_text_generation(fake_hub):
    _FakeHfApi._models = []
    fetch.search_hub("foo")
    assert _FakeHfApi.last_kwargs.get("pipeline_tag") == "text-generation"


def test_estimate_size_uses_file_size_fields(fake_hub, monkeypatch):
    infos = [
        _FakeDryRun(file_size=5_000_000_000, filename="a.gguf", will_download=True),
        _FakeDryRun(file_size=1_000_000_000, filename="b.bin", is_cached=True, will_download=False),
    ]
    monkeypatch.setattr(fake_hub, "snapshot_download", lambda *a, **k: infos)
    est = fetch.estimate_size("repo/x")
    assert est is not None
    assert est.total_bytes == 6_000_000_000
    assert est.cached_bytes == 1_000_000_000
    assert est.to_download_bytes == 5_000_000_000
    assert est.file_count == 2


def test_estimate_size_handles_no_dry_run(fake_hub, monkeypatch):
    def _no_dry_run(*a, **k):
        raise TypeError("dry_run not supported")

    monkeypatch.setattr(fake_hub, "snapshot_download", _no_dry_run)
    assert fetch.estimate_size("repo/x") is None


def test_pick_gguf_file_matches_quant(fake_hub):
    _FakeHfApi._repo_files = ["model-Q8_0.gguf", "model-Q4_K_M.gguf", "README.md"]
    assert fetch.pick_gguf_file("r", "Q4_K_M") == "model-Q4_K_M.gguf"
    # No quant match -> first gguf.
    assert fetch.pick_gguf_file("r", "Q2_K") == "model-Q8_0.gguf"


def test_pick_gguf_file_none_when_no_gguf(fake_hub):
    _FakeHfApi._repo_files = ["config.json", "model.safetensors"]
    assert fetch.pick_gguf_file("r", "Q4_K_M") is None


def test_detect_target(fake_hub):
    # mlx-community prefix -> mlx (no network needed).
    assert fetch.detect_target(None, "mlx-community/Qwen3-4bit") == "mlx"
    # repo with gguf files -> ollama.
    _FakeHfApi._repo_files = ["m-Q4_K_M.gguf"]
    assert fetch.detect_target(None, "someone/Model-GGUF") == "ollama"
    # plain repo -> transformers.
    _FakeHfApi._repo_files = ["config.json"]
    assert fetch.detect_target(None, "meta/Llama") == "transformers"


def test_hubmodel_capability_flags():
    assert fetch.HubModel(id="mlx-community/x").is_mlx is True
    assert fetch.HubModel(id="a/b", tags=["gguf"]).is_gguf is True
    assert fetch.HubModel(id="a/b", library="gguf").is_gguf is True
    assert fetch.HubModel(id="a/b").is_gguf is False


def test_not_installed_raises(monkeypatch):
    # Simulate huggingface_hub missing.
    monkeypatch.setitem(sys.modules, "huggingface_hub", None)
    with pytest.raises(fetch.HFNotInstalled):
        fetch.search_hub("x")


# --- Phase 2: cache mgmt + MLX convert ---------------------------------------

def test_mlx_allow_patterns_present():
    assert "*.safetensors" in fetch.MLX_ALLOW_PATTERNS
    assert any("gguf" in p.lower() for p in fetch.MLX_ALLOW_PATTERNS) is False  # never pulls GGUF


def test_scan_cache_maps_repos(fake_hub, monkeypatch):
    class _Rev:
        commit_hash = "abc"
    class _Repo:
        repo_id = "acme/model"
        size_on_disk = 5_000_000_000
        nb_files = 7
        last_accessed = 1700000000.0
        repo_path = "/cache/acme"
        revisions = [_Rev()]
    class _Info:
        repos = [_Repo()]
    monkeypatch.setattr(fake_hub, "scan_cache_dir", lambda: _Info())
    repos = fetch.scan_cache()
    assert len(repos) == 1
    assert repos[0].repo_id == "acme/model"
    assert repos[0].size_display == "4.7GB"


def test_delete_cached_matches_pattern(fake_hub, monkeypatch):
    deleted = {}
    class _Strategy:
        def execute(self_inner):
            deleted["done"] = True
    class _Rev:
        commit_hash = "h1"
    class _Repo:
        repo_id = "junk/model-x"
        size_on_disk = 2_000_000_000
        revisions = [_Rev()]
    class _Info:
        repos = [_Repo()]
        def delete_revisions(self_inner, *hashes):
            deleted["hashes"] = hashes
            return _Strategy()
    monkeypatch.setattr(fake_hub, "scan_cache_dir", lambda: _Info())
    count, freed = fetch.delete_cached("junk")
    assert count == 1 and freed == 2_000_000_000
    assert deleted.get("done") and deleted["hashes"] == ("h1",)


def test_delete_cached_no_match(fake_hub, monkeypatch):
    class _Info:
        repos = []
    monkeypatch.setattr(fake_hub, "scan_cache_dir", lambda: _Info())
    assert fetch.delete_cached("nope") == (0, 0)


def test_convert_unavailable_without_mlx(monkeypatch):
    import sys
    from superqode.providers.huggingface import convert as conv
    monkeypatch.setitem(sys.modules, "mlx_lm", None)
    import pytest as _pytest
    with _pytest.raises(conv.MlxConvertUnavailable):
        conv.convert_to_mlx("google/gemma-4-31b-it")
