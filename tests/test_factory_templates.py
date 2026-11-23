"""Starter factories built from a description, with no model call."""

import asyncio

import pytest
import yaml

from superqode.factory.definition import validate_definition
from superqode.factory.generation import proposal_from_description
from superqode.factory.templates import TEMPLATE_NAMES, compose_from_description, factory_template


def _run(request):
    from superqode.desktop_service.factory_studio import run

    captured = {}

    def emit(kind, payload):
        captured[kind] = payload

    asyncio.run(run(request, emit))
    return captured["result"]


def test_every_starter_is_a_valid_factory():
    assert TEMPLATE_NAMES == (
        "fix-and-verify",
        "continuous-outcomes",
        "build-test-deploy",
        "kanban",
        "scrum",
        "xp",
        "lean",
    )
    for name in TEMPLATE_NAMES:
        validate_definition(factory_template(name))


def test_a_build_test_deploy_description_becomes_that_workflow():
    data = compose_from_description("build me software factory for build test and deploy workflow")
    validate_definition(data)
    assert [stage["id"] for stage in data["orchestration"]["stages"]] == ["build", "test", "deploy"]
    assert data["metadata"]["name"] == "build-test-deploy"
    assert data["metadata"]["description"].startswith("build me software factory")
    proposal = proposal_from_description(
        "build me software factory for build test and deploy workflow"
    )
    assert proposal["proposal_only"] is True
    assert "No model was called" in proposal["assumptions"][0]
    assert yaml.safe_load(proposal["yaml"])["metadata"]["name"] == "build-test-deploy"


def test_agile_words_and_the_selected_workflow_choose_the_starter():
    assert compose_from_description("Run this as Kanban")["metadata"]["name"] == "kanban"
    assert compose_from_description("One sprint slice")["metadata"]["name"] == "scrum"
    assert compose_from_description("Use XP")["metadata"]["name"] == "xp"
    assert compose_from_description("Keep the slice lean")["metadata"]["name"] == "lean"
    selected = compose_from_description("Ship the next slice", workflow="scrum")
    assert [stage["id"] for stage in selected["orchestration"]["stages"]] == [
        "refine",
        "build",
        "review",
        "retro",
    ]
    # Words in the description win over the picker.
    named = compose_from_description("Use a Kanban board", workflow="scrum")
    assert named["metadata"]["name"] == "kanban"


def test_a_private_route_cloud_model_falls_back_to_the_description(monkeypatch):
    async def rejected(**kwargs):
        raise ValueError("This factory's private route requires a local drafting model")

    monkeypatch.setattr("superqode.factory.generation.generate_factory", rejected)

    result = _run(
        {
            "factory_action": "generate",
            "cwd": ".",
            "description": "build me software factory for build test and deploy workflow",
            "provider": "openai",
            "model": "gpt-4o",
            "yaml": "ignored",
            "workflow": "kanban",
        }
    )
    data = yaml.safe_load(result["yaml"])
    assert data["metadata"]["name"] == "build-test-deploy"
    assert result["proposal_only"] is True


def test_other_generation_errors_still_surface(monkeypatch):
    async def rejected(**kwargs):
        raise ValueError("Model must return a JSON factory proposal")

    monkeypatch.setattr("superqode.factory.generation.generate_factory", rejected)

    with pytest.raises(ValueError, match="JSON factory proposal"):
        _run(
            {
                "factory_action": "generate",
                "cwd": ".",
                "description": "Ship the next slice",
                "provider": "ollama",
                "model": "qwen3:8b",
                "yaml": "ignored",
                "workflow": "lean",
            }
        )


def test_no_model_uses_the_selected_workflow():
    result = _run(
        {
            "factory_action": "generate",
            "cwd": ".",
            "description": "Ship the next slice",
            "provider": "",
            "model": "",
            "yaml": "",
            "workflow": "lean",
        }
    )
    data = yaml.safe_load(result["yaml"])
    assert [stage["id"] for stage in data["orchestration"]["stages"]] == [
        "value",
        "build",
        "check",
        "improve",
    ]


def test_punctuation_does_not_prevent_workflow_detection():
    assert compose_from_description("Use Kanban, please.")["metadata"]["name"] == "kanban"
    assert compose_from_description("We do scrum.")["metadata"]["name"] == "scrum"
    assert compose_from_description("We use XP!")["metadata"]["name"] == "xp"
    assert compose_from_description("Keep it lean.")["metadata"]["name"] == "lean"
    assert compose_from_description("Build, test.")["metadata"]["name"] == "build-test-deploy"
    assert (
        compose_from_description("Build, test, deploy")["metadata"]["name"] == "build-test-deploy"
    )
