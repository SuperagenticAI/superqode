"""Versioned factory definitions, preserving the existing routing policy shape."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator
import yaml

from . import contracts

API_VERSION = "superqode.dev/v1alpha1"
LAYERS = (
    "Factories-as-code",
    "Data and context",
    "Compute",
    "Inference",
    "Improvement",
    "Orchestration",
    "Access",
)
MAX_FILE_BYTES = 250_000
NAME = {"type": "string", "pattern": "^[a-z][a-z0-9-]{0,63}$"}
TEXT = {"type": "string", "minLength": 1, "pattern": r"\S"}


def obj(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def named(value, minimum=0):
    return {
        "type": "object",
        "propertyNames": NAME,
        "additionalProperties": value,
        "minProperties": minimum,
    }


def strings(items=TEXT, minimum=0):
    return {"type": "array", "items": items, "uniqueItems": True, "minItems": minimum}


PERMISSIONS = obj(
    {
        key: {"type": "boolean"}
        for key in (
            "allow_read",
            "allow_write",
            "allow_shell",
            "allow_network",
        )
    }
)
HARNESS = obj(
    {"path": TEXT, "template": TEXT, "model": TEXT, "skills": {**strings(NAME), "maxItems": 8}}
)
HARNESS["oneOf"] = [{"required": ["path"]}, {"required": ["template"]}]
ROUTE = {
    "type": "object",
    "properties": {
        "allow_cloud": {"type": "boolean"},
        "allow_subscription_runtimes": {"type": "boolean"},
        "prefer": strings(),
        "harness": TEXT,
    },
}
EXPERIMENT_POLICY = obj(
    {
        "triggers": strings(
            {
                "enum": [
                    "reviewed_failure",
                    "reviewer_feedback",
                    "cost_drift",
                    "incident",
                    "dependency_update",
                ]
            },
            1,
        ),
        "event_sources": obj(
            {
                key: TEXT
                for key in ("reviewer_feedback", "cost_drift", "incident", "dependency_update")
            }
        ),
        "max_experiments": {"type": "integer", "minimum": 1, "maximum": 20},
        "max_seconds": {"type": "integer", "minimum": 1, "maximum": 86400},
        "max_tokens": {"type": "integer", "minimum": 1},
        "max_tool_calls": {"type": "integer", "minimum": 1},
        "max_cost_usd": {"type": "number", "exclusiveMinimum": 0},
        "cooldown_seconds": {"type": "integer", "minimum": 0, "maximum": 86400},
        "max_depth": {"type": "integer", "minimum": 0, "maximum": 3},
        "stop_after_holds": {"type": "integer", "minimum": 1, "maximum": 20},
        "experiment": obj(
            {
                "binding": NAME,
                "tasks": TEXT,
                "fixture": TEXT,
                "target_kind": {"enum": ["harness", "skill", "route", "workflow"]},
                "skill": TEXT,
                "stage": NAME,
                "route_models": strings(TEXT, 1),
                "reflection_model": TEXT,
                "optimizer_engine": {
                    "enum": ["gepa", "evaluator-optimizer", "metaharness", "omni"]
                },
                "max_evals": {"type": "integer", "minimum": 1, "maximum": 20},
                "max_seconds": {"type": "integer", "minimum": 1, "maximum": 600},
            },
            (
                "binding",
                "tasks",
                "fixture",
                "reflection_model",
                "optimizer_engine",
                "max_evals",
                "max_seconds",
            ),
        ),
    },
    (
        "triggers",
        "max_experiments",
        "max_seconds",
        "max_tokens",
        "max_tool_calls",
        "max_cost_usd",
        "cooldown_seconds",
        "max_depth",
        "stop_after_holds",
        "experiment",
    ),
)
INTAKE_SOURCE = obj(
    {
        "secret_env": {"type": "string", "pattern": "^SUPERQODE_FACTORY_[A-Z0-9_]+_SECRET$"},
        "scope": TEXT,
        "actions": strings(TEXT, 1),
    },
    ("secret_env", "scope", "actions"),
)
SCHEMA = obj(
    {
        "apiVersion": {"const": API_VERSION},
        "kind": {"const": "Factory"},
        "metadata": obj({"name": NAME, "description": {"type": "string"}}, ("name",)),
        # These keys remain at their legacy locations for existing route consumers.
        "default_route": NAME,
        "routes": named(ROUTE),
        "data_context": obj(
            {
                "repository": {"const": "."},
                "requirements": {
                    **named(
                        obj(
                            {
                                "description": {**TEXT, "maxLength": 2000},
                                "stages": strings(NAME, 1),
                                "checks": strings(NAME, 1),
                            },
                            ("description", "stages", "checks"),
                        )
                    ),
                    "maxProperties": 128,
                },
                "files": named(
                    obj(
                        {
                            "path": TEXT,
                            "purpose": {
                                "enum": [
                                    "context",
                                    "skill",
                                    "evaluator",
                                ]
                            },
                        },
                        ("path", "purpose"),
                    )
                ),
            },
            ("repository",),
        ),
        "compute": obj({"runner": {"const": "worktree"}}, ("runner",)),
        "inference": obj({"harnesses": named(HARNESS, 1)}, ("harnesses",)),
        "improvement": obj(
            {
                "checks": named(
                    obj(
                        {
                            "command": TEXT,
                            "files": strings(NAME),
                            "evaluator": NAME,
                            "category": {
                                "enum": ["test", "build", "start", "health", "service", "security"]
                            },
                        },
                        ("command",),
                    ),
                    1,
                ),
                "optimization": obj(
                    {
                        "automatic_experiments": {"type": "boolean"},
                        "experiment_policy": EXPERIMENT_POLICY,
                        "editable": strings(
                            {"enum": ["skills", "harnesses", "routes", "workflow"]}
                        ),
                        "protected": strings(TEXT),
                    }
                ),
            },
            ("checks",),
        ),
        "orchestration": obj(
            {
                "intake": obj(
                    {
                        "enabled": {"type": "boolean"},
                        "max_pending": {"type": "integer", "minimum": 1, "maximum": 64},
                        "max_per_hour": {"type": "integer", "minimum": 1, "maximum": 64},
                        "sources": obj(
                            {name: INTAKE_SOURCE for name in ("github", "linear", "monitor")}
                        ),
                        "schedules": {
                            "type": "array",
                            "maxItems": 16,
                            "items": obj(
                                {
                                    "id": NAME,
                                    "goal": TEXT,
                                    "interval_minutes": {
                                        "type": "integer",
                                        "minimum": 5,
                                        "maximum": 10080,
                                    },
                                },
                                ("id", "goal", "interval_minutes"),
                            ),
                        },
                    },
                    ("enabled", "max_pending", "max_per_hour", "sources"),
                ),
                "stages": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 64,
                    "items": obj(
                        {
                            "id": NAME,
                            "title": TEXT,
                            "goal": TEXT,
                            "harness": NAME,
                            "role": {"enum": ["investigator", "implementer", "reviewer", "tester"]},
                            "depends_on": strings(NAME),
                            "checks": strings(NAME),
                            "permissions": PERMISSIONS,
                            "human_gate": {"type": "boolean"},
                            "inputs": contracts.named(contracts.INPUT),
                            "outputs": contracts.named(contracts.OUTPUT),
                            "when": contracts.WHEN,
                        },
                        ("id", "goal", "harness", "role"),
                    ),
                },
                "acceptance_checks": strings(NAME, 1),
                "revision_loop": contracts.REVISION_LOOP,
            },
            ("stages", "acceptance_checks"),
        ),
        "access": obj({"interfaces": strings({"enum": ["cli", "tui", "macos", "api", "mcp"]})}),
        "governance": obj(
            {
                "permissions": PERMISSIONS,
                "budget": obj(
                    {
                        "max_workers": {"type": "integer", "minimum": 1},
                        "max_seconds": {"type": "integer", "minimum": 1},
                        "max_cost_usd": {"type": "number", "exclusiveMinimum": 0},
                        "max_tokens": {"type": "integer", "minimum": 1},
                        "max_tool_calls": {"type": "integer", "minimum": 1},
                    },
                    ("max_workers", "max_seconds"),
                ),
                "release": {"const": "human"},
                # SuperGauge is the release quality control. Ship is always required.
                "release_gauge": obj(
                    {
                        "level": {"enum": ["L1", "L2", "L3", "L4"]},
                        "require_ship": {"const": True},
                    }
                ),
                "release_authority": obj(
                    {
                        "method": {"const": "p256-signature"},
                        "keys": named(
                            obj(
                                {"public_key": {"type": "string", "maxLength": 128}},
                                ("public_key",),
                            ),
                            1,
                        ),
                        "challenge_ttl_seconds": {"type": "integer", "minimum": 30, "maximum": 300},
                    },
                    ("method", "keys"),
                ),
            },
            ("permissions", "budget", "release"),
        ),
    },
    (
        "apiVersion",
        "kind",
        "metadata",
        "data_context",
        "compute",
        "inference",
        "improvement",
        "orchestration",
        "access",
        "governance",
    ),
)


class _UniqueLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str) or key in result:
            raise ValueError("Factory YAML requires unique string mapping keys")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def read_mapping(text: str) -> dict:
    if len(text.encode()) > MAX_FILE_BYTES:
        raise ValueError("Factory component exceeds 250 KB")
    try:
        data = yaml.load(text, Loader=_UniqueLoader)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid factory YAML: {exc}") from exc
    _bounded(data)
    if not isinstance(data, dict):
        raise ValueError("Factory definition must be a mapping")
    return data


def _bounded(value, ancestors=(), depth=0, budget=None):
    budget = [20_000] if budget is None else budget
    budget[0] -= 1
    if budget[0] < 0 or depth > 32 or id(value) in ancestors:
        raise ValueError("Factory YAML is too deeply nested or contains recursive aliases")
    if isinstance(value, (dict, list)):
        values = value.values() if isinstance(value, dict) else value
        for child in values:
            _bounded(child, (*ancestors, id(value)), depth + 1, budget)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError("Factory YAML must contain JSON-compatible values")
    if isinstance(value, float):
        import math

        if not math.isfinite(value):
            raise ValueError("Factory numbers must be finite")


def relative_path(relative: str) -> Path:
    """Validate a portable project-relative path without touching the filesystem."""
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("Factory paths must be project-relative")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or ".git" in path.parts or "\0" in relative:
        raise ValueError(f"Factory path must stay inside the project: {relative}")
    return path


def project_path(root: Path, relative: str) -> Path:
    """Resolve a declared project file without following links out of the project."""
    path = relative_path(relative)
    candidate = root
    for part in path.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError(f"Factory paths cannot use symbolic links: {relative}")
    if not candidate.resolve().is_relative_to(root):
        raise ValueError(f"Factory path must stay inside the project: {relative}")
    return candidate


@dataclass(frozen=True)
class FactoryDefinition:
    root: Path
    path: Path
    data: dict
    legacy: bool = False


def validate_definition(data: dict) -> None:
    _bounded(data)
    errors = sorted(Draft202012Validator(SCHEMA).iter_errors(data), key=lambda e: str(e.path))
    if errors:
        error = errors[0]
        location = ".".join(str(item) for item in error.absolute_path) or "factory"
        raise ValueError(f"{location}: {error.message}")
    optimization = data["improvement"].get("optimization", {})
    if optimization.get("automatic_experiments") and "experiment_policy" not in optimization:
        raise ValueError("automatic_experiments requires an explicit bounded experiment_policy")
    if "experiment_policy" in optimization:
        policy = optimization["experiment_policy"]
        budget = data["governance"]["budget"]
        for key in ("max_seconds", "max_tokens", "max_tool_calls", "max_cost_usd"):
            if policy[key] > budget.get(key, policy[key]):
                raise ValueError("Experiment campaign exceeds Factory budget: " + key)
        if min(policy["max_tokens"], policy["max_tool_calls"]) < policy["max_experiments"]:
            raise ValueError("Campaign budget must reserve positive limits for each experiment")
        if policy["experiment"]["binding"] not in data["inference"]["harnesses"]:
            raise ValueError("Campaign experiment requires a declared harness binding")
        for kind in policy["triggers"]:
            if kind == "reviewed_failure":
                continue
            source = policy.get("event_sources", {}).get(kind, "")
            path = relative_path(source)
            if (
                not source.startswith(".superqode/factory-events/")
                or source != path.as_posix()
                or len(path.parts) != 3
                or path.suffix != ".json"
            ):
                raise ValueError(
                    "Campaign triggers require pinned project-local JSON event_sources"
                )
    authority = data["governance"].get("release_authority")
    if authority:
        import base64
        from cryptography.hazmat.primitives.asymmetric import ec

        for signer in authority["keys"].values():
            try:
                raw = base64.b64decode(signer["public_key"], validate=True)
                if len(raw) != 65 or raw[0] != 4:
                    raise ValueError("Expected an uncompressed P-256 public key")
                ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    "Release authority requires base64 uncompressed P-256 public keys"
                ) from exc
    stages = data["orchestration"]["stages"]
    identifiers = [stage["id"] for stage in stages]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Factory stage ids must be unique")
    checks = data["improvement"]["checks"]
    for requirement in data["data_context"].get("requirements", {}).values():
        if set(requirement["stages"]) - set(identifiers):
            raise ValueError("Requirement references an unknown stage")
        if set(requirement["checks"]) - set(data["orchestration"]["acceptance_checks"]):
            raise ValueError("Requirement checks must be final acceptance checks")
    assets = data["data_context"].get("files", {})
    evaluator_paths = {
        relative_path(v["path"]).as_posix() for v in assets.values() if v["purpose"] == "evaluator"
    }
    for binding in data["inference"]["harnesses"].values():
        for identity in binding.get("skills", []):
            asset = assets.get(identity, {})
            if (
                asset.get("purpose") != "skill"
                or relative_path(asset["path"]).as_posix() in evaluator_paths
            ):
                raise ValueError(
                    "Harness skills must reference declared skill assets, never evaluator files"
                )
    for check in checks.values():
        if set(check.get("files", ())) - assets.keys():
            raise ValueError("Acceptance check references an unknown declared file")
        if "evaluator" in check:
            asset = assets.get(check["evaluator"], {})
            if asset.get("purpose") != "evaluator":
                raise ValueError("Protected checks require a declared evaluator file")
    requested = list(data["orchestration"]["acceptance_checks"])
    graph = {}
    ceiling = data["governance"]["permissions"]
    for stage in stages:
        if stage["harness"] not in data["inference"]["harnesses"]:
            raise ValueError(f"Stage {stage['id']} references an unknown harness")
        requested.extend(stage.get("checks", ()))
        graph[stage["id"]] = stage.get("depends_on", [])
        if set(graph[stage["id"]]) - set(identifiers):
            raise ValueError(f"Stage {stage['id']} has an unknown dependency")
        for key, enabled in stage.get("permissions", {}).items():
            if enabled and not ceiling.get(key, False):
                raise ValueError(f"Stage {stage['id']} widens factory permission {key}")
    if set(requested) - checks.keys():
        raise ValueError("Workflow references an unknown acceptance check")
    pending, completed = set(graph), set()
    while pending:
        ready = {key for key in pending if set(graph[key]) <= completed}
        if not ready:
            raise ValueError("Factory workflow contains a dependency cycle")
        pending -= ready
        completed |= ready
    from .contracts import validate as validate_contracts

    validate_contracts(stages)
    from .workflow import validate_composition

    validate_composition(data)
    if (
        any(s.get("inputs") or s.get("outputs") for s in stages)
        and data["governance"]["budget"]["max_workers"] != 1
    ):
        raise ValueError("Explicit stage handoffs currently require one worker per Factory")


def load_factory(path=".superqode/factory.yaml", *, root=".") -> FactoryDefinition:
    root = Path(root).resolve()
    source = project_path(root, str(path))
    if not source.is_file():
        raise ValueError("Factory definition must be a regular file")
    if source.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Factory definition exceeds 250 KB")
    data = read_mapping(source.read_text(encoding="utf-8"))
    versioned = "apiVersion" in data or "kind" in data
    if versioned:
        validate_definition(data)
    else:
        # Legacy policies stay routing-only; they are never silently upgraded.
        if set(data) - {"default_route", "routes"}:
            raise ValueError("A full FactorySpec requires apiVersion and kind")
        if "routes" in data and not isinstance(data["routes"], dict):
            raise ValueError("Legacy factory routes must be a mapping")
        if "default_route" in data and not isinstance(data["default_route"], str):
            raise ValueError("Legacy factory default_route must be a string")
    return FactoryDefinition(root, source, data, legacy=not versioned)
