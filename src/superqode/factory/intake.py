"""Authenticated inbound work admission; receipts never execute or release work."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import time

from superqode.desktop_service.ownership import Lease
from superqode.workorders.models import TERMINAL_WORK_ORDER_STATUSES
from .compiler import compile_factory, materialize_snapshot
from .definition import load_factory, project_path, _bounded
from .handover import _json
from .maintenance import execution
from .operations import read, write
from .runtime import factory_store, admit_factory, load_compiled_plan
from .snapshot import resolve_factory, canonical
from .versioning import _safe_text

PREFIX = ".superqode/factory-intake"
MAX_BODY = 64000


def _path(root, name):
    return project_path(Path(root).resolve(), PREFIX + "/" + name)


def _string(value, name, limit=8000):
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > limit:
        raise ValueError("Webhook field is missing or exceeds its bound: " + name)
    return value


def _normalize(kind, data, headers, policy):
    if kind == "github":
        if headers.get("x-github-event") != "issues":
            raise ValueError("Only GitHub issue events are accepted")
        repository = data.get("repository", {})
        issue = data.get("issue", {})
        if not isinstance(repository, dict) or not isinstance(issue, dict):
            raise ValueError("GitHub repository and issue must be objects")
        scope = repository.get("full_name")
        if "pull_request" in issue:
            raise ValueError("Pull requests require a separate intake contract")
        title, body = issue.get("title"), issue.get("body") or ""
        action = data.get("action")
        identity = headers.get("x-github-delivery")
        timestamp = None
    elif kind == "linear":
        if data.get("type") != "Issue" or headers.get("linear-event") != "Issue":
            raise ValueError("Only Linear Issue events are accepted")
        scope = data.get("organizationId")
        issue = data.get("data", {})
        if not isinstance(issue, dict):
            raise ValueError("Linear issue must be an object")
        title, body = issue.get("title"), issue.get("description") or ""
        action, identity = data.get("action"), headers.get("linear-delivery")
        milliseconds = data.get("webhookTimestamp")
        timestamp = milliseconds / 1000 if type(milliseconds) in {int, float} else None
    else:
        scope = data.get("service")
        title, body = data.get("title"), data.get("description") or ""
        action, identity = data.get("action"), data.get("event_id")
        timestamp = data.get("timestamp")
    if scope != policy["scope"] or action not in policy["actions"]:
        raise ValueError("Webhook source or action is outside the saved intake policy")
    identity = _string(identity, "delivery", 128)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", identity):
        raise ValueError("Webhook delivery id is not a safe bounded identifier")
    goal = _string(title, "title", 1000)
    if not isinstance(body, str) or len(body.encode()) > 8000:
        raise ValueError("Webhook body exceeds its task bound")
    goal += "\n\n" + body
    _safe_text("incoming-task.md", goal)
    return identity, goal, timestamp


def receive(root, kind, raw, headers):
    """Verify raw-body HMAC, scope and bounds before recording a queued job."""
    root = Path(root).resolve()
    if (
        kind not in {"github", "linear", "monitor"}
        or not isinstance(raw, bytes)
        or len(raw) > MAX_BODY
    ):
        raise ValueError("Unknown webhook source or oversized body")
    definition = load_factory(root=root)
    intake = definition.data["orchestration"].get("intake", {})
    policy = intake.get("sources", {}).get(kind)
    if not intake.get("enabled") or not policy:
        raise ValueError("This webhook source is not enabled in the saved Factory")
    secret = os.environ.get(policy["secret_env"], "")
    if len(secret.encode()) < 32:
        raise ValueError(
            "Configure a high-entropy webhook secret in the declared environment binding"
        )
    if not isinstance(headers, dict):
        raise ValueError("Webhook headers must be an object")
    headers = {str(k).lower(): v for k, v in headers.items()}
    header = {
        "github": "x-hub-signature-256",
        "linear": "linear-signature",
        "monitor": "x-superqode-signature",
    }[kind]
    signature = headers.get(header, "")
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if kind != "linear":
        expected = "sha256=" + expected
    if not isinstance(signature, str) or not hmac.compare_digest(expected, signature):
        raise ValueError("Webhook authentication failed")
    data = _json(raw)
    if not isinstance(data, dict):
        raise ValueError("Webhook must be a JSON object")
    _bounded(data)
    delivery, goal, timestamp = _normalize(kind, data, headers, policy)
    fingerprint = hashlib.sha256(raw).hexdigest()
    identity = kind + ":" + delivery
    catalog_path = _path(root, "ledger.json")
    with execution(root), _lease(root):
        catalog = (
            json.loads(read(catalog_path, 2000000))
            if catalog_path.exists()
            else {"format": "superqode.factory-intake/1", "events": {}}
        )
        if catalog.get("format") != "superqode.factory-intake/1":
            raise ValueError("Unsupported webhook admission ledger")
        events = catalog["events"]
        previous = events.get(identity) or next(
            (value for value in events.values() if identity in value.get("aliases", [])), None
        )
        if previous and previous["fingerprint"] != fingerprint:
            raise ValueError("Delivery id already binds a different payload")
        if previous is None:
            previous = next(
                (
                    value
                    for value in events.values()
                    if value["kind"] == kind and value["fingerprint"] == fingerprint
                ),
                None,
            )
            if previous is not None:
                if len(previous.get("aliases", [])) >= 32:
                    raise ValueError("Webhook delivery alias limit reached")
                previous.setdefault("aliases", []).append(identity)
                write(catalog_path, canonical(catalog))
        if previous is not None:
            plan = load_compiled_plan(
                json.loads(read(_path(root, previous["plan"]), 16000000)), root=root
            )
            order = admit_factory(
                plan, request_id=previous["request_id"], actor="authenticated " + kind + " intake"
            )
            return {
                "work_order_id": order.work_order_id,
                "deduplicated": True,
                "execution_started": False,
            }
        now = time.time()
        if kind != "github" and (
            type(timestamp) not in {int, float}
            or not math.isfinite(timestamp)
            or abs(now - timestamp) > 60
        ):
            raise ValueError("Webhook timestamp is outside its 60-second replay window")
        if (
            len(events) >= 1000
            or sum(value["received"] > now - 3600 for value in events.values())
            >= intake["max_per_hour"]
        ):
            raise ValueError("Webhook admission ledger or hourly limit exhausted")
        db = project_path(root, ".superqode/workorders/store.sqlite3")
        if db.exists():
            pending = [
                o
                for o in factory_store(root, read_only=True).list()
                if "factory" in o.metadata and o.status not in TERMINAL_WORK_ORDER_STATUSES
            ]
            if len(pending) >= intake["max_pending"]:
                raise ValueError("Factory intake pending-work limit reached")
        snapshot = resolve_factory(definition)
        plan = compile_factory(snapshot, root=root, goal=goal)
        materialize_snapshot(plan)
        plan_name = "plans/" + hashlib.sha256(identity.encode()).hexdigest() + ".json"
        request_id = "factory-intake:" + identity
        write(_path(root, plan_name), canonical(plan.to_dict()))
        events[identity] = {
            "kind": kind,
            "fingerprint": fingerprint,
            "received": now,
            "plan": plan_name,
            "request_id": request_id,
        }
        # Persist the exact submission contract before the queue transaction.
        write(catalog_path, canonical(catalog))
        order = admit_factory(
            plan, request_id=request_id, actor="authenticated " + kind + " intake"
        )
        return {
            "work_order_id": order.work_order_id,
            "deduplicated": False,
            "execution_started": False,
        }


class _lease:
    def __init__(self, root):
        self.lease = Lease(_path(root, "writer.lock"))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.lease.close()


def serve(root, *, host="127.0.0.1", port=8767):
    """Serve behind the customer's HTTPS reverse proxy; queue only, no agents."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("Bind the intake receiver to loopback behind an authenticated TLS proxy")
    root = Path(root).resolve()

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass  # Never log external task bodies, signatures or secrets.

        def do_POST(self):
            try:
                if not re.fullmatch(r"/factory/webhook/(github|linear|monitor)", self.path):
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length", "-1"))
                if not 0 < length <= MAX_BODY or self.headers.get("Transfer-Encoding"):
                    self.send_error(413)
                    return
                raw = self.rfile.read(length)
                if len(raw) != length:
                    self.send_error(400)
                    return
                result = receive(root, self.path.rsplit("/", 1)[-1], raw, dict(self.headers))
                body = canonical(result).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (ValueError, KeyError, OSError):
                self.send_error(
                    400, "Webhook rejected; inspect the saved policy and local admission state"
                )

    with HTTPServer((host, port), Handler) as server:
        server.serve_forever(poll_interval=0.5)
