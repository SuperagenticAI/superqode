from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from superqode.main import cli_main


def test_harness_eval_filters_held_out_split():
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("harness.yaml").write_text("name: demo\ninherits: no-tool\n", encoding="utf-8")
        Path("tasks.yaml").write_text(
            "\n".join(
                [
                    "tasks:",
                    "  - id: train",
                    "    split: held-in",
                    "    prompt: train prompt",
                    "  - id: gate",
                    "    split: held-out",
                    "    prompt: gate prompt",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = runner.invoke(
            cli_main,
            [
                "harness",
                "eval",
                "--spec",
                "harness.yaml",
                "--tasks",
                "tasks.yaml",
                "--split",
                "held-out",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["split"] == "held-out"
        assert payload["task_count"] == 1
        assert payload["split_counts"] == {"held-in": 1, "held-out": 1, "all": 2}
        assert payload["variants"][0]["tasks"][0]["id"] == "gate"


def test_harness_optimize_export_includes_split_checks_and_evidence():
    runner = CliRunner()
    with runner.isolated_filesystem():
        Path("harness.yaml").write_text("name: demo\ninherits: no-tool\n", encoding="utf-8")
        Path("tasks.yaml").write_text(
            "\n".join(
                [
                    "tasks:",
                    "  - id: train",
                    "    split: held-in",
                    "    prompt: train prompt",
                    "  - id: gate",
                    "    split: held-out",
                    "    prompt: gate prompt",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = runner.invoke(
            cli_main,
            [
                "harness",
                "optimize",
                "--spec",
                "harness.yaml",
                "--tasks",
                "tasks.yaml",
                "--project-dir",
                "mh-project",
                "--export-only",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        tasks = json.loads(Path("mh-project/tasks.json").read_text(encoding="utf-8"))
        by_id = {item["id"]: item for item in tasks}
        assert "--split held-in" in by_id["harness-eval-held-in-dry"]["command"]
        assert "--split held-out" in by_id["harness-eval-held-out-dry"]["command"]
        evidence = Path("mh-project/trace-evidence.md").read_text(encoding="utf-8")
        assert "- split held-in: 1" in evidence
        assert "- split held-out: 1" in evidence
        assert "- train [held-in]: train prompt" in evidence
        assert "- gate [held-out]: gate prompt" in evidence
