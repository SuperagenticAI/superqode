"""Runtime onboarding tests: no installers, downloads, servers or inference."""

import asyncio
import json
import shlex
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from superqode.commands.local import local
from superqode.local import install


@pytest.fixture(autouse=True)
def isolated_host(monkeypatch, tmp_path):
    monkeypatch.setattr(install.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(install.shutil, "which", lambda _: None)
    monkeypatch.setattr(install.sys, "platform", "linux")


def test_macos_brew_plan(monkeypatch):
    monkeypatch.setattr(install.sys, "platform", "darwin")
    monkeypatch.setattr(
        install.shutil, "which", lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None
    )
    assert install.install_plan("llamacpp").steps == (
        ("/opt/homebrew/bin/brew", "install", "llama.cpp"),
    )
    assert install.install_plan("ollama").steps[-1][-1] == "ollama"


def test_linux_ollama_privileged_install_is_manual():
    plan = install.install_plan("ollama")
    assert not plan.steps
    assert "sudo" in plan.guidance
    assert "brew" not in plan.guidance
    assert plan.command == "curl -fsSL https://ollama.com/install.sh | sh"


def test_windows_never_offers_unix_installer(monkeypatch):
    monkeypatch.setattr(install.sys, "platform", "win32")
    assert not install.install_plan("lmstudio").steps
    assert not install.install_plan("llama.cpp").steps


def test_gpu_install_is_isolated_and_platform_aware(monkeypatch):
    monkeypatch.setattr(
        install.shutil,
        "which",
        lambda name: f"/bin/{name}" if name in {"uv", "nvidia-smi"} else None,
    )
    plan = install.install_plan("sglang")
    assert len(plan.steps) == 2
    assert "/.superqode/runtimes/sglang" in plan.command
    assert "--prerelease=allow" in plan.steps[1]
    assert "--python" in plan.steps[1]
    monkeypatch.setattr(install.sys, "platform", "darwin")
    assert not install.install_plan("sglang").steps


def test_mlx_unsupported_platform_explains_alternatives():
    plan = install.install_plan("mlx")
    assert not plan.steps
    assert "Apple Silicon" in plan.guidance
    assert "Ollama" in plan.guidance


def test_headless_installer_propagates_download_failure(monkeypatch):
    monkeypatch.setattr(install.shutil, "which", lambda name: f"/bin/{name}")
    plan = install.install_plan("lmstudio")
    assert plan.steps[0][:4] == ("bash", "-o", "pipefail", "-c")
    assert "curl -fsSL https://lmstudio.ai/install.sh" in plan.steps[0][4]


def _plan(monkeypatch):
    plan = install.InstallPlan(
        "ollama",
        "Ollama",
        (("fake-installer", "--runtime"),),
        "Test plan",
        "https://ollama.com/download",
    )
    monkeypatch.setattr(install, "install_plan", lambda engine: plan)
    monkeypatch.setattr(install, "runtime_installed", lambda engine: False)
    return plan


@pytest.mark.parametrize("flag", ["--dry-run", "--json"])
def test_cli_preview_does_not_execute_or_probe(monkeypatch, flag):
    _plan(monkeypatch)
    monkeypatch.setattr(
        install, "runtime_installed", lambda engine: pytest.fail("preview probed runtime")
    )
    monkeypatch.setattr(
        install.subprocess, "run", lambda *a, **k: pytest.fail("preview ran installer")
    )
    result = CliRunner().invoke(local, ["install", "ollama", flag])
    assert result.exit_code == 0, result.output
    if flag == "--json":
        assert json.loads(result.output)["automatic"] is True


def test_cli_declining_does_not_install(monkeypatch):
    _plan(monkeypatch)
    monkeypatch.setattr(
        install.subprocess, "run", lambda *a, **k: pytest.fail("declined installer ran")
    )
    result = CliRunner().invoke(local, ["install", "ollama"], input="n\n")
    assert result.exit_code != 0


def test_cli_install_verifies_and_shows_coding_steps(monkeypatch):
    plan = _plan(monkeypatch)
    checks = iter([False, True])
    monkeypatch.setattr(install, "runtime_installed", lambda engine: next(checks))
    calls = []
    monkeypatch.setattr(
        install.subprocess,
        "run",
        lambda argv, **kw: calls.append(argv) or SimpleNamespace(returncode=0),
    )
    result = CliRunner().invoke(local, ["install", "ollama", "--yes"])
    assert result.exit_code == 0, result.output
    assert calls == list(plan.steps)
    assert ":connect local ollama" in result.output
    assert ":build" in result.output


def test_cli_failed_install_has_retry_and_no_followup(monkeypatch):
    _plan(monkeypatch)
    monkeypatch.setattr(install.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=7))
    result = CliRunner().invoke(local, ["install", "ollama", "--yes"])
    assert result.exit_code != 0
    assert "exited with 7" in result.output
    assert "superqode local install ollama" in result.output
    assert ":build" not in result.output


def test_cli_manual_install_does_not_report_success(monkeypatch):
    monkeypatch.setattr(install, "runtime_installed", lambda engine: False)
    result = CliRunner().invoke(local, ["install", "ollama", "--yes"])
    assert result.exit_code != 0
    assert "platform-specific installation" in result.output


def test_cli_success_exit_requires_runtime_verification(monkeypatch):
    _plan(monkeypatch)
    monkeypatch.setattr(install.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0))
    result = CliRunner().invoke(local, ["install", "ollama", "--yes"])
    assert result.exit_code != 0
    assert "runtime is not available" in result.output


def test_lmstudio_next_steps_start_daemon_before_download():
    steps = install.next_steps("lmstudio")
    assert steps[0].endswith("daemon up")
    assert "get <model-name>" in steps[1]


def test_tui_install_runs_steps_separately_then_resumes(monkeypatch):
    from superqode.app.mixins.local_models import LocalModelsMixin

    checks = iter([False, True])
    monkeypatch.setattr(install, "runtime_installed", lambda engine: next(checks))
    steps = (("uv", "venv", "/path with spaces/runtime"), ("uv", "pip", "install", "vllm"))
    plan = install.InstallPlan("vllm", "vLLM", steps, "", "")
    calls = []

    async def run(title, command, log):
        calls.append(shlex.split(command))
        return SimpleNamespace(returncode=0)

    async def resume(provider, log):
        calls.append(provider)

    app = SimpleNamespace(_run_install_with_progress=run, _show_local_provider_models=resume)
    log = SimpleNamespace(add_success=lambda message: None)
    asyncio.run(LocalModelsMixin._install_runtime_then_continue(app, plan, log))
    assert calls == [list(step) for step in steps] + ["vllm"]
    assert app.is_busy is False


def test_tui_cancel_does_not_resume_or_run_later_steps(monkeypatch):
    from superqode.app.mixins.local_models import LocalModelsMixin
    from superqode.app.mixins.commands_impl import InstallCancelled

    monkeypatch.setattr(install, "runtime_installed", lambda engine: False)
    plan = install.InstallPlan("vllm", "vLLM", (("first",), ("second",)), "", "")
    calls = []

    async def run(*args):
        calls.append("install")
        raise InstallCancelled()

    app = SimpleNamespace(
        _run_install_with_progress=run, _show_install_recovery=lambda *a: calls.append("recovery")
    )
    log = SimpleNamespace(add_error=lambda message: None)
    asyncio.run(LocalModelsMixin._install_runtime_then_continue(app, plan, log))
    assert calls == ["install", "recovery"]
    assert app.is_busy is False
