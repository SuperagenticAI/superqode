"""Agent Card trust review for A2ABreak protocol risks.

Findings use the same field names and issue text as SuperOptiX
``agent-card-review`` so the two products report the same protocol risks.
These are specification-compliant adversary issues, not SuperQode CVEs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

ALLOWED_ORIGINS_ENV = "SUPERQODE_A2A_ALLOWED_ORIGINS"
JWS_TRUST_ROOT_ENV = "SUPERQODE_A2A_JWS_TRUST_ROOT"

# SuperOptiX agent-card-review wording, mirrored exactly.
SKILLS_ATTESTATION_ISSUE = (
    "Skill claims are self-asserted. A2A 1.0 provides no attestation or "
    "capability challenge (A2ABreak protocol risk: Unattested Skill Claims)."
)
UNSIGNED_SIGNATURE_ISSUE = (
    "Card is unsigned. Signed cards are the A2A 1.0 mechanism "
    "for proving the card came from the domain owner."
)
JWS_TRUST_ISSUE = (
    "JWS authenticates the card publisher, not skill capability. "
    "A signature does not attest that advertised skills are truthful "
    "(A2ABreak protocol risk: JWS Key Trust Model Gap)."
)
SECURITY_SCHEMES_ISSUE = "No security schemes declared, so callers cannot tell how to authenticate."


@dataclass(frozen=True)
class CardFinding:
    """One Agent Card review finding."""

    severity: str
    field: str
    issue: str

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "field": self.field, "issue": self.issue}

    def summary(self) -> str:
        return f"{self.severity} {self.field}: {self.issue}"


@dataclass(frozen=True)
class CardReview:
    """Scored list of protocol-risk findings for one Agent Card."""

    findings: tuple[CardFinding, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"findings": [item.to_dict() for item in self.findings]}

    @property
    def fields(self) -> set[str]:
        return {item.field for item in self.findings}


def card_has_signature(card: dict[str, Any]) -> bool:
    """True when the card carries a JWS ``signature`` or ``signatures`` field."""
    return bool(card.get("signature") or card.get("signatures"))


def parse_origin_allowlist(
    values: tuple[str, ...] | list[str] | None = None,
    *,
    env: str | None = None,
) -> tuple[str, ...]:
    """CLI values first, then ``SUPERQODE_A2A_ALLOWED_ORIGINS``."""
    items: list[str] = []
    for value in values or ():
        text = str(value).strip()
        if text:
            items.append(text)
    source = env if env is not None else os.environ.get(ALLOWED_ORIGINS_ENV, "")
    for part in source.split(","):
        text = part.strip()
        if text:
            items.append(text)
    return tuple(items)


def resolve_jws_trust_root(
    path: str | None = None,
    *,
    env: str | None = None,
) -> str:
    """CLI path first, then ``SUPERQODE_A2A_JWS_TRUST_ROOT``."""
    if path and str(path).strip():
        return str(path).strip()
    source = env if env is not None else os.environ.get(JWS_TRUST_ROOT_ENV, "")
    return str(source).strip()


def origin_host(url: str) -> str:
    """Hostname of an origin or interface URL, lowercased."""
    text = (url or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"https://{text}"
    return (urlsplit(text).hostname or "").lower()


def origin_is_allowed(url: str, allowlist: tuple[str, ...] | list[str]) -> bool:
    """Empty allowlist means every origin is allowed."""
    if not allowlist:
        return True
    host = origin_host(url)
    if not host:
        return False
    for item in allowlist:
        allowed = (
            origin_host(item)
            if ("://" in item or item.startswith("."))
            else item.lower().lstrip(".")
        )
        if item.startswith("."):
            suffix = item.lower()
            if host.endswith(suffix) or host == suffix.lstrip("."):
                return True
            continue
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


def interface_hosts(card: dict[str, Any]) -> list[str]:
    """Hosts advertised on ``url`` and ``supportedInterfaces``."""
    hosts: list[str] = []
    raw_url = card.get("url")
    if isinstance(raw_url, str) and raw_url.strip():
        host = origin_host(raw_url)
        if host:
            hosts.append(host)
    interfaces = card.get("supportedInterfaces") or []
    if isinstance(interfaces, list):
        for item in interfaces:
            if not isinstance(item, dict):
                continue
            host = origin_host(str(item.get("url") or ""))
            if host:
                hosts.append(host)
    return hosts


def review_agent_card(
    card: dict[str, Any],
    *,
    origin: str = "",
    allowed_origins: tuple[str, ...] | list[str] = (),
    jws_trust_root: str = "",
) -> CardReview:
    """Return SuperOptiX-aligned findings plus SuperQode inspect extras.

    A JWS, when present, is never treated as authentication or skill
    attestation. A configured trust root only records that the operator
    supplied one. It does not satisfy ``securitySchemes``.
    """
    del jws_trust_root  # presence is recorded by the caller; JWS is never auth
    findings: list[CardFinding] = []

    if card_has_signature(card):
        findings.append(
            CardFinding(severity="medium", field="signature.trust", issue=JWS_TRUST_ISSUE)
        )
    else:
        findings.append(
            CardFinding(severity="high", field="signature", issue=UNSIGNED_SIGNATURE_ISSUE)
        )

    if not card.get("securitySchemes"):
        findings.append(
            CardFinding(severity="medium", field="securitySchemes", issue=SECURITY_SCHEMES_ISSUE)
        )
    else:
        unknown = _unknown_requirement_schemes(card)
        if unknown:
            listed = ", ".join(unknown)
            findings.append(
                CardFinding(
                    severity="medium",
                    field="securitySchemes",
                    issue=(
                        f"securityRequirements name scheme(s) {listed} that are "
                        "not declared in securitySchemes."
                    ),
                )
            )

    skills = card.get("skills") or []
    if skills:
        findings.append(
            CardFinding(
                severity="high",
                field="skills.attestation",
                issue=SKILLS_ATTESTATION_ISSUE,
            )
        )

    capabilities = card.get("capabilities") if isinstance(card.get("capabilities"), dict) else {}
    if capabilities.get("pushNotifications") or capabilities.get("push_notifications"):
        findings.append(
            CardFinding(
                severity="medium",
                field="capabilities.pushNotifications",
                issue=(
                    "Card claims push notifications. Treat webhook URLs as "
                    "untrusted. SuperQode serve a2a leaves pushNotifications "
                    "false, which mitigates unverified webhooks."
                ),
            )
        )

    if origin:
        advertised = interface_hosts(card)
        discovery = origin_host(origin)
        mismatched = [host for host in advertised if discovery and host != discovery]
        if mismatched:
            findings.append(
                CardFinding(
                    severity="medium",
                    field="url.host",
                    issue=(
                        f"Interface host {', '.join(dict.fromkeys(mismatched))} "
                        f"does not match the discovery origin {discovery}."
                    ),
                )
            )
        if allowed_origins and not origin_is_allowed(origin, tuple(allowed_origins)):
            findings.append(
                CardFinding(
                    severity="high",
                    field="origin.allowlist",
                    issue=f"Origin {origin} is not on the configured A2A allowlist.",
                )
            )

    return CardReview(findings=tuple(findings))


def record_card_review(inspect_log: Any, review: CardReview) -> None:
    """Append each finding to an InspectLog as a ``trust`` event."""
    if inspect_log is None:
        return
    for finding in review.findings:
        inspect_log.add(
            "trust",
            finding.summary(),
            severity=finding.severity,
            field=finding.field,
            issue=finding.issue,
        )


def _unknown_requirement_schemes(card: dict[str, Any]) -> list[str]:
    schemes = card.get("securitySchemes")
    if not isinstance(schemes, dict):
        return []
    declared = {str(name) for name in schemes}
    raw = card.get("securityRequirements") or card.get("security") or []
    if not isinstance(raw, list):
        return []
    unknown: list[str] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        mapping = item.get("schemes") if isinstance(item.get("schemes"), dict) else item
        if not isinstance(mapping, dict):
            continue
        for name in mapping:
            key = str(name)
            if key and key not in declared and key != "schemes" and key not in unknown:
                unknown.append(key)
    return unknown
