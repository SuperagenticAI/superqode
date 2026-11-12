"""Reviewed runtime setup uses fixed vendor recipes and no model credentials."""

import pytest

from superqode.local import runtime_setup


@pytest.mark.parametrize(
    "template,formula",
    [("omlx", "jundot/omlx/omlx"), ("vllm-metal", "vllm-project/vllm-metal/vllm-metal")],
)
def test_mac_install_plan_is_explicit_and_does_not_download_weights(monkeypatch, template, formula):
    monkeypatch.setattr(runtime_setup.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(runtime_setup.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(runtime_setup.shutil, "which", lambda _: "/opt/homebrew/bin/brew")
    plan = runtime_setup.plan(
        {
            "id": "fixture",
            "name": "Fixture",
            "template": template,
            "endpoint": "http://127.0.0.1:8000/v1",
        }
    )
    assert plan["automatic"] is True
    assert plan["steps"][-1] == ["/opt/homebrew/bin/brew", "install", formula]
    assert "model" not in " ".join(plan["commands"])
    assert plan["digest"]


def test_other_platforms_and_missing_brew_get_manual_guidance(monkeypatch):
    monkeypatch.setattr(runtime_setup.platform, "system", lambda: "Linux")
    monkeypatch.setattr(runtime_setup.shutil, "which", lambda _: None)
    plan = runtime_setup.plan(
        {"id": "fixture", "template": "vllm-metal", "endpoint": "http://127.0.0.1:8000/v1"}
    )
    assert not plan["automatic"] and not plan["steps"]
    assert "Homebrew" in plan["guidance"] and plan["docs_url"].startswith("https://")


def test_installation_refuses_an_unreviewed_or_changed_plan(desktop, monkeypatch):
    service, _, _ = desktop
    service.dispatch(
        "local.runtimes.save",
        {"id": "fixture", "template": "omlx", "endpoint": "http://127.0.0.1:8000/v1"},
    )
    monkeypatch.setattr(runtime_setup, "plan", lambda _: {"automatic": True, "digest": "current"})
    with pytest.raises(ValueError, match="plan changed"):
        service.dispatch(
            "local.runtimes.setup.start", {"id": "fixture", "expected_digest": "stale"}
        )
    assert not service.processes


from test_desktop_service import desktop  # noqa: E402,F401
