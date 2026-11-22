"""Explicit instance retirement preserves evidence and cancels pending work."""

import json
from pathlib import Path
import time

from .compiler import _git
from .definition import load_factory, project_path
from .maintenance import execution
from .operations import ownership, path, read, write, readiness
from .recovery import _idle
from .runtime import factory_store
from .snapshot import canonical, digest, resolve_factory


def review(root):
    root = Path(root).resolve()
    database = project_path(root, ".superqode/workorders/store.sqlite3")
    orders = factory_store(root, read_only=True).list() if database.exists() else []
    value = {
        "format": "superqode.factory-retirement/1",
        "repository": str(root),
        "factory_digest": resolve_factory(load_factory(root=root)).digest,
        "commit": _git(root, "rev-parse", "HEAD"),
        "orders": [
            {
                "id": o.work_order_id,
                "status": o.status.value,
                "updated": o.updated_at,
                "tasks": [(t.task_id, t.status.value, t.attempts) for t in o.tasks],
            }
            for o in orders
        ],
        "evidence_retained": True,
        "worktrees_retained": True,
        "external_services_managed": False,
    }
    value["digest"] = digest(canonical(value))
    return value


def retire(root, expected):
    from superqode.workorders.models import TERMINAL_WORK_ORDER_STATUSES

    root = Path(root).resolve()
    with ownership(root), execution(root, exclusive=True, require_enabled=False):
        _idle(root)
        current = review(root)
        if current["digest"] != expected:
            raise ValueError("Retirement inventory changed; review it again")
        marker = {**current, "retired_at": time.time(), "execution_enabled": False}
        write(path(root, "retired.json"), canonical(marker))
        database = project_path(root, ".superqode/workorders/store.sqlite3")
        if database.exists():
            store = factory_store(root)
            for order in store.list():
                if "factory" in order.metadata and order.status not in TERMINAL_WORK_ORDER_STATUSES:
                    store.cancel(
                        order.work_order_id,
                        actor="explicit retirement operator",
                        reason="Factory instance retired; evidence retained",
                    )
        return {
            "retired": True,
            "review_digest": expected,
            "execution_enabled": False,
            "evidence_retained": True,
            "worktrees_retained": True,
            "release_authorized": False,
        }


def reactivate(root, expected, *, probe=False):
    root = Path(root).resolve()
    with ownership(root), execution(root, exclusive=True, require_enabled=False):
        marker_path = path(root, "retired.json")
        marker = json.loads(read(marker_path, 1000000))
        review_body = {
            k: v
            for k, v in marker.items()
            if k not in {"digest", "retired_at", "execution_enabled"}
        }
        if marker.get("digest") != expected or digest(canonical(review_body)) != expected:
            raise ValueError("Retirement receipt changed")
        if path(root, "recovery-required.json").exists():
            raise ValueError("Complete recovery acknowledgement before reactivation")
        _idle(root)
        if (
            probe is not True
            or not readiness(root, probe=True, allow_disarmed=True)["worker_ready"]
        ):
            raise ValueError("Actual host readiness probes must pass before reactivation")
        write(
            path(root, "retirements/" + expected.removeprefix("sha256:") + ".json"),
            canonical(marker),
        )
        marker_path.unlink()
        return {
            "execution_enabled": True,
            "cancelled_work_restarted": False,
            "release_authorized": False,
        }
