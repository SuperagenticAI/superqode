import json
import subprocess

import pytest

from superqode.app_main import SuperQodeApp
from superqode.providers.acp_free_models import _parse_opencode_models_for_free
from superqode.providers.acp_models import get_acp_agent_models
from superqode.providers.opencode_models import _parse_opencode_models, clear_cache
from superqode.providers.opencode_models import get_opencode_models_sync
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


def test_opencode_parser_preserves_provider_model_ids_from_cli_output():
    output = """
opencode/big-pickle
{"name":"Big Pickle","cost":{"input":0,"output":0},"limit":{"context":200000}}

deepseek/deepseek-v4-pro
{"name":"DeepSeek V4 Pro","cost":{"input":1,"output":1},"limit":{"context":1000000}}
"""

    models = _parse_opencode_models(output)

    assert [model["id"] for model in models] == [
        "opencode/big-pickle",
        "deepseek/deepseek-v4-pro",
    ]
    assert [model["provider"] for model in models] == ["opencode", "deepseek"]


def test_opencode_json_parser_preserves_non_opencode_provider_ids():
    output = """
[
  {"id": "deepseek/deepseek-v4-pro", "name": "DeepSeek V4 Pro"},
  {"id": "bare-free-model", "name": "Bare Free Model"}
]
"""

    models = _parse_opencode_models(output)

    assert models[0]["id"] == "deepseek/deepseek-v4-pro"
    assert models[0]["provider"] == "deepseek"
    assert models[1]["id"] == "opencode/bare-free-model"


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
                    "modelId": "agent/new-free",
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

    def fake_get_opencode_models_sync(force_refresh=False):
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
        "superqode.providers.opencode_models.get_opencode_models_sync",
        fake_get_opencode_models_sync,
    )

    app = SuperQodeApp()
    models = app.opencode_models

    # Everything OpenCode offers is listed, free first, in the picker's shape.
    assert models == [
        {
            "id": "opencode/live-free",
            "name": "Live Free",
            "context": 123456,
            "free": True,
            "recommended": False,
            "desc": "from cli",
            "catalog_unavailable": False,
        },
        {
            "id": "opencode/live-paid",
            "name": "Live Paid",
            "context": 123456,
            "free": False,
            "recommended": False,
            "desc": "OpenCode",
            "catalog_unavailable": False,
        },
    ]


def test_tui_opencode_picker_lists_every_model_with_free_ones_first(monkeypatch):
    """Discovery already limits this to what OpenCode will route.

    Filtering again in the picker only hid usable models, so the whole
    catalogue is listed and the free rows lead.
    """
    clear_cache()

    def fake_get_opencode_models_sync(force_refresh=False):
        return [
            {
                "id": "anthropic/claude-opus",
                "name": "Claude Opus",
                "is_free": False,
                "context": 200000,
            },
            {
                "id": "opencode/big-pickle",
                "name": "Big Pickle",
                "is_free": True,
                "context": 200000,
            },
            {
                "id": "openai/gpt-5",
                "name": "GPT-5",
                "is_free": False,
                "context": 400000,
            },
        ]

    monkeypatch.setattr(
        "superqode.providers.opencode_models.get_opencode_models_sync",
        fake_get_opencode_models_sync,
    )

    app = SuperQodeApp()
    ids = [model["id"] for model in app.opencode_models]
    assert ids[0] == "opencode/big-pickle"
    assert set(ids) == {"opencode/big-pickle", "anthropic/claude-opus", "openai/gpt-5"}


@pytest.mark.asyncio
async def test_opencode_models_do_not_fall_back_to_static_catalog(monkeypatch):
    clear_cache()
    monkeypatch.setattr("superqode.providers.opencode_models.shutil.which", lambda name: None)

    models = await get_opencode_models_with_fallback(force_refresh=True)

    assert models == []


