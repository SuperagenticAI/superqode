"""models.dev Labs discovery for local model recommendations."""

from click.testing import CliRunner

from superqode.commands.local import local
from superqode.local import labs


def _fake_models_dev():
    return {
        "zhipuai": {
            "models": {
                "glm-4.5-air": {
                    "name": "GLM-4.5-Air",
                    "tool_call": True,
                    "reasoning": True,
                    "structured": True,
                    "weights": {"open": True, "huggingface": "THUDM/GLM-4.5-Air"},
                    "limit": {"context": 131072, "output": 8192},
                    "modalities": {"input": ["text"]},
                },
                "glm-5.1": {
                    "name": "GLM-5.1",
                    "tool_call": True,
                    "weights": {"open": True},
                    "limit": {"context": 262144, "output": 16384},
                },
                "closed-glm": {
                    "name": "Closed GLM",
                    "tool_call": True,
                    "limit": {"context": 131072, "output": 8192},
                },
            }
        }
    }


def test_list_curated_labs_promotes_glm():
    rows = labs.list_curated_labs()

    assert rows[0].recommended is True
    assert any(row.id == "zhipuai" and "GLM" in row.name for row in rows)


def test_lab_models_mark_open_tool_long_context_glm(monkeypatch):
    monkeypatch.setattr(labs, "load_models_dev_api", lambda refresh=False: _fake_models_dev())

    rows = labs.list_lab_models("zhipuai")

    assert rows[0].id == "glm-4.5-air"
    assert rows[0].recommended_for_local is True
    assert rows[0].supports_tools is True
    assert rows[0].context_window == 131072
    assert "THUDM/GLM-4.5-Air" in rows[0].install_hint
    assert next(row for row in rows if row.id == "glm-5.1").recommended_for_local is False


def test_local_labs_cli_lists_curated_labs():
    result = CliRunner().invoke(local, ["labs"])

    assert result.exit_code == 0
    assert "zhipuai" in result.output
    assert "models.dev" not in result.output.lower()


def test_local_labs_cli_json_models(monkeypatch):
    monkeypatch.setattr(labs, "load_models_dev_api", lambda refresh=False: _fake_models_dev())

    result = CliRunner().invoke(local, ["labs", "zhipuai", "--json"])

    assert result.exit_code == 0
    assert '"id": "glm-4.5-air"' in result.output
    assert '"recommended_for_local": true' in result.output
