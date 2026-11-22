"""One-time candidate-bound release signatures, independent of client labels."""

from __future__ import annotations

import base64
import time
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from superqode.workorders.models import WorkOrderStatus
from superqode.workorders.store import _require_factory_verification
from .runtime import _pinned_plan, factory_store, validate_factory_order
from .verification import prepare_verified_candidate
from .snapshot import canonical, digest

DOMAIN = "superqode.factory.delivery-authorization/1"


def release_context(order):
    from .maintenance import assert_enabled

    assert_enabled(order.repository)
    plan = _pinned_plan(order)
    policy = plan.snapshot.payload["definition"]["governance"].get("release_authority")
    if not policy:
        raise ValueError("Configure pinned release_authority keys before approving delivery")
    receipt = order.metadata.get("factory_verification", {})
    candidate = next(
        (a for a in reversed(order.artifacts) if a.kind == "integration_candidate"), None
    )
    if candidate is None:
        raise ValueError("Prepare the verified factory candidate before approval")
    _require_factory_verification(order, candidate.artifact_id)
    evidence = next(a for a in order.artifacts if a.artifact_id == receipt["artifact_id"])
    context = {
        "domain": DOMAIN,
        "action": "apply-verified-change",
        "repository": order.repository,
        "work_order_id": order.work_order_id,
        "factory_digest": plan.snapshot.digest,
        "candidate_id": candidate.artifact_id,
        "candidate_digest": candidate.digest,
        "candidate_tree": candidate.metadata["candidate_tree"],
        "target_tree": candidate.metadata["target_tree"],
        "expected_tree": candidate.metadata["expected_tree"],
        "verification_id": evidence.artifact_id,
        "verification_digest": evidence.digest,
    }
    return policy, context


def verify_signature(order, payload, signature, *, fresh=True):
    policy, expected = release_context(order)
    if any(payload.get(key) != value for key, value in expected.items()):
        raise ValueError("Release challenge no longer matches the verified candidate")
    if set(payload) != set(expected) | {"id", "key_id", "issued_at", "expires_at"}:
        raise ValueError("Release challenge has unsupported fields")
    issued, expires = payload.get("issued_at"), payload.get("expires_at")
    if (
        not isinstance(issued, (int, float))
        or not isinstance(expires, (int, float))
        or not 0 < expires - issued <= policy.get("challenge_ttl_seconds", 120)
        or (fresh and (issued > time.time() + 5 or expires < time.time()))
    ):
        raise ValueError("Release challenge expired or has invalid timing")
    signer = policy["keys"].get(payload.get("key_id"))
    if signer is None:
        raise ValueError("Release signer is not authorized by the pinned factory policy")
    try:
        public = base64.b64decode(signer["public_key"], validate=True)
        key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public)
        raw_signature = base64.b64decode(signature, validate=True)
        if len(raw_signature) > 128:
            raise ValueError("Oversized release signature")
        key.verify(raw_signature, canonical(payload).encode(), ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise ValueError("Release signature is invalid") from exc
    return "p256:" + payload["key_id"]


def issue_challenge(reference, *, root=".", key_id):
    store = factory_store(root)
    order = store.get(reference)
    validate_factory_order(order, store=store)
    if not store.policy_decision(reference, phase="completion").allowed:
        raise ValueError("Factory budget or policy does not permit approval")
    if order.status != WorkOrderStatus.READY_TO_MERGE:
        prepare_verified_candidate(store, reference, actor="release-review")
        order = store.get(reference)
    policy, context = release_context(order)
    if key_id not in policy["keys"]:
        raise ValueError("Choose a signer declared in the pinned release authority")
    now = time.time()
    payload = {
        **context,
        "id": "release_" + uuid4().hex,
        "key_id": key_id,
        "issued_at": now,
        "expires_at": now + policy.get("challenge_ttl_seconds", 120),
    }
    store.issue_factory_release_challenge(reference, payload)
    return {
        "challenge": payload,
        "message": base64.b64encode(canonical(payload).encode()).decode(),
        "message_digest": digest(canonical(payload)),
    }


def authorize_release(reference, proof, *, root="."):
    store = factory_store(root)
    row = store.factory_release_challenge(proof.get("challenge_id", ""))
    if row["work_order_id"] != store.get(reference).work_order_id:
        raise ValueError("Release challenge belongs to another factory run")
    if not row["used"]:
        validate_factory_order(store.get(reference), store=store)
    return store.authorize_factory_release(
        reference, challenge_id=row["id"], signature=proof.get("signature", "")
    )


def require_authorization(order):
    from .maintenance import assert_enabled

    assert_enabled(order.repository)
    authorization = order.metadata.get("factory_release", {})
    recovering = order.status == WorkOrderStatus.MERGING
    if (
        not order.decision
        or order.decision.verdict != "accepted"
        or not authorization.get("payload")
        or not authorization.get("signature")
    ):
        raise ValueError("Factory release authorization requires a signed candidate approval")
    actor = verify_signature(
        order, authorization["payload"], authorization["signature"], fresh=not recovering
    )
    if order.decision.actor != actor:
        raise ValueError("Release decision does not match its authenticated signer")
    if (
        recovering
        and order.metadata.get("merge_intent", {}).get("authorization_id")
        != authorization["payload"]["id"]
    ):
        raise ValueError("Merge recovery does not match its persisted release authorization")
    return actor


def apply_approved(reference, *, root=".", candidate_id, candidate_digest):
    from superqode.workorders.integration import merge_integration

    store = factory_store(root)
    order = store.get(reference)
    authorization = order.metadata.get("factory_release", {}).get("payload", {})
    if (
        authorization.get("candidate_id") != candidate_id
        or authorization.get("candidate_digest") != candidate_digest
    ):
        raise ValueError("Inspected candidate does not match the authorized change")
    if order.status == WorkOrderStatus.MERGED:
        return order
    return merge_integration(
        store,
        reference,
        expected_candidate_id=candidate_id,
        expected_candidate_digest=candidate_digest,
    )