@pytest.mark.asyncio
async def test_connect_clears_the_agent_list_before_the_catalogue_loads(monkeypatch):
    """Discovery shells out to the OpenCode CLI and takes a second or two.

    Running it inline left the ACP agent registry painted and frozen on screen
    for that whole wait, so the list appeared to flash up and vanish. The
    placeholder has to be on screen before the fetch begins.
    """
    from superqode.app.widgets import ConversationLog

    app = SuperQodeApp()
    async with app.run_test(size=(92, 30)) as pilot:
        log = app.query_one("#log", ConversationLog)
        log.write("ACP AGENT REGISTRY LISTING")
        await pilot.pause()

        seen_during_fetch = []

        async def fake_fetch(force_refresh=False):
            seen_during_fetch.append("\n".join(line.text for line in log.lines))
            return [
                {
                    "id": "opencode/big-pickle",
                    "name": "Big Pickle",
                    "is_free": True,
                    "context": 200000,
                }
            ]

        monkeypatch.setattr("superqode.providers.opencode_models.get_opencode_models", fake_fetch)
        app._opencode_models = None
        await app._prepare_opencode_models(log)
        await pilot.pause()

        assert seen_during_fetch, "the catalogue fetch never ran"
        onscreen = seen_during_fetch[0]
        assert "ACP AGENT REGISTRY LISTING" not in onscreen
        assert "Loading models" in onscreen
        assert [model["id"] for model in app._opencode_models] == ["opencode/big-pickle"]


def test_connect_awaits_the_prefetch_before_painting_the_picker():
    """Guard the wiring, not just the helper.

    The previous attempt at this fix was reverted wholesale along with an
    unrelated change in the same commit, and nothing failed to catch it. The
    picker must not be painted until the catalogue has been awaited off-loop.
    """
    import inspect

    from superqode.app.mixins.connect import ConnectMixin

    source = inspect.getsource(ConnectMixin._connect_agent)
    prefetch = source.index("await self._prepare_opencode_models(log)")
    picker = source.index("self._show_opencode_models_selection(agent, log)")
    assert prefetch < picker


@pytest.mark.asyncio
async def test_agent_catalogue_does_not_repaint_over_the_model_picker():
    """The registry revalidates in the background and can land mid-selection.

    Repainting the agent list then flashes every agent across the screen while
    the user is reading the model picker, so the refresh has to stand down
    until the picker is gone.
    """
    from superqode.app.widgets import ConversationLog

    app = SuperQodeApp()
    async with app.run_test(size=(92, 30)) as pilot:
        log = app.query_one("#log", ConversationLog)
        repainted = []
        app._reshow_acp_agents = lambda _log: repainted.append(True)
        app._acp_picker_snapshot_at = 0.0
        app._awaiting_acp_agent_selection = True
        app._awaiting_model_selection = True

        await app._revalidate_acp_catalog(log).wait()
        for _ in range(4):
            await pilot.pause()

        assert repainted == []


def test_opencode_offers_its_default_when_the_cli_lists_nothing(monkeypatch):
    """A signed-out OpenCode must still give the picker something selectable."""
    clear_cache()
    from superqode.providers import opencode_models as mod

    monkeypatch.setattr(mod.shutil, "which", lambda name: "opencode")
    monkeypatch.setattr(mod, "_cli_model_list", lambda: [])
    monkeypatch.setattr(
        mod,
        "_run_opencode",
        lambda args, timeout=15: subprocess.CompletedProcess(args, 1, "", "not logged in"),
    )

    models = get_opencode_models_sync(force_refresh=True)

    assert [model["id"] for model in models] == ["opencode/auto"]
    assert models[0]["catalog_unavailable"] is True


