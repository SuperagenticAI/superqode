"""Native campaign receipts retain exact-job adoption and project boundaries."""
# ruff: noqa: F401, F811

import json
from threading import Thread
import time

import pytest

from test_factory_definition import project
from test_factory_improvement import prepared
from test_factory_campaigns import configured, admit
from test_factory_search_metering import model, evaluator
from superqode.factory import campaigns, recovery
from superqode.desktop_service.service import DesktopService


def test_worker_advances_admitted_event_and_stops_for_review(configured, model, monkeypatch):
    root, policy, source = configured
    evaluator(monkeypatch)
    current = campaigns.create(root)
    admit(root, current, source)
    result = campaigns.run_worker(
        root, current["manifest"]["id"], current["manifest"]["digest"], live=True
    )
    assert result["state"]["status"] == "awaiting_review"
    assert len(model[0]) == 1 and result["reserved_experiments"] == 1
    assert not result["adoption_authorized"]


def test_idle_worker_can_be_drained_and_blocks_offline_capture(configured):
    root, policy, source = configured
    current = campaigns.create(root)
    identity, token = current["manifest"]["id"], current["manifest"]["digest"]
    result = []
    worker = Thread(
        target=lambda: result.append(
            campaigns.run_worker(root, identity, token, live=True, poll_interval=0.05)
        )
    )
    worker.start()
    try:
        for _ in range(200):
            if campaigns.inspect(root, identity)["state"]["started"] is not None:
                break
            time.sleep(0.01)
        assert campaigns.inspect(root, identity)["state"]["started"] is not None
        with pytest.raises(ValueError, match="still owns"):
            recovery.create(root)
        campaigns.stop(root, identity, token)
    finally:
        campaigns.stop(root, identity, token)
        worker.join(timeout=5)
    assert not worker.is_alive() and result[0]["reserved_experiments"] == 0


def test_headless_plan_and_campaign_comparison_can_be_reviewed_natively(
    configured, model, monkeypatch, tmp_path
):
    root, policy, source = configured
    evaluator(monkeypatch)
    current = campaigns.create(root)
    admit(root, current, source)
    result = campaigns.advance(
        root, current["manifest"]["id"], current["manifest"]["digest"], live=True
    )
    event = result["state"]["events"][0]
    service = DesktopService(tmp_path / "native-state")
    try:
        project_id = service.open_project(str(root))["id"]
        request = {
            "factory_action": "campaign-run",
            "campaign": current["manifest"]["id"],
            "campaign_digest": current["manifest"]["digest"],
        }
        service._write(
            "INSERT INTO jobs(id,project,kind,title,status,request,result,created,updated) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "simulated-controller-job",
                project_id,
                "factory",
                "Fixture controller",
                "completed",
                json.dumps(request),
                json.dumps(result),
                time.time(),
                time.time(),
            ),
        )
        plans = service.dispatch("factory.improvement.list", {"project": project_id})["plans"]
        assert any(p["id"] == event["plan"] for p in plans)
        opened = service.dispatch(
            "factory.improvement.open", {"project": project_id, "plan": event["plan"]}
        )
        assert (
            opened["comparison_job"] == "simulated-controller-job"
            and opened["comparison"]["eligible"]
        )
        args = {
            "project": project_id,
            "plan": event["plan"],
            "candidate": event["comparison"]["candidate"],
            "comparison_job": "simulated-controller-job",
            "confirmed": True,
        }
        before = (root / ".superqode/factory.yaml").read_bytes()
        draft = service.dispatch("factory.improvement.adopt", args)
        assert draft["proposal_only"] and (root / ".superqode/factory.yaml").read_bytes() == before
        request["campaign_digest"] = "sha256:" + "0" * 64
        service._write(
            "UPDATE jobs SET request=? WHERE id=?",
            (json.dumps(request), "simulated-controller-job"),
        )
        with pytest.raises(ValueError, match="does not authorize"):
            service.dispatch("factory.improvement.adopt", args)
    finally:
        service.close()


def test_native_stop_remains_available_while_project_writer_is_owned(configured, tmp_path):
    from superqode.desktop_service.ownership import Lease, project_lease_path

    root, policy, source = configured
    current = campaigns.create(root)
    service = DesktopService(tmp_path / "stop-state")
    try:
        project_id = service.open_project(str(root))["id"]
        lease = Lease(project_lease_path(service.root, root))
        try:
            result = service.dispatch(
                "factory.campaign.stop",
                {
                    "project": project_id,
                    "id": current["manifest"]["id"],
                    "digest": current["manifest"]["digest"],
                    "confirmed": True,
                },
            )
            assert result["stop_requested"]
        finally:
            lease.close()
    finally:
        service.close()
