"""A2ABreak Agent Card review: SuperOptiX wording, plus SuperQode extras."""

from __future__ import annotations

from superqode.a2a.trust import (
    JWS_TRUST_ISSUE,
    SKILLS_ATTESTATION_ISSUE,
    UNSIGNED_SIGNATURE_ISSUE,
    origin_is_allowed,
    parse_origin_allowlist,
    review_agent_card,
)


def _card(**extra):
    payload = {
        "name": "Demo",
        "protocolVersion": "1.0",
        "skills": [
            {
                "id": "s",
                "name": "Skill",
                "description": "A concrete skill description with enough text.",
            }
        ],
        "url": "https://agent.example",
        "supportedInterfaces": [
            {
                "url": "https://agent.example",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
    }
    payload.update(extra)
    return payload


def test_unsigned_card_is_high_and_skills_are_unattested():
    review = review_agent_card(_card())
    fields = {item.field: item for item in review.findings}
    assert "skills.attestation" in fields
    assert fields["skills.attestation"].severity == "high"
    assert fields["skills.attestation"].issue == SKILLS_ATTESTATION_ISSUE
    assert "signature" in fields
    assert fields["signature"].severity == "high"
    assert fields["signature"].issue == UNSIGNED_SIGNATURE_ISSUE
    assert "signature.trust" not in fields


def test_signed_card_flags_jws_trust_model_gap():
    review = review_agent_card(_card(signature={"protected": "x", "signature": "y"}))
    fields = {item.field: item for item in review.findings}
    assert "signature.trust" in fields
    assert fields["signature.trust"].severity == "medium"
    assert fields["signature.trust"].issue == JWS_TRUST_ISSUE
    assert "signature" not in fields
    assert any("JWS authenticates" in item.issue for item in review.findings)
    assert any("Unattested Skill Claims" in item.issue for item in review.findings)


def test_signatures_array_is_treated_as_present():
    review = review_agent_card(_card(signatures=[{"protected": "x", "signature": "y"}]))
    assert "signature.trust" in review.fields
    assert "signature" not in review.fields


def test_missing_security_schemes_uses_superoptix_wording():
    card = _card()
    card.pop("securitySchemes")
    review = review_agent_card(card)
    item = next(finding for finding in review.findings if finding.field == "securitySchemes")
    assert item.severity == "medium"
    assert "cannot tell how to authenticate" in item.issue


def test_push_notifications_are_called_out():
    review = review_agent_card(_card(capabilities={"pushNotifications": True}))
    item = next(
        finding for finding in review.findings if finding.field == "capabilities.pushNotifications"
    )
    assert "untrusted" in item.issue
    assert "pushNotifications false" in item.issue


def test_host_mismatch_is_reported():
    review = review_agent_card(_card(), origin="https://discovery.example")
    item = next(finding for finding in review.findings if finding.field == "url.host")
    assert "agent.example" in item.issue
    assert "discovery.example" in item.issue


def test_allowlist_rejects_an_unlisted_origin():
    assert origin_is_allowed("https://agent.example", ())
    assert origin_is_allowed("https://agent.example", ("agent.example",))
    assert not origin_is_allowed("https://evil.example", ("agent.example",))
    review = review_agent_card(
        _card(),
        origin="https://evil.example",
        allowed_origins=("agent.example",),
    )
    assert "origin.allowlist" in review.fields


def test_parse_origin_allowlist_reads_cli_then_env(monkeypatch):
    monkeypatch.setenv("SUPERQODE_A2A_ALLOWED_ORIGINS", "env.example, other.example")
    assert parse_origin_allowlist(("cli.example",)) == (
        "cli.example",
        "env.example",
        "other.example",
    )


def test_inspect_records_superoptix_findings():
    from superqode.a2a.client import A2AClient

    client = A2AClient("https://agent.example")
    client._parse_agent_card(_card())
    summaries = [event.summary for event in client.inspect.events if event.kind == "trust"]
    assert any("skills.attestation" in line for line in summaries)
    assert any("Unattested Skill Claims" in line for line in summaries)
    assert any("signature:" in line or "signature " in line for line in summaries)
    choice = client.inspect.events[-1]
    assert choice.kind == "choice"
