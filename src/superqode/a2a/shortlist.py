"""Rank Harness Hub entries against a stated set of constraints.

The ranking covers third-party harnesses only. SuperQode's own native
harnesses and presets are held back and offered separately, because a
recommendation that leads with the vendor's own product is worth nothing to
the person reading it.

Two Hub properties make that separation necessary rather than merely polite.
Published readiness is derived from integration level, so every native entry
and every preset reads as ``ready`` while every third-party entry reads as
``setup-required``. Scoring on readiness would therefore promote our own
harnesses in every request, with no way for a third-party entry to compete.

The skill costs nothing to run. There is no model call, no sandbox and no
checkout, which is what makes it answerable on a public endpoint. Deciding
which candidate actually wins on a specific codebase is a measurement, and
that belongs to HarnessBench.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

#: Hub entries tracked for awareness rather than use.
_UNRUNNABLE_READINESS = "not-supported"

#: Integration levels that identify a SuperQode-supplied entry.
_OWN_INTEGRATION_LEVELS = frozenset({"native", "preset"})

#: The Hub records openness as "open", "closed", or "" when unstated.
_OPEN = "open"

#: Phrases that ask for a SuperQode harness or a custom build directly.
_OWN_PHRASES = (
    "superqode",
    "native harness",
    "build our own",
    "build my own",
    "build your own",
    "our own harness",
    "custom harness",
    "from scratch",
)

_OPEN_PHRASES = (
    "open source",
    "open-source",
    "oss",
    "self-host",
    "self host",
    "vendor neutral",
    "vendor-neutral",
)

#: Request wording mapped to the capability a Hub record would declare.
_CAPABILITY_TERMS = {
    "sandbox": "sandbox",
    "sandboxed": "sandbox",
    "isolation": "sandbox",
    "approval": "approvals",
    "approvals": "approvals",
    "mcp": "mcp",
    "streaming": "streaming",
    "shell": "shell",
    "local": "local",
    "offline": "local",
}

#: Every spelling a record might use for a capability. Hub policy strings are
#: labelled ("Approvals: balanced"), and singular/plural drift is what makes a
#: labelled check fall through to a loose substring match.
_CAPABILITY_LABELS = {
    "sandbox": ("sandbox",),
    "approvals": ("approvals", "approval"),
    "mcp": ("mcp",),
    "streaming": ("streaming",),
    "shell": ("shell", "bash"),
    "local": ("local", "ollama"),
}

#: Policy values meaning the capability is off. "yolo" auto-approves
#: everything, so a harness carrying it offers no approvals at all.
_DISABLED_SETTINGS = frozenset(
    {"", "none", "not required", "blocked", "no", "off", "yolo", "disabled"}
)

_STOPWORDS = frozenset(
    """
    a an and any are as at be best both but by can could do does for from get give
    has have how i if in into is it its like looking me my need needs of on or our
    please recommend recommendation should show so some suggest team that the their
    them then there these they this to us use used using want we what when which
    who will with would you your harness harnesses agent agents coding run running
    """.split()
)


@dataclass(frozen=True)
class ShortlistConstraints:
    """What the request asked for, and what was understood."""

    terms: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    open_source_preferred: bool = False
    own_requested: bool = False

    @property
    def summary(self) -> str:
        """One line naming the constraints that were applied."""
        parts = list(self.capabilities)
        if self.open_source_preferred:
            parts.append("open source")
        if not parts:
            return "none recognised"
        return ", ".join(parts)


@dataclass(frozen=True)
class ShortlistEntry:
    """One candidate and the basis for including it."""

    id: str
    name: str
    description: str
    category: str
    runtime: str
    readiness: str
    openness: str
    license: str
    docs_url: str
    install_command: str
    score: float
    meets: tuple[str, ...] = ()
    lacks: tuple[str, ...] = ()
    policy_known: bool = False
    superqode_supplied: bool = False

    def to_dict(self) -> dict[str, Any]:
        # camelCase: A2A JSON field names (specification 5.5). A snake_case
        # key anywhere in a response fails DM-SERIAL-001.
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "runtime": self.runtime,
            "readiness": self.readiness,
            "openness": self.openness,
            "license": self.license,
            "docsUrl": self.docs_url,
            "installCommand": self.install_command,
            "score": round(self.score, 3),
            "meets": list(self.meets),
            "lacks": list(self.lacks),
            "policyKnown": self.policy_known,
            "superqodeSupplied": self.superqode_supplied,
        }


@dataclass(frozen=True)
class Shortlist:
    """A ranked answer and the context needed to judge it."""

    entries: tuple[ShortlistEntry, ...]
    constraints: ShortlistConstraints
    third_party_considered: int
    own_considered: int
    hub_schema_version: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def includes_own(self) -> bool:
        return any(entry.superqode_supplied for entry in self.entries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "superqode.harness-shortlist",
            "hubSchemaVersion": self.hub_schema_version,
            "thirdPartyConsidered": self.third_party_considered,
            "ownConsidered": self.own_considered,
            "constraints": {
                "capabilities": list(self.constraints.capabilities),
                "openSourcePreferred": self.constraints.open_source_preferred,
                "terms": list(self.constraints.terms),
            },
            "entries": [entry.to_dict() for entry in self.entries],
            "notes": list(self.notes),
        }


def _has_structured_policy(record: dict[str, Any]) -> bool:
    """Return whether a record's policies are machine-readable facts.

    Native harnesses and presets declare labelled policies such as
    ``"Sandbox: local"``. Managed and protocol entries carry prose disclaimers
    instead, because the vendor owns that loop and SuperQode does not know
    what it does. Reading capability claims out of prose invents precision
    that is not there.
    """
    return any(
        f"{label}:" in str(value).casefold()
        for value in (record.get("policies") or ())
        for labels in _CAPABILITY_LABELS.values()
        for label in labels
    )


def _provides(declared: list[str], capability: str) -> bool:
    """Return whether a labelled policy set offers a capability.

    Only meaningful for records that pass :func:`_has_structured_policy`.
    A labelled policy counts only when its value is not a disabled setting.
    """
    labels = _CAPABILITY_LABELS.get(capability, (capability,))
    for value in declared:
        for label in labels:
            prefix = f"{label}:"
            if prefix in value:
                _, _, setting = value.partition(prefix)
                return setting.strip() not in _DISABLED_SETTINGS
    return False


def parse_constraints(request: str) -> ShortlistConstraints:
    """Read the constraints a request states, ignoring what it does not."""
    lowered = request.casefold()
    return ShortlistConstraints(
        terms=tuple(
            dict.fromkeys(
                word
                for word in "".join(c if c.isalnum() else " " for c in lowered).split()
                if len(word) > 2 and word not in _STOPWORDS
            )
        )[:8],
        capabilities=tuple(
            dict.fromkeys(
                canonical for word, canonical in _CAPABILITY_TERMS.items() if word in lowered
            )
        ),
        open_source_preferred=any(phrase in lowered for phrase in _OPEN_PHRASES),
        own_requested=any(phrase in lowered for phrase in _OWN_PHRASES),
    )


def _is_own(record: dict[str, Any]) -> bool:
    return str(record.get("integration_level", "")) in _OWN_INTEGRATION_LEVELS


def _declared(record: dict[str, Any]) -> list[str]:
    return [
        str(value).casefold()
        for key in ("capabilities", "policies", "tools")
        for value in (record.get(key) or ())
    ]


def _score(record: dict[str, Any], constraints: ShortlistConstraints) -> ShortlistEntry:
    """Score one record on what the Hub actually knows.

    Neither readiness nor capability fitness is scored. Published readiness
    tracks integration level rather than quality, and capability data exists
    only for entries SuperQode supplies, so scoring either would rank our own
    harnesses above every third-party one by construction. Both are reported
    as facts where they are known and left out of the ordering.
    """
    score = 0.0

    haystack = " ".join(
        str(record.get(name, ""))
        for name in ("id", "name", "description", "category", "kind", "runtime", "source")
    ).casefold()
    score += 2.0 * sum(1 for term in constraints.terms if term in haystack)

    if str(record.get("openness", "")) == _OPEN:
        score += 2.0 if constraints.open_source_preferred else 0.5

    # A rank, so lower is better known. Small enough to break ties only.
    score += max(0.0, (500 - int(record.get("popularity_rank") or 500)) / 500.0)

    known = _has_structured_policy(record)
    declared = _declared(record) if known else []
    meets = tuple(c for c in constraints.capabilities if _provides(declared, c)) if known else ()
    lacks = tuple(c for c in constraints.capabilities if c not in meets) if known else ()

    return ShortlistEntry(
        id=str(record.get("id", "")),
        name=str(record.get("name", "")),
        description=str(record.get("description", "")),
        category=str(record.get("category", "")),
        runtime=str(record.get("runtime", "")),
        readiness=str(record.get("readiness", "")),
        openness=str(record.get("openness", "")),
        license=str(record.get("license", "")),
        docs_url=str(record.get("docs_url", "")),
        install_command=str(record.get("install_command", "")),
        score=score,
        meets=meets,
        lacks=lacks,
        policy_known=known,
        superqode_supplied=_is_own(record),
    )


def _rank(records: list[dict[str, Any]], constraints: ShortlistConstraints) -> list[ShortlistEntry]:
    entries = [_score(record, constraints) for record in records]
    entries.sort(key=lambda entry: (-entry.score, entry.name))
    return entries


def build_shortlist(
    request: str,
    *,
    records: Iterable[dict[str, Any]] | None = None,
    limit: int = 5,
    hub_schema_version: str = "",
    constraints: ShortlistConstraints | None = None,
) -> Shortlist:
    """Rank Hub entries against a free-text request.

    Third-party harnesses are ranked first and alone. SuperQode's own entries
    are appended only when the request asks for them, or when too few
    third-party candidates satisfy the stated capabilities.

    ``constraints`` accepts constraints derived elsewhere, so a caller that
    read the request with a model can hand them in. Ranking is unchanged
    either way: the constraints decide what is wanted, and the catalogue
    decides what is true.
    """
    version = hub_schema_version
    if records is None:
        from superqode.harness.hub import build_hub_index

        index = build_hub_index(public=True)
        records = index["items"]
        version = version or str(index.get("schema_version", ""))

    runnable = [
        record for record in records if str(record.get("readiness", "")) != _UNRUNNABLE_READINESS
    ]
    if constraints is None:
        constraints = parse_constraints(request)
    third_party = [r for r in runnable if not _is_own(r)]
    own = [r for r in runnable if _is_own(r)]

    limit = max(1, limit)
    ranked = _rank(third_party, constraints)
    notes: list[str] = []

    if constraints.own_requested:
        entries = _rank(third_party + own, constraints)[:limit]
    elif not third_party:
        entries = _rank(own, constraints)[:limit]
    else:
        entries = ranked[:limit]

    if constraints.capabilities and not any(entry.policy_known for entry in entries):
        notes.append(
            f"The Hub does not record {', '.join(constraints.capabilities)} for these "
            "entries. Each vendor owns its own tool loop, so that behaviour has to be "
            "measured rather than looked up."
        )

    return Shortlist(
        entries=tuple(entries),
        constraints=constraints,
        third_party_considered=len(third_party),
        own_considered=len(own),
        hub_schema_version=version,
        notes=tuple(notes),
    )


def render_shortlist(shortlist: Shortlist) -> str:
    """Render a shortlist as plain text."""
    lines = [
        "Third-party harnesses from the Harness Hub.",
        f"Constraints: {shortlist.constraints.summary}.",
        "",
    ]

    for position, entry in enumerate(shortlist.entries, start=1):
        origin = "SuperQode" if entry.superqode_supplied else entry.category
        header = f"{position}. {entry.name}"
        if entry.openness:
            header += f"  ({origin}, {entry.openness} source)"
        else:
            header += f"  ({origin})"
        lines.append(header)
        if entry.description:
            lines.append(f"   {entry.description}")
        if entry.policy_known and entry.meets:
            lines.append(f"   Declares: {', '.join(entry.meets)}")
        if entry.policy_known and entry.lacks:
            lines.append(f"   Does not declare: {', '.join(entry.lacks)}")
        if entry.install_command:
            lines.append(f"   Install: {entry.install_command}")
        if entry.docs_url:
            lines.append(f"   Docs: {entry.docs_url}")
        lines.append("")

    lines.extend(shortlist.notes)
    if shortlist.notes:
        lines.append("")

    lines.append(
        "These are catalogue entries, not measurements. Ranking them on your own "
        "repository requires running HarnessBench over the candidates with the "
        "model you intend to use."
    )
    if not shortlist.includes_own and shortlist.own_considered:
        lines.append("")
        lines.append(
            "If none of these fit, SuperQode can evaluate and optimise any of them "
            "against your own repository, or adapt a native harness into one you own "
            "and control outright. Disclosure: the native harnesses are ours, and they "
            "are excluded from the ranking above."
        )
    return "\n".join(lines).rstrip() + "\n"
