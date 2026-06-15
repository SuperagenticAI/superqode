"""models.dev lab discovery for local coding model recommendations."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

MODELS_DEV_API_URL = "https://models.dev/api.json"
LABS_CACHE_FILE = Path.home() / ".superqode" / "labs_cache.json"
DEFAULT_CACHE_TTL = timedelta(hours=6)


@dataclass(frozen=True)
class LocalLab:
    id: str
    name: str
    provider_ids: tuple[str, ...]
    description: str
    recommended: bool = False


@dataclass(frozen=True)
class LabModel:
    id: str
    name: str
    lab: str
    provider: str
    context_window: int = 0
    max_output: int = 0
    supports_tools: bool = False
    supports_reasoning: bool = False
    supports_structured: bool = False
    supports_vision: bool = False
    open_weights: bool = False
    free_route: bool = False
    released: str = ""
    updated: str = ""
    recommended_for_local: bool = False
    install_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CURATED_LOCAL_LABS: dict[str, LocalLab] = {
    "zhipuai": LocalLab(
        id="zhipuai",
        name="Zhipu AI / GLM",
        provider_ids=("zhipuai", "zhipu", "glm"),
        description="GLM 4.x/5.x models: strong agentic coding, long context, tools.",
        recommended=True,
    ),
    "alibaba": LocalLab(
        id="alibaba",
        name="Alibaba / Qwen",
        provider_ids=("alibaba", "qwen", "dashscope"),
        description="Qwen coder and general models with strong local tool calling.",
        recommended=True,
    ),
    "deepseek": LocalLab(
        id="deepseek",
        name="DeepSeek",
        provider_ids=("deepseek",),
        description="DeepSeek coder and DS4-compatible local/server-class routes.",
        recommended=True,
    ),
    "google": LocalLab(
        id="google",
        name="Google / Gemma",
        provider_ids=("google", "gemma"),
        description="Gemma instruction models for local coding and vision-capable workflows.",
        recommended=True,
    ),
    "mistral": LocalLab(
        id="mistral",
        name="Mistral / Devstral",
        provider_ids=("mistral",),
        description="Devstral and Mistral local/server routes for coding.",
        recommended=True,
    ),
}


def list_curated_labs() -> list[LocalLab]:
    return sorted(CURATED_LOCAL_LABS.values(), key=lambda lab: (not lab.recommended, lab.name))


def _cache_fresh(path: Path, ttl: timedelta = DEFAULT_CACHE_TTL) -> bool:
    try:
        return datetime.now() - datetime.fromtimestamp(path.stat().st_mtime) < ttl
    except OSError:
        return False


def load_models_dev_api(*, refresh: bool = False) -> dict[str, Any]:
    """Load models.dev provider data, using a small local cache."""
    if not refresh and LABS_CACHE_FILE.exists() and _cache_fresh(LABS_CACHE_FILE):
        try:
            return json.loads(LABS_CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    request = Request(MODELS_DEV_API_URL, headers={"User-Agent": "SuperQode"}, method="GET")
    with urlopen(request, timeout=30) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    LABS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LABS_CACHE_FILE.write_text(json.dumps(payload), encoding="utf-8")
    return payload if isinstance(payload, dict) else {}


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _model_has_open_weights(data: dict[str, Any]) -> bool:
    weights = data.get("weights")
    if isinstance(weights, bool):
        return weights
    if isinstance(weights, str):
        return weights.lower() in {"open", "true", "yes", "huggingface", "hf"}
    if isinstance(weights, dict):
        return bool(weights.get("open") or weights.get("url") or weights.get("huggingface"))
    return bool(data.get("open_weights") or data.get("open"))


def _model_free(data: dict[str, Any]) -> bool:
    cost = data.get("cost")
    if isinstance(cost, dict):
        return float(cost.get("input") or 0) == 0 and float(cost.get("output") or 0) == 0
    return False


def _model_context(data: dict[str, Any]) -> tuple[int, int]:
    limits = data.get("limit")
    if isinstance(limits, dict):
        return _int_value(limits.get("context")), _int_value(limits.get("output"))
    return _int_value(data.get("context")), _int_value(data.get("output"))


def _install_hint(model_id: str, model: dict[str, Any], lab_id: str) -> str:
    weights = model.get("weights")
    if isinstance(weights, dict):
        hf_repo = weights.get("huggingface") or weights.get("hf") or weights.get("repo")
        if hf_repo:
            return f"hf download {hf_repo}"
        if weights.get("url"):
            return str(weights["url"])

    lowered = model_id.lower()
    if lab_id == "zhipuai" or "glm" in lowered:
        return f"hf download THUDM/{model_id.split('/')[-1]}"
    if "qwen" in lowered:
        return f"hf download Qwen/{model_id.split('/')[-1]}"
    if "gemma" in lowered:
        return f"hf download google/{model_id.split('/')[-1]}"
    # No known repo: point at a real search, not a made-up download command.
    return f"superqode models hub {model_id.split('/')[-1]}"


def _recommended_for_local(item: LabModel) -> bool:
    if not item.open_weights:
        return False
    if not (item.supports_tools or item.supports_structured):
        return False
    if item.context_window and item.context_window < 32000:
        return False
    # GLM-5 class models can be open/free but are server-class for most
    # developers; show them, but do not mark them as workstation-local picks.
    slug = item.id.lower().split("/")[-1]
    if slug in {"glm-5", "glm-5.1", "glm-5.2"}:
        return False
    return True


def list_lab_models(lab_id: str, *, refresh: bool = False) -> list[LabModel]:
    lab_key = lab_id.strip().lower()
    lab = CURATED_LOCAL_LABS.get(lab_key)
    provider_ids = lab.provider_ids if lab else (lab_key,)
    data = load_models_dev_api(refresh=refresh)
    rows: list[LabModel] = []

    for provider_id in provider_ids:
        provider_data = data.get(provider_id)
        if not isinstance(provider_data, dict):
            continue
        models = provider_data.get("models") or {}
        if not isinstance(models, dict):
            continue
        for model_id, model_data in models.items():
            if not isinstance(model_data, dict):
                continue
            context, output = _model_context(model_data)
            modalities = model_data.get("modalities") or {}
            input_modalities = modalities.get("input") if isinstance(modalities, dict) else []
            row = LabModel(
                id=str(model_id),
                name=str(model_data.get("name") or model_id),
                lab=lab_key,
                provider=provider_id,
                context_window=context,
                max_output=output,
                supports_tools=bool(model_data.get("tool_call")),
                supports_reasoning=bool(model_data.get("reasoning")),
                supports_structured=bool(
                    model_data.get("structured") or model_data.get("tool_call")
                ),
                supports_vision="image" in (input_modalities or [])
                or "video" in (input_modalities or []),
                open_weights=_model_has_open_weights(model_data),
                free_route=_model_free(model_data),
                released=str(model_data.get("release_date") or ""),
                updated=str(model_data.get("last_updated") or model_data.get("updated") or ""),
                install_hint=_install_hint(str(model_id), model_data, lab_key),
            )
            rows.append(
                LabModel(
                    **{
                        **row.to_dict(),
                        "recommended_for_local": _recommended_for_local(row),
                    }
                )
            )

    return sorted(
        rows,
        key=lambda item: (
            not item.recommended_for_local,
            not item.open_weights,
            not item.supports_tools,
            -item.context_window,
            item.name,
        ),
    )


# Vetted Hugging Face publishers: the model labs plus the quant communities
# SuperQode trusts. Live Hub search is filtered to these so "latest from the
# labs" never surfaces a random unvetted upload.
TRUSTED_HF_ORGS = {
    "qwen",
    "google",
    "deepseek-ai",
    "mistralai",
    "zai-org",
    "thudm",
    "mlx-community",
    "lmstudio-community",
    "ggml-org",
    "unsloth",
}


def search_hub_trusted(query: str, *, kind: str | None = None, limit: int = 8) -> list:
    """Live Hugging Face search restricted to trusted publishers.

    ``kind`` is ``"gguf"``, ``"mlx"``, or ``None`` (general text-generation).
    Returns ``HubModel`` entries, newest-popular first, only from
    ``TRUSTED_HF_ORGS``. Raises ``HFNotInstalled`` if ``huggingface_hub`` is
    missing so the caller can show an install hint.
    """
    from superqode.providers.huggingface.fetch import search_hub

    raw = search_hub(query, kind=kind, sort="downloads", limit=max(limit * 4, 24))
    out = []
    for model in raw:
        org = model.id.split("/", 1)[0].lower() if "/" in model.id else ""
        if org in TRUSTED_HF_ORGS:
            out.append(model)
        if len(out) >= limit:
            break
    return out


__all__ = [
    "CURATED_LOCAL_LABS",
    "LabModel",
    "LocalLab",
    "TRUSTED_HF_ORGS",
    "list_curated_labs",
    "list_lab_models",
    "load_models_dev_api",
    "search_hub_trusted",
]
