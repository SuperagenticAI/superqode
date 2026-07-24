"""Tests for the native ``:agy`` command surface."""

from __future__ import annotations

import asyncio
import subprocess
from types import SimpleNamespace

from superqode.app_main import SuperQodeApp


class _Log:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.output = ""

    def add_info(self, value) -> None:
        self.messages.append(("info", str(value)))

    def add_success(self, value) -> None:
        self.messages.append(("success", str(value)))

    def add_error(self, value) -> None:
        self.messages.append(("error", str(value)))

    def write(self, value) -> None:
        self.output += str(value)


def test_agy_root_subcommands_cover_installed_cli_surface():
    values = {
        candidate.value for candidate in SuperQodeApp._agy_subcommand_completion_candidates(":agy ")
    }

    assert {
        ":agy connect",
        ":agy status",
        ":agy agents",
        ":agy models",
        ":agy changelog",
        ":agy plugin",
        ":agy update",
        ":agy install",
        ":agy launch",
        ":agy continue",
        ":agy resume",
    } <= values


def test_agy_plugin_and_effort_values_are_contextually_completed():
    app = SuperQodeApp()

    plugin_values = {
        candidate.value for candidate in app._prompt_completion_candidates_for(":agy plugin ")
    }
    assert plugin_values == {
        ":agy plugin list",
        ":agy plugin import",
        ":agy plugin install",
        ":agy plugin uninstall",
        ":agy plugin enable",
        ":agy plugin disable",
        ":agy plugin validate",
        ":agy plugin link",
        ":agy plugin help",
    }
    assert app._suggest_prompt_completion(":agy effort h") == ":agy effort high"


def test_agy_native_routes_are_explicit_argv_not_shell_text():
    calls = []

    class Stub:
        def _run_agy_native(self, command, _log, label, **kwargs):
            calls.append((command, label, kwargs))

        def _show_agy_plugin_help(self, _log):
            calls.append(("help",))

    log = _Log()
    stub = Stub()

    SuperQodeApp._agy_plugin_cmd(stub, "list", log)
    SuperQodeApp._agy_plugin_cmd(stub, "import gemini", log)
    SuperQodeApp._agy_plugin_cmd(stub, 'install "tools pack@marketplace"', log)
    SuperQodeApp._agy_plugin_cmd(stub, "link marketplace target", log)

    assert [call[0] for call in calls] == [
        ["plugin", "list"],
        ["plugin", "import", "gemini"],
        ["plugin", "install", "tools pack@marketplace"],
        ["plugin", "link", "marketplace", "target"],
    ]


def test_agy_install_rejects_unknown_flags():
    calls = []

    class Stub:
        def _run_agy_native(self, *args, **kwargs):
            calls.append((args, kwargs))

    log = _Log()
    SuperQodeApp._agy_install_cmd(Stub(), "--dangerously-skip-permissions", log)

    assert calls == []
    assert any("Unsupported" in message for kind, message in log.messages if kind == "error")


def test_agy_launch_refuses_permission_bypass():
    log = _Log()

    SuperQodeApp._show_agy_launch(
        SimpleNamespace(),
        log,
        "--dangerously-skip-permissions",
    )

    assert "bypass all agy permissions" in log.messages[0][1]
    assert log.output == ""


def test_agy_cli_runner_uses_binary_argv_and_no_stdin(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, stdout="model-a\n", stderr="")

    monkeypatch.setattr("superqode.app.mixins.commands_impl.shutil.which", lambda name: "/opt/agy")
    monkeypatch.setattr("superqode.app.mixins.commands_impl.subprocess.run", fake_run)
    monkeypatch.chdir(tmp_path)
    log = _Log()

    asyncio.run(
        SuperQodeApp._agy_cli_cmd(
            SimpleNamespace(),
            ["models"],
            log,
            "Antigravity models",
        )
    )

    assert captured["command"] == ["/opt/agy", "models"]
    assert "shell" not in captured["kwargs"]
    assert captured["kwargs"]["stdin"] is subprocess.DEVNULL
    assert captured["kwargs"]["cwd"] == tmp_path
    assert "model-a" in log.output


def test_bare_agy_shows_help_without_running_account_commands():
    calls = []

    class Stub:
        def _show_agy_help(self, _log):
            calls.append("help")

    SuperQodeApp._agy_cmd(Stub(), "", _Log())

    assert calls == ["help"]


def test_colon_agy_dispatches_to_native_namespace_not_route_alias():
    calls = []

    class Stub:
        _acp_client = None

        def _record_ex_command(self, *_args):
            pass

        def _agy_cmd(self, args, _log):
            calls.append(("agy", args))

        def _antigravity_cmd(self, args, _log):
            calls.append(("antigravity", args))

        def set_timer(self, *_args, **_kwargs):
            pass

        def _ensure_input_focus(self):
            pass

    SuperQodeApp._handle_command(Stub(), ":agy models", _Log())

    assert calls == [("agy", "models")]
