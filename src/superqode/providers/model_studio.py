"""Alibaba Cloud Model Studio routing and Chat Completions options."""

import os
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

METERED_PROVIDERS = frozenset({"qwen-cn", "qwen-intl"})
TOKEN_PLAN_PROVIDER = "alibaba-token-plan"
STUDIO_PROVIDERS = METERED_PROVIDERS | {TOKEN_PLAN_PROVIDER}
TOKEN_PLAN_BASE = "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
# 24:00 on 25 November 2026 in China Standard Time (UTC+8).
_PREVIEW_END = datetime(2026, 11, 25, 16, 0, tzinfo=timezone.utc)
_PLAN_ONLY_MODELS = frozenset({"qwen4-max-preview"})
_QWEN4_MODELS = frozenset({"qwen4-max", "qwen4-max-preview"})
_QWEN4_EFFORT = {
    "low": "low",
    "medium": "high",
    "high": "high",
    "xhigh": "xhigh",
    "max": "xhigh",
}
# Qwen4 counts thinking and the answer against one output budget. A cap sized
# for a short answer truncates the reply while the model is still thinking.
_QWEN4_THINKING_OUTPUT = 32768
_QWEN4_ANSWER_OUTPUT = 8192
_CACHE_PREFIX_CHARS = 4000


def bare_model(model: str) -> str:
    return (model or "").lower().removeprefix("openai/").strip()


def is_plan_model(model: str) -> bool:
    return bare_model(model) in _PLAN_ONLY_MODELS


def is_qwen4(model: str) -> bool:
    return bare_model(model) in _QWEN4_MODELS


def preview_open(now: datetime | None = None) -> bool:
    """True while Alibaba still serves qwen4-max-preview on Token Plan."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc) < _PREVIEW_END


def credential_kind(key: str) -> str:
    return "plan" if key.strip().startswith("sk-sp-") else "metered"


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
        raise ValueError(
            "Use a metered Model Studio API key and endpoint for this connection. "
            "A key starting with sk-sp- is a Token Plan or Coding Plan key. "
            "Choose Token Plan for qwen4-max, or Qwen Code /auth for Coding Plan."
        )


def _noninteractive() -> bool:
    return os.environ.get("SUPERQODE_NONINTERACTIVE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def validate_token_plan_route(base_url: str, key: str) -> None:
    """Token Plan accepts only its own key, host, and interactive sessions."""
    if _noninteractive():
        raise ValueError(
            "Alibaba Token Plan is for interactive coding in SuperQode. "
            "Headless runs, evaluations, and batch jobs are refused."
        )
    parts = urlsplit(base_url.strip())
    host = (parts.hostname or "").rstrip(".")
    if (
        parts.scheme != "https"
        or host != "token-plan.ap-southeast-1.maas.aliyuncs.com"
        or parts.path.rstrip("/") != "/compatible-mode/v1"
        or parts.username is not None
        or parts.query
        or parts.fragment
    ):
        raise ValueError(
            "Token Plan uses https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1."
        )
    if credential_kind(key) != "plan":
        raise ValueError(
            "Token Plan keys start with sk-sp-. A Model Studio pay-as-you-go key uses International."
        )


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
    model = bare_model(model)
    # Qwen4-Max thinks at high by default and bills that thinking. An unset
    # effort stays on, at low, so a trial turn does not spend the large budget.
    if model in _QWEN4_MODELS and not level:
        level = "low"
    if level not in {"off", "low", "medium", "high", "xhigh", "max"}:
        return {}
    if model in _QWEN4_MODELS:
        if level == "off":
            return {"enable_thinking": False}
        return {"enable_thinking": True, "reasoning_effort": _QWEN4_EFFORT[level]}
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
        aliases = (
            {"low": "high", "medium": "high", "xhigh": "max"}
            if model == "deepseek-v4-pro"
            else {"medium": "high", "xhigh": "high"}
        )
        return {"enable_thinking": True, "reasoning_effort": aliases.get(level, level)}
    return {}


def thinking_policy(model: str) -> str:
    """Describe only model families whose thinking settings we translate."""
    if not thinking_options(model, "low"):
        return "unknown"
    return "configurable" if thinking_options(model, "off") else "required"


def output_limit(model: str, thinking: bool, requested: int | None) -> int | None:
    """Raise a short Qwen4 cap so thinking does not consume the whole answer."""
    if not is_qwen4(model) or requested is None:
        return None
    floor = _QWEN4_THINKING_OUTPUT if thinking else _QWEN4_ANSWER_OUTPUT
    if requested >= floor:
        return None
    return floor


def mark_explicit_cache(messages: list) -> bool:
    """Mark a long Qwen4 system prefix for explicit cache. Short prompts stay unmarked."""
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or message.get("role") != "system":
            continue
        content = message.get("content")
        text = content if isinstance(content, str) else ""
        if isinstance(content, list):
            text = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        if len(text) < _CACHE_PREFIX_CHARS:
            return False
        if isinstance(content, str):
            blocks = [
                {
                    "type": "text",
                    "text": content,
                    "prompt_cache_breakpoint": {"mode": "explicit"},
                }
            ]
        else:
            blocks = [dict(part) if isinstance(part, dict) else part for part in content]
            for part in blocks:
                if isinstance(part, dict) and part.get("type") == "text":
                    part["prompt_cache_breakpoint"] = {"mode": "explicit"}
                    break
            else:
                return False
        messages[index] = {**message, "content": blocks}
        return True
    return False


def explain_failure(provider: str, error_text: str, key: str, base_url: str) -> str | None:
    """Plain cause for the Model Studio mistakes people hit first."""
    if provider not in STUDIO_PROVIDERS:
        return None
    text = error_text or ""
    lowered = text.lower()
    kind = credential_kind(key) if key else ""
    host = (urlsplit(base_url).hostname or "") if base_url else ""
    plan_host = host.startswith(("token-plan.", "coding-intl.dashscope.", "coding.dashscope."))
    if "datainspectionfailed" in lowered:
        return (
            "Model Studio stopped this request in its content check. "
            "Rephrase the prompt or remove the text that looks like a scanner or exploit."
        )
    if "max_tokens" in lowered or "max_completion_tokens" in lowered:
        return (
            "Qwen4-Max counts thinking and the answer against one output limit. "
            "A cap sized only for the answer can stop the reply mid-sentence."
        )
    auth_failed = (
        "401" in text
        or "invalid api" in lowered
        or "invalidapikey" in lowered
        or "authentication" in lowered
    )
    forbidden = "403" in text or "forbidden" in lowered or "allocationquota" in lowered
    if not auth_failed and not forbidden:
        return None
    if provider == TOKEN_PLAN_PROVIDER or plan_host or kind == "plan":
        return (
            "This key and endpoint are not a Token Plan pair. "
            "Token Plan needs an sk-sp- key and "
            "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1. "
            "A pay-as-you-go key uses the International Model Studio endpoint. "
            "Coding Plan uses a different host and does not include qwen4-max."
        )
    return (
        "This key and endpoint are not a pair. "
        "An International key calls the Singapore endpoint, and a China key calls the China endpoint. "
        "A Token Plan key starts with sk-sp- and does not belong on pay-as-you-go."
    )
