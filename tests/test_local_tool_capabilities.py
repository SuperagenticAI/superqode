"""Tool-capability resolution must come from the runtime, not a name list.

A hardcoded family allowlist is stale the day a new model ships, and the
failure mode is silent: the harness sends no tools and the model answers by
describing the command it would have run instead of running it.
"""

import pytest

from superqode.agent.loop import _model_supports_tools, _should_send_tools
from superqode.providers.local import capabilities


@pytest.fixture(autouse=True)
def _clear_capability_cache():
    capabilities.clear_cache()
    yield
    capabilities.clear_cache()


def _declare(monkeypatch, capability_list):
    """Pretend Ollama's /api/show reports ``capability_list``."""

    def fake_show(model_id):
        return "tools" in capability_list if capability_list else None

    monkeypatch.setattr(capabilities, "_ollama_declares_tools", fake_show)


def test_model_absent_from_every_list_still_gets_tools(monkeypatch):
    """The regression: muse-glimmer is in no allowlist and no registry, but
    Ollama declares tool support, so the harness must send tools."""
    _declare(monkeypatch, ["completion", "vision", "tools", "thinking"])

    assert _model_supports_tools("ollama", "muse-glimmer:30b-mlx") is True
    assert (
        _should_send_tools("ollama", "muse-glimmer:30b-mlx", "how many files?", [{"t": 1}]) is True
    )


def test_runtime_denial_is_respected(monkeypatch):
    """An explicit "no tools" from the runtime is the one thing that disables
    them, so embedding models are not handed a toolbox."""
    _declare(monkeypatch, ["completion"])

    assert _model_supports_tools("ollama", "nomic-embed-text:latest") is False


def test_unknown_model_defaults_to_tools_on(monkeypatch):
    """When nothing can answer, prefer a loud failure over a silent downgrade."""
    monkeypatch.setattr(capabilities, "_ollama_declares_tools", lambda model_id: None)

    assert _model_supports_tools("ollama", "some-model-released-next-year:70b") is True


def test_passthrough_providers_do_not_consult_model_names():
    """These runtimes forward tool definitions verbatim, so support is a
    property of the server, not of whatever model name it happens to serve."""
    for provider in ("ds4", "vllm", "sglang", "tgi", "lmstudio"):
        assert _model_supports_tools(provider, "anything/at-all:v9") is True


def test_capability_probe_is_cached(monkeypatch):
    """The probe sits on the turn path; it must not re-hit the runtime."""
    calls = []

    def counting_probe(model_id):
        calls.append(model_id)
        return True

    monkeypatch.setattr(capabilities, "_ollama_declares_tools", counting_probe)

    for _ in range(5):
        capabilities.declared_tool_support("ollama", "muse-glimmer:30b-mlx")

    assert len(calls) == 1


def test_probe_failure_does_not_raise(monkeypatch):
    """A runtime that is down must not take the turn down with it."""

    def boom(model_id):
        raise OSError("connection refused")

    monkeypatch.setattr(capabilities, "_ollama_declares_tools", boom)

    # Falls through to the local default rather than propagating.
    assert _model_supports_tools("ollama", "muse-glimmer:30b-mlx") is True
