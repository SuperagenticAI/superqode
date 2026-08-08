"""Regression coverage for Prime Agent's native Python TUI route."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from superqode.app.mixins.connect import ConnectMixin
from superqode.app.mixins.slash_commands import SlashCommandMixin
from superqode.providers.prime_agent import PrimeLaunchOptions


class _Log:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.infos: list[str] = []
        self.successes: list[str] = []

    def add_error(self, message: str) -> None:
        self.errors.append(str(message))

    def add_info(self, message: str) -> None:
        self.infos.append(str(message))

    def add_success(self, message: str) -> None:
        self.successes.append(str(message))


class _Pure:
    def __init__(self) -> None:
        self.session = SimpleNamespace(connected=False)
        self._harness_spec = None
        self.spec = None
        self.connection = None

    def set_harness(self, spec) -> None:
        self.spec = spec
        self._harness_spec = spec

    def _resolve_harness_route(self):
        return "", ""

    def connect(self, **kwargs) -> None:
        self.connection = kwargs
        self.session.connected = True


class _ConnectHarness(ConnectMixin):
    def __init__(self) -> None:
        self._prime_options = PrimeLaunchOptions(
            goal="ship it",
            autonomous=True,
            gates=("pytest -q",),
            max_depth=3,
        )
        self._acp_client = None
        self.current_mode = "home"
        self.current_agent = ""
        self.current_provider = ""
        self.current_model = ""

    def _prime_opts(self):
        return self._prime_options

    def _prime_set_opts(self, **changes):
        self._prime_options = replace(self._prime_options, **changes)
        return self._prime_options

    def _install_pure_permission_bridge(self, pure, log) -> None:
        return None

    def query_one(self, *args, **kwargs):
        raise LookupError("widgets are not mounted in this unit test")


def test_subscription_connect_uses_python_harness_and_keeps_launch_settings(monkeypatch):
    from superqode.providers import prime_agent

    monkeypatch.setattr(prime_agent, "is_installed", lambda: True)
    monkeypatch.setenv("SUPERQODE_HARNESS", "core")
    app = _ConnectHarness()
    pure = _Pure()
    log = _Log()

    connected = app._connect_prime_rpc(
        "github-copilot/gpt-4.1",
        log,
        pure=pure,
    )

    assert connected is True
    assert pure.spec.runtime.backend == "prime-agent"
    config = pure.spec.runtime.config["prime_agent"]
    assert config["args"] == [
        "--goal",
        "ship it",
        "--autonomous",
        "--autonomous-gate",
        "pytest -q",
    ]
    assert config["env"] == {"RLM_MAX_DEPTH": "3"}
    assert pure.connection["provider"] == "github-copilot"
    assert pure.connection["model"] == "gpt-4.1"
    assert "prime-agent-python-client" in log.successes[0]
    assert ":connect acp prime-agent" in log.infos[0]


def test_startup_harness_auto_connects_before_first_prompt(monkeypatch):
    pure = _Pure()
    pure._harness_spec = SimpleNamespace(runtime=SimpleNamespace(backend="prime-agent"))

    class _StartupHarness(SlashCommandMixin):
        def __init__(self) -> None:
            self._pure_mode = pure
            self.calls = []

        def _connect_prime_rpc(self, selector, log, **kwargs):
            self.calls.append((selector, kwargs))
            pure.session.connected = True
            return True

    monkeypatch.setenv("SUPERQODE_HARNESS", "prime-agent.yaml")
    app = _StartupHarness()

    assert app._auto_connect_configured_prime_harness(_Log()) is True
    assert app.calls == [("", {"pure": pure, "select_default": False})]
    assert pure.session.connected is True
