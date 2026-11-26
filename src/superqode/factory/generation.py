"""Explicit model-assisted proposals; no tools, file writes or activation."""

import asyncio
from dataclasses import asdict
import json

import yaml

from .definition import SCHEMA, read_mapping, validate_definition
from .templates import compose_from_description


def proposal_from_description(description, workflow="", *, privacy_blocked=False):
    """A reviewable FactorySpec built on this Mac from the description alone."""
    data = compose_from_description(description, workflow=workflow)
    validate_definition(data)
    proposal = {
        "yaml": yaml.safe_dump(data, sort_keys=False),
        "assumptions": [
            "Built on this Mac from your description. No model was called, and nothing has run."
        ],
        "missing_capabilities": [],
        "proposal_only": True,
    }
    if privacy_blocked:
        proposal["assumptions"].append(
            "The selected cloud drafting model was blocked by the Factory's private route. "
            "Starter settings were generated without a model call. Choose a local model, "
            "or explicitly review and save a cloud-enabled route before drafting with a frontier model."
        )
    return proposal


def check_generation_route(data, provider, model):
    from superqode.session.factory import default_policy, classify_model_ref

    defaults = default_policy()
    name = data.get("default_route", defaults["default_route"])
    route = {**defaults["routes"].get(name, {}), **data.get("routes", {}).get(name, {})}
    local = "LOCAL" in classify_model_ref(provider + "/" + model)["tags"]
    if route.get("allow_cloud") is False and not local:
        raise ValueError("This factory's private route requires a local drafting model")


async def generate_factory(*, description, yaml_text, provider, model, gateway=None):
    from superqode.providers.gateway import GatewayFactory, Message
    from superqode.desktop_service.studio import _credentials

    if not description.strip() or len(description) > 8000 or not provider or not model:
        raise ValueError("Describe the factory and explicitly select a generation provider/model")
    before = read_mapping(yaml_text)
    validate_definition(before)
    _credentials(before)
    check_generation_route(before, provider, model)
    gateway = gateway or GatewayFactory.create(timeout=60)
    prompt = (
        "Propose a SuperQode FactorySpec for the user's process. Return JSON only with keys "
        "yaml (string), assumptions (list of strings), missing_capabilities (list of strings). "
        "Keep the seven-layer schema. Use existing template references or files already named "
        "in the draft; do not invent files, credentials, protected acceptance results or release keys. "
        "Preserve release_authority exactly. Do not claim runtime readiness or measured quality. "
        "No tools are available and nothing will execute. Schema:\n" + json.dumps(SCHEMA)
    )
    response = await asyncio.wait_for(
        gateway.chat_completion(
            messages=[
                Message(role="system", content=prompt),
                Message(role="user", content=description + "\nCurrent definition:\n" + yaml_text),
            ],
            model=model,
            provider=provider,
            max_tokens=6000,
            temperature=0.2,
            tools=[],
        ),
        timeout=65,
    )
    text = response.content.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    if len(text.encode()) > 250000:
        raise ValueError("Factory proposal exceeds its size limit")
    proposal = json.loads(text)
    if not isinstance(proposal, dict) or not isinstance(proposal.get("yaml"), str):
        raise ValueError("Model must return a JSON factory proposal")
    data = read_mapping(proposal["yaml"])
    validate_definition(data)
    _credentials(data)
    if data["governance"].get("release_authority") != before["governance"].get("release_authority"):
        raise ValueError("AI proposals cannot change the factory's release authority")
    for key in ("assumptions", "missing_capabilities"):
        if (
            not isinstance(proposal.get(key), list)
            or len(proposal[key]) > 20
            or any(not isinstance(item, str) or len(item) > 2000 for item in proposal[key])
        ):
            raise ValueError("Model proposal needs bounded assumption and capability lists")
    return {
        "yaml": proposal["yaml"],
        "assumptions": proposal["assumptions"],
        "missing_capabilities": proposal["missing_capabilities"],
        "usage": asdict(response.usage) if response.usage else None,
        "cost": asdict(response.cost) if response.cost else None,
        "proposal_only": True,
    }
