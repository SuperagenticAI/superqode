from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from superqode.commands.optimize import optimize
from superqode.optimize.profiles import (
    build_launch_plan,
    get_profile,
    profiles,
    provider_upstream,
)
from superqode.optimize.launchers import (
    LAUNCHER_MARKER,
    disable_launchers,
    enable_launchers,
    install_launcher,
    launch_arguments,
    launcher_rows,
    load_config,
)


def test_registry_covers_target_harnesses() -> None:
    assert {profile.id for profile in profiles()} == {
        "codex",
        "claude",
        "opencode",
        "grok",
        "pi",
        "antigravity",
        "superqode",
    }


def test_codex_plan_uses_process_local_provider_without_websockets_or_compression(
    monkeypatch,
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")
    plan = build_launch_plan(
        get_profile("codex"),
        gateway_url="http://127.0.0.1:8765",
        provider="openai",
        extra_args=("exec", "fix tests"),
    )

    assert plan.command[0] == "/bin/codex"
    assert 'model_provider="superqode_jev"' in plan.command
    assert 'model_providers.superqode_jev.base_url="http://127.0.0.1:8765/v1"' in plan.command
    assert "model_providers.superqode_jev.supports_websockets=false" in plan.command
    assert "features.enable_request_compression=false" in plan.command
    assert plan.command[-2:] == ("exec", "fix tests")
    assert plan.environment == {}


def test_claude_plan_is_process_local(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")
    plan = build_launch_plan(
        get_profile("claude"),
        gateway_url="http://127.0.0.1:8765",
        provider="anthropic",
    )

    assert plan.command == ("/bin/claude",)
    assert plan.environment == {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8765"}


def test_opencode_plan_uses_inline_high_precedence_overlay(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")
    plan = build_launch_plan(
        get_profile("opencode"),
        gateway_url="http://127.0.0.1:8765",
        provider="anthropic",
    )

    overlay = json.loads(plan.environment["OPENCODE_CONFIG_CONTENT"])
    assert overlay["provider"]["anthropic"]["options"]["baseURL"].endswith("/v1")


def test_opencode_google_plan_uses_native_google_provider(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")
    plan = build_launch_plan(
        get_profile("opencode"),
        gateway_url="http://127.0.0.1:8765",
        provider="google",
        model="gemini-3.8-flash",
        extra_args=("run", "inspect the repository"),
    )

    overlay = json.loads(plan.environment["OPENCODE_CONFIG_CONTENT"])
    provider = overlay["provider"]["google"]
    assert provider["options"]["baseURL"] == "http://127.0.0.1:8765/v1beta"
    assert plan.environment["GOOGLE_GENERATIVE_AI_API_KEY"] == "superqode-local-gateway"
    assert plan.command == (
        "/bin/opencode",
        "--model",
        "google/gemini-3.8-flash",
        "run",
        "inspect the repository",
    )


def test_grok_plan_uses_documented_models_endpoint(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")
    plan = build_launch_plan(
        get_profile("grok"),
        gateway_url="http://127.0.0.1:8765",
        provider="xai",
    )

    assert plan.environment["GROK_MODELS_BASE_URL"] == "http://127.0.0.1:8765/v1"


def test_superqode_plan_enables_valid_native_shadow_mode(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")
    plan = build_launch_plan(
        get_profile("superqode"),
        gateway_url="http://127.0.0.1:8765",
        provider="openai",
    )

    assert plan.environment["SUPERQODE_TOOL_ROUTING"] == "shadow"


def test_pi_plan_generates_only_temporary_configuration(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")
    plan = build_launch_plan(
        get_profile("pi"),
        gateway_url="http://127.0.0.1:8765",
        provider="anthropic",
        model="claude-test",
        temp_dir=tmp_path,
        environ={"ANTHROPIC_API_KEY": "secret"},
    )

    models = json.loads(plan.generated_files["models.json"])
    assert plan.environment["PI_CODING_AGENT_DIR"] == str(tmp_path)
    assert models["providers"]["superqode"]["apiKey"] == "$ANTHROPIC_API_KEY"
    assert "secret" not in plan.generated_files["models.json"]


def test_pi_google_plan_uses_native_gemini_api(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")
    plan = build_launch_plan(
        get_profile("pi"),
        gateway_url="http://127.0.0.1:8765",
        provider="google",
        model="gemini-3.8-flash",
        temp_dir=tmp_path,
        environ={"GEMINI_API_KEY": "secret"},
    )

    provider = json.loads(plan.generated_files["models.json"])["providers"]["superqode"]
    assert provider["api"] == "google-generative-ai"
    assert provider["baseUrl"] == "http://127.0.0.1:8765/v1beta"
    assert provider["apiKey"] == "superqode-local-gateway"
    assert "secret" not in plan.generated_files["models.json"]
    assert provider_upstream("google") == (
        "https://generativelanguage.googleapis.com",
        "GEMINI_API_KEY",
    )


def test_antigravity_run_fails_with_capability_explanation() -> None:
    result = CliRunner().invoke(optimize, ["run", "antigravity"])

    assert result.exit_code != 0
    assert "cannot be routed" in result.output


def test_managed_launcher_round_trip_is_non_secret(tmp_path: Path) -> None:
    config = tmp_path / "config" / "jev-routing.json"
    bin_dir = tmp_path / "bin"

    enabled, skipped = enable_launchers(
        ["opencode"],
        provider="google",
        model="gemini-test",
        bin_dir=bin_dir,
        path=config,
    )

    assert skipped == []
    assert enabled[0].launcher == str(bin_dir / "opencode-jev")
    launcher = (bin_dir / "opencode-jev").read_text(encoding="utf-8")
    assert LAUNCHER_MARKER in launcher
    assert 'exec superqode optimize launch opencode -- "$@"' in launcher
    assert load_config(config)["harnesses"]["opencode"] == {
        "launcher": str(bin_dir / "opencode-jev"),
        "mode": "shadow",
        "model": "gemini-test",
        "provider": "google",
        "threshold": 0.3,
    }
    assert config.stat().st_mode & 0o777 == 0o600
    assert launch_arguments("opencode", ("run", "inspect"), config) == [
        "optimize",
        "run",
        "opencode",
        "--provider",
        "google",
        "--model",
        "gemini-test",
        "--mode",
        "shadow",
        "--threshold",
        "0.3",
        "--",
        "run",
        "inspect",
    ]

    removed, retained = disable_launchers(["opencode"], path=config)
    assert removed == ["opencode"]
    assert retained == []
    assert not config.exists()
    assert not (bin_dir / "opencode-jev").exists()


def test_launcher_never_overwrites_or_removes_unmanaged_file(tmp_path: Path) -> None:
    target = tmp_path / "opencode-jev"
    target.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")

    try:
        install_launcher("opencode", tmp_path)
    except FileExistsError as exc:
        assert "unmanaged" in str(exc)
    else:  # pragma: no cover - documents the destructive safety contract
        raise AssertionError("unmanaged launcher was overwritten")
    assert target.read_text(encoding="utf-8") == "#!/bin/sh\necho mine\n"


def test_launcher_refuses_symlink_target(tmp_path: Path) -> None:
    destination = tmp_path / "owned"
    destination.write_text(f"#!/bin/sh\n# {LAUNCHER_MARKER}\n", encoding="utf-8")
    (tmp_path / "opencode-jev").symlink_to(destination)

    try:
        install_launcher("opencode", tmp_path)
    except FileExistsError as exc:
        assert "unmanaged" in str(exc)
    else:  # pragma: no cover - documents the symlink safety contract
        raise AssertionError("launcher followed a symlink")
    assert destination.read_text(encoding="utf-8") == f"#!/bin/sh\n# {LAUNCHER_MARKER}\n"


def test_enable_skips_incompatible_protocol_and_model_less_pi(tmp_path: Path) -> None:
    enabled, skipped = enable_launchers(
        ["claude", "pi"],
        provider="google",
        bin_dir=tmp_path / "bin",
        path=tmp_path / "config.json",
    )

    assert enabled == []
    assert {row["harness"] for row in skipped} == {"claude", "pi"}
    assert "wire protocol" in next(row["reason"] for row in skipped if row["harness"] == "claude")
    assert "requires --model" in next(row["reason"] for row in skipped if row["harness"] == "pi")


def test_enable_status_disable_cli_uses_isolated_paths(tmp_path: Path) -> None:
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    runner = CliRunner()
    environment = {"SUPERQODE_HOME": str(home), "PATH": str(bin_dir)}

    enabled = runner.invoke(
        optimize,
        [
            "enable",
            "opencode",
            "--provider",
            "google",
            "--model",
            "gemini-test",
            "--bin-dir",
            str(bin_dir),
            "--json",
        ],
        env=environment,
    )
    assert enabled.exit_code == 0, enabled.output
    assert json.loads(enabled.output)["credentials_written"] is False
    assert (bin_dir / "opencode-jev").is_file()

    status = runner.invoke(optimize, ["status", "--json"], env=environment)
    assert status.exit_code == 0, status.output
    assert json.loads(status.output)["enabled"][0]["launcher_managed"] is True

    disabled = runner.invoke(optimize, ["disable", "opencode", "--json"], env=environment)
    assert disabled.exit_code == 0, disabled.output
    assert json.loads(disabled.output)["removed"] == ["opencode"]
    assert launcher_rows(home / "jev-routing.json") == []


def test_doctor_json_reports_every_profile(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")
    result = CliRunner().invoke(optimize, ["doctor", "--json"])

    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert len(rows) == 7
    assert next(row for row in rows if row["id"] == "antigravity")["support"] == "detect-only"


def test_env_outputs_machine_readable_plan(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")
    result = CliRunner().invoke(
        optimize,
        ["env", "codex", "--port", "9911", "--json"],
    )

    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert 'model_providers.superqode_jev.base_url="http://127.0.0.1:9911/v1"' in output["command"]


def test_benchmark_requires_typesafe_key(monkeypatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    result = CliRunner().invoke(optimize, ["bench"])

    assert result.exit_code != 0
    assert "TYPESAFE_API_KEY is required" in result.output


def _probe_result() -> dict[str, object]:
    return {
        "status": "ok",
        "original_tools": 6,
        "selected_tools": 2,
        "dropped": ["image_gen", "send_email", "database_query", "deploy"],
        "original_schema_bytes": 900,
        "selected_schema_bytes": 300,
        "latency_ms": 200,
        "cache_reused": True,
    }


def test_setup_is_non_persistent_and_prints_launch_commands(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        "superqode.commands.optimize._run_routing_probe", lambda threshold: _probe_result()
    )
    result = CliRunner().invoke(
        optimize,
        ["setup", "--model", "claude-test", "--json"],
        env={"TYPESAFE_API_KEY": "test-key"},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["writes_configuration"] is False
    assert payload["connectivity"]["cache_reused"] is True
    assert len(payload["harnesses"]) == 7
    pi = next(row for row in payload["harnesses"] if row["id"] == "pi")
    assert "--model claude-test" in pi["command"]
    assert "test-key" not in result.output


def test_setup_missing_key_fails_without_writing(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")
    result = CliRunner().invoke(optimize, ["setup", "opencode", "--json"], env={})

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["connectivity"]["status"] == "missing-key"
    assert payload["writes_configuration"] is False


def test_verify_supported_harness_reports_control_route(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        "superqode.commands.optimize._run_routing_probe", lambda threshold: _probe_result()
    )
    result = CliRunner().invoke(
        optimize,
        ["verify", "opencode", "--json"],
        env={"TYPESAFE_API_KEY": "test-key"},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "verified"
    assert payload["tool_catalogue_visible"] is True
    assert payload["actual_harness_traffic_tested"] is False
    assert payload["control_probe"]["selected_schema_bytes"] == 300


def test_verify_codex_is_honestly_gateway_limited(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        "superqode.commands.optimize._run_routing_probe", lambda threshold: _probe_result()
    )
    result = CliRunner().invoke(
        optimize,
        ["verify", "codex", "--json"],
        env={"TYPESAFE_API_KEY": "test-key"},
    )

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["status"] == "gateway-limited"
    assert payload["verified"] is False
    assert payload["tool_catalogue_visible"] is False


def test_verify_pi_requires_model(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        "superqode.commands.optimize._run_routing_probe", lambda threshold: _probe_result()
    )
    result = CliRunner().invoke(
        optimize,
        ["verify", "pi", "--json"],
        env={"TYPESAFE_API_KEY": "test-key"},
    )

    assert result.exit_code == 1
    assert json.loads(result.output)["status"] == "needs-model"
