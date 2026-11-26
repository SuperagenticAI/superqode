"""Model onboarding explains privacy and availability without inference."""

import json

from click.testing import CliRunner
import pytest
import yaml

from test_factory_definition import project  # noqa: F401
from superqode.commands.factory import factory
from superqode.factory.generation import check_generation_route
from superqode.factory.model_setup import inspect_models


def test_fresh_project_needs_no_drafting_model_and_writes_nothing(tmp_path):
    report = inspect_models(tmp_path)
    assert report["drafting"]["state"] == "starter-only"
    assert report["execution"] == []
    assert report["model_calls"] == 0
    assert not list(tmp_path.iterdir())


def test_private_cloud_conflict_precedes_connection_check(project):
    original = (project / ".superqode/factory.yaml").read_bytes()
    calls = []
    report = inspect_models(
        project,
        drafting_model="openai/frontier",
        check_connection=lambda *args: calls.append(args)
        or {"ready": True, "state": "model-discovered", "message": "Discovered"},
    )
    assert report["drafting"]["state"] == "privacy-blocked"
    assert report["drafting"]["next_step"] == "review-privacy"
    assert "explicitly" in report["drafting"]["message"]
    assert calls and all(provider != "openai" for provider, _, _ in calls)
    assert (project / ".superqode/factory.yaml").read_bytes() == original


def test_cloud_key_and_execution_selection_are_independent(project):
    data = yaml.safe_load((project / ".superqode/factory.yaml").read_text())
    data["default_route"] = "best"
    checked = []

    def check(provider, model, binding):
        checked.append((provider, model, binding))
        return {"ready": False, "state": "missing-credential", "message": "Connect this provider."}

    report = inspect_models(
        project,
        yaml_text=yaml.safe_dump(data),
        drafting_model="anthropic/frontier",
        check_connection=check,
    )
    assert report["drafting"]["state"] == "missing-credential"
    assert report["drafting"]["next_step"] == "connect-provider"
    assert report["execution"]
    assert all(row["provider"] == "ollama" for row in report["execution"])
    assert any(provider == "anthropic" for provider, _, _ in checked)
    assert not any(row["inference_verified"] for row in report["execution"])


def test_discovered_model_separates_drafting_from_execution_evidence(project):
    report = inspect_models(
        project,
        drafting_model="ollama/local-coder",
        check_connection=lambda *args: {
            "ready": True,
            "state": "model-discovered",
            "message": "Found locally",
        },
    )
    assert report["drafting"]["eligible"] is True
    assert report["drafting"]["inference_verified"] is False
    assert report["drafting"]["next_step"] == "generate-draft"
    assert report["execution"][0]["next_step"] == "run-trial"


def test_missing_execution_component_does_not_block_connecting_drafter(project):
    data = yaml.safe_load((project / ".superqode/factory.yaml").read_text())
    data["inference"]["harnesses"]["coder"] = {"path": "missing-harness.yaml"}
    report = inspect_models(
        project, yaml_text=yaml.safe_dump(data), drafting_model="ollama/drafter"
    )
    assert report["drafting"]["eligible"] is True
    assert not report["execution_configured"]
    assert report["execution_error"]


def test_failed_connection_keeps_other_routes_and_hides_diagnostic(project):
    def check(provider, model, binding):
        if model == "offline":
            raise OSError("https://user:private-key@unreachable.invalid")
        return {"ready": True, "state": "model-discovered", "message": "Found"}

    report = inspect_models(project, drafting_model="ollama/offline", check_connection=check)
    assert report["drafting"]["state"] == "connection-unavailable"
    assert report["execution"][0]["state"] == "model-discovered"
    assert "private-key" not in json.dumps(report)


def test_cloud_fallback_is_reported_separately_under_private_route(project):
    from superqode.factory.authoring import inspect_definition

    data = yaml.safe_load((project / ".superqode/factory.yaml").read_text())
    (project / "harness.yaml").write_text(
        "inherits: core\nmodel_policy:\n  primary: ollama/test\n  fallbacks: [openai/frontier]\n"
    )
    data["inference"]["harnesses"]["coder"] = {"path": "harness.yaml"}
    report = inspect_models(project, yaml_text=yaml.safe_dump(data))
    assert len(report["execution"]) == 2
    assert report["execution"][0]["state"] == "unchecked"
    assert report["execution"][1]["fallback"] is True
    assert report["execution"][1]["state"] == "privacy-blocked"
    review = inspect_definition(project, yaml.safe_dump(data))
    assert any(
        "coder fallback:" in warning and "local models only" in warning
        for warning in review["warnings"]
    )


