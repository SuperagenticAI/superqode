"""CLI parity with the macOS app: init, describe, sources commit, check and decide."""
# ruff: noqa: F401, F811

import asyncio
import json

from click.testing import CliRunner
import pytest
import yaml

from test_factory_definition import project, git, rewrite
from superqode.commands.factory import factory
from superqode.factory import authoring
from superqode.factory.definition import load_factory
from superqode.providers.gateway import GatewayResponse
from superqode.session.factory import SoftwareFactory


def invoke(*args):
    return CliRunner().invoke(factory, list(args))


def test_init_template_writes_a_full_factory_spec_and_keeps_routes(project):
    path = project / ".superqode/factory.yaml"
    path.write_text("default_route: cheap\nroutes:\n  cheap:\n    prefer: [local/test]\n")
    result = invoke("init", "--project", str(project), "--template", "continuous-outcomes")
    assert result.exit_code == 0, result.output
    assert "✅" in result.output
    data = yaml.safe_load(path.read_text())
    assert data["apiVersion"] and data["metadata"]["name"] == "continuous-outcomes"
    assert data["default_route"] == "cheap" and "cheap" in data["routes"]
    assert not load_factory(root=project).legacy
    revisions = list((project / ".superqode/factory-studio/revisions").glob("*.yaml"))
    assert len(revisions) == 2  # the new revision and the preserved route policy
    again = invoke("init", "--project", str(project))
    assert again.exit_code != 0 and "--force" in again.output
    forced = invoke("init", "--project", str(project), "--force", "--json")
    assert forced.exit_code == 0 and json.loads(forced.output)["template"] == "fix-and-verify"


def test_init_policy_writes_factory_spec_by_default_and_routes_only_on_request(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".superqode").mkdir()
    path = SoftwareFactory(storage_dir=".superqode/sessions").init_policy()
    data = yaml.safe_load(path.read_text())
    assert data["kind"] == "Factory" and data["default_route"] == "no-subscription"
    assert SoftwareFactory(storage_dir=".superqode/sessions").policy()["routes"]
    legacy = SoftwareFactory(storage_dir=".superqode/sessions").init_policy(
        force=True, routes_only=True
    )
    assert "apiVersion" not in yaml.safe_load(legacy.read_text())


class Gateway:
    def __init__(self, text):
        self.text = text

    async def chat_completion(self, **kwargs):
        assert kwargs["tools"] == []
        return GatewayResponse(
            content=json.dumps(
                {"yaml": self.text, "assumptions": ["Fixture"], "missing_capabilities": []}
            )
        )


def test_describe_drafts_without_writing_and_saves_only_when_confirmed(project):
    path = project / ".superqode/factory.yaml"
    before = path.read_text()
    proposed = yaml.safe_load(before)
    proposed["metadata"]["description"] = "Drafted from a team description"
    text = yaml.safe_dump(proposed, sort_keys=False)
    draft = asyncio.run(
        authoring.draft(
            project, "We fix bugs", provider="ollama", model="qwen3:8b", gateway=Gateway(text)
        )
    )
    assert draft["written"] is False and draft["proposal_only"]
    assert "Drafted from a team description" in draft["diff"]
    assert path.read_text() == before
    denied = invoke("describe", "--project", str(project), "--apply", draft["digest"])
    assert denied.exit_code != 0 and "Confirm" in denied.output
    assert path.read_text() == before
    saved = invoke("describe", "--project", str(project), "--apply", draft["digest"], "--confirm")
    assert saved.exit_code == 0, saved.output
    assert path.read_text() == text


def test_describe_draft_is_rejected_when_the_factory_changed(project):
    path = project / ".superqode/factory.yaml"
    proposed = yaml.safe_load(path.read_text())
    proposed["metadata"]["description"] = "Draft"
    draft = asyncio.run(
        authoring.draft(
            project,
            "We fix bugs",
            provider="ollama",
            model="qwen3:8b",
            gateway=Gateway(yaml.safe_dump(proposed, sort_keys=False)),
        )
    )
    rewrite(project, lambda d: d["metadata"].update(description="Changed meanwhile"))
    with pytest.raises(ValueError, match="changed"):
        authoring.apply_draft(project, draft["digest"], reason="Save", confirmed=True)


