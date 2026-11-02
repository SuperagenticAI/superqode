"""Reviewed Harness Studio editing, immutable revisions and exact-definition evidence."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

import yaml

from superqode.harness.catalog import resolve_harness, list_harnesses
from superqode.harness.loader import (
    harness_spec_from_dict,
    harness_spec_to_dict,
    validate_harness_data,
)
from superqode.harness.backends.registry import inspect_harness_backend


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", value):
        raise ValueError(
            "Use a lowercase harness name with letters, numbers or hyphens (up to 64 characters)"
        )
    return value


def within(root, relative):
    original = root / relative
    for part in (original, *original.parents):
        if part == root:
            break
        if part.is_symlink():
            raise ValueError("Harness Studio storage cannot use symbolic links")
    path = original.resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("Harness Studio storage points outside this project")
    return path


def target(root, slug):
    return within(root, Path(".superqode/harnesses") / (name(slug) + ".yaml"))


def revision_folder(root, slug):
    return within(root, Path(".superqode/harness-studio") / name(slug))


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def text_at(path):
    return path.read_bytes().decode("utf-8")


def _credentials(data, seen=None, depth=0, budget=None):
    budget = [20_000] if budget is None else budget
    budget[0] -= 1
    if budget[0] < 0:
        raise ValueError("Use a smaller definition without repeated YAML aliases")
    if depth > 32:
        raise ValueError("Use a HarnessSpec with at most 32 nested levels")
    if isinstance(data, (dict, list)):
        seen = set() if seen is None else seen
        if id(data) in seen:
            raise ValueError("Recursive YAML aliases are not supported")
        seen = seen | {id(data)}
        pairs = data.items() if isinstance(data, dict) else enumerate(data)
        for key, value in pairs:
            credential = re.sub(r"[^a-z]", "", str(key).lower()) in {
                "apikey",
                "token",
                "accesstoken",
                "secret",
                "clientsecret",
                "password",
                "authorization",
            }
            if (
                credential
                and isinstance(value, str)
                and value
                and not re.fullmatch(r"\$\{[A-Z][A-Z0-9_]*\}", value)
            ):
                raise ValueError(
                    "Keep credentials in Connect/Keychain or an environment reference; remove inline credentials before saving"
                )
            _credentials(value, seen, depth + 1, budget)


def parse(text, slug):
    if not isinstance(text, str) or len(text.encode()) > 250_000:
        raise ValueError("Use a HarnessSpec smaller than 250 KB")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("Enter a YAML HarnessSpec mapping")
    data = data.get("harness", data)
    if not isinstance(data, dict) or "inherits" in data or "extends" in data:
        raise ValueError("Load a resolved preset before editing an inherited definition")
    _credentials(data)
    data["name"] = name(slug)
    validate_harness_data(data)
    return harness_spec_from_dict(data)


def route(params, spec):
    from superqode.providers.registry import PROVIDERS
    from superqode.local.workbench import ENGINES, PROVIDERS as LOCAL_PROVIDERS
    from superqode.local.servers import SPECS

    selection = params.get("route") or {}
    if selection.get("source") == "local":
        engine = selection.get("engine")
        if engine not in ENGINES:
            raise ValueError("Choose a supported local server")
        provider = LOCAL_PROVIDERS[engine]
        endpoint = f"http://127.0.0.1:{SPECS[engine].default_port}/v1"
    elif selection.get("source") == "provider":
        provider = selection.get("provider")
        if provider not in PROVIDERS or PROVIDERS[provider].harness_only:
            raise ValueError("Choose a model provider from Connect")
        endpoint = None
    elif selection.get("source") in {None, "definition"}:
        primary = spec.model_policy.primary or ""
        stored = spec.metadata.get("desktop_model_route") or {}
        if (
            isinstance(stored, dict)
            and stored.get("source") in {"local", "provider"}
            and primary == str(stored.get("provider")) + "/" + str(stored.get("model"))
        ):
            return route({"route": stored}, spec)
        provider, _, model = primary.partition("/")
        return spec, {
            "source": "definition",
            "provider": provider if model else "",
            "model": model or primary,
            "endpoint": None,
        }
    else:
        raise ValueError("Agent-owned model selection stays in Connect with that agent")
    model = selection.get("model")
    if (
        not isinstance(model, str)
        or not model.strip()
        or len(model) > 4096
        or any(ord(c) < 32 for c in model)
    ):
        raise ValueError("Choose a model identifier")
    model = model.strip()
    return replace(spec, model_policy=replace(spec.model_policy, primary=provider + "/" + model)), {
        "source": selection["source"],
        "provider": provider,
        "model": model,
        "endpoint": endpoint,
        **({"engine": selection["engine"]} if endpoint else {}),
    }


def inspect(service, params):
    root = service.project(params["project"])
    spec, selected = route(params, parse(params.get("yaml"), params.get("name")))
    spec = replace(spec, metadata={**spec.metadata, "desktop_model_route": selected})
    data = harness_spec_to_dict(spec)
    text = yaml.safe_dump(data, sort_keys=False)
    inspection = inspect_harness_backend(spec.runtime.backend, spec).to_dict()
    warnings = [item["message"] for item in inspection["issues"]]
    if inspection["capabilities"]["availability"] != "available":
        warnings.append("Backend dependencies or configuration need setup before execution.")
    if not spec.model_policy.primary:
        warnings.append("Choose a primary model before running this definition.")
    routes = [{"role": "Primary", "model": spec.model_policy.primary or "Selected when running"}]
    routes += [{"role": "Fallback", "model": model} for model in spec.model_policy.fallbacks]
    routes += [
        {"role": "Agent " + agent.id, "model": agent.model} for agent in spec.agents if agent.model
    ]
    if spec.recursion.child_model:
        routes.append({"role": "Recursive child", "model": spec.recursion.child_model})
    if selected["source"] == "local" and len(routes) > 1:
        warnings.append(
            "Only the primary route is bound locally; inspect delegate and fallback routes separately."
        )
    from superqode import __version__

    review = {
        "project": params["project"],
        "name": spec.name,
        "yaml": text,
        "digest": sha(text),
        "route": selected,
        "backend": spec.runtime.backend,
        "inspection": inspection,
        "routes": routes,
        "policy": data["execution_policy"],
        "tools": [tool for agent in spec.agents for tool in agent.tools],
        "warnings": warnings,
        "engine_version": __version__,
        "created": time.time(),
        "expected_file_digest": file_digest(target(root, spec.name)),
    }
    identity = sha(json.dumps(review, sort_keys=True))
    service._write("DELETE FROM studio_reviews WHERE created<?", (time.time() - 1800,))
    service._write(
        "INSERT INTO studio_reviews VALUES(?,?,?,?)",
        (identity, params["project"], json.dumps(review), time.time()),
    )
    return {**review, "review": identity}


def reviewed(service, params):
    rows = service._all(
        "SELECT * FROM studio_reviews WHERE id=? AND project=?",
        (params.get("review"), params["project"]),
    )
    if not rows or time.time() - rows[0]["created"] > 1800:
        raise ValueError("Validate the harness again; this review is missing or expired")
    review = json.loads(rows[0]["payload"])
    if params.get("digest") != review["digest"]:
        raise ValueError("The definition changed after validation")
    return review


def _atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".studio-")
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _snapshot(root, slug, text, metadata):
    digest = sha(text)
    folder = revision_folder(root, slug)
    yaml_path = within(root, folder.relative_to(root) / (digest + ".yaml"))
    record_path = within(root, folder.relative_to(root) / (digest + ".json"))
    if yaml_path.exists() and text_at(yaml_path) != text:
        raise ValueError("A stored revision was modified; restore it before saving")
    if not yaml_path.exists():
        _atomic(yaml_path, text)
    if not record_path.exists():
        _atomic(
            record_path, json.dumps({**metadata, "digest": digest, "name": slug}, indent=2) + "\n"
        )
    return yaml_path


def save(service, params):
    from .ownership import Lease, project_lease_path

    review = reviewed(service, params)
    root = service.project(params["project"])
    reason = params.get("reason", "")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
        raise ValueError("Describe this revision in up to 2,000 characters")
    with service.lock:
        if service._all(
            "SELECT id FROM jobs WHERE project=? AND status IN ('running','queued','needs_approval','cancelling')",
            (params["project"],),
        ):
            raise ValueError("Finish project work before saving a harness revision")
        lease = Lease(project_lease_path(service.root, root))
        try:
            path = target(root, review["name"])
            current = file_digest(path)
            if (
                params.get("expected_file_digest", "") != current
                or review["expected_file_digest"] != current
            ):
                raise ValueError("The project definition changed. Reload it before saving")
            if not current and any(h.id == review["name"] for h in list_harnesses(root)):
                raise ValueError(
                    "That harness name is already in the catalog. Save this copy under a new name"
                )
            if current:
                _snapshot(
                    root,
                    review["name"],
                    text_at(path),
                    {
                        "created": time.time(),
                        "reason": "Previous project definition",
                        "source": "existing-file",
                    },
                )
            revision = _snapshot(
                root,
                review["name"],
                review["yaml"],
                {
                    "created": time.time(),
                    "reason": reason.strip(),
                    "parent": current,
                    "route": review["route"],
                    "backend": review["backend"],
                    "engine_version": review["engine_version"],
                },
            )
            _atomic(path, review["yaml"])
            history = within(
                root, revision_folder(root, review["name"]).relative_to(root) / "history.jsonl"
            )
            with history.open("a", encoding="utf-8") as output:
                output.write(
                    json.dumps(
                        {
                            "digest": review["digest"],
                            "parent": current,
                            "created": time.time(),
                            "reason": reason.strip(),
                        }
                    )
                    + "\n"
                )
                output.flush()
                os.fsync(output.fileno())
            return {
                "id": review["name"],
                "path": str(path),
                "reference": str(revision),
                "digest": review["digest"],
                "route": review["route"],
            }
        finally:
            lease.close()


def revisions(service, project, slug):
    root = service.project(project)
    folder = revision_folder(root, slug)
    current = file_digest(target(root, slug))
    rows = []
    for file in folder.glob("*.json"):
        try:
            file = within(root, file.relative_to(root))
            if not re.fullmatch(r"[0-9a-f]{64}\.json", file.name) or file.stat().st_size > 300_000:
                continue
            data = json.loads(file.read_text())
            if not isinstance(data, dict) or type(data.get("created")) not in {int, float}:
                continue
            digest = file.stem
            path = within(root, folder.relative_to(root) / (digest + ".yaml"))
            rows.append(
                {
                    **data,
                    "id": digest,
                    "current": digest == current,
                    "intact": path.is_file() and file_digest(path) == digest,
                    "reference": str(path),
                }
            )
        except (OSError, ValueError, TypeError):
            continue
    return sorted(rows, key=lambda row: row.get("created", 0), reverse=True)[:100]


def open_definition(service, params):
    root = service.project(params["project"])
    if params.get("revision"):
        row = next(
            (
                r
                for r in revisions(service, params["project"], name(params.get("name")))
                if r["id"] == params["revision"] and r["intact"]
            ),
            None,
        )
        if not row:
            raise ValueError("This revision is unavailable or has changed")
        text, slug = text_at(Path(row["reference"])), params["name"]
        _, selected = route({}, harness_spec_from_dict(yaml.safe_load(text)))
    else:
        definition = resolve_harness(params.get("reference") or "core", root=root)
        data = harness_spec_to_dict(replace(definition.spec, inherits=None))
        text = yaml.safe_dump(data, sort_keys=False)
        own = (
            re.fullmatch(r"[a-z][a-z0-9-]{0,63}", definition.spec.name)
            and definition.path
            and definition.path.resolve() == target(root, definition.spec.name)
        )
        slug = (
            definition.spec.name
            if own
            else ("my-" + re.sub(r"[^a-z0-9-]", "-", definition.spec.name.lower()))[:64]
        )
        _, selected = route({}, definition.spec)
    return {
        "yaml": text,
        "name": slug,
        "route": selected,
        "expected_file_digest": file_digest(target(root, slug)),
    }


def catalog(service, project):
    root = service.project(project)
    directory = within(root, ".superqode/harness-studio")
    rows = []
    for folder in sorted(directory.glob("*")):
        if (
            not folder.is_symlink()
            and folder.is_dir()
            and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", folder.name)
        ):
            versions = revisions(service, project, folder.name)
            if versions:
                rows.append({"id": folder.name, "revisions": versions})
    return rows[:200]


def prepare_check(service, params):
    from superqode.harness.verification import SUPPORTED_CHECK_BACKENDS
    from superqode.providers.registry import PROVIDERS
    from .local_models import available
    from superqode.local.workbench import PROVIDERS as LOCAL_PROVIDERS

    review = reviewed(service, params)
    kind, repeats = params.get("check", "read"), params.get("repeats", 1)
    if kind not in {"read", "edit"} or type(repeats) is not int or not 1 <= repeats <= 5:
        raise ValueError("Choose a read/edit check and between one and five attempts")
    if review["backend"] not in SUPPORTED_CHECK_BACKENDS:
        raise ValueError(
            "This backend needs its own check adapter; use Evaluate with the saved revision"
        )
    inspection = review["inspection"]
    if not inspection["ok"] or inspection["capabilities"]["availability"] != "available":
        raise ValueError("Resolve backend setup and validation errors before running a check")
    source_spec = harness_spec_from_dict(yaml.safe_load(review["yaml"]))
    if not source_spec.is_coding or not source_spec.execution_policy.allow_read:
        raise ValueError(
            "Read/edit checks need a coding harness with reads enabled; use Test model for a no-tool definition"
        )
    if kind == "edit" and not source_spec.execution_policy.allow_write:
        raise ValueError(
            "This definition disables writes. Choose a read check or revise its write policy first"
        )
    selected = dict(review["route"])
    if selected.get("provider") not in PROVIDERS or not selected.get("model"):
        raise ValueError("Choose a provider and primary model before preparing the check")
    local_engine = next(
        (
            engine
            for engine, provider in LOCAL_PROVIDERS.items()
            if provider == selected["provider"]
        ),
        None,
    )
    if local_engine:
        live = available(local_engine)
        if selected["model"] not in live["models"]:
            raise ValueError("Load this model on the selected local server before checking it")
        selected.update(source="local", engine=local_engine, endpoint=live["endpoint"])
    plan = {
        "project": params["project"],
        "source_digest": review["digest"],
        "spec": yaml.safe_load(review["yaml"]),
        "route": selected,
        "check": kind,
        "repeats": repeats,
        "engine_version": review["engine_version"],
        "title": f"Harness check · {review['name']} · {repeats} attempt(s)",
        "created": time.time(),
        "scope": "Reduced profile using this backend and primary model; model settings follow the adapter's capabilities. Original instructions, context, hooks, MCP, fallbacks, delegation and shell are excluded. Up to six model turns, a requested limit of 768 output tokens per call, and 120 seconds per attempt. Provider charges can apply. No project files are passed to the check.",
    }
    identity = sha(json.dumps(plan, sort_keys=True))
    service._write("DELETE FROM studio_check_plans WHERE created<?", (time.time() - 1800,))
    service._write(
        "INSERT INTO studio_check_plans VALUES(?,?,?,?)",
        (identity, params["project"], json.dumps(plan), time.time()),
    )
    return {**plan, "plan": identity, "digest": identity}


def start_check(service, params):
    from .local_models import available

    rows = service._all(
        "SELECT * FROM studio_check_plans WHERE id=? AND project=?",
        (params.get("plan"), params["project"]),
    )
    if not rows or time.time() - rows[0]["created"] > 1800:
        raise ValueError("Prepare the harness check again; this plan expired")
    plan = json.loads(rows[0]["payload"])
    if params.get("digest") != sha(json.dumps(plan, sort_keys=True)):
        raise ValueError("The reviewed check changed")
    # Check idempotency before probing an endpoint that may have stopped afterwards.
    for old in service._all(
        "SELECT id,request FROM jobs WHERE project=? AND kind='studio'", (params["project"],)
    ):
        request = json.loads(old["request"])
        if params.get("command_id") and request.get("command_id") == params["command_id"]:
            if request.get("studio_plan") != plan:
                raise ValueError("This command ID belongs to another check")
            return {"id": old["id"]}
    if plan["route"].get("engine"):
        route = available(plan["route"]["engine"])
        if (
            route["endpoint"] != plan["route"]["endpoint"]
            or plan["route"]["model"] not in route["models"]
        ):
            raise ValueError("The local server/model changed; prepare the check again")
    return service.start(
        params["project"],
        "studio",
        {
            "studio_plan": plan,
            "provider": plan["route"]["provider"],
            "model": plan["route"]["model"],
            "command_id": params.get("command_id"),
        },
    )


def evidence(service, params):
    service.project(params["project"])
    rows = service._all(
        "SELECT id,title,status,request,result,created FROM jobs WHERE project=? AND kind='studio' ORDER BY created DESC LIMIT 100",
        (params["project"],),
    )
    output = []
    for row in rows:
        request = json.loads(row.pop("request"))
        if params.get("digest") and request["studio_plan"]["source_digest"] != params["digest"]:
            continue
        output.append(
            {
                **row,
                "result": json.loads(row["result"]) if row["result"] else None,
                "source_digest": request["studio_plan"]["source_digest"],
            }
        )
    return output


def use_revision(service, params):
    from .local_models import available

    project = params["project"]
    row = next(
        (
            r
            for r in revisions(service, project, name(params.get("name")))
            if r["id"] == params.get("revision") and r["intact"]
        ),
        None,
    )
    if not row:
        raise ValueError("Choose an intact saved revision")
    definition = resolve_harness(row["reference"], root=service.project(project))
    selected = definition.spec.metadata.get("desktop_model_route") or {}
    inspection = inspect_harness_backend(definition.spec.runtime.backend, definition.spec)
    if not inspection.ok or inspection.capabilities.availability != "available":
        raise ValueError("Set up this backend and resolve its validation issues first")
    if not selected.get("provider") or not selected.get("model"):
        _, selected = route({}, definition.spec)
    if not selected.get("provider") or not selected.get("model"):
        raise ValueError(
            "Choose a primary provider/model before selecting this revision. Agent-owned connections are selected through Connect"
        )
    with service.lock:
        if service._all(
            "SELECT id FROM jobs WHERE project=? AND status IN ('running','queued','needs_approval','cancelling')",
            (project,),
        ):
            raise ValueError("Finish project work before changing its selected revision")
        if selected.get("source") == "local":
            live = available(selected["engine"])
            if selected["model"] not in live["models"] or live["endpoint"] != selected["endpoint"]:
                raise ValueError(
                    "Load the revision's model on its local server before selecting it"
                )
            for reference in (row["reference"], "no-tool"):
                service._write(
                    "INSERT OR REPLACE INTO local_model_bindings VALUES(?,?,?,?,?)",
                    (
                        project,
                        reference,
                        selected["provider"],
                        selected["model"],
                        selected["endpoint"],
                    ),
                )
        if selected.get("source") == "provider":
            service._write(
                "DELETE FROM local_model_bindings WHERE project=? AND provider=? AND model=?",
                (project, selected["provider"], selected["model"]),
            )
        service._write(
            "INSERT OR REPLACE INTO settings VALUES(?,?)",
            (
                "studio-selection:" + project,
                json.dumps(
                    {"reference": row["reference"], "digest": row["id"], "name": params["name"]}
                ),
            ),
        )
    return {"reference": row["reference"], "digest": row["id"], "route": selected}


def selection(service, project):
    rows = service._all("SELECT value FROM settings WHERE key=?", ("studio-selection:" + project,))
    if not rows:
        return []
    try:
        record = json.loads(rows[0]["value"])
        version = next(
            (
                r
                for r in revisions(service, project, record["name"])
                if r["id"] == record["digest"] and r["intact"]
            ),
            None,
        )
        if not version:
            return []
        definition = resolve_harness(version["reference"], root=service.project(project))
        from .session_controls import enforces_session_controls

        return [
            {
                "id": version["reference"],
                "name": record["name"] + " · " + record["digest"][:8],
                "description": "Saved Harness Studio revision",
                "runtime": definition.runtime,
                "available": definition.available,
                "issue": definition.issue,
                "digest": definition.digest,
                "path": version["reference"],
                "enforces_session_controls": enforces_session_controls(definition.runtime),
            }
        ]
    except (ValueError, KeyError, OSError):
        return []


def handle(service, method, params):
    if method == "studio.check.prepare":
        return prepare_check(service, params)
    if method == "studio.check.start":
        return start_check(service, params)
    if method == "studio.evidence":
        return evidence(service, params)
    if method == "studio.use":
        return use_revision(service, params)
    if method == "studio.open":
        return open_definition(service, params)
    if method == "studio.inspect":
        return inspect(service, params)
    if method == "studio.save":
        return save(service, params)
    if method == "studio.list":
        return catalog(service, params["project"])
    if method == "studio.revisions":
        return revisions(service, params["project"], name(params.get("name")))
    raise ValueError("Unknown Harness Studio operation")
