"""Real signature verification and one-time local delivery authorization."""
# ruff: noqa: F811

import base64
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from test_factory_definition import project, rewrite  # noqa: F401
from test_factory_verification import make_completed, simulated_probes  # noqa: F401
from superqode.factory import release, verification
from superqode.workorders.models import WorkOrderStatus


@pytest.fixture
def release_ready(project, monkeypatch, simulated_probes):
    key = ec.generate_private_key(ec.SECP256R1())
    public = base64.b64encode(
        key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    ).decode()
    rewrite(
        project,
        lambda d: d["governance"].update(
            release_authority={
                "method": "p256-signature",
                "keys": {"owner": {"public_key": public}},
                "challenge_ttl_seconds": 60,
            }
        ),
    )
    root, store, run = make_completed(project, monkeypatch)
    verification.verify_factory(run, root=root)
    return root, store, run, key


def signed(challenge, key):
    signature = key.sign(base64.b64decode(challenge["message"]), ec.ECDSA(hashes.SHA256()))
    return {
        "challenge_id": challenge["challenge"]["id"],
        "signature": base64.b64encode(signature).decode(),
    }


def test_signature_authorizes_only_exact_candidate_and_apply_is_retry_safe(release_ready):
    root, store, run, key = release_ready
    challenge = release.issue_challenge(run, root=root, key_id="owner")
    before = (root / "app.py").read_text()
    approved = release.authorize_release(run, signed(challenge, key), root=root)
    assert approved.decision.actor == "p256:owner"
    assert (root / "app.py").read_text() == before
    payload = challenge["challenge"]
    applied = release.apply_approved(
        run,
        root=root,
        candidate_id=payload["candidate_id"],
        candidate_digest=payload["candidate_digest"],
    )
    assert applied.status == WorkOrderStatus.MERGED
    assert (root / "app.py").read_text() == "print(43)\n"
    assert (
        release.apply_approved(
            run,
            root=root,
            candidate_id=payload["candidate_id"],
            candidate_digest=payload["candidate_digest"],
        ).status
        == WorkOrderStatus.MERGED
    )


def test_wrong_key_and_actor_label_cannot_approve(release_ready):
    root, store, run, key = release_ready
    challenge = release.issue_challenge(run, root=root, key_id="owner")
    wrong = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(ValueError, match="signature is invalid"):
        release.authorize_release(run, signed(challenge, wrong), root=root)
    payload = challenge["challenge"]
    with pytest.raises(ValueError, match="signed challenge"):
        store.accept(
            run,
            actor="owner",
            expected_candidate_id=payload["candidate_id"],
            expected_candidate_digest=payload["candidate_digest"],
        )
    assert not store.factory_release_challenge(payload["id"])["used"]


def test_expired_challenge_cannot_authorize(release_ready, monkeypatch):
    root, store, run, key = release_ready
    challenge = release.issue_challenge(run, root=root, key_id="owner")
    proof = signed(challenge, key)
    expired = challenge["challenge"]["expires_at"] + 1
    monkeypatch.setattr(release.time, "time", lambda: expired)
    with pytest.raises(ValueError, match="expired"):
        release.authorize_release(run, proof, root=root)


def test_replaced_verification_invalidates_signature(release_ready):
    root, store, run, key = release_ready
    challenge = release.issue_challenge(run, root=root, key_id="owner")
    proof = signed(challenge, key)
    verification.verify_factory(run, root=root)
    with pytest.raises(ValueError, match="no longer matches"):
        release.authorize_release(run, proof, root=root)


def test_cancelled_approval_cannot_be_replayed(release_ready):
    root, store, run, key = release_ready
    challenge = release.issue_challenge(run, root=root, key_id="owner")
    proof = signed(challenge, key)
    release.authorize_release(run, proof, root=root)
    store.cancel(run, actor="owner", reason="Withdrawn")
    with pytest.raises(ValueError, match="already consumed"):
        release.authorize_release(run, proof, root=root)


def test_competing_signature_acknowledgments_record_one_approval(release_ready):
    root, store, run, key = release_ready
    challenge = release.issue_challenge(run, root=root, key_id="owner")
    proof = signed(challenge, key)
    with ThreadPoolExecutor(max_workers=2) as clients:
        results = list(
            clients.map(lambda _: release.authorize_release(run, proof, root=root), range(2))
        )
    assert all(row.decision.actor == "p256:owner" for row in results)
    assert [event.type for event in store.events(run)].count("factory.release_authorized") == 1


def test_approval_must_be_fresh_when_application_starts(release_ready, monkeypatch):
    root, store, run, key = release_ready
    challenge = release.issue_challenge(run, root=root, key_id="owner")
    release.authorize_release(run, signed(challenge, key), root=root)
    before = (root / "app.py").read_text()
    monkeypatch.setattr(release.time, "time", lambda: challenge["challenge"]["expires_at"] + 1)
    with pytest.raises(ValueError, match="expired"):
        release.apply_approved(
            run,
            root=root,
            candidate_id=challenge["challenge"]["candidate_id"],
            candidate_digest=challenge["challenge"]["candidate_digest"],
        )
    assert (root / "app.py").read_text() == before


def test_signed_candidate_cannot_overwrite_target_drift(release_ready):
    root, store, run, key = release_ready
    challenge = release.issue_challenge(run, root=root, key_id="owner")
    release.authorize_release(run, signed(challenge, key), root=root)
    (root / "app.py").write_text("print('a later human edit')\n")
    with pytest.raises(ValueError, match="repository changes|Target checkout changed"):
        release.apply_approved(
            run,
            root=root,
            candidate_id=challenge["challenge"]["candidate_id"],
            candidate_digest=challenge["challenge"]["candidate_digest"],
        )
    assert "later human edit" in (root / "app.py").read_text()


def test_persisted_application_recovers_after_expiry_without_reapplying(release_ready, monkeypatch):
    from superqode.workorders.store import WorkOrderStore

    root, store, run, key = release_ready
    challenge = release.issue_challenge(run, root=root, key_id="owner")
    release.authorize_release(run, signed(challenge, key), root=root)
    original = WorkOrderStore.mark_merged

    def interrupted(*args, **kwargs):
        raise RuntimeError("Simulated crash after filesystem apply")

    monkeypatch.setattr(WorkOrderStore, "mark_merged", interrupted)
    args = dict(
        root=root,
        candidate_id=challenge["challenge"]["candidate_id"],
        candidate_digest=challenge["challenge"]["candidate_digest"],
    )
    with pytest.raises(RuntimeError, match="Simulated crash"):
        release.apply_approved(run, **args)
    assert (root / "app.py").read_text() == "print(43)\n"
    assert store.get(run).status == WorkOrderStatus.MERGING
    monkeypatch.setattr(WorkOrderStore, "mark_merged", original)
    monkeypatch.setattr(release.time, "time", lambda: challenge["challenge"]["expires_at"] + 1)
    assert release.apply_approved(run, **args).status == WorkOrderStatus.MERGED
