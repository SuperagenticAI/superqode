import json
import sys

from click.testing import CliRunner

from superqode.commands.benchmark import benchmark


def test_dry_run_never_executes_target(tmp_path):
    manifest = tmp_path / "manifest.json"
    marker = tmp_path / "executed"
    manifest.write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "name": name,
                        "command": [sys.executable, "-c", f"open({str(marker)!r}, 'w').close()"],
                        "provider": "fixture",
                        "model": "same",
                        "revision": "fixture-v1",
                    }
                    for name in ("candidate", "baseline")
                ],
                "tasks": [
                    {
                        "id": "fixture",
                        "prompt": "test",
                        "cwd": ".",
                        "checks": [[sys.executable, "-c", "raise SystemExit(1)"]],
                    }
                ],
            }
        )
    )
    result = CliRunner().invoke(benchmark, ["compare", str(manifest), "--dry-run"])
    assert result.exit_code == 0, result.output
    plan = json.loads(result.output)
    assert plan["ready"] and plan["planned_attempts"] == 6
    assert not plan["live_certification"]
    assert not marker.exists()


def test_preflight_reports_missing_workspace_and_binary(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "name": name,
                        "command": ["superqode-nonexistent-fixture-binary"],
                        "provider": "fixture",
                        "model": "same",
                        "revision": "v1",
                    }
                    for name in ("a", "b")
                ],
                "tasks": [
                    {
                        "id": "missing",
                        "prompt": "test",
                        "cwd": "missing",
                        "checks": [[sys.executable, "-c", "pass"]],
                    }
                ],
            }
        )
    )
    runner = CliRunner()
    result = runner.invoke(benchmark, ["compare", str(manifest), "--dry-run"])
    assert result.exit_code == 0
    assert not json.loads(result.output)["ready"]
    result = runner.invoke(benchmark, ["compare", str(manifest)])
    assert result.exit_code != 0
    assert "setup incomplete" in result.output
