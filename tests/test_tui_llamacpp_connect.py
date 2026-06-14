"""llama.cpp (provider id 'llamacpp') lists from its OpenAI-compatible endpoint."""

from __future__ import annotations

import asyncio

import pytest

import superqode.local.bench as bench
from superqode.app_main import SuperQodeApp


class _Log:
    def __init__(self):
        self.msgs = []

    def add_info(self, t):
        self.msgs.append(("info", t))

    def add_error(self, t):
        self.msgs.append(("error", t))

    def write(self, x):
        self.msgs.append(("write", getattr(x, "plain", str(x))))

    @property
    def text(self):
        return "\n".join(m[1] for m in self.msgs)


def _app():
    app = SuperQodeApp.__new__(SuperQodeApp)
    app._reopened = False
    app._show_local_provider_picker = lambda log: setattr(app, "_reopened", True)
    app._picker_link_style = lambda style, n: style
    app.set_timer = lambda *a, **k: None
    app._ensure_input_focus = lambda: None
    return app


def test_llamacpp_server_down_reopens_picker_no_hang(monkeypatch):
    monkeypatch.setattr(bench, "list_endpoint_models", lambda *a, **k: [])
    app = _app()
    log = _Log()
    asyncio.run(SuperQodeApp._show_openai_compatible_models(app, "llamacpp", log))
    assert app._reopened is True
    assert getattr(app, "_awaiting_local_model", None) in (None, False)
    assert "llama-server" in log.text  # actionable guidance, not "not supported"


def test_llamacpp_server_up_lists_models_and_arms_selection(monkeypatch):
    monkeypatch.setattr(
        bench, "list_endpoint_models", lambda *a, **k: ["my-gguf-model", "nomic-embed-text"]
    )
    app = _app()
    log = _Log()
    asyncio.run(SuperQodeApp._show_openai_compatible_models(app, "llamacpp", log))
    # embedding model filtered out
    assert app._local_model_list == ["my-gguf-model"]
    assert app._awaiting_local_model is True
    assert app._local_selected_provider == "llamacpp"
    assert app._reopened is False
