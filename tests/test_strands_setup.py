"""Packaged CLI setup and provider diagnostic contracts."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner
import pytest

from superqode.commands.harness import harness
from superqode.harness import strands_setup
from superqode.harness.backends.strands_environment import worker_environment, redact_error


def test_packaged_cli_doctor_missing_environment_has_actionable_error(tmp_path):
    result = CliRunner().invoke(
        harness, ["strands", "doctor", "--python", str(tmp_path / "missing")]
    )
    assert result.exit_code == 1
    assert "superqode harness strands setup" in result.output
    assert "Traceback" not in result.output


@pytest.mark.parametrize("action,install", [("setup", True), ("doctor", False)])
def test_cli_dispatches_packaged_installer(monkeypatch, tmp_path, action, install):
    called = []
    monkeypatch.setattr(
        strands_setup,
        "setup_runtime",
        lambda interpreter, install: called.append((interpreter, install))
        or {"strands-harness": "0.3.3"},
    )
    target = tmp_path / "venv/bin/python"
    result = CliRunner().invoke(harness, ["strands", action, "--python", str(target)])
    assert result.exit_code == 0, result.output
    assert called == [(target, install)]
    assert "Strands runtime ready" in result.output


def test_setup_installs_litellm_extra_in_separate_environment(tmp_path, monkeypatch):
    target = tmp_path / "runtime/bin/python"
    target.parent.mkdir(parents=True)
    target.touch()
    (target.parent.parent / "pyvenv.cfg").touch()
    calls = []
    monkeypatch.setenv("GITHUB_TOKEN", "setup-fixture-token")
    monkeypatch.setattr(strands_setup.shutil, "which", lambda name: "/fixture/uv")

    def run(argv, **kwargs):
        calls.append(argv)
        if "--check" in argv:
            assert "GITHUB_TOKEN" not in kwargs["env"]
        return SimpleNamespace(
            returncode=0, stdout='{"type":"ready","versions":{"strands-harness":"0.3.3"}}'
        )

    monkeypatch.setattr(strands_setup.subprocess, "run", run)
    assert strands_setup.setup_runtime(target, install=True) == {"strands-harness": "0.3.3"}
    assert "strands-harness[anthropic,openai,gemini,ollama,litellm]==0.3.3" in calls[0]
    assert calls[-1][2].endswith("superqode/harness/backends/strands_worker.py")


def test_environment_keeps_only_selected_provider_and_transport_configuration(
    monkeypatch, tmp_path
):
    from superqode.providers import credentials

    monkeypatch.setattr(credentials, "provider_api_key", lambda definition: None)
    for name, value in {
        "GITHUB_TOKEN": "github-fixture",
        "OPENAI_API_KEY": "openai-fixture",
        "AWS_SECRET_ACCESS_KEY": "aws-fixture",
        "AWS_PROFILE": "dev-profile",
        "AWS_REGION": "eu-west-2",
        "AWS_WEB_IDENTITY_TOKEN_FILE": "/fixture/identity",
        "AWS_ROLE_ARN": "arn:fixture",
        "HTTP_PROXY": "http://proxy:8080",
        "SSL_CERT_FILE": "/fixture/ca.pem",
        "MONTY_BIN": "/poison",
        "PYTHONPATH": "/poison",
        "UNRELATED_CUSTOM_SECRET": "custom-fixture",
    }.items():
        monkeypatch.setenv(name, value)
    bedrock = worker_environment("bedrock", tmp_path / "bin/python")
    assert bedrock["AWS_PROFILE"] == "dev-profile"
    assert bedrock["AWS_WEB_IDENTITY_TOKEN_FILE"] == "/fixture/identity"
    assert bedrock["AWS_SECRET_ACCESS_KEY"] == "aws-fixture"
    assert bedrock["HTTP_PROXY"] == "http://proxy:8080"
    assert bedrock["SSL_CERT_FILE"] == "/fixture/ca.pem"
    assert (
        not {"OPENAI_API_KEY", "GITHUB_TOKEN", "MONTY_BIN", "PYTHONPATH", "UNRELATED_CUSTOM_SECRET"}
        & bedrock.keys()
    )
    openai = worker_environment("openai", tmp_path / "bin/python")
    assert openai["OPENAI_API_KEY"] == "openai-fixture"
    assert not any(name.startswith("AWS_") for name in openai)
    assert redact_error("Rejected openai-fixture", openai) == "Rejected [REDACTED]"


@pytest.fixture
def worker_module():
    path = Path(strands_setup.__file__).with_name("backends") / "strands_worker.py"
    spec = importlib.util.spec_from_file_location("strands_diagnostic_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "status,category",
    [
        (401, "authentication"),
        (403, "permission"),
        (404, "model_not_found"),
        (429, "rate_limit"),
        (400, "configuration"),
    ],
)
def test_provider_errors_are_distinct_without_response_body_secrets(
    worker_module, status, category
):
    class ProviderError(Exception):
        status_code = status

    error = ProviderError("secret-fixture-key https://user:password@example.org")
    actual, message = worker_module.error_diagnostic(error)
    assert actual == category
    assert "secret-fixture-key" not in message
    assert "password" not in message
    assert "example.org" not in message


def test_missing_dependency_points_to_packaged_setup(worker_module):
    category, message = worker_module.error_diagnostic(ModuleNotFoundError("fixture-package"))
    assert category == "runtime_setup"
    assert "superqode harness strands setup" in message
