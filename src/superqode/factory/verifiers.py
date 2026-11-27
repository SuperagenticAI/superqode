"""Reviewable project-specific verifier drafts using the protected probe runtime."""

import asyncio
from dataclasses import asdict
from copy import deepcopy
import difflib
import json
from pathlib import Path
import shlex

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
        "diff": "".join(
            difflib.unified_diff(
                before.path.read_text().splitlines(True),
                text.splitlines(True),
                fromfile="Saved Factory",
                tofile="Proposed verifier configuration",
            )
        ),
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


def _extract_json_object(text: str) -> dict:
    """Parse a JSON object even when a model wraps it in markdown fences or prose."""
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        parts = stripped.split("\n", 1)
        body = parts[1] if len(parts) > 1 else ""
        if "```" in body:
            body = body.rsplit("```", 1)[0]
        stripped = body.strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(stripped):
        if ch != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(stripped[idx:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    raise ValueError("Model response did not contain a valid JSON object")


def build_default_probe_manifest(root: Path, *, command: str = "") -> dict | None:
    """Build a starter protected Python probe manifest from the repo's test command."""
    root = Path(root).resolve()
    tokens: list[str] = []
    if command and command.strip():
        try:
            tokens = shlex.split(command.strip())
        except ValueError:
            tokens = []
    case_argv: list[str] | None = None
    if tokens and Path(tokens[0]).name in {"python", "python3"} and len(tokens) >= 2:
        if tokens[1] == "-m" and len(tokens) >= 3:
            module = tokens[2]
            mod_argv = [module, *tokens[3:]]
            code = (
                f"import runpy, sys; sys.path.insert(0, '.'); sys.argv = {mod_argv!r}; "
                f"runpy.run_module({module!r}, run_name='__main__'); print('SUPERQODE_PROBE_OK')"
            )
            case_argv = ["python", "-c", code]
        elif not tokens[1].startswith("-"):
            script = tokens[1]
            try:
                candidate = source_path(root, script)
            except ValueError:
                candidate = None
            if candidate is not None and candidate.is_file():
                script_argv = [script, *tokens[2:]]
                code = (
                    f"import runpy, sys; sys.path.insert(0, '.'); sys.argv = {script_argv!r}; "
                    f"runpy.run_path({script!r}, run_name='__main__'); print('SUPERQODE_PROBE_OK')"
                )
                case_argv = ["python", "-c", code]
    if case_argv is None and (root / "self_check.py").is_file():
        code = (
            "import runpy, sys; sys.path.insert(0, '.'); sys.argv = ['self_check.py']; "
            "runpy.run_path('self_check.py', run_name='__main__'); print('SUPERQODE_PROBE_OK')"
        )
        case_argv = ["python", "-c", code]
    if case_argv is None and (root / "app.py").is_file():
        code = (
            "import py_compile; py_compile.compile('app.py', doraise=True); "
            "print('SUPERQODE_PROBE_OK')"
        )
        case_argv = ["python", "-c", code]
    if case_argv is None:
        return None
    manifest = {
        "format": "superqode.factory-probes/1",
        "cases": [
            {
                "id": "regression-probe",
                "argv": case_argv,
                "stdout_contains": "SUPERQODE_PROBE_OK",
                "returncode": 0,
            }
        ],
    }
    parse_probes(canonical(manifest))
    return manifest


def scaffold_evaluator(
    root,
    *,
    yaml_text: str = "",
    check: str = "regression",
    command: str = "",
    manifest: dict | None = None,
) -> dict:
    """Write a starter protected probe manifest and bind it into the Factory draft."""
    root = Path(root).resolve()
    data = read_mapping(yaml_text) if yaml_text and yaml_text.strip() else None
    effective_command = command.strip()
    if data and "apiVersion" in data:
        validate_definition(data)
        checks = data.get("improvement", {}).get("checks", {})
        if check not in checks:
            accepted = data.get("orchestration", {}).get("acceptance_checks") or []
            if accepted:
                check = str(accepted[0])
        existing_check = checks.get(check) if isinstance(checks, dict) else None
        if isinstance(existing_check, dict):
            existing_eval = existing_check.get("evaluator")
            files_map = data.get("data_context", {}).get("files", {})
            if (
                existing_eval
                and existing_eval in files_map
                and (root / files_map[existing_eval]["path"]).is_file()
            ):
                return {
                    "written": False,
                    "already_configured": True,
                    "path": files_map[existing_eval]["path"],
                    "asset": existing_eval,
                    "yaml": yaml_text,
                }
            if not effective_command:
                effective_command = str(existing_check.get("command") or "")
    chosen_manifest = manifest or build_default_probe_manifest(root, command=effective_command)
    if chosen_manifest is None:
        return {
            "written": False,
            "already_configured": False,
            "yaml": yaml_text,
            "reason": "No Python check script detected for automatic protected probe scaffolding.",
        }
    text = canonical(chosen_manifest)
    _safe_text("protected-probes.json", text)
    parse_probes(text)
    rel_path = f".superqode/evaluators/{check}.json"
    asset = f"evaluator-{check}"
    write(source_path(root, rel_path), text)
    updated_yaml = yaml_text
    if data and "apiVersion" in data:
        checks = data.setdefault("improvement", {}).setdefault("checks", {})
        if check in checks and isinstance(checks[check], dict):
            data.setdefault("data_context", {}).setdefault("files", {})[asset] = {
                "path": rel_path,
                "purpose": "evaluator",
            }
            checks[check]["evaluator"] = asset
            validate_definition(data)
            updated_yaml = yaml.safe_dump(data, sort_keys=False)
    return {
        "written": True,
        "already_configured": False,
        "path": rel_path,
        "asset": asset,
        "yaml": updated_yaml,
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
    text = (response.content or "").strip()
    if len(text.encode()) > 250000:
        raise ValueError("Verifier proposal exceeds its bound")
    data = _extract_json_object(text)
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
