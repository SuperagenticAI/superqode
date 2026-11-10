"""The macOS app installs harness extras itself and can publish its own CLI."""

import os
import platform
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import pytest

from test_desktop_service import desktop  # noqa: F401

from superqode.desktop_service import app_setup, local_models


def test_worker_pythonpath_keeps_packages_installed_by_the_app(tmp_path):
    extras = tmp_path / "python-extras"
    extras.mkdir()
    path = app_setup.engine_pythonpath(tmp_path)
    assert path.split(os.pathsep) == [
        str(Path(app_setup.__file__).resolve().parents[2]),
        str(extras.resolve()),
    ]


def test_installable_extras_match_pyproject():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    extras = project["project"]["optional-dependencies"]
    for name, packages in app_setup.EXTRAS.items():
        assert list(extras[name]) == list(packages)


def test_install_targets_the_app_folder_not_a_terminal_command(monkeypatch, tmp_path):
    monkeypatch.setattr(app_setup, "packages_for", lambda extra: ["deepseek-harness-sdk>=0.1"])
    monkeypatch.setattr(app_setup, "ensure_uv", lambda bin_dir: "/tmp/superqode-uv")
    checked = []
    monkeypatch.setattr(
        app_setup, "verify_extra", lambda root, extra: checked.append((root, extra))
    )
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(app_setup.subprocess, "run", fake_run)
    app_setup.install_extra(tmp_path, "deepseek-harness")
    assert calls[0][:4] == [
        "/tmp/superqode-uv",
        "pip",
        "install",
        "--python",
    ]
    assert calls[0][4] == sys.executable
    assert "--target" in calls[0]
    assert str(tmp_path / "python-extras") in calls[0]
    assert "deepseek-harness-sdk>=0.1" in calls[0]
    assert "uv tool" not in " ".join(calls[0])
    assert checked == [(tmp_path, "deepseek-harness")]


def test_activation_uses_the_same_path_as_a_coding_job(tmp_path):
    package = tmp_path / "python-extras" / "sq_probe_pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("READY = True\n", encoding="utf-8")
    app_setup._import_in_job_process(tmp_path, ("sq_probe_pkg",))
    missing = tmp_path / "empty"
    missing.mkdir()
    with pytest.raises(RuntimeError, match="does not load|ModuleNotFoundError|No module"):
        app_setup._import_in_job_process(missing, ("sq_probe_missing",))


def test_missing_harness_install_finishes_in_the_background(desktop, monkeypatch):
    service, project, _ = desktop
    monkeypatch.setattr(
        local_models,
        "harnesses",
        lambda service, project: [
            {
                "id": "deepseek-harness",
                "name": "DeepSeek Harness",
                "selectable": False,
                "install_extra": "deepseek-harness",
            }
        ],
    )
    seen = []
    monkeypatch.setattr(app_setup, "install_extra", lambda root, extra: seen.append(extra))
    started = local_models.install(
        service, {"project": project["id"], "harness": "deepseek-harness"}
    )
    status = started
    for _ in range(100):
        if status["status"] != "running":
            break
        time.sleep(0.01)
        status = local_models.install_status(service, {"id": started["id"]})
    assert status["status"] == "completed", status
    assert seen == ["deepseek-harness"]


def test_deepseek_package_follows_the_platform_marker():
    supported = (sys.platform == "darwin" and platform.machine() == "arm64") or (
        sys.platform == "linux" and platform.machine() in {"x86_64", "aarch64"}
    )
    if supported:
        assert app_setup.packages_for("deepseek-harness") == [
            "deepseek-harness-sdk>=0.1.0rc6,<0.2.0"
        ]
    else:
        with pytest.raises(ValueError, match="does not ship"):
            app_setup.packages_for("deepseek-harness")


def test_publish_cli_adds_a_command_without_replacing_a_real_binary(tmp_path):
    home = tmp_path / "home"
    root = tmp_path / "state"
    app_setup.publish_cli(root, home=home)
    link = home / ".local" / "bin" / "superqode"
    assert link.is_symlink()
    assert link.resolve() == (root / "bin" / "superqode").resolve()
    assert 'export PATH="$HOME/.local/bin:$PATH"' in (home / ".zshrc").read_text(encoding="utf-8")
    other = tmp_path / "existing-superqode"
    other.write_text("keep", encoding="utf-8")
    link.unlink()
    link.symlink_to(other)
    app_setup.publish_cli(root, home=home)
    assert link.resolve() == other.resolve()
    link.unlink()
    link.write_text("#!/bin/sh\n", encoding="utf-8")
    app_setup.publish_cli(root, home=home)
    assert not link.is_symlink()
    assert link.read_text(encoding="utf-8") == "#!/bin/sh\n"
