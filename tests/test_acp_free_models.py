import pytest

from superqode.app_main import SuperQodeApp
from superqode.providers.acp_free_models import _parse_opencode_models_for_free
from superqode.providers.acp_models import get_acp_agent_models
from superqode.providers.opencode_models import _parse_opencode_models, clear_cache
from superqode.providers.opencode_models import get_opencode_models_with_fallback


def test_opencode_parser_detects_new_zero_cost_model_from_cli_output():
    output = """
opencode/new-dynamic-model
{"name":"New Dynamic Model","cost":{"input":0,"output":0},"limit":{"context":262144}}

opencode/paid-model
{"name":"Paid Model","cost":{"input":1,"output":1},"limit":{"context":128000}}
"""

    models = _parse_opencode_models(output)

    free = [model for model in models if model["is_free"]]
    assert [model["id"] for model in free] == ["opencode/new-dynamic-model"]
    assert free[0]["context"] == 262144


def test_acp_free_models_reuses_dynamic_opencode_parser():
    output = """
opencode/fresh-free-model
{"name":"Fresh Free Model","cost":{"input":"0","output":"0"},"context":200000}

opencode/fresh-paid-model
{"name":"Fresh Paid Model","cost":{"input":"0.10","output":"0.20"}}
"""

    models = _parse_opencode_models_for_free(output)

    assert [model.model_id for model in models] == ["opencode/fresh-free-model"]
    assert models[0].model_name == "Fresh Free Model"
    assert models[0].context_window == 200000


@pytest.mark.asyncio
async def test_acp_protocol_model_discovery_uses_dynamic_cost_metadata():
    class FakeACPClient:
        async def get_available_models(self):
            return [
                {
                    "id": "agent/new-free",
                    "name": "New Free",
                    "cost": {"input": 0, "output": 0},
                    "context_window": 64000,
                },
                {
                    "id": "agent/paid",
                    "name": "Paid",
                    "cost": {"input": 1, "output": 1},
                },
            ]

    models = await get_acp_agent_models(FakeACPClient())

    assert models[0].is_free is True
    assert models[0].context_window == 64000
    assert models[1].is_free is False


def test_tui_opencode_models_are_loaded_dynamically(monkeypatch):
    clear_cache()

    async def fake_get_opencode_models_with_fallback(force_refresh=False):
        return [
            {
                "id": "opencode/live-free",
                "name": "Live Free",
                "is_free": True,
                "context": 123456,
                "description": "from cli",
            },
            {
                "id": "opencode/live-paid",
                "name": "Live Paid",
                "is_free": False,
                "context": 123456,
            },
        ]

    monkeypatch.setattr(
        "superqode.providers.opencode_models.get_opencode_models_with_fallback",
        fake_get_opencode_models_with_fallback,
    )

    app = SuperQodeApp()
    models = app.opencode_models

    assert models == [
        {
            "id": "opencode/live-free",
            "name": "Live Free",
            "context": 123456,
            "free": True,
            "recommended": False,
            "desc": "from cli",
        }
    ]


@pytest.mark.asyncio
async def test_opencode_models_do_not_fall_back_to_static_catalog(monkeypatch):
    clear_cache()
    monkeypatch.setattr("superqode.providers.opencode_models.shutil.which", lambda name: None)

    models = await get_opencode_models_with_fallback(force_refresh=True)

    assert models == []
