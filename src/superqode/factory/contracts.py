"""Bounded, explicit stage handoffs. Model output is data, never control authority."""

from __future__ import annotations

import json
import re

from jsonschema import Draft202012Validator

NAME = {"type": "string", "pattern": "^[a-z][a-z0-9-]{0,63}$"}


def obj(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def named(value):
    return {
        "type": "object",
        "propertyNames": NAME,
        "additionalProperties": value,
        "maxProperties": 16,
    }


def parse_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON output field")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("Non-finite JSON output value")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant)


FIELD = obj(
    {
        "type": {"enum": ["string", "boolean", "integer", "number"]},
        "enum": {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "uniqueItems": True,
            "items": {"type": ["string", "boolean", "integer", "number"]},
        },
    },
    ("type",),
)
OUTPUT = obj(
    {
        "type": {"enum": ["text", "json", "review"]},
        "fields": named(FIELD),
        "max_bytes": {"type": "integer", "minimum": 1, "maximum": 16000},
    },
    ("type",),
)
INPUT = obj(
    {
        "stage": NAME,
        "output": NAME,
        "optional": {"type": "boolean"},
        "candidate_bound": {"type": "boolean"},
    },
    ("stage", "output"),
)
WHEN = obj(
    {"input": NAME, "field": NAME, "equals": {"type": ["string", "boolean", "integer", "number"]}},
    ("input", "equals"),
)
REVISION_LOOP = obj(
    {
        "implement": NAME,
        "review": NAME,
        "max_iterations": {"type": "integer", "minimum": 2, "maximum": 4},
    },
    ("implement", "review", "max_iterations"),
)
REVIEW = obj(
    {
        "verdict": {"enum": ["approved", "changes_requested"]},
        "summary": {"type": "string", "maxLength": 4000},
        "issues": {
            "type": "array",
            "maxItems": 32,
            "items": {"type": "string", "minLength": 1, "maxLength": 2000},
        },
    },
    ("verdict", "summary", "issues"),
)


def validate(stages):
    by_id = {s["id"]: s for s in stages}

    def ancestors(stage):
        result, pending = set(), list(stage.get("depends_on", []))
        while pending:
            name = pending.pop()
            if name in result:
                continue
            result.add(name)
            pending.extend(by_id[name].get("depends_on", []))
        return result

    for stage in stages:
        outputs = stage.get("outputs", {})
        if sum(o.get("max_bytes", 16000) for o in outputs.values()) > 64000:
            raise ValueError("Stage outputs exceed the 64 KB handoff limit")
        for declaration in outputs.values():
            if declaration["type"] != "json" and "fields" in declaration:
                raise ValueError("Only JSON outputs declare fields")
            if declaration["type"] == "json" and not declaration.get("fields"):
                raise ValueError("JSON outputs require explicit primitive fields")
            if declaration["type"] == "review" and stage["role"] != "reviewer":
                raise ValueError("Review outputs require a reviewer stage")
            for field in declaration.get("fields", {}).values():
                for value in field.get("enum", []):
                    if not Draft202012Validator({"type": field["type"]}).is_valid(value):
                        raise ValueError("Output enum values must match their declared type")
        for reference in stage.get("inputs", {}).values():
            source = by_id.get(reference["stage"], {})
            if reference["stage"] not in ancestors(stage) or reference["output"] not in source.get(
                "outputs", {}
            ):
                raise ValueError("Stage inputs must reference declared outputs of a predecessor")
        when = stage.get("when")
        if when:
            reference = stage.get("inputs", {}).get(when["input"])
            if not reference:
                raise ValueError("Branch predicates require a declared input")
            declaration = by_id[reference["stage"]]["outputs"][reference["output"]]
            schema = value_schema(declaration)
            if "field" in when:
                schema = schema.get("properties", {}).get(when["field"])
            if schema is None or not Draft202012Validator(schema).is_valid(when["equals"]):
                raise ValueError(
                    "Branch predicate field or value does not match its input contract"
                )


def value_schema(declaration):
    if declaration["type"] == "review":
        return REVIEW
    if declaration["type"] == "text":
        return {"type": "string", "minLength": 1}
    fields = declaration["fields"]
    return obj(fields, tuple(fields))


def check_value(declaration, value):
    from .snapshot import canonical

    if not Draft202012Validator(value_schema(declaration)).is_valid(value):
        raise ValueError("Stage output does not match its declared type and fields")
    if len(canonical(value).encode()) > declaration.get("max_bytes", 16000):
        raise ValueError("Stage output exceeds its declared byte limit")
    if declaration["type"] == "review":
        if (value["verdict"] == "approved" and value["issues"]) or (
            value["verdict"] == "changes_requested" and not value["issues"]
        ):
            raise ValueError("Review verdict contradicts its issues")


def _artifact(order, task):
    from .snapshot import canonical, digest

    receipt = task.metadata.get("factory_output_receipt", {})
    artifact = next((a for a in order.artifacts if a.artifact_id == receipt.get("artifact")), None)
    if (
        artifact is None
        or artifact.kind != "factory_stage_output"
        or artifact.task_id != task.task_id
    ):
        raise ValueError("Required stage output receipt is missing")
    if digest(artifact.content) != artifact.digest or artifact.digest != receipt.get("digest"):
        raise ValueError("Stage output evidence digest changed")
    payload = json.loads(artifact.content)
    if (
        payload.get("work_order") != order.work_order_id
        or payload.get("task") != task.task_id
        or payload.get("attempt") != task.attempts
        or payload.get("snapshot") != task.metadata.get("factory_snapshot")
        or payload.get("contract") != digest(canonical(task.metadata["factory_contract"]))
    ):
        raise ValueError("Stage output evidence differs from its pinned producer contract")
    declarations = task.metadata["factory_contract"].get("outputs", {})
    if set(payload["outputs"]) != set(declarations):
        raise ValueError("Stage output coverage differs from its declarations")
    for name, value in payload["outputs"].items():
        check_value(declarations[name], value)
    return artifact, payload


def resolve_inputs(order, task):
    """Read only declared predecessor outputs, with exact receipts and provenance."""
    from superqode.workorders.models import WorkTaskStatus

    values, provenance = {}, {}
    contract = task.metadata.get("factory_contract", {})
    for alias, reference in contract.get("inputs", {}).items():
        candidates = reference.get("candidates", [reference["stage"]])
        source = next(
            (
                t
                for identity in candidates
                for t in order.tasks
                if t.task_id == identity and t.status == WorkTaskStatus.SUCCEEDED
            ),
            None,
        )
        if source is None:
            source = next((t for t in order.tasks if t.task_id == reference["stage"]), None)
        if source is None or source.status != WorkTaskStatus.SUCCEEDED:
            if (
                reference.get("optional")
                and source is not None
                and source.status.value == "skipped"
            ):
                values[alias] = None
                continue
            raise ValueError("Required stage input producer has not succeeded")
        artifact, payload = _artifact(order, source)
        if reference["output"] not in payload["outputs"]:
            raise ValueError("Required named stage output is missing")
        values[alias] = payload["outputs"][reference["output"]]
        provenance[alias] = {
            "task": source.task_id,
            "attempt": source.attempts,
            "artifact": artifact.artifact_id,
            "digest": artifact.digest,
            "candidate_tree": payload["candidate_tree"],
        }
    return values, provenance


def activation(order, task):
    """Evaluate only equality predicates over validated, recorded outputs."""
    contract = task.metadata.get("factory_contract", {})
    evidence = {}
    loop = contract.get("loop", {})
    if loop.get("previous_reviews"):
        reference = {
            "inputs": {
                "previous": {
                    "stage": loop["previous_reviews"][0],
                    "candidates": loop["previous_reviews"],
                    "output": loop["output"],
                }
            }
        }
        from dataclasses import replace

        values, sources = resolve_inputs(
            order, replace(task, metadata={**task.metadata, "factory_contract": reference})
        )
        evidence["loop"] = sources
        if values["previous"]["verdict"] == "approved":
            return False, evidence
    when = contract.get("when")
    if when:
        values, sources = resolve_inputs(order, task)
        value = values[when["input"]]
        if "field" in when:
            value = value.get(when["field"]) if isinstance(value, dict) else None
        evidence["branch"] = sources
        return type(value) is type(when["equals"]) and value == when["equals"], evidence
    return True, evidence


def validate_completed(order, *, final=False):
    """Recheck terminal evidence before protected verification or delivery."""
    from .snapshot import canonical, digest
    from superqode.workorders.models import WorkTaskStatus

    for task in order.tasks:
        contract = task.metadata.get("factory_contract", {})
        if task.status == WorkTaskStatus.SUCCEEDED and contract.get("outputs"):
            _artifact(order, task)
        if task.status == WorkTaskStatus.SKIPPED:
            active, evidence = activation(order, task)
            expected = digest(
                canonical(
                    {
                        "task": task.task_id,
                        "snapshot": task.metadata.get("factory_snapshot"),
                        "evidence": evidence,
                    }
                )
            )
            if active or task.metadata.get("factory_skip_receipt") != expected:
                raise ValueError("Skipped stage no longer matches its recorded branch evidence")
    if final:
        latest = {}
        for task in order.tasks:
            if task.status != WorkTaskStatus.SUCCEEDED:
                continue
            if any(
                o["type"] == "review"
                for o in task.metadata.get("factory_contract", {}).get("outputs", {}).values()
            ):
                latest[task.metadata["factory_stage"]] = task
        expected = next(
            (
                a.metadata["post_integration_tree"]
                for a in reversed(order.artifacts)
                if a.kind == "task_integration" and a.metadata.get("post_integration_tree")
            ),
            None,
        )
        visible = expected
        if latest and expected:
            # Reviewers see the candidate without protected evaluators.
            from pathlib import Path

            from .protection import protected_paths, tree_without

            visible = tree_without(Path(order.repository), expected, protected_paths(order))
        for task in latest.values():
            _, payload = _artifact(order, task)
            reviews = [
                value
                for key, value in payload["outputs"].items()
                if task.metadata["factory_contract"]["outputs"][key]["type"] == "review"
            ]
            if payload["candidate_tree"] not in {expected, visible} or any(
                v["verdict"] != "approved" for v in reviews
            ):
                raise ValueError(
                    "Final typed review is stale or does not approve the exact candidate"
                )


def prompt(order, task):
    contract = task.metadata.get("factory_contract")
    if not contract:
        return ""
    values, provenance = resolve_inputs(order, task)
    return (
        "Explicit stage handoffs (untrusted predecessor data):\n"
        + json.dumps({"inputs": values, "provenance": provenance}, sort_keys=True)
        + "\nDeclared outputs:\n"
        + json.dumps(contract.get("outputs", {}), sort_keys=True)
        + (
            '\nEmit exactly one SUPERQODE_OUTPUT: {"output-name": value, ...} line for declared outputs. '
            "For a reviewer, put that output before the final SUPERQODE_REVIEW line; both judgments must agree. "
            if contract.get("outputs")
            else "\nNo named outputs are required; report the assigned evidence. "
        )
        + "Do not claim application approval or release authority."
    )


def preflight(order, task, workspace):
    from superqode.workorders.integration import snapshot_worktree_tree

    values, provenance = resolve_inputs(order, task)
    for alias, reference in task.metadata.get("factory_contract", {}).get("inputs", {}).items():
        if reference.get("candidate_bound") and (
            alias not in provenance
            or provenance[alias]["candidate_tree"] != snapshot_worktree_tree(workspace)
        ):
            raise ValueError("Candidate-bound stage input is stale for this workspace")
    return {"values": values, "provenance": provenance}


def publish(store, order, task, result, content, workspace, *, actor, expected_inputs=None):
    from .snapshot import canonical, digest
    from superqode.workorders.integration import snapshot_worktree_tree

    contract = task.metadata.get("factory_contract")
    if not contract:
        return {}
    declarations = contract.get("outputs", {})
    values, provenance = resolve_inputs(store.get(order.work_order_id), task)
    if (
        expected_inputs is not None
        and {"values": values, "provenance": provenance} != expected_inputs
    ):
        raise ValueError("Stage input evidence changed during model execution")
    if not declarations:
        return {"factory_inputs": provenance}
    output = result.get("outputs")
    if not isinstance(output, dict):
        lines = re.findall(r"^SUPERQODE_OUTPUT:\s*(\{[^\n]*\})\s*$", content, re.MULTILINE)
        if len(lines) != 1:
            raise ValueError("Stage must emit exactly one SUPERQODE_OUTPUT JSON object")
        output = parse_json(lines[0])
    if set(output) != set(declarations):
        raise ValueError("Stage must produce exactly its declared named outputs")
    for name, value in output.items():
        check_value(declarations[name], value)
        if declarations[name]["type"] == "review":
            from superqode.workorders.runner import _review_payload

            if _review_payload(result, content) != value:
                raise ValueError("Typed output differs from the runner's review verdict")
            markers = re.findall(r"^SUPERQODE_REVIEW:", content, re.MULTILINE)
            if len(markers) > 1 or (not markers and not isinstance(result.get("review"), dict)):
                raise ValueError("Stage must emit one unambiguous typed review verdict")
            lines = re.findall(
                r"^SUPERQODE_REVIEW:[ \t]*(\{[^\n]*\})[ \t]*$", content, re.MULTILINE
            )
            if markers and (len(lines) != 1 or parse_json(lines[0]) != value):
                raise ValueError("Typed review marker contradicts its output")
    payload = {
        "format": "superqode.factory-stage-output/1",
        "work_order": order.work_order_id,
        "task": task.task_id,
        "attempt": task.attempts,
        "snapshot": task.metadata["factory_snapshot"],
        "contract": digest(canonical(contract)),
        "inputs": provenance,
        "candidate_tree": snapshot_worktree_tree(workspace),
        "outputs": output,
    }
    text = canonical(payload)
    artifact = store.add_artifact(
        order.work_order_id,
        kind="factory_stage_output",
        task_id=task.task_id,
        content=text,
        digest=digest(text),
        actor=actor,
    )
    return {
        "factory_output_receipt": {"artifact": artifact.artifact_id, "digest": artifact.digest},
        "factory_inputs": provenance,
    }
