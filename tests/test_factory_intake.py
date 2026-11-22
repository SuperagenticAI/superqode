"""Signed intake never widens a Factory, replays delivery or starts inference."""
# ruff: noqa: F401, F811

import hashlib
import hmac
import json
import time

import pytest

from test_factory_definition import project, rewrite, git
from superqode.factory import intake
from superqode.factory.runtime import factory_store
from superqode.factory.snapshot import canonical

SECRET = "fixture-only-webhook-secret-000000000000"


@pytest.fixture
def configured(project, monkeypatch):
    monkeypatch.setenv("SUPERQODE_FACTORY_FIXTURE_SECRET", SECRET)
    rewrite(
        project,
        lambda d: d["orchestration"].update(
            intake={
                "enabled": True,
                "max_pending": 2,
                "max_per_hour": 3,
                "sources": {
                    kind: {
                        "scope": "fixture",
                        "secret_env": "SUPERQODE_FACTORY_FIXTURE_SECRET",
                        "actions": ["opened"] if kind == "github" else ["create"],
                    }
                    for kind in ("github", "linear", "monitor")
                },
            }
        ),
    )
    return project


def event(kind="github", delivery="delivery-1", **changes):
    if kind == "github":
        data = {
            "repository": {"full_name": "fixture"},
            "issue": {"title": "Fix a fixture bug", "body": "Keep its acceptance checks"},
            "action": "opened",
        }
        headers = {"X-GitHub-Event": "issues", "X-GitHub-Delivery": delivery}
    elif kind == "linear":
        data = {
            "organizationId": "fixture",
            "type": "Issue",
            "data": {"title": "Fix a fixture bug"},
            "action": "create",
            "webhookTimestamp": int(time.time() * 1000),
        }
        headers = {"Linear-Event": "Issue", "Linear-Delivery": delivery}
    else:
        data = {
            "service": "fixture",
            "title": "Investigate a fixture incident",
            "event_id": delivery,
            "action": "create",
            "timestamp": time.time(),
        }
        headers = {}
    data.update(changes)
    return signed(kind, data, headers)


def signed(kind, data, headers):
    raw = canonical(data).encode()
    signature = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    name = {
        "github": "X-Hub-Signature-256",
        "linear": "Linear-Signature",
        "monitor": "X-SuperQode-Signature",
    }[kind]
    return raw, {**headers, name: signature if kind == "linear" else "sha256=" + signature}


@pytest.mark.parametrize("kind", ["github", "linear", "monitor"])
def test_signed_scoped_events_only_queue_the_pinned_contract(configured, kind):
    root = configured
    raw, headers = event(kind)
    result = intake.receive(root, kind, raw, headers)
    assert not result["execution_started"] and not result["deduplicated"]
    order = factory_store(root, read_only=True).get(result["work_order_id"])
    assert order.status.value == "queued" and all(t.attempts == 0 for t in order.tasks)
    assert intake.receive(root, kind, raw, headers)["work_order_id"] == order.work_order_id
    assert len(factory_store(root, read_only=True).list()) == 1


def test_unsigned_and_changed_payloads_never_create_a_queue(configured):
    raw, headers = event()
    with pytest.raises(ValueError, match="authentication"):
        intake.receive(configured, "github", raw, {})
    with pytest.raises(ValueError, match="authentication"):
        intake.receive(configured, "github", raw + b" ", headers)
    assert not (configured / ".superqode/workorders/store.sqlite3").exists()


def test_cross_scope_events_and_unknown_actions_are_rejected(configured):
    for changes in (
        {"repository": {"full_name": "other/repo"}},
        {"action": "deleted"},
        {"repository": []},
    ):
        raw, headers = event(**changes)
        with pytest.raises(ValueError):
            intake.receive(configured, "github", raw, headers)


def test_replaying_a_signature_under_another_delivery_id_is_deduplicated(configured):
    root = configured
    raw, headers = event()
    first = intake.receive(root, "github", raw, headers)
    second = intake.receive(root, "github", raw, {**headers, "X-GitHub-Delivery": "alias"})
    assert first["work_order_id"] == second["work_order_id"] and second["deduplicated"]
    other_raw, other_headers = event(delivery="alias", issue={"title": "Different request"})
    with pytest.raises(ValueError, match="different payload"):
        intake.receive(root, "github", other_raw, other_headers)


def test_unknown_stale_linear_and_monitor_events_are_rejected(configured):
    for kind, changes in [("linear", {"webhookTimestamp": 1}), ("monitor", {"timestamp": 1})]:
        raw, headers = event(kind, **changes)
        with pytest.raises(ValueError, match="replay window"):
            intake.receive(configured, kind, raw, headers)


def test_pending_work_is_bounded_without_starting_models(configured):
    for n in range(2):
        raw, headers = event(delivery=f"request-{n}", issue={"title": f"Task {n}"})
        intake.receive(configured, "github", raw, headers)
    raw, headers = event(delivery="request-extra", issue={"title": "Extra task"})
    with pytest.raises(ValueError, match="pending-work limit"):
        intake.receive(configured, "github", raw, headers)
    assert len(factory_store(configured, read_only=True).list()) == 2


def test_lost_admission_response_reuses_receipt_after_application_drift(configured, monkeypatch):
    root = configured
    raw, headers = event()
    original = intake.admit_factory

    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("Simulated lost response")

    monkeypatch.setattr(intake, "admit_factory", lost)
    with pytest.raises(RuntimeError):
        intake.receive(root, "github", raw, headers)
    monkeypatch.setattr(intake, "admit_factory", original)
    (root / "app.py").write_text("answer = 43\n")
    result = intake.receive(root, "github", raw, headers)
    assert result["deduplicated"]
    assert len(factory_store(root, read_only=True).list()) == 1


def test_retired_instance_rejects_even_authenticated_admission(configured):
    root = configured
    marker = root / ".superqode/factory-operations/retired.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{}")
    raw, headers = event()
    with pytest.raises(ValueError, match="retired"):
        intake.receive(root, "github", raw, headers)


def test_listener_refuses_public_plaintext_binding(configured):
    with pytest.raises(ValueError, match="loopback"):
        intake.serve(configured, host="0.0.0.0")
