"""Strands selection contracts across the CLI, ACP, TUI and desktop catalog."""

import sys
from pathlib import Path

from click.testing import CliRunner
import pytest
from textual.app import App

from superqode.acp.server import SuperQodeAcpAgent
from superqode.app.harness_picker import harness_picker_items
from superqode.commands.serve import serve
from superqode.desktop_service.connect_workflow import connection_menu
from superqode.widgets.harness_hub import HarnessHubResult, HarnessHubScreen


@pytest.mark.parametrize("reference", ["strands", "aws-strands"])
def test_acp_selects_strands_before_project_discovery(tmp_path, monkeypatch, reference):
    monkeypatch.setenv("SUPERQODE_ACP_SPEC", "template:core")
    spec = SuperQodeAcpAgent(harness=reference)._load_spec(tmp_path)
    assert spec.runtime.backend == "strands"
    assert spec.execution_policy.allow_read
    assert not spec.execution_policy.allow_write
    assert not spec.execution_policy.allow_shell


@pytest.mark.parametrize("env_selection", [False, True])
def test_acp_cli_dispatches_named_harness(monkeypatch, env_selection):
    from superqode.acp import server

    calls = []

    async def run(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(server, "run_acp_server", run)
    monkeypatch.delenv("SUPERQODE_ACP_HARNESS", raising=False)
    if env_selection:
        monkeypatch.setenv("SUPERQODE_ACP_HARNESS", "strands")
    arguments = ["acp", "--provider", "ollama", "--model", "fixture"]
    if not env_selection:
        arguments += ["--harness", "strands"]
    result = CliRunner().invoke(serve, arguments)
    assert result.exit_code == 0, result.output
    assert calls[0]["harness"] == "strands"
    assert calls[0]["provider"] == "ollama"
    assert calls[0]["model"] == "fixture"


def test_acp_cli_rejects_conflicting_or_unknown_harness(tmp_path):
    for extra in (["--dir", str(tmp_path)], ["--spec", str(Path(__file__))]):
        result = CliRunner().invoke(serve, ["acp", "--harness", "strands", *extra])
        assert result.exit_code == 1
        assert "Pass only one" in result.output
    result = CliRunner().invoke(serve, ["acp", "--harness", "unknown-harness-name"])
    assert result.exit_code == 1
    assert "Unknown harness" in result.output


def test_strands_appears_in_terminal_and_gui_connect_menus(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_STRANDS_PYTHON", sys.executable)
    terminal = harness_picker_items(tmp_path, include_all=False, include_live_registry=False)
    item = next(item for item in terminal if item.id == "strands")
    assert item.available
    assert item.runtime == "strands"
    gui = connection_menu(tmp_path, "open-harnesses")["rows"]
    row = next(row for row in gui if row["id"] == "strands")
    assert row["harness_ref"] == "strands"
    assert row["connector"] == "key-harness"


def test_strands_missing_runtime_has_setup_guidance(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_STRANDS_PYTHON", str(tmp_path / "missing-python"))
    items = harness_picker_items(tmp_path, include_all=False, include_live_registry=False)
    item = next(item for item in items if item.id == "strands")
    assert not item.available
    assert "superqode harness strands setup" in item.issue
    assert not item.install_extra  # The isolated runtime is never installed into core.


@pytest.mark.asyncio
async def test_tui_hub_can_select_strands(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERQODE_STRANDS_PYTHON", sys.executable)
    items = harness_picker_items(tmp_path, include_all=False, include_live_registry=False)
    item = next(item for item in items if item.id == "strands")
    app = App()
    selected = []
    async with app.run_test(size=(100, 34)) as pilot:
        app.push_screen(HarnessHubScreen([item]), callback=selected.append)
        await pilot.pause()
        assert await pilot.click("#hub-use")
        await pilot.pause()
    assert selected == [HarnessHubResult("use", "strands")]


def test_hub_open_filter_and_setup_steps_include_strands(tmp_path, monkeypatch):
    from superqode.harness.hub import build_hub_index, filter_hub_records

    monkeypatch.setenv("SUPERQODE_STRANDS_PYTHON", str(tmp_path / "missing-python"))
    items = harness_picker_items(tmp_path, include_all=False, include_live_registry=False)
    item = next(item for item in items if item.id == "strands")
    records = build_hub_index(items=[item])["items"]
    records = filter_hub_records(records, openness="open")
    assert len(records) == 1
    record = records[0]
    assert record["id"] == "strands"
    assert record["language"] == "Python"
    assert record["license"] == "Apache-2.0"
    assert record["install_command"] == "superqode harness strands setup"
    assert record["docs_url"].endswith("/advanced/strands-harness/")
    assert any("serve acp --harness strands" in command for command in record["cli_commands"])
