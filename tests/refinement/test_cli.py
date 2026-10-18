from __future__ import annotations

import json

from click.testing import CliRunner

from superqode.main import cli_main


def test_refinement_dry_run_is_offline_and_writes_nothing(tmp_path):
    output = tmp_path / ".superqode" / "job"
    result = CliRunner().invoke(
        cli_main,
        [
            "harness",
            "refine",
            "--source",
            str(tmp_path),
            "--output",
            str(output),
            "--prompt",
            "Fix a bug",
            "--model",
            "gemma4:12b",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["solver_runs"] == 4 and payload["nominal_sessions"] == 7
    assert payload["executor"] == "codegem"
    assert not output.exists()


def test_refinement_invalid_settings_fail_before_execution(tmp_path):
    result = CliRunner().invoke(
        cli_main,
        [
            "harness",
            "refine",
            "--source",
            str(tmp_path),
            "--prompt",
            "Fix",
            "--model",
            "gemma4:12b",
            "--max-sessions",
            "2",
            "--dry-run",
        ],
    )
    assert result.exit_code != 0
    assert "at least 7" in result.output


def test_refinement_cli_documents_lifecycle():
    result = CliRunner().invoke(cli_main, ["harness", "refine", "--help"])
    assert result.exit_code == 0
    assert all(command in result.output for command in ("inspect", "resume", "cancel", "apply"))


def test_spec_settings_and_cli_overrides_are_explicit(tmp_path):
    spec = tmp_path / "local.yaml"
    spec.write_text(
        "name: local\ninherits: codegem\nmodel_policy:\n  primary: ollama/gemma4:12b\n"
        "optimization:\n  config:\n    method: harness2\n    k: 2\n    mode: parallel\n"
    )
    args = [
        "harness",
        "refine",
        "--source",
        str(tmp_path),
        "--spec",
        str(spec),
        "--prompt",
        "Fix",
        "--dry-run",
    ]
    result = CliRunner().invoke(cli_main, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["nominal_sessions"] == 15
    result = CliRunner().invoke(cli_main, [*args, "--k", "1"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["nominal_sessions"] == 7
    spec.write_text(spec.read_text() + "    library: persistent\n")
    result = CliRunner().invoke(cli_main, args)
    assert result.exit_code != 0 and "Unsupported Harness² settings: library" in result.output
