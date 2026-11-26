"""The TUI :factory subcommands share the CLI engine and keep the route commands."""
# ruff: noqa: F401, F811

from superqode.app.mixins.factory import FactoryMixin
from superqode.app.mixins.slash_commands import SlashCommandMixin
from test_factory_definition import project


class Log:
    def __init__(self):
        self.lines = []

    def add_error(self, text):
        self.lines.append(("error", text))

    def add_success(self, text):
        self.lines.append(("success", text))

    def add_info(self, text):
        self.lines.append(("info", text))


class Host(FactoryMixin):
    def __init__(self):
        self.shown, self.passthrough = [], []

    def _show_command_output(self, log, text):
        self.shown.append(text.plain)

    def _run_cli_passthrough(self, parts, log, label):
        self.passthrough.append(parts)

    def _factory(self):
        from superqode.session.factory import SoftwareFactory

        return SoftwareFactory(storage_dir=".superqode/sessions")

    def factory(self, args):
        log = Log()
        SlashCommandMixin._handle_factory(self, args, log)
        return log


def test_tui_factory_flow_status_trial_run_evidence_and_decide(project, monkeypatch):
    monkeypatch.chdir(project)
    host = Host()
    host.factory("")
    assert "Stages:" in host.shown[-1] and 'Next: :factory trial "<goal>"' in host.shown[-1]
    host.factory('trial "Fix the answer"')
    assert "⏸️ Queued" in host.shown[-1] and "no agent has run" in host.shown[-1]
    run = host.shown[-1].split("Queued ")[1].split(" ")[0]
    host.factory(f"run {run}")
    assert host.passthrough[-1] == ["factory", "worker", run, "--live"]
    host.factory(f"evidence {run}")
    assert "➖ never ran" in host.shown[-1]
    host.factory(f"decide {run}")
    assert "⛔ Release blocked" in host.shown[-1]
    host.factory("evidence outcomes")
    assert host.passthrough[-1] == ["factory", "evidence", "outcomes"]
    host.factory("check --application")
    assert host.passthrough[-1] == ["factory", "check", "--application"]
    host.factory('describe "We fix bugs" --model ollama/qwen3:8b')
    assert host.passthrough[-1][:3] == ["factory", "describe", "We fix bugs"]
    host.factory("workflows")
    shown = host.shown[-1]
    for name in ("kanban", "scrum", "xp", "lean", "build-test-deploy"):
        assert name in shown
    host.factory('describe "build test and deploy"')
    assert host.passthrough[-1][:3] == ["factory", "describe", "build test and deploy"]
    assert "--model" not in host.passthrough[-1]


def test_tui_init_creates_spec_and_route_commands_still_work(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".superqode").mkdir()
    host = Host()
    host.factory("")
    assert "No Factory in this project yet" in host.shown[-1]
    log = host.factory("init --template continuous-outcomes")
    assert log.lines[-1][0] == "success" and "continuous-outcomes" in log.lines[-1][1]
    log = host.factory("init")
    assert log.lines[-1][0] == "error" and "--force" in log.lines[-1][1]
    host.factory("routes")
    assert "no-subscription" in host.shown[-1]
    log = host.factory("init-policy --force --routes-only")
    assert log.lines[-1][0] == "success"
    host.factory("status")
    assert "route-only policy" in host.shown[-1]


def test_onboarding_model_setup_and_benchmarks_use_shared_cli():
    host = Host()
    for command in (
        "start",
        "models",
        "models --check-connections",
        "benchmark history",
        "demo check --execute",
        "draft show",
        "evidence summary work-example",
    ):
        host.factory(command)
        assert host.passthrough[-1] == ["factory", *command.split()]
    host.factory("help")
    assert ":factory start" in host.shown[-1]
    assert ":factory models" in host.shown[-1]


def test_onboarding_commands_have_discoverable_completion_descriptions():
    from superqode.command_registry import DEFAULT_COMMANDS

    commands = {item.command: item.description for item in DEFAULT_COMMANDS}
    for command in (
        ":factory start",
        ":factory models",
        ":factory benchmark history",
        ":factory demo",
        ":factory draft show",
        ":factory evidence summary",
    ):
        assert commands[command]
