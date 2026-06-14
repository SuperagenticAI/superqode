"""MLX/llama.cpp connect routing: start the one-model server before connecting."""

from __future__ import annotations

import pytest

from superqode.app_main import SuperQodeApp


@pytest.fixture(autouse=True)
def _plain_is_busy(monkeypatch):
    monkeypatch.setattr(SuperQodeApp, "is_busy", False, raising=False)


class _Log:
    def add_info(self, t): pass
    def add_error(self, t): pass
    def add_system(self, t): pass
    def write(self, x): pass


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


def test_mlx_with_server_down_starts_server_first(monkeypatch):
    app = _app(monkeypatch, running=False)
    SuperQodeApp._connect_local_mode(app, "mlx", "mlx-community/phi-2", _Log())
    # Routed to the start-then-connect worker, NOT a bare connect.
    assert len(app._started) == 1
    assert app._connected == []
    # close the un-awaited coroutine to avoid a warning
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
