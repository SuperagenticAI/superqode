"""Metered Alibaba Cloud Model Studio routing and Chat Completions options."""

import re
from urllib.parse import urlsplit

METERED_PROVIDERS = frozenset({"qwen-cn", "qwen-intl"})
_PLAN_ONLY_MODELS = frozenset({"qwen4-max-preview"})


def is_plan_model(model: str) -> bool:
    return model.lower() in _PLAN_ONLY_MODELS


def validate_metered_route(base_url: str, key: str) -> None:
    parts = urlsplit(base_url)
    host = (parts.hostname or "").rstrip(".")
    if (
        parts.scheme not in {"http", "https"}
        or not host
        or parts.username is not None
        or parts.query
        or parts.fragment
    ):
        raise ValueError(
            "Enter a valid Model Studio API endpoint without credentials or query parameters."
        )
    if key.strip().startswith("sk-sp-") or host.startswith(
        ("token-plan.", "coding-intl.dashscope.", "coding.dashscope.")
    ):
        raise ValueError("Use a metered Model Studio API key and endpoint for this connection.")


def workspace_catalog_url(base_url: str) -> str | None:
    parts = urlsplit(base_url)
    host = parts.hostname or ""
    if (
        parts.scheme == "https"
        and parts.netloc.lower() == host
        and parts.path.rstrip("/") == "/compatible-mode/v1"
        and not parts.query
        and not parts.fragment
        and re.fullmatch(r"[a-z0-9-]+\.[a-z0-9-]+\.maas\.aliyuncs\.com", host)
    ):
        return f"https://{host}/api/v1/models"
    return None


def validate_workspace_endpoint(base_url: str) -> str:
    """Allow official metered Alibaba endpoints in the desktop picker."""
    base_url = base_url.strip().rstrip("/")
    if len(base_url) > 512 or any(char.isspace() for char in base_url):
        raise ValueError(
            "Enter the HTTPS OpenAI-compatible Model Studio URL from your Alibaba console."
        )
    validate_metered_route(base_url, "")
    if workspace_catalog_url(base_url) or base_url in {
        f"https://{host}/compatible-mode/v1"
        for host in (
            "dashscope.aliyuncs.com",
            "dashscope-intl.aliyuncs.com",
            "dashscope-us.aliyuncs.com",
            "cn-hongkong.dashscope.aliyuncs.com",
        )
    }:
        return base_url
    raise ValueError(
        "Enter the HTTPS OpenAI-compatible Model Studio URL from your Alibaba console."
    )


def thinking_options(model: str, level: str | None) -> dict:
    """Translate SuperQode's effort controls for the documented pilot models."""
    level = (level or "").strip().lower()
    level = {"none": "off", "minimal": "low"}.get(level, level)
    if level not in {"off", "low", "medium", "high", "xhigh", "max"}:
        return {}
    model = model.lower().removeprefix("openai/")
    if model in {
        "qwen3.8-flash",
        "qwen3.8-max",
        "qwen3.8-max-0902",
        "qwen3.8-2.4t-a95b",
        "qwen3.8-27b",
    }:
        if level == "off":
            return {"enable_thinking": False}
        return {
            "enable_thinking": True,
            "reasoning_effort": level if level in {"low", "medium"} else "xhigh",
        }
    if model in {"qwen3.7-plus", "qwen3.7-plus-2026-05-26"}:
        if level == "off":
            return {"enable_thinking": False}
        budgets = {"low": 1024, "medium": 4096, "high": 8192, "xhigh": 16384, "max": 16384}
        return {"enable_thinking": True, "thinking_budget": budgets[level]}
    if model in {"glm-5.3", "zhipu/glm-5.3"}:
        if level == "off":  # The API rejects disabling thinking for this family.
            return {}
        return {"reasoning_effort": {"medium": "high", "xhigh": "max"}.get(level, level)}
    if model in {
        "deepseek-v4.1-flash",
        "deepseek-v4.1-flash-1017",
        "deepseek-v4-flash-0731",
        "deepseek-v4-pro",
        "deepseek-v4-pro-0813",
    }:
        if level == "off":
            return {"enable_thinking": False}
        return {
            "enable_thinking": True,
            "reasoning_effort": {"medium": "high", "xhigh": "high"}.get(level, level),
        }
    return {}


def thinking_policy(model: str) -> str:
    """Describe only model families whose thinking settings we translate."""
    if not thinking_options(model, "low"):
        return "unknown"
    return "configurable" if thinking_options(model, "off") else "required"
