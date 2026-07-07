from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from superqode.main import cli_main


def test_harness_self_improve_mines_logbook_and_exports_project():
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("harness.yaml").write_text(
            "\n".join(
                [
                    "name: demo",
                    "inherits: no-tool",
                    "optimization:",
                    "  enabled: true",
                    "  editable_surfaces: [context]",
                    "  protected_surfaces: [checks]",
                    "  heldout_fraction: 0.2",
                    "  max_candidate_edits: 2",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        Path("tasks.yaml").write_text(
            "tasks:\n  - id: smoke\n    prompt: say hello\n",
            encoding="utf-8",
        )
        Path("eval-result.json").write_text(
            json.dumps(
                {
                    "tasks_file": "tasks.yaml",
                    "live": True,
                    "status": "passed",
                    "baseline": "demo",
                    "best": "demo",
                    "variants": [
                        {
                            "harness": "demo",
                            "spec": "harness.yaml",
                            "score": 0.0,
                            "passed": 0,
                            "failed": 1,
                            "skipped": 0,
                            "regressions_vs_baseline": ["smoke"],
                            "tasks": [
                                {
                                    "id": "smoke",
                                    "status": "failed",
                                    "reason": "missing expected text: hello",
                                    "failure_digest": {
                                        "failure_category": "tool_or_permission_error",
                                        "dimension": {
                                            "id": "D7",
                                            "label": "control and safety",
                                            "field": "execution_policy",
                                        },
                                        "evidence": ["eval_task: missing expected text: hello"],
                                    },
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        mined = runner.invoke(
            cli_main,
            [
                "harness",
                "mine-failures",
                "--eval-result",
                "eval-result.json",
                "--output",
                "failures.json",
                "--json",
            ],
        )
        assert mined.exit_code == 0, mined.output
        mined_payload = json.loads(mined.output)
        assert mined_payload["failure_count"] == 1
        assert mined_payload["failures"][0]["failure_id"] == "fail_0001"
        assert mined_payload["failures"][0]["suggested_surfaces"] == [
            "execution_policy",
            "agents.tools",
        ]
        assert Path("failures.json").exists()

        updated = runner.invoke(
            cli_main,
            [
                "harness",
                "logbook",
                "update",
                "--from-failures",
                "failures.json",
                "--json",
            ],
        )
        assert updated.exit_code == 0, updated.output
        updated_payload = json.loads(updated.output)
        assert updated_payload["added"] == 1
        assert updated_payload["patterns"] == 1

        shown = runner.invoke(cli_main, ["harness", "logbook", "show", "--json"])
        assert shown.exit_code == 0, shown.output
        logbook = json.loads(shown.output)
        assert logbook["failure_patterns"][0]["summary"] == "missing expected text: hello"
        assert logbook["failure_patterns"][0]["confidence"] == "low"

        pruned = runner.invoke(
            cli_main,
            ["harness", "logbook", "prune", "--min-count", "2", "--dry-run", "--json"],
        )
        assert pruned.exit_code == 0, pruned.output
        pruned_payload = json.loads(pruned.output)
        assert pruned_payload["dry_run"] is True
        assert pruned_payload["before"] == 1
        assert pruned_payload["pruned"] == 1

        improved = runner.invoke(
            cli_main,
            [
                "harness",
                "improve",
                "--spec",
                "harness.yaml",
                "--tasks",
                "tasks.yaml",
                "--from-failures",
                "failures.json",
                "--project-dir",
                "improve-project",
                "--export-only",
                "--json",
            ],
        )
        assert improved.exit_code == 0, improved.output
        improved_payload = json.loads(improved.output)
        assert improved_payload["run"] is None
        assert improved_payload["self_improve"]["failure_count"] == 1
        assert improved_payload["optimization_policy"]["editable_surfaces"] == ["context"]
        assert improved_payload["optimization_policy"]["protected_surfaces"] == ["checks"]
        assert improved_payload["optimization_policy"]["heldout_fraction"] == 0.2
        assert improved_payload["optimization_policy"]["max_candidate_edits"] == 2
        evidence = Path("improve-project/trace-evidence.md").read_text(encoding="utf-8")
        assert "## Self-Improvement Guidance" in evidence
        assert "### Mined Failures" in evidence
        assert "Editable surfaces: context" in evidence
        assert "Protected surfaces: checks" in evidence
        assert "Heldout fraction: 0.2" in evidence
        assert "Max candidate edits: 2" in evidence
        assert "Self-Improvement Logbook" in evidence
        assert "Previous Harness Edit Attempts" in evidence
        assert "missing expected text: hello" in evidence


def test_harness_mine_failures_accepts_benchmark_run_jsonl():
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("harbor").mkdir()
        Path("harbor/results.jsonl").write_text(
            json.dumps(
                {
                    "id": "terminal-bench-1",
                    "status": "failed",
                    "reason": "patch did not apply",
                    "harness": "demo",
                    "surface": "workflow",
                    "trace": "trajectory.txt",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        result = runner.invoke(
            cli_main,
            [
                "harness",
                "mine-failures",
                "--harbor-run",
                "harbor",
                "--output",
                "failures.json",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["failure_count"] == 1
        failure = payload["failures"][0]
        assert failure["source_type"] == "benchmark_run"
        assert failure["task_id"] == "terminal-bench-1"
        assert failure["mechanism"] == "workflow"
        assert failure["addressable"] is True


def test_harness_candidate_audit_and_ledger_commands():
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("base.yaml").write_text(
            "\n".join(
                [
                    "name: demo",
                    "inherits: no-tool",
                    "context:",
                    "  instruction_files: [AGENTS.md]",
                    "checks:",
                    "  enabled: true",
                    "  fail_on_error: true",
                    "  custom_steps:",
                    "    - name: lint",
                    "      command: ruff check .",
                    "optimization:",
                    "  enabled: true",
                    "  editable_surfaces: [context]",
                    "  protected_surfaces: [execution_policy, checks, sandbox, approvals]",
                    "  max_candidate_edits: 2",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        Path("candidate-good.yaml").write_text(
            "\n".join(
                [
                    "name: demo",
                    "inherits: no-tool",
                    "context:",
                    "  instruction_files: [AGENTS.md, SUPERQODE.md]",
                    "checks:",
                    "  enabled: true",
                    "  fail_on_error: true",
                    "  custom_steps:",
                    "    - name: lint",
                    "      command: ruff check .",
                    "optimization:",
                    "  enabled: true",
                    "  editable_surfaces: [context]",
                    "  protected_surfaces: [execution_policy, checks, sandbox, approvals]",
                    "  max_candidate_edits: 2",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        Path("candidate-bad.yaml").write_text(
            "\n".join(
                [
                    "name: demo",
                    "flavor: coding",
                    "execution_policy:",
                    "  allow_shell: true",
                    "checks:",
                    "  enabled: false",
                    "  fail_on_error: false",
                    "optimization:",
                    "  enabled: true",
                    "  editable_surfaces: [context]",
                    "  protected_surfaces: [execution_policy, checks, sandbox, approvals]",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        Path("tasks.yaml").write_text(
            "\n".join(
                [
                    "tasks:",
                    "  - id: gate",
                    "    split: held-out",
                    "    prompt: gate prompt",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        Path("eval-heldout.json").write_text(
            json.dumps(
                {
                    "split": "held-out",
                    "live": True,
                    "variants": [
                        {
                            "harness": "demo",
                            "spec": "base.yaml",
                            "regressed": False,
                            "regressions_vs_baseline": [],
                            "tasks": [{"id": "gate", "status": "passed"}],
                        },
                        {
                            "harness": "demo",
                            "spec": "candidate-good.yaml",
                            "regressed": False,
                            "regressions_vs_baseline": [],
                            "tasks": [{"id": "gate", "status": "passed"}],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        good = runner.invoke(
            cli_main,
            [
                "harness",
                "audit-candidate",
                "--base",
                "base.yaml",
                "--candidate",
                "candidate-good.yaml",
                "--tasks",
                "tasks.yaml",
                "--eval-result",
                "eval-heldout.json",
                "--require-heldout",
                "--record",
                "--json",
            ],
        )
        assert good.exit_code == 0, good.output
        good_payload = json.loads(good.output)
        assert good_payload["accepted"] is True
        assert good_payload["decision"] == "accepted"
        assert good_payload["recorded"]["record"]["accepted"] is True

        listed = runner.invoke(cli_main, ["harness", "candidates", "list", "--json"])
        assert listed.exit_code == 0, listed.output
        ledger = json.loads(listed.output)
        assert ledger["candidate_count"] == 1
        candidate_id = ledger["candidates"][0]["candidate_id"]

        shown = runner.invoke(
            cli_main,
            ["harness", "candidates", "show", candidate_id, "--json"],
        )
        assert shown.exit_code == 0, shown.output
        assert json.loads(shown.output)["candidate_id"] == candidate_id

        exported = runner.invoke(cli_main, ["harness", "candidates", "export"])
        assert exported.exit_code == 0, exported.output
        assert "Previous Harness Edit Attempts" in exported.output

        bad = runner.invoke(
            cli_main,
            [
                "harness",
                "audit-candidate",
                "--base",
                "base.yaml",
                "--candidate",
                "candidate-bad.yaml",
                "--tasks",
                "tasks.yaml",
                "--eval-result",
                "eval-heldout.json",
                "--require-heldout",
                "--json",
            ],
        )
        assert bad.exit_code == 0, bad.output
        bad_payload = json.loads(bad.output)
        assert bad_payload["accepted"] is False
        codes = {item["code"] for item in bad_payload["violations"]}
        assert "protected_surface_change" in codes
        assert "permission_widening" in codes
        assert "check_weakening" in codes