@pytest.mark.parametrize(
    "reference", ["acp/codex", "ollama/text-embed", "unknown/model", "bare-model"]
)
def test_unsuitable_models_have_actionable_feedback(project, reference):
    row = inspect_models(project, drafting_model=reference)["drafting"]
    assert row["state"] == "unsupported"
    assert row["eligible"] is False
    assert row["next_step"] == "choose-model"


@pytest.mark.parametrize(
    "provider", ["local-openai", "apple-foundation", "swift-mlx", "mlx", "ds4", "sglang", "tgi"]
)
def test_supported_local_runtime_can_draft_on_private_route(provider, project):
    from superqode.factory import compile_factory, load_factory, resolve_factory
    from superqode.session.factory import classify_model_ref

    assert "LOCAL" in classify_model_ref(provider + "/local-model")["tags"]
    check_generation_route({}, provider, "local-model")
    path = project / ".superqode/factory.yaml"
    data = yaml.safe_load(path.read_text())
    data["inference"]["harnesses"]["coder"]["model"] = provider + "/local-model"
    path.write_text(yaml.safe_dump(data))
    compile_factory(
        resolve_factory(load_factory(root=project)), root=project, goal="Check local route"
    )


def test_cloud_variant_of_local_provider_stays_blocked():
    with pytest.raises(ValueError, match="private route"):
        check_generation_route({}, "ollama-cloud", "cloud-model")


def test_cli_reports_setup_without_modifying_project(project):
    result = CliRunner().invoke(
        factory, ["models", "--project", str(project), "--draft-model", "openai/frontier", "--json"]
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["drafting"]["state"] == "privacy-blocked"
    assert report["connections_checked"] is False


def test_desktop_uses_project_connection_checker_and_binding(project, tmp_path, monkeypatch):
    from superqode.desktop_service.service import DesktopService

    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    service = DesktopService(tmp_path / "desktop")
    identity = service.open_project(str(project))["id"]
    dispatch = service.dispatch
    calls = []

    def checked(method, params):
        if method == "providers.check":
            calls.append(params)
            return {"ready": True, "state": "local-model-advertised", "message": "Found"}
        return dispatch(method, params)

    monkeypatch.setattr(service, "dispatch", checked)
    try:
        report = checked(
            "factory.models.inspect",
            {
                "project": identity,
                "drafting_model": "ollama/drafter",
                "drafting_harness": "selected-harness",
                "check_connections": True,
            },
        )
        assert report["execution"]
        assert calls and all(row["project"] == identity and row["harness"] for row in calls)
        assert (
            next(row for row in calls if row["model"] == "drafter")["harness"] == "selected-harness"
        )
        assert report["model_calls"] == 0
    finally:
        service.close()


def test_cloud_permission_control_edits_only_reviewable_draft(project, tmp_path, monkeypatch):
    from superqode.desktop_service.service import DesktopService

    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path / "home"))
    service = DesktopService(tmp_path / "desktop")
    identity = service.open_project(str(project))["id"]
    path = project / ".superqode/factory.yaml"
    original = path.read_text()
    before = yaml.safe_load(original)
    try:
        result = service.dispatch(
            "factory.edit",
            {
                "project": identity,
                "yaml": original,
                "controls": {"default_route": "best"},
            },
        )
        after = yaml.safe_load(result["yaml"])
        assert after["default_route"] == "best"
        assert after["inference"] == before["inference"]
        assert after["governance"] == before["governance"]
        assert path.read_text() == original
        check_generation_route(after, "openai", "frontier")
        with pytest.raises(ValueError, match="existing Factory route"):
            service.dispatch(
                "factory.edit",
                {
                    "project": identity,
                    "yaml": original,
                    "controls": {"default_route": "unknown"},
                },
            )
    finally:
        service.close()
