"""`local search`: find trusted models, their get-commands, and hardware fit."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from superqode.commands.local import local
from superqode.local.labs import search_hub_trusted as _real_search_hub_trusted
from superqode.local.matrix import search_models


@pytest.fixture(autouse=True)
def _offline_hub(monkeypatch):
    # Search now always consults the Hub for per-engine commands; keep tests
    # offline by default. Specific tests override this with their own models.
    import superqode.local.labs as labs

    monkeypatch.setattr(labs, "search_hub_trusted", lambda *a, **k: [])


def test_search_finds_qwen_with_commands():
    hits = search_models("qwen", tier="apple_64", inventory=[])
    assert hits, "expected qwen matches in the trusted catalog"
    names = " ".join(h.name.lower() for h in hits)
    assert "qwen" in names
    # Every hit carries at least one get-command with an engine label.
    for h in hits:
        assert h.commands
        for engine, command in h.commands:
            assert engine and command


def test_search_fit_depends_on_tier():
    # A 30B coder model is tuned for big tiers; it should not "fit" cpu.
    cpu_hits = {h.name: h.fits for h in search_models("qwen3-coder", tier="cpu", inventory=[])}
    big_hits = {
        h.name: h.fits for h in search_models("qwen3-coder", tier="apple_128", inventory=[])
    }
    big_model = "Qwen3-Coder 30B-A3B"
    assert cpu_hits.get(big_model) is False
    assert big_hits.get(big_model) is True


def test_search_marks_downloaded():
    from superqode.local.inventory import LocalModel

    inv = [LocalModel(model_id="ollama:qwen3.5:9b", source="ollama")]
    hits = search_models("qwen3.5 9b", tier="apple_64", inventory=inv)
    hit = next(h for h in hits if "9b" in h.name.lower())
    assert hit.downloaded_as is not None


def test_search_no_match_is_empty():
    assert search_models("zzz-not-a-model", tier="apple_64", inventory=[]) == []


def test_search_to_dict_round_trips():
    hit = search_models("glm", tier="apple_128", inventory=[])[0]
    d = hit.to_dict()
    assert d["name"] == hit.name
    assert "commands" in d and isinstance(d["commands"], list)
    assert all({"engine", "command"} <= set(c) for c in d["commands"])


def test_search_cli_renders_and_json():
    runner = CliRunner()
    text = runner.invoke(local, ["search", "qwen"])
    assert text.exit_code == 0
    assert "qwen" in text.output.lower()

    js = runner.invoke(local, ["search", "glm", "--json"])
    assert js.exit_code == 0
    assert '"results"' in js.output


def test_search_cli_no_match_points_to_labs():
    result = CliRunner().invoke(local, ["search", "zzz-nope"])
    assert result.exit_code == 0
    assert "local labs" in result.output


def test_memory_estimate_from_name():
    from superqode.local.matrix import estimate_model_memory_gb as est

    # 30B at 4bit ~17GB; same at bf16 ~60GB; FP8 ~31GB.
    assert 15 <= est("Qwen3-Coder 30B-A3B", quantized_default=True) <= 20
    assert 55 <= est("Qwen/Qwen3-Coder-30B-A3B-Instruct", quantized_default=False) <= 65
    assert 28 <= est("Qwen3-Coder-30B-FP8") <= 34
    # No parameter count in the name -> unknown.
    assert est("zai-org/GLM-4.5-Air") is None
    assert est("4bit-only-no-params") is None


def test_memory_fit_phrase_verdicts():
    from superqode.local.matrix import memory_fit_phrase as fit

    assert "likely fits" in fit(5.0, 16)
    assert "too large" in fit(30.0, 16)
    assert fit(None, 16) == "size unknown"
    assert fit(5.0, None) == "~5 GB"  # no RAM known -> size only


def test_search_hit_carries_estimate_in_json():
    from superqode.local.matrix import search_models

    hits = search_models("qwen3.5 9b", tier="apple_64", inventory=[])
    hit = next(h for h in hits if "9b" in h.name.lower())
    assert hit.est_memory_gb is not None
    assert "est_memory_gb" in hit.to_dict()


class _FakeHubModel:
    def __init__(self, id, downloads=0, gguf=False, mlx=False):
        self.id = id
        self.downloads = downloads
        self.is_gguf = gguf
        self.is_mlx = mlx


def test_augment_adds_mlx_and_gguf_commands_per_model():
    from superqode.local.matrix import augment_commands_with_hub

    hits = search_models("qwen3-coder", tier="apple_128", inventory=[])
    hub = [
        _FakeHubModel("mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit", 100, mlx=True),
        _FakeHubModel("unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF", 90, gguf=True),
    ]
    augment_commands_with_hub(hits, hub)
    hit = next(h for h in hits if h.name == "Qwen3-Coder 30B-A3B")
    engines = {e for e, _ in hit.commands}
    assert "ollama" in engines  # native, from the catalog
    assert "MLX" in engines  # hf download ...
    assert "llama.cpp" in engines  # llama-server -hf ...
    assert "LM Studio" in engines  # lms get ...
    cmds = " ".join(c for _, c in hit.commands)
    assert "hf download mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit" in cmds
    assert "llama-server -hf unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF" in cmds
    assert "lms get https://huggingface.co/unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF" in cmds
    # The convenience SuperQode alternative is recorded too.
    assert hit.hub_repo == "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit"


def test_search_cli_shows_all_engines(monkeypatch):
    import superqode.local.labs as labs

    monkeypatch.setattr(
        labs,
        "search_hub_trusted",
        lambda *a, **k: [
            _FakeHubModel("mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit", 100, mlx=True),
            _FakeHubModel("unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF", 90, gguf=True),
        ],
    )
    result = CliRunner().invoke(local, ["search", "qwen3-coder"])
    assert result.exit_code == 0
    assert "ollama pull" in result.output
    assert "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit" in result.output
    assert "unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF" in result.output


def test_search_hub_trusted_filters_to_vetted_orgs(monkeypatch):
    import superqode.providers.huggingface.fetch as fetch

    raw = [
        _FakeHubModel("Qwen/Qwen3-Coder-30B", 100),
        _FakeHubModel("randomuser/sketchy-merge", 999),  # not vetted -> dropped
        _FakeHubModel("unsloth/Qwen3-Coder-GGUF", 50, gguf=True),
        _FakeHubModel("mlx-community/Qwen3-Coder-4bit", 40, mlx=True),
    ]
    monkeypatch.setattr(fetch, "search_hub", lambda *a, **k: raw)
    out = _real_search_hub_trusted("qwen3-coder", limit=8)
    ids = [m.id for m in out]
    assert "randomuser/sketchy-merge" not in ids
    assert "Qwen/Qwen3-Coder-30B" in ids
    assert "unsloth/Qwen3-Coder-GGUF" in ids


def test_search_cli_hub_section(monkeypatch):
    import superqode.local.labs as labs

    monkeypatch.setattr(
        labs,
        "search_hub_trusted",
        lambda *a, **k: [
            _FakeHubModel("Qwen/Qwen3-Coder-30B-A3B-Instruct", 1348446),
            _FakeHubModel("unsloth/Qwen3-Coder-Next-GGUF", 1077346, gguf=True),
        ],
    )
    result = CliRunner().invoke(local, ["search", "qwen3-coder", "--hub"])
    assert result.exit_code == 0
    # Unmatched safetensors model appears in the "newer / other" Hub tail.
    assert "Hugging Face" in result.output
    assert "superqode models download Qwen/Qwen3-Coder-30B-A3B-Instruct" in result.output
    # The GGUF gets attached to a curated model as a per-engine command.
    assert "Qwen3-Coder-Next-GGUF" in result.output


def test_search_cli_hub_unavailable_is_graceful(monkeypatch):
    import superqode.local.labs as labs

    def _boom(*a, **k):
        raise RuntimeError("huggingface_hub is required")

    monkeypatch.setattr(labs, "search_hub_trusted", _boom)
    result = CliRunner().invoke(local, ["search", "qwen", "--hub"])
    assert result.exit_code == 0  # never crashes on a hub failure


def test_hub_mode_toggle_and_one_shot():
    from superqode.app_main import SuperQodeApp

    class _L:
        def add_info(self, t):
            pass

        def add_user(self, t):
            pass

        def write(self, x):
            pass

    app = SuperQodeApp.__new__(SuperQodeApp)
    app._hub_mode = False
    app._started = []
    app.run_worker = lambda coro: (app._started.append(coro), coro.close())

    SuperQodeApp._hub_cmd(app, "", _L())
    assert app._hub_mode is True  # :hub toggles on
    SuperQodeApp._hub_cmd(app, "off", _L())
    assert app._hub_mode is False  # :hub off
    SuperQodeApp._hub_cmd(app, "qwen3-coder", _L())
    assert app._hub_mode is False  # one-shot does not change mode
    assert len(app._started) == 1  # ...but schedules a search


def test_hub_mode_routes_typed_text_to_search(monkeypatch):
    from superqode.app_main import SuperQodeApp

    monkeypatch.setattr(SuperQodeApp, "is_busy", False, raising=False)

    class _L:
        def add_user(self, t):
            pass

    app = SuperQodeApp.__new__(SuperQodeApp)
    app._hub_mode = True
    app._started = []
    app.run_worker = lambda coro: (app._started.append(coro), coro.close())
    app._handle_agent_question_input = lambda t, log: False
    app._enqueue_message = lambda t: None

    SuperQodeApp._handle_message(app, "qwen3-coder", _L())
    assert len(app._started) == 1  # typed name went to model search, not the agent


def test_tui_local_search_renders():
    import asyncio

    from superqode.app_main import SuperQodeApp

    class _Log:
        def __init__(self):
            self.parts = []

        def add_info(self, t):
            self.parts.append(t)

        def add_error(self, t):
            self.parts.append("ERR:" + t)

        @property
        def text(self):
            return "\n".join(self.parts)

    app = SuperQodeApp.__new__(SuperQodeApp)
    app._call_ui = lambda f, *a: f(*a)
    app._show_command_output = lambda log, t, **k: log.parts.append(getattr(t, "plain", str(t)))
    log = _Log()
    asyncio.run(SuperQodeApp._local_search(app, "qwen3-coder", log))
    assert "Qwen3-Coder" in log.text
    assert "ollama pull" in log.text
    assert ":connect local" in log.text
