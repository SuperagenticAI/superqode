"""Reviewable project-specific verifier drafts using the protected probe runtime."""

import asyncio
from dataclasses import asdict
from copy import deepcopy
import json
from pathlib import Path

import yaml

from .definition import FactoryDefinition, load_factory, read_mapping, validate_definition
from .snapshot import resolve_factory, canonical, digest
from .probes import parse_probes, PROBE_SCHEMA
from .operations import ownership, write
from .maintenance import execution
from .versioning import source_path, _safe_text


def draft(root, checks, *, yaml_text=None):
    """Package explicit probe expectations into a proposal; do not write or run them."""
    root = Path(root).resolve()
    before = load_factory(root=root)
    current = resolve_factory(before)
    data = read_mapping(yaml_text) if yaml_text is not None else deepcopy(before.data)
    validate_definition(data)
    # A verifier proposal cannot modify workflow, permissions or release authority.
    if data != before.data:
        raise ValueError("Save the Factory draft before proposing its verifiers")
    accepted = data["orchestration"]["acceptance_checks"]
    if not isinstance(checks, dict) or not checks or set(checks) - set(accepted):
        raise ValueError("Choose existing final acceptance checks for verifier drafts")
    files = {}
    for name, manifest in checks.items():
        text = canonical(manifest)
        _safe_text("protected-probes.json", text)
        parse_probes(text)
        token = digest(text)[7:]
        asset = "verify-" + token[:24]
        path = ".superqode/evaluators/probe-" + token + ".json"
        files[path] = text
        existing = data["data_context"].setdefault("files", {}).get(asset)
        binding = {"path": path, "purpose": "evaluator"}
        if existing is not None and existing != binding:
            raise ValueError("Generated verifier asset conflicts with an existing binding")
        data["data_context"]["files"][asset] = binding
        data["improvement"]["checks"][name]["evaluator"] = asset
    text = yaml.safe_dump(data, sort_keys=False)
    snapshot = resolve_factory(
        FactoryDefinition(root, before.path, data), source_text=text, source_overlays=files
    )
    from .compiler import _compile_factory
    from .verification import evaluator_contract

    # Validate the complete final check set, including the existing evaluators.
    # Partial drafts can still be reviewed but report what's not protected yet.
    missing = [name for name in accepted if "evaluator" not in data["improvement"]["checks"][name]]
    if not missing:
        from .compiler import repository_revision

        evaluator_contract(
            _compile_factory(
                snapshot,
                root=root,
                goal="Review verifier configuration",
                revision=repository_revision(root),
            )
        )
    value = {
        "format": "superqode.factory-verifier-draft/1",
        "base_snapshot_digest": current.digest,
        "snapshot_digest": snapshot.digest,
        "yaml": text,
        "files": files,
        "checks": checks,
        "missing_protected_checks": missing,
        "proposal_only": True,
        "execution_started": False,
        "notice": "Review expectations independently. Generated checks are unmeasured and do not establish release readiness.",
    }
    value["digest"] = digest(canonical(value))
    return value


def install(root, proposal, *, expected, confirmed=False):
    """Save reviewed configuration only. New runs still require fresh compilation."""
    if confirmed is not True:
        raise ValueError("Explicitly confirm saving the reviewed verifier configuration")
    if (
        not isinstance(proposal, dict)
        or proposal.get("format") != "superqode.factory-verifier-draft/1"
    ):
        raise ValueError("Choose a reviewed verifier proposal")
    root = Path(root).resolve()
    with execution(root, exclusive=True), ownership(root):
        regenerated = draft(root, proposal["checks"])
        if regenerated != proposal or regenerated["digest"] != expected:
            raise ValueError("Verifier draft or its source changed; generate and review again")
        # Content-addressed new files first, factory last. An interrupted save may
        # leave inert assets, but cannot point the factory at incomplete files.
        for name, text in proposal["files"].items():
            path = source_path(root, name)
            if path.exists() and path.read_text() != text:
                raise ValueError("Verifier file contents changed")
        for name, text in proposal["files"].items():
            write(source_path(root, name), text)
        write(source_path(root, ".superqode/factory.yaml"), proposal["yaml"])
    return {
        "saved": True,
        "snapshot_digest": proposal["snapshot_digest"],
        "execution_started": False,
        "release_authorized": False,
    }


async def generate(root, *, description, provider, model, gateway=None):
    """Use an explicit drafting model; its output remains an unexecuted proposal."""
    from superqode.providers.gateway import GatewayFactory, Message
    from superqode.desktop_service.studio import _credentials
    from .generation import check_generation_route

    if (
        not isinstance(description, str)
        or not 0 < len(description.strip()) <= 8000
        or not provider
        or not model
    ):
        raise ValueError("Describe acceptance expectations and explicitly select a model")
    definition = load_factory(root=root)
    _credentials(definition.data)
    check_generation_route(definition.data, provider, model)
    before = resolve_factory(definition).digest
    gateway = gateway or GatewayFactory.create(timeout=60)
    response = await asyncio.wait_for(
        gateway.chat_completion(
            messages=[
                Message(
                    role="system",
                    content=(
                        "Propose protected acceptance probes. Return JSON with checks, assumptions and missing_capabilities. "
                        "checks maps existing final acceptance check names to probe manifests; the other fields are lists of strings. "
                        "Runtime is Python standard library only, "
                        "read-only candidate, writable TMPDIR, no sockets/network or third-party dependencies. "
                        "Cover requested build/start/health/service behavior only when achievable under these limits. "
                        "Report unsupported requirements in missing_capabilities; return empty checks if none can be tested. "
                        "Do not claim probes passed. Expectations need independent human review. No tools are available. "
                        "Do not invent credentials or silently change expected business behavior. Manifest schema: "
                        + json.dumps(PROBE_SCHEMA)
                    ),
                ),
                Message(
                    role="user",
                    content=description + "\nFactory:\n" + yaml.safe_dump(definition.data),
                ),
            ],
            provider=provider,
            model=model,
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
        raise ValueError("Verifier proposal exceeds its bound")
    data = json.loads(text)
    if (
        not isinstance(data, dict)
        or "checks" not in data
        or set(data) - {"checks", "assumptions", "missing_capabilities"}
    ):
        raise ValueError("Model must return a checks object")
    for key in ("assumptions", "missing_capabilities"):
        values = data.get(key, [])
        if (
            not isinstance(values, list)
            or len(values) > 20
            or any(not isinstance(v, str) or len(v) > 2000 for v in values)
        ):
            raise ValueError("Model must return bounded assumptions and missing capabilities")
    if data["checks"] == {} and data.get("missing_capabilities"):
        result = None
    else:
        result = draft(root, data["checks"])
    if resolve_factory(load_factory(root=root)).digest != before:
        raise ValueError("Factory changed during verifier generation")
    return {
        "proposal": result,
        "assumptions": data.get("assumptions", []),
        "missing_capabilities": data.get("missing_capabilities", []),
        "usage": asdict(response.usage) if response.usage else None,
        "cost": asdict(response.cost) if response.cost else None,
    }
