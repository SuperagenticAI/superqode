"""Tests for sandbox execution providers."""

import subprocess
from pathlib import Path

import pytest

from superqode.sandbox.execution import run_in_sandbox, sandbox_provider_status


def test_docker_status_reports_cli_presence(monkeypatch):
    monkeypatch.setattr("superqode.sandbox.execution.shutil.which", lambda name: "/usr/bin/docker")

    status = sandbox_provider_status("docker")

    assert status.backend == "docker"
    assert status.available is True
    assert status.executable == "docker"


def test_optional_provider_status_reports_missing_setup(monkeypatch):
    monkeypatch.delenv("E2B_API_KEY", raising=False)

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "e2b":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    status = sandbox_provider_status("e2b")

    assert status.available is False
    assert status.required_env == ["E2B_API_KEY"]
    assert status.optional_dependency == "e2b"


def test_run_docker_builds_isolated_command(monkeypatch, tmp_path):
    calls = {}

    monkeypatch.setattr("superqode.sandbox.execution.shutil.which", lambda name: "/usr/bin/docker")

    def fake_run(args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr("superqode.sandbox.execution.subprocess.run", fake_run)

    result = run_in_sandbox("docker", "pytest -q", tmp_path, timeout=42, image="python:3.12")

    assert result.success is True
    assert result.stdout == "ok\n"
    assert calls["args"] == [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{tmp_path.resolve()}:/workspace",
        "-w",
        "/workspace",
        "python:3.12",
        "sh",
        "-lc",
        "pytest -q",
    ]
    assert calls["kwargs"]["timeout"] == 42
    assert calls["kwargs"]["check"] is False


def test_run_unsupported_backend_raises(tmp_path: Path):
    with pytest.raises(ValueError, match="Unsupported sandbox execution backend"):
        run_in_sandbox("unknown", "echo hi", tmp_path)