def test_opencode_picker_keeps_paid_rows_when_nothing_reads_as_free(monkeypatch):
    """Free detection relies on pricing metadata that some rows never carry."""

    def fake_get_opencode_models_sync(force_refresh=False):
        return [
            {"id": "opencode/big-pickle", "name": "Big Pickle", "context": 200000},
            {"id": "opencode/mimo-v2.5", "name": "MiMo v2.5", "context": 128000},
        ]

    monkeypatch.setattr(
        "superqode.providers.opencode_models.get_opencode_models_sync",
        fake_get_opencode_models_sync,
    )

    app = SuperQodeApp()
    ids = sorted(model["id"] for model in app.opencode_models)
    assert ids == ["opencode/big-pickle", "opencode/mimo-v2.5"]


def test_opencode_cache_only_enriches_models_the_cli_offers(tmp_path, monkeypatch):
    """CLI may list only wired free models; OpenCode's cache still has the rest."""
    from superqode.providers import opencode_models as mod

    clear_cache()
    catalog = tmp_path / "models.json"
    catalog.write_text(
        json.dumps(
            {
                "opencode": {
                    "id": "opencode",
                    "models": {
                        "big-pickle": {
                            "id": "big-pickle",
                            "name": "Big Pickle",
                            "cost": {"input": 0, "output": 0},
                            "limit": {"context": 200000},
                        },
                        "claude-opus-4-8": {
                            "id": "claude-opus-4-8",
                            "name": "Claude Opus 4.8",
                            "cost": {"input": 5, "output": 25},
                            "limit": {"context": 200000},
                        },
                    },
                },
                "anthropic": {
                    "id": "anthropic",
                    "models": {
                        "claude-sonnet-4": {
                            "id": "claude-sonnet-4",
                            "name": "Claude Sonnet 4",
                            "cost": {"input": 3, "output": 15},
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_run(args, timeout=15):
        command = args[0] if args else ""
        if command == "models":
            stdout = "opencode/big-pickle\n"
            if "--verbose" in args:
                stdout = (
                    "opencode/big-pickle\n"
                    '{"name":"Big Pickle","cost":{"input":0,"output":0},'
                    '"limit":{"context":200000}}\n'
                )
            return subprocess.CompletedProcess(args, 0, stdout, "")
        if command == "debug" and args[1:] == ["paths"]:
            return subprocess.CompletedProcess(args, 0, f"cache {catalog.parent}\n", "")
        if command == "debug" and args[1:] == ["v2"]:
            return subprocess.CompletedProcess(
                args, 0, json.dumps({"providers": [{"id": "opencode"}]}), ""
            )
        return subprocess.CompletedProcess(args, 1, "", "unexpected")

    monkeypatch.setattr(mod.shutil, "which", lambda name: "opencode")
    monkeypatch.setattr(mod, "_run_opencode", fake_run)

    models = get_opencode_models_sync(force_refresh=True)
    ids = {model["id"] for model in models}

    # The CLI is the only source of truth for what OpenCode can route. The
    # cache carries the whole models.dev catalogue, including ids this install
    # would refuse, so offering them puts unusable rows in the picker.
    assert ids == {"opencode/big-pickle"}
    assert "opencode/claude-opus-4-8" not in ids
    assert "anthropic/claude-sonnet-4" not in ids

    # The cache is still used, for metadata on the model the CLI did offer.
    offered = next(model for model in models if model["id"] == "opencode/big-pickle")
    assert offered["name"] == "Big Pickle"
    assert offered["context"] == 200000
    assert offered["is_free"] is True


def test_sync_opencode_models_works_inside_running_event_loop(monkeypatch):
    clear_cache()
    monkeypatch.setattr("superqode.providers.opencode_models.shutil.which", lambda name: "opencode")

    class FakeCompletedProcess:
        returncode = 0
        stdout = """
opencode/sync-free
{"name":"Sync Free","cost":{"input":0,"output":0},"limit":{"context":333000}}
"""
        stderr = ""

    monkeypatch.setattr(
        "superqode.providers.opencode_models.subprocess.run",
        lambda *args, **kwargs: FakeCompletedProcess(),
    )

    models = get_opencode_models_sync(force_refresh=True)

    assert models[0]["id"] == "opencode/sync-free"
    assert models[0]["is_free"] is True
