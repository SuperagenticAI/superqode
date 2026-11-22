"""Headless clients preserve the engine's policy and explicit execution boundary."""
# ruff: noqa: F401, F811

import asyncio
import json

from click.testing import CliRunner
import pytest

from test_factory_definition import project
from test_factory_improvement import prepared, proposed
from superqode.commands.factory import factory
from superqode.factory import improvement
from superqode.mcp.factory_server import build_factory_mcp_server


def invoke(root, *args):
    return CliRunner().invoke(factory, ["improve", *args, "--project", str(root)])


def test_cli_prepares_and_reopens_same_pinned_contract(prepared):
    root, plan = prepared
    result = invoke(root, "inspect", plan["id"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["plan"]["digest"] == plan["digest"]
    assert data["budget"]["request_count"] == 0
    result = invoke(
        root,
        "prepare",
        "--binding",
        "coder",
        "--tasks",
        plan["tasks"],
        "--fixture",
        "fixture",
        "--max-seconds",
        "60",
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["optimizer_engine"] == "evaluator-optimizer"


@pytest.mark.parametrize("action", ["search", "compare"])
def test_cli_never_executes_without_live(prepared, monkeypatch, action):
    root, plan = prepared

    def forbidden(*args, **kwargs):
        pytest.fail("Unconfirmed command invoked a model action")

    monkeypatch.setattr(improvement, "optimize", forbidden)
    monkeypatch.setattr(improvement, "compare", forbidden)
    args = [action, plan["id"]]
    if action == "compare":
        args += ["a" * 64]
    result = invoke(root, *args, "--digest", plan["digest"])
    assert result.exit_code != 0 and "--live" in result.output


def test_cli_external_scores_cannot_produce_adoption(prepared):
    root, plan = prepared
    candidate = proposed(root, plan)
    before = (root / ".superqode/factory.yaml").read_bytes()
    result = invoke(
        root,
        "draft",
        plan["id"],
        candidate["candidate"],
        "--receipt",
        "sha256:" + "a" * 64,
        "--confirm",
    )
    assert result.exit_code != 0
    assert (root / ".superqode/factory.yaml").read_bytes() == before


def test_mcp_scope_and_execution_are_explicit(prepared):
    root, plan = prepared
    server = build_factory_mcp_server(root)

    async def check():
        tools = await server.list_tools()
        assert not any(t.name in {"factory_apply", "factory_approve"} for t in tools)
        assert await server.call_tool("factory_resolve", {}) is not None
        with pytest.raises(Exception, match="allow-execution"):
            await server.call_tool(
                "factory_improvement_search",
                {"plan": plan["id"], "digest": plan["digest"], "confirmed": True},
            )
        with pytest.raises(Exception, match="Confirm preparing"):
            await server.call_tool(
                "factory_improvement_prepare",
                {"binding": "coder", "tasks": plan["tasks"], "fixture": "fixture"},
            )

    asyncio.run(check())


def test_mcp_prevents_project_escape_and_stages_no_release(prepared):
    root, plan = prepared
    server = build_factory_mcp_server(root)

    async def check():
        with pytest.raises(Exception):
            await server.call_tool("factory_improvement_inspect", {"plan": "../outside"})
        text = improvement.baseline_proposal(root, plan)
        assert (
            await server.call_tool(
                "factory_improvement_stage",
                {"plan": plan["id"], "proposal": text, "confirmed": True},
            )
            is not None
        )

    asyncio.run(check())


def test_mcp_can_compile_and_submit_without_inference(project):
    from superqode.factory.compiler import compile_factory, materialize_snapshot
    from superqode.factory.definition import load_factory
    from superqode.factory.snapshot import resolve_factory
    from superqode.factory.runtime import factory_store

    plan = compile_factory(
        resolve_factory(load_factory(root=project)), root=project, goal="Inspect a fixture"
    )
    materialize_snapshot(plan)
    server = build_factory_mcp_server(project)

    async def check():
        args = {"plan": plan.to_dict(), "request_id": "mcp-fixture", "confirmed": True}
        assert await server.call_tool("factory_submit", args) is not None
        assert await server.call_tool("factory_submit", args) is not None

    asyncio.run(check())
    orders = factory_store(project, read_only=True).list()
    assert len(orders) == 1 and all(t.attempts == 0 for t in orders[0].tasks)


def test_mcp_resolve_does_not_publish_protected_evaluator_contents(project):
    from test_factory_definition import rewrite

    (project / "protected-grader.txt").write_text("SEALED_EVALUATOR_CONTENT_MUST_NOT_BE_PUBLISHED")
    rewrite(
        project,
        lambda d: d["data_context"]["files"].update(
            grader={"path": "protected-grader.txt", "purpose": "evaluator"}
        ),
    )
    server = build_factory_mcp_server(project)
    result = asyncio.run(server.call_tool("factory_resolve", {}))
    assert "SEALED_EVALUATOR_CONTENT" not in str(result)
