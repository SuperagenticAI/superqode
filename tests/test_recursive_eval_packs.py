from pathlib import Path

from click.testing import CliRunner

from superqode.harness import eval_pack_path, list_eval_packs, load_eval_tasks
from superqode.main import cli_main


def test_local_recursive_eval_pack_is_discoverable_and_loadable():
    packs = {item["id"]: item for item in list_eval_packs()}

    assert "local-recursive-smoke" in packs
    assert packs["local-recursive-smoke"]["tasks"] == 1
    assert "local-dynamic-workflow-smoke" in packs
    assert packs["local-dynamic-workflow-smoke"]["tasks"] == 1

    path = eval_pack_path("local-recursive-smoke")
    loaded = load_eval_tasks(path)

    assert loaded["metadata"]["id"] == "local-recursive-smoke"
    assert loaded["tasks"][0]["id"] == "ci-log-root-cause"
    assert "context_handle" in loaded["tasks"][0]["prompt"]
    assert "spawn_harness" in loaded["tasks"][0]["prompt"]

    dynamic = load_eval_tasks(eval_pack_path("local-dynamic-workflow-smoke"))
    assert dynamic["metadata"]["id"] == "local-dynamic-workflow-smoke"
    assert dynamic["tasks"][0]["id"] == "ci-log-dynamic-root-cause"
    assert "dynamic_workflow_script" in dynamic["tasks"][0]["prompt"]


def test_local_recursive_eval_fixture_exists():
    pack = eval_pack_path("local-recursive-smoke")
    fixture = pack.parents[1] / "eval_fixtures" / "ci-root-cause.log"

    assert fixture.exists()
    assert "ROOT_CAUSE:" in fixture.read_text(encoding="utf-8")

    dynamic_fixture = pack.parents[1] / "eval_fixtures" / "ci-dynamic-root-cause.log"
    assert dynamic_fixture.exists()
    assert "downstream" in eval_pack_path("local-dynamic-workflow-smoke").read_text(
        encoding="utf-8"
    )


def test_harness_eval_packs_cli_lists_and_resolves_pack():
    runner = CliRunner()

    listed = runner.invoke(cli_main, ["harness", "eval-packs", "--json"])
    assert listed.exit_code == 0
    assert "local-recursive-smoke" in listed.output
    assert "local-dynamic-workflow-smoke" in listed.output

    resolved = runner.invoke(cli_main, ["harness", "eval-packs", "local-recursive-smoke"])
    assert resolved.exit_code == 0
    assert Path(resolved.output.strip()).name == "local_recursive_smoke.yaml"

    dynamic = runner.invoke(cli_main, ["harness", "eval-packs", "local-dynamic-workflow-smoke"])
    assert dynamic.exit_code == 0
    assert Path(dynamic.output.strip()).name == "local_dynamic_workflow_smoke.yaml"
