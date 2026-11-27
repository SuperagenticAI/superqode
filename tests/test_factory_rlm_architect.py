"""Tests for RLM On-Demand Software Factory architect."""

from __future__ import annotations

from types import SimpleNamespace
import json
import yaml

from superqode.factory.definition import read_mapping, validate_definition
from superqode.factory.rlm_architect import architect_factory


async def test_rlm_architect_inspects_python_repo_locally_without_model(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "billing-api"\n[tool.pytest.ini_options]\naddopts = "-q"\n',
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text("def check_token(): return True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_auth.py").write_text("def test_ok(): assert True\n")
    (tmp_path / ".env").write_text("SECRET_KEY=must-never-be-read\n", encoding="utf-8")

    result = await architect_factory(tmp_path, description="Keep auth changes safe")

    assert result["proposal_only"] is True
    data = read_mapping(result["yaml"])
    validate_definition(data)
    assert data["improvement"]["checks"]["regression"]["command"] == "pytest -q"
    # Sensitive auth path automatically steers toward two-gate triage-spec-build.
    assert result["rlm_lineage"]["recommended_workflow"] == "triage-spec-build"
    assert "python" in result["rlm_lineage"]["detected_stacks"]
    assert ".env" not in result["rlm_lineage"]["files_inspected"]
    assert "pyproject.toml" in result["rlm_lineage"]["files_inspected"]
    assert result["rlm_lineage"]["mode"] == "rlm-local-inspect"
    skill_names = {s["name"] for s in result["recommended_skills"]}
    assert skill_names == {"merge-risk", "ui-verification"}


async def test_rlm_architect_detects_web_stack_and_runs_bounded_subcalls(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "name": "web-dashboard",
                "scripts": {"test": "vitest run", "build": "vite build"},
                "dependencies": {"react": "^19.0.0"},
                "devDependencies": {"@playwright/test": "^1.50.0"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.tsx").write_text("export function App() { return <div />; }\n")

    calls = []
    base = {"default_route": "best"}

    class FakeGateway:
        async def chat_completion(self, *, messages, model, provider, **kwargs):
            calls.append((provider, model, messages[0].content))
            if "architecture" in messages[0].content or "stage_guidance" in messages[0].content:
                payload = {
                    "workflow": "triage-spec-build",
                    "stage_guidance": {
                        "implement": "Keep React components modular and update tests."
                    },
                    "assumptions": ["Detected React + Vite frontend with Playwright tests."],
                }
            else:
                payload = {
                    "test_command": "npm test",
                    "ui_preset": "web",
                    "requirements": {
                        "ui-proof": "Capture Playwright screenshots for changed views."
                    },
                    "gotchas": ["Run vite build before Playwright smoke checks."],
                }
            return SimpleNamespace(
                content=json.dumps(payload),
                usage=SimpleNamespace(prompt_tokens=120, completion_tokens=45),
            )

    result = await architect_factory(
        tmp_path,
        description="Build features safely with visual verification",
        provider="openai",
        model="gpt-5-mini",
        gateway=FakeGateway(),
        yaml_text=yaml.safe_dump(base),
    )

    assert len(calls) == 2
    assert result["rlm_lineage"]["mode"] == "rlm-live"
    assert result["rlm_lineage"]["subcall_budget"]["used_calls"] == 2
    assert result["rlm_lineage"]["subcall_budget"]["total_tokens"] == 330
    ui_skill = next(s for s in result["recommended_skills"] if s["name"] == "ui-verification")
    assert ui_skill["preset"] == "web"
    data = read_mapping(result["yaml"])
    validate_definition(data)
    assert data["improvement"]["checks"]["regression"]["command"] == "npm test"
    assert "ui-proof" in data["data_context"]["requirements"]


async def test_rlm_architect_preserves_existing_release_authority(tmp_path):
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from superqode.factory.templates import factory_template

    key = ec.generate_private_key(ec.SECP256R1())
    pub_b64 = base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    ).decode()

    (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")
    existing = factory_template("fix-and-verify")
    existing["metadata"]["name"] = "pinned-app"
    existing["governance"]["release_authority"] = {
        "method": "p256-signature",
        "keys": {"owner": {"public_key": pub_b64}},
        "challenge_ttl_seconds": 120,
    }
    result = await architect_factory(
        tmp_path,
        description="Upgrade to two gates",
        workflow="continuous-outcomes",
        yaml_text=yaml.safe_dump(existing, sort_keys=False),
    )
    updated = read_mapping(result["yaml"])
    validate_definition(updated)
    assert updated["governance"]["release_authority"] == existing["governance"]["release_authority"]
    assert updated["orchestration"] == existing["orchestration"]
    assert any(
        "Requested starter `continuous-outcomes` was not applied" in item
        for item in result["assumptions"]
    )


async def test_authoring_architect_stores_reviewable_draft_without_writing_factory(tmp_path):
    from superqode.factory import authoring

    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo-svc"\n', encoding="utf-8")
    (tmp_path / "app.py").write_text("def run(): return 1\n", encoding="utf-8")

    draft = await authoring.architect(tmp_path)
    assert draft["proposal_only"] is True
    assert draft["written"] is False
    assert not (tmp_path / ".superqode" / "factory.yaml").exists()
    assert draft["rlm_lineage"]["repo_files"] == 2
    assert len(draft["recommended_skills"]) == 2


async def test_architect_factory_applies_explicit_cloud_route_and_execution_model_for_new_draft(
    tmp_path,
):
    import yaml

    (tmp_path / "app.py").write_text("def total(values): return 0\n", encoding="utf-8")

    proposal = await architect_factory(
        tmp_path,
        description="Fix bugs and verify the repair",
        allow_cloud=True,
        execution_model="grok-cli/grok-4.7",
        use_monty=False,
    )
    spec = yaml.safe_load(proposal["yaml"])
    assert spec["default_route"] == "best"
    assert spec["inference"]["harnesses"]["coder"]["model"] == "grok-cli/grok-4.7"
