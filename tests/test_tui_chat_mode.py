"""Raw chat mode: toggle, isolated streaming, and speed metrics."""

from __future__ import annotations

import asyncio

import pytest

from superqode.app_main import SuperQodeApp
from superqode.providers.gateway.base import Message, StreamChunk, Usage


@pytest.fixture(autouse=True)
def _plain_is_busy(monkeypatch):
    # is_busy is a Textual reactive; replace it with a plain attribute so tests
    # can construct SuperQodeApp via __new__ without a running app.
    monkeypatch.setattr(SuperQodeApp, "is_busy", False, raising=False)


class _StubLog:
    def __init__(self):
        self.buf: list[str] = []

    def write(self, x):
        self.buf.append(getattr(x, "plain", str(x)))

    def add_info(self, t):
        self.buf.append(f"[info]{t}")

    def add_error(self, t):
        self.buf.append(f"[error]{t}")

    def add_user(self, t):
        self.buf.append(f"[user]{t}")

    def add_response_chunk(self, t):
        self.buf.append(f"[chunk]{t}")

    def write_final_response(self, t, agent="Assistant", **k):
        self.buf.append(f"[final:{agent}]{t}")

    @property
    def text(self):
        return "\n".join(self.buf)


class _Session:
    def __init__(self, connected=True):
        self.connected = connected
        self.provider = "ollama"
        self.model = "qwen3-coder"


class _PureMode:
    def __init__(self, connected=True):
        self.session = _Session(connected)


def _app(connected=True):
    app = SuperQodeApp.__new__(SuperQodeApp)
    app._chat_mode = False
    app._chat_history = None
    app._cancel_requested = False
    app.is_busy = False
    app._pure_mode = _PureMode(connected)
    app._call_ui = lambda func, *a: func(*a)
    app._update_terminal_title = lambda t: None
    # Animation helpers touch the live DOM; stub them for headless tests.
    app._start_thinking = lambda *a, **k: None
    app._stop_thinking = lambda *a, **k: None
    return app


def test_chat_cmd_toggles_mode():
    app = _app()
    log = _StubLog()
    SuperQodeApp._chat_cmd(app, "", log)
    assert app._chat_mode is True
    SuperQodeApp._chat_cmd(app, "", log)
    assert app._chat_mode is False
    SuperQodeApp._chat_cmd(app, "on", log)
    assert app._chat_mode is True
    SuperQodeApp._chat_cmd(app, "off", log)
    assert app._chat_mode is False


def test_chat_cmd_clear_resets_history():
    app = _app()
    app._chat_history = [Message(role="user", content="hi")]
    SuperQodeApp._chat_cmd(app, "clear", _StubLog())
    assert app._chat_history == []


def _fake_gateway(chunks):
    class _GW:
        def __init__(self, *a, **k):
            pass

        async def stream_completion(self, **kwargs):
            # The call must be isolated: no tools, just the user message(s).
            assert kwargs.get("tools") is None
            for c in chunks:
                yield c

    return _GW


def test_send_chat_message_streams_and_reports_metrics(monkeypatch):
    import superqode.providers.gateway.litellm_gateway as gw_mod

    chunks = [
        StreamChunk(content="Hel"),
        StreamChunk(content="lo!"),
        StreamChunk(content="", usage=Usage(completion_tokens=12)),
    ]
    monkeypatch.setattr(gw_mod, "LiteLLMGateway", _fake_gateway(chunks))

    app = _app()
    app._chat_history = []
    log = _StubLog()
    asyncio.run(SuperQodeApp._send_chat_message(app, "Say hi", log))

    # streamed chunks + a final response + a metrics line
    assert "[chunk]Hel" in log.buf
    assert any(s.startswith("[final:ollama/qwen3-coder]Hello!") for s in log.buf)
    assert any("tok/s" in s or "12 tok" in s for s in log.buf)
    # history captured both turns
    assert [m.role for m in app._chat_history] == ["user", "assistant"]
    assert app._chat_history[-1].content == "Hello!"
    assert app.is_busy is False


def test_send_chat_message_handles_empty_output(monkeypatch):
    import superqode.providers.gateway.litellm_gateway as gw_mod

    monkeypatch.setattr(gw_mod, "LiteLLMGateway", _fake_gateway([StreamChunk(content="")]))
    app = _app()
    app._chat_history = []
    log = _StubLog()
    asyncio.run(SuperQodeApp._send_chat_message(app, "think hard", log))
    assert any("no text" in s for s in log.buf)
    assert app.is_busy is False


def test_write_chat_stats_formats_line():
    app = _app()
    log = _StubLog()
    SuperQodeApp._write_chat_stats(app, log, 0.7, 42.0, 120, 3.6)
    line = log.buf[-1]
    assert "TTFT 0.70s" in line
    assert "42.0 tok/s" in line
    assert "120 tok" in line
