"""An explicit Codex connection must execute and display the Codex harness."""

from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from superqode.agent.loop import AgentResponse
from superqode.app_main import SuperQodeApp
from superqode.harness.events import HarnessEvent
from superqode.main import cli_main
from superqode.pure_mode import PureMode
from superqode.widgets.sidebar_panels import HarnessPanel


@pytest.fixture
def project_harness(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPERQODE_RUNTIME", "builtin")
    path = tmp_path / "harness.yaml"
    path.write_text(
        "name: project-coder\nruntime:\n  backend: builtin\n"
        "model_policy:\n  primary: anthropic/project-model\n"
    )
    monkeypatch.setenv("SUPERQODE_HARNESS", str(path))
    return path


class Runtime:
    def __init__(self, config):
        self.config = config
        self.prompts = []

    async def run(self, prompt):
        self.prompts.append(prompt)
        return AgentResponse(
            content="native answer",
            messages=[],
            tool_calls_made=0,
            iterations=1,
            stopped_reason="complete",
        )

    async def run_harness_events(self, prompt):
        self.prompts.append(prompt)
        yield HarnessEvent(type="model_delta", data={"text": "native stream"})

    def cancel(self):
        pass


@pytest.fixture
def runtimes(monkeypatch):
    created = []

    def create(name, **kwargs):
        runtime = Runtime(kwargs["config"])
        created.append((name, runtime))
        return runtime

    monkeypatch.setattr("superqode.pure_mode.create_runtime", create)
    return created


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime_name", ["codex-cli", "codex-sdk"])
async def test_codex_startup_ignores_saved_harness_and_executes_native(
    project_harness, runtimes, runtime_name
):
    original = project_harness.read_bytes()
    pure = PureMode(runtime=runtime_name)
    pure.connect("openai", "", working_directory=project_harness.parent)
    assert pure._harness_spec is None
    assert pure._harness_definition is None
    assert pure._runtime.config.harness_id == "codex"
    assert pure._runtime.config.harness_source == "runtime"
    assert runtimes[0][0] == runtime_name
    assert pure._runtime.config.model == ""
    assert (await pure.run("first")).content == "native answer"
    assert [chunk async for chunk in pure.run_streaming("second")] == ["native stream"]
    assert pure._runtime.prompts == ["first", "second"]
    assert pure.get_status()["harness"]["id"] == "codex"
    assert project_harness.read_bytes() == original


@pytest.mark.parametrize("runtime_name", ["codex-cli", "codex-sdk"])
def test_connect_switch_clears_loaded_project_harness(
    project_harness, runtimes, monkeypatch, runtime_name
):
    pure = PureMode(runtime="builtin")
    assert pure._harness_spec.name == "project-coder"
    # A loaded spec normally routes connect through the harness kernel.
    pure.connect("anthropic", "project-model")
    assert not runtimes
    app = SuperQodeApp()
    app._pure_mode = pure
    monkeypatch.setattr(
        "superqode.runtime.list_runtimes",
        lambda: [SimpleNamespace(name=runtime_name, installed=True, implemented=True, ready=True)],
    )
    monkeypatch.setattr(app, "_set_status_runtime", lambda *args: None)
    monkeypatch.setattr(app, "_install_pure_permission_bridge", lambda *args: None)
    announced = []
    monkeypatch.setattr(
        app, "_announce_self_contained_connection", lambda *args: announced.append(args)
    )
    log = SimpleNamespace(add_info=lambda text: None, add_error=pytest.fail)
    app._runtime_cmd(runtime_name, log)
    assert announced
    assert pure._harness_spec is None
    assert pure._harness_session is None
    assert runtimes[-1][0] == runtime_name
    assert pure.session.provider == "openai"
    assert pure.session.model == ""
    assert pure.get_status()["harness"]["source"] == "runtime"
    import os

    assert os.environ["SUPERQODE_HARNESS"] == str(project_harness)
    assert pure.session.harness_name == "Codex"
    # The file can still be deliberately selected after the vendor connection.
    pure.load_harness(project_harness)
    pure.connect("anthropic", "project-model")
    assert pure._harness_spec.name == "project-coder"
    assert pure._runtime is None
    assert len(runtimes) == 1


@pytest.mark.parametrize("runtime_name", ["codex-cli", "codex-sdk"])
def test_sidebar_reports_executing_codex_instead_of_repository_file(
    project_harness, runtimes, monkeypatch, runtime_name
):
    pure = PureMode(runtime=runtime_name)
    pure.connect("openai", "")
    monkeypatch.setattr(
        HarnessPanel, "app", property(lambda panel: SimpleNamespace(_pure_mode=pure))
    )
    panel = HarnessPanel()
    assert panel._load_active_harness() == (None, "", "")
    summary = panel._render_summary().plain
    assert "Codex" in summary and runtime_name in summary
    assert "project-coder" not in summary
    assert "none loaded" not in summary
    pure.load_harness(project_harness)
    assert panel._active_codex_harness() == ""
    assert panel._load_active_harness()[0].name == "project-coder"


@pytest.mark.parametrize(
    "runtime_name,profile", [("codex-cli", "codex"), ("codex-sdk", "codex-sdk")]
)
@pytest.mark.parametrize("explicit_harness", [False, True])
def test_headless_codex_ignores_project_defaults_but_keeps_explicit_harness(
    project_harness, monkeypatch, runtime_name, profile, explicit_harness
):
    monkeypatch.delenv("SUPERQODE_RUNTIME")
    monkeypatch.setattr(
        "superqode.config.loader.load_config",
        lambda: SimpleNamespace(
            superqode=SimpleNamespace(runtime=None, harness=str(project_harness))
        ),
    )
    calls = []

    async def run(**kwargs):
        calls.append(kwargs)
        return await Runtime(None).run(kwargs["prompt"])

    monkeypatch.setattr("superqode.headless.run_headless", run)
    args = ["--connect", profile, "--print"]
    if explicit_harness:
        args += ["--harness", str(project_harness)]
    result = CliRunner().invoke(cli_main, [*args, "hello"])
    assert result.exit_code == 0, result.output
    assert calls[0]["runtime"] == runtime_name
    assert calls[0]["profile_name"] == (str(project_harness) if explicit_harness else "core")
    assert calls[0]["provider"] == ("anthropic" if explicit_harness else "openai")


@pytest.mark.parametrize("runtime_name", ["codex-cli", "codex-sdk"])
def test_returning_to_builtin_restores_saved_project_harness(
    project_harness, runtimes, monkeypatch, runtime_name
):
    import os

    pure = PureMode(runtime=runtime_name)
    pure.connect("openai", "")
    app = SuperQodeApp()
    app._pure_mode = pure
    monkeypatch.setenv("SUPERQODE_RUNTIME", runtime_name)
    monkeypatch.setattr(
        "superqode.runtime.list_runtimes",
        lambda: [SimpleNamespace(name="builtin", installed=True, implemented=True, ready=True)],
    )
    monkeypatch.setattr(app, "_set_status_runtime", lambda *args: None)
    monkeypatch.setattr(app, "_set_status_model", lambda *args: None)
    log = SimpleNamespace(add_info=lambda text: None, add_error=pytest.fail)
    app._runtime_cmd("builtin", log)
    assert os.environ["SUPERQODE_HARNESS"] == str(project_harness)
    assert pure._harness_spec.name == "project-coder"
    assert pure.runtime_name == "builtin"
    pure.connect("anthropic", "project-model")
    assert pure._runtime is None


@pytest.mark.parametrize("runtime_name", ["codex-cli", "codex-sdk"])
def test_reload_extensions_keeps_codex_owner_with_default_model(
    project_harness, runtimes, runtime_name
):
    pure = PureMode(runtime=runtime_name)
    pure.connect("openai", "")
    pure.reload_extensions()
    assert len(runtimes) == 2
    assert pure._harness_definition is None and pure._harness_spec is None
    assert pure._runtime.config.harness_id == "codex"
    assert pure.get_status()["harness"]["source"] == "runtime"
