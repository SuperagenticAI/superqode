"""MLX/llama.cpp connect routing: ask before starting one-model servers."""

from __future__ import annotations

import pytest

from superqode.app_main import SuperQodeApp


@pytest.fixture(autouse=True)
def _plain_is_busy(monkeypatch):
    monkeypatch.setattr(SuperQodeApp, "is_busy", False, raising=False)


class _Log:
    def __init__(self):
        self.messages = []

    def add_info(self, t):
        self.messages.append(("info", t))

    def add_error(self, t):
        self.messages.append(("error", t))

    def add_system(self, t):
        self.messages.append(("system", t))

    def write(self, x):
        self.messages.append(("write", getattr(x, "plain", str(x))))

    @property
    def text(self):
        return "\n".join(str(item[1]) for item in self.messages)


def _app(monkeypatch, running: bool):
    import superqode.local.servers as servers

    class _Mgr:
        def status(self, engine):
            return {"running": running}

    monkeypatch.setattr(servers, "get_manager", lambda: _Mgr())

    app = SuperQodeApp.__new__(SuperQodeApp)
    app._started = []
    app._connected = []
    app.run_worker = lambda coro: app._started.append(coro)
    app._connect_byok_mode = lambda p, m, log: app._connected.append((p, m))
    return app


def test_mlx_with_server_down_prompts_before_starting(monkeypatch):
    app = _app(monkeypatch, running=False)
    log = _Log()
    SuperQodeApp._connect_local_mode(app, "mlx", "mlx-community/phi-2", log)
    assert app._started == []
    assert app._connected == []
    assert app._awaiting_local_connect_start["engine"] == "mlx"
    assert "mlx_lm.server --model mlx-community/phi-2" in log.text
    assert ":local serve mlx --model mlx-community/phi-2" in log.text


def test_mlx_confirmed_start_schedules_worker(monkeypatch):
    app = _app(monkeypatch, running=False)
    log = _Log()
    SuperQodeApp._connect_local_mode(app, "mlx", "mlx-community/phi-2", log)
    assert SuperQodeApp._handle_local_connect_start_input(app, "", log) is True
    assert len(app._started) == 1
    assert app._connected == []
    app._started[0].close()


def test_mlx_with_server_running_connects_directly(monkeypatch):
    app = _app(monkeypatch, running=True)
    SuperQodeApp._connect_local_mode(app, "mlx", "mlx-community/phi-2", _Log())
    assert app._started == []
    assert app._connected == [("mlx", "mlx-community/phi-2")]


def test_ollama_always_connects_directly(monkeypatch):
    # Ollama is an always-on background server, never auto-started here.
    app = _app(monkeypatch, running=False)
    SuperQodeApp._connect_local_mode(app, "ollama", "qwen3:8b", _Log())
    assert app._started == []
    assert app._connected == [("ollama", "qwen3:8b")]
