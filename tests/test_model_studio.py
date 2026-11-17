"""Qwen4-Max effort, output budget, cache markers, and credential pairing."""

from datetime import datetime, timezone

import pytest

from superqode.providers.model_studio import (
    TOKEN_PLAN_BASE,
    explain_failure,
    mark_explicit_cache,
    output_limit,
    preview_open,
    thinking_options,
    thinking_policy,
    validate_token_plan_route,
    validate_workspace_endpoint,
)


def test_qwen4_effort_defaults_to_low_and_maps_the_documented_levels():
    assert thinking_options("qwen4-max", None) == {
        "enable_thinking": True,
        "reasoning_effort": "low",
    }
    assert thinking_options("openai/qwen4-max", "off") == {"enable_thinking": False}
    assert thinking_options("qwen4-max", "medium")["reasoning_effort"] == "high"
    assert thinking_options("qwen4-max", "high")["reasoning_effort"] == "high"
    assert thinking_options("qwen4-max", "max")["reasoning_effort"] == "xhigh"
    assert "thinking_budget" not in thinking_options("qwen4-max", "high")
    assert thinking_policy("qwen4-max") == "configurable"


def test_qwen4_output_floor_raises_only_a_short_cap():
    assert output_limit("qwen4-max", True, 768) == 32768
    assert output_limit("qwen4-max", False, 768) == 8192
    assert output_limit("qwen4-max", True, 40000) is None
    assert output_limit("qwen4-max", True, None) is None
    assert output_limit("qwen3.8-flash", True, 768) is None


def test_explicit_cache_marks_only_a_long_system_prefix():
    short = [{"role": "system", "content": "short"}]
    assert mark_explicit_cache(short) is False
    assert short[0]["content"] == "short"
    long = [{"role": "system", "content": "S" * 4000}, {"role": "user", "content": "go"}]
    assert mark_explicit_cache(long) is True
    assert long[0]["content"][0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
    assert long[1]["content"] == "go"


def test_preview_closes_at_the_published_utc_instant():
    assert preview_open(datetime(2026, 11, 25, 15, 59, tzinfo=timezone.utc))
    assert not preview_open(datetime(2026, 11, 25, 16, 0, tzinfo=timezone.utc))


def test_failure_text_names_the_key_and_endpoint_pair():
    plan = explain_failure(
        "qwen-intl",
        "Error code: 401 InvalidApiKey",
        "sk-sp-secret",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )
    assert "sk-sp-" in plan and "token-plan.ap-southeast-1" in plan
    assert "sk-sp-secret" not in plan
    metered = explain_failure(
        "qwen-intl",
        "401 authentication failed",
        "sk-intl",
        "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    )
    assert "same Model Studio region" in metered and "sk-intl" not in metered
    assert "content check" in explain_failure("qwen-intl", "DataInspectionFailed", "", "")


def test_workspace_endpoint_accepts_any_official_model_studio_region():
    frankfurt = "https://ws-london.eu-central-1.maas.aliyuncs.com/compatible-mode/v1"
    assert validate_workspace_endpoint(frankfurt + "/") == frankfurt
    assert (
        validate_workspace_endpoint(
            "https://WS-Demo.ap-northeast-1.maas.aliyuncs.com/compatible-mode/v1"
        )
        == "https://ws-demo.ap-northeast-1.maas.aliyuncs.com/compatible-mode/v1"
    )
    assert (
        validate_workspace_endpoint("https://dashscope-eu.aliyuncs.com/compatible-mode/v1")
        == "https://dashscope-eu.aliyuncs.com/compatible-mode/v1"
    )
    assert (
        validate_workspace_endpoint("https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1")
        == "https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1"
    )


def test_workspace_endpoint_rejects_other_hosts_and_plan_routes():
    with pytest.raises(ValueError, match="Model Studio region"):
        validate_workspace_endpoint("https://example.com/compatible-mode/v1")
    with pytest.raises(ValueError, match="sk-sp-"):
        validate_workspace_endpoint(
            "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
        )
    with pytest.raises(ValueError, match="sk-sp-"):
        validate_workspace_endpoint("https://coding-intl.dashscope.aliyuncs.com/compatible-mode/v1")
    with pytest.raises(ValueError, match="Model Studio region"):
        validate_workspace_endpoint(
            "https://ws-demo.eu-central-1.maas.aliyuncs.com/compatible-mode/v1?x=1"
        )


def test_token_plan_route_rejects_a_paygo_key(monkeypatch):
    monkeypatch.delenv("SUPERQODE_NONINTERACTIVE", raising=False)
    with pytest.raises(ValueError, match="sk-sp-"):
        validate_token_plan_route(TOKEN_PLAN_BASE, "sk-paygo")


def test_token_plan_install_accepts_only_a_plan_key(monkeypatch):
    from superqode.desktop_service.connections import install

    monkeypatch.delenv("SUPERQODE_NONINTERACTIVE", raising=False)
    saved = {}
    install(saved, {"provider": "alibaba-token-plan", "key": "sk-sp-demo"})
    assert saved["alibaba-token-plan"] == "sk-sp-demo"
    with pytest.raises(ValueError, match="credential type"):
        install({}, {"provider": "alibaba-token-plan", "key": "sk-paygo"})
    monkeypatch.setenv("SUPERQODE_NONINTERACTIVE", "1")
    with pytest.raises(ValueError, match="interactive"):
        install({}, {"provider": "alibaba-token-plan", "key": "sk-sp-demo"})