def test_describe_without_a_model_stores_a_starter(project):
    path = project / ".superqode/factory.yaml"
    before = path.read_text()
    result = invoke(
        "describe",
        "--project",
        str(project),
        "build me software factory for build test and deploy workflow",
        "--json",
    )
    assert result.exit_code == 0, result.output
    draft = json.loads(result.output)
    assert draft["written"] is False and "No model was called" in draft["assumptions"][0]
    assert yaml.safe_load(draft["yaml"])["metadata"]["name"] == "build-test-deploy"
    assert path.read_text() == before
    saved = invoke(
        "describe",
        "--project",
        str(project),
        "--apply",
        draft["digest"],
        "--confirm",
        "--reason",
        "Reviewed starter",
    )
    assert saved.exit_code == 0, saved.output
    assert yaml.safe_load(path.read_text())["metadata"]["name"] == "build-test-deploy"


def test_describe_uses_the_workflow_flag_and_rejects_a_bare_model(project):
    missing = invoke("describe", "--project", str(project))
    assert missing.exit_code != 0 and "sq factory workflows" in missing.output
    bare = invoke("describe", "--project", str(project), "Ship the next slice", "--model", "ollama")
    assert bare.exit_code != 0 and "provider/model" in bare.output
    selected = invoke(
        "describe",
        "--project",
        str(project),
        "Ship the next slice",
        "--workflow",
        "lean",
        "--json",
    )
    assert selected.exit_code == 0, selected.output
    assert yaml.safe_load(json.loads(selected.output)["yaml"])["metadata"]["name"] == "lean"


def test_workflows_lists_every_starter():
    result = invoke("workflows")
    assert result.exit_code == 0, result.output
    for name in (
        "fix-and-verify",
        "continuous-outcomes",
        "build-test-deploy",
        "kanban",
        "scrum",
        "xp",
        "lean",
    ):
        assert name in result.output


def test_a_private_route_cloud_model_falls_back_in_the_cli_engine(project, monkeypatch):
    async def rejected(**kwargs):
        raise ValueError("This factory's private route requires a local drafting model")

    monkeypatch.setattr("superqode.factory.generation.generate_factory", rejected)
    draft = asyncio.run(
        authoring.draft(
            project,
            "Use a Kanban board",
            provider="openai",
            model="gpt-4o",
            workflow="scrum",
        )
    )
    assert yaml.safe_load(draft["yaml"])["metadata"]["name"] == "kanban"
    assert "No model was called" in draft["assumptions"][0]


def test_other_model_errors_still_surface(project, monkeypatch):
    async def rejected(**kwargs):
        raise ValueError("Model must return a JSON factory proposal")

    monkeypatch.setattr("superqode.factory.generation.generate_factory", rejected)
    with pytest.raises(ValueError, match="JSON factory proposal"):
        asyncio.run(
            authoring.draft(project, "Ship the next slice", provider="ollama", model="qwen3:8b")
        )


def test_sources_commit_requires_review_digest_and_confirmation(project):
    git(project, "config", "commit.gpgsign", "false")
    inspected = invoke("sources", "inspect", "--project", str(project))
    assert inspected.exit_code == 0, inspected.output
    review = json.loads(inspected.output)
    args = [
        "sources",
        "commit",
        "--project",
        str(project),
        "--digest",
        review["digest"],
        "--path",
        ".superqode/factory.yaml",
        "--message",
        "Version the Factory",
    ]
    assert invoke(*args).exit_code != 0
    stale = list(args)
    stale[stale.index(review["digest"])] = "sha256:" + "0" * 64
    assert "changed since review" in invoke(*stale, "--confirm").output
    committed = invoke(*args, "--confirm")
    assert committed.exit_code == 0, committed.output
    assert json.loads(committed.output)["pushed"] is False
    assert git(project, "log", "-1", "--format=%s") == "Version the Factory"


def test_check_and_show_render_status_emoji(project):
    result = invoke("check", "--project", str(project))
    assert "[configured]" in result.output and "→" in result.output
    shown = invoke("show", "--project", str(project))
    assert shown.exit_code == 0, shown.output
    assert "Release: SuperGauge L2" in shown.output


def test_decide_lists_what_is_missing(project, monkeypatch):
    from test_factory_verification import make_completed

    root, store, run = make_completed(project, monkeypatch)
    result = invoke("decide", "--project", str(root), run)
    assert result.exit_code == 2
    assert "⛔ Release blocked" in result.output
    assert "Protected verification has not run" in result.output
    assert "release_authority" in result.output


def test_trial_queues_without_running_agents(project):
    result = invoke("trial", "--project", str(project), "Fix the answer", "--json")
    assert result.exit_code == 0, result.output
    queued = json.loads(result.output)
    assert queued["execution_started"] is False and queued["status"] == "queued"
