"""Shared harness command helpers."""

from pathlib import Path


def _harness_mcp_config_path(spec) -> Path | None:
    runtime_config = spec.runtime.config
    pydanticai_config = runtime_config.get("pydanticai", {})
    if isinstance(pydanticai_config, dict):
        configured = pydanticai_config.get("mcp_config_path") or pydanticai_config.get("mcp_config")
        if configured:
            return Path(configured)
    configured = runtime_config.get("mcp_config_path") or runtime_config.get("mcp_config")
    return Path(configured) if configured else None


def _harness_model_registry_check(spec) -> dict:
    provider = str(spec.model_policy.config.get("provider") or "").strip().lower()
    models = [item for item in (spec.model_policy.primary, *spec.model_policy.fallbacks) if item]
    if not models:
        return {
            "status": "ok",
            "message": "No model policy models are configured.",
            "provider": provider,
            "models": [],
            "unknown_models": [],
        }

    from superqode.providers.registry import PROVIDERS

    normalized = [_normalize_harness_model_id(model) for model in models]
    if not provider and ":" in str(models[0]):
        provider = str(models[0]).split(":", 1)[0].lower()
    if provider == "local":
        unknown = [
            model
            for model, normalized_model in zip(models, normalized)
            if not (
                normalized_model.endswith("-local")
                or normalized_model == "local-model"
                or "/" in normalized_model
            )
        ]
        status = "warning" if unknown else "ok"
        return {
            "status": status,
            "message": (
                "Local model aliases look usable."
                if not unknown
                else "Some local model aliases are not recognized by SuperQode's static hints."
            ),
            "provider": provider,
            "models": models,
            "unknown_models": unknown,
        }
    provider_def = PROVIDERS.get(provider)
    if provider_def is None:
        return {
            "status": "warning",
            "message": (
                "Model availability was not checked because no known provider is configured."
            ),
            "provider": provider,
            "models": models,
            "unknown_models": [],
        }
    known = {
        _normalize_harness_model_id(model)
        for model in (*provider_def.example_models, *provider_def.free_models)
    }
    unknown = [
        model
        for model, normalized_model in zip(models, normalized)
        if normalized_model not in known
    ]
    return {
        "status": "warning" if unknown else "ok",
        "message": (
            f"Model policy models are listed for provider '{provider}'."
            if not unknown
            else f"Some model policy models are not listed for provider '{provider}'."
        ),
        "provider": provider,
        "models": models,
        "unknown_models": unknown,
    }


def _normalize_harness_model_id(model: str) -> str:
    from superqode.providers.model_specs import split_provider_model_ref

    value = str(model).strip()
    if ":" in value and "/" not in value.split(":", 1)[0]:
        value = value.split(":", 1)[1]
    parsed = split_provider_model_ref(value)
    if parsed.provider in {"openai", "anthropic", "google", "gemini", "ollama", "huggingface"}:
        return parsed.model
    return value


def _diff_dicts(left: object, right: object, path: str = "") -> list[dict]:
    if isinstance(left, dict) and isinstance(right, dict):
        changes: list[dict] = []
        for key in sorted(set(left) | set(right)):
            child_path = f"{path}.{key}" if path else str(key)
            if key not in left:
                changes.append({"path": child_path, "left": None, "right": right[key]})
            elif key not in right:
                changes.append({"path": child_path, "left": left[key], "right": None})
            else:
                changes.extend(_diff_dicts(left[key], right[key], child_path))
        return changes
    if isinstance(left, list) and isinstance(right, list):
        if left == right:
            return []
        if all(isinstance(item, dict) and "id" in item for item in left + right):
            left_by_id = {item["id"]: item for item in left}
            right_by_id = {item["id"]: item for item in right}
            return _diff_dicts(left_by_id, right_by_id, path)
        return [{"path": path, "left": left, "right": right}]
    if left != right:
        return [{"path": path, "left": left, "right": right}]
    return []


def _permission_config_to_dict(config) -> dict:
    return {
        "default": config.default.value,
        "groups": {group.value: permission.value for group, permission in config.groups.items()},
        "tools": {tool: permission.value for tool, permission in config.tools.items()},
        "allow_patterns": list(config.allow_patterns),
        "deny_patterns": list(config.deny_patterns),
    }
