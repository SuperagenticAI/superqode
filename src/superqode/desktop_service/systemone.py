"""Project-scoped SystemOne setup. Saving never makes an inference request."""

import asyncio
from dataclasses import replace
from uuid import uuid4

from superqode.systemone.providers import get_provider


def configure(service, params):
    import yaml
    from superqode.harness.templates import systemone_template
    from superqode.harness.loader import harness_spec_to_dict
    from .connect_workflow import save_harness

    provider = get_provider(str(params.get("provider") or "typesafe"))
    model = str(params.get("model") or provider.model)
    if model not in provider.models:
        raise ValueError("Choose a supported decision model")
    reviewed = params.get("policy_reviewed", False)
    mode = str(params.get("mode") or "shadow")
    if not isinstance(reviewed, bool) or mode not in {"shadow", "enforce"}:
        raise ValueError("Choose shadow or reviewed enforcement")
    if mode == "enforce" and not reviewed:
        raise ValueError("Review this provider/model policy before enforcement")
    record = params.get("record_decisions", False)
    if not isinstance(record, bool):
        raise ValueError("Choose whether to record decision calls")
    name = "systemone-" + provider.id + "-" + uuid4().hex[:8]
    spec = systemone_template(name=name)
    spec = replace(
        spec,
        metadata={**spec.metadata, "decision_provider_pinned": True},
        tool_discovery=replace(
            spec.tool_discovery,
            judge={"backend": "systemone", "mode": "rerank" if mode == "enforce" else "shadow"},
        ),
        systemone=replace(
            spec.systemone,
            enabled=True,
            client="live",
            provider=provider.id,
            model=model,
            endpoint=provider.endpoint,
            api_key_env=provider.api_key_env,
            mode=mode,
            policy_reviewed=reviewed,
            tool_search_mode="rerank" if mode == "enforce" else "shadow",
            record_dir=str(service.root / "decision-records" / params["project"] / name)
            if record
            else "",
        ),
    )
    return save_harness(
        service.project(params["project"]),
        name,
        yaml.safe_dump(harness_spec_to_dict(spec), sort_keys=False),
    )


def test_decision(service, params):
    from superqode.systemone.live import LiveSystemOneClient
    from superqode.systemone.api_clients import GoogleDecisionClient, OpenAIDecisionClient
    from superqode.systemone.connectivity import check_connection

    provider = get_provider(str(params.get("provider") or "typesafe"))
    identity = "systemone" if provider.id == "typesafe" else "systemone:" + provider.id
    key = params.get("key") or service.vendor_keys.get(identity)
    if (
        not isinstance(key, str)
        or not key.strip()
        or len(key) > 16000
        or any(ord(c) < 32 for c in key)
    ):
        raise ValueError(f"Enter a valid {provider.label} API key")
    model = str(params.get("model") or provider.model)
    if model not in provider.models:
        raise ValueError("Choose a supported decision model")
    client_type = {
        "typesafe": LiveSystemOneClient,
        "google": GoogleDecisionClient,
        "openai": OpenAIDecisionClient,
    }[provider.id]

    async def run():
        return await check_connection(
            client_type(api_key=key.strip(), model=model, timeout_ms=10000)
        )

    return asyncio.run(run())
