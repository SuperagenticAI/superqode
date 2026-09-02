"""Tests for the Harness Hub shortlist skill.

These exercise the ranking directly rather than through A2A, so they do not
need the optional a2a extra.
"""

from __future__ import annotations

from superqode.a2a.shortlist import (
    _has_structured_policy,
    _provides,
    build_shortlist,
    parse_constraints,
    render_shortlist,
)


def _third_party(**overrides):
    """A managed or protocol entry: prose policies, no capability facts."""
    base = {
        "id": "vendor-agent",
        "name": "Vendor Agent",
        "description": "A third-party coding agent",
        "category": "Coding agents",
        "kind": "managed",
        "integration_level": "managed",
        "runtime": "vendor",
        "source": "vendor",
        "readiness": "setup-required",
        "openness": "open",
        "license": "MIT",
        "docs_url": "",
        "install_command": "",
        "policies": ("The connected coding agent owns its tool loop",),
        "capabilities": ("Managed connection from SuperQode",),
        "tools": (),
        "popularity_rank": 500,
    }
    base.update(overrides)
    return base


def _own(**overrides):
    """A native SuperQode entry: labelled, machine-readable policies."""
    base = dict(
        _third_party(),
        id="core",
        name="Core",
        category="SuperQode harnesses",
        kind="native",
        integration_level="native",
        runtime="builtin",
        source="built-in",
        readiness="ready",
        license="Apache-2.0",
        policies=("Sandbox: local", "Approvals: balanced"),
    )
    base.update(overrides)
    return base


def test_disabled_policies_do_not_count_as_provided():
    """ "Approvals: none" and "Approvals: yolo" both mean no approvals."""
    assert _provides(["approvals: balanced"], "approvals") is True
    assert _provides(["approvals: none"], "approvals") is False
    assert _provides(["approvals: yolo"], "approvals") is False
    assert _provides(["sandbox: docker"], "sandbox") is True
    assert _provides(["sandbox: none"], "sandbox") is False


def test_singular_request_matches_plural_policy_label():
    """The Hub writes "Approvals:" while a caller says "approval"."""
    assert parse_constraints("we need approval gates").capabilities == ("approvals",)


def test_prose_policies_are_not_treated_as_capability_facts():
    """Vendor entries describe their loop in prose, not in labelled policies.

    Reading capability claims out of that prose invents precision the Hub does
    not have, which is how a vendor whose description merely mentions the word
    "sandbox" would outrank one that does not.
    """
    assert _has_structured_policy(_own()) is True
    assert _has_structured_policy(_third_party()) is False
    assert (
        _has_structured_policy(
            _third_party(policies=("DeepSeek owns the loop, tools, and sandbox",))
        )
        is False
    )


def test_own_harnesses_are_excluded_from_the_ranking_by_default():
    """A recommendation that leads with our own product is worth nothing.

    Every entry the Hub marks "ready" is one SuperQode supplies, so any
    ranking that rewards readiness promotes our own harnesses in every
    request. They are held back and disclosed separately instead.
    """
    result = build_shortlist("a coding agent", records=[_third_party(), _own()], limit=5)
    assert [entry.id for entry in result.entries] == ["vendor-agent"]
    assert result.includes_own is False
    assert result.own_considered == 1
    assert result.third_party_considered == 1

    text = render_shortlist(result)
    assert "Disclosure: the native harnesses are ours" in text


def test_own_harnesses_appear_when_the_request_asks_for_them():
    result = build_shortlist(
        "we want to build our own harness", records=[_third_party(), _own()], limit=5
    )
    assert {entry.id for entry in result.entries} == {"vendor-agent", "core"}
    assert result.includes_own is True


def test_own_harnesses_appear_when_no_third_party_entry_exists():
    result = build_shortlist("anything", records=[_own()], limit=5)
    assert [entry.id for entry in result.entries] == ["core"]


def test_capability_requests_say_the_hub_cannot_answer_them():
    result = build_shortlist("needs a sandbox", records=[_third_party()], limit=5)
    assert result.entries[0].policy_known is False
    assert result.entries[0].meets == ()
    joined = " ".join(result.notes)
    assert "does not record sandbox" in joined
    assert "measured rather than looked up" in joined


def test_readiness_does_not_influence_the_ranking():
    """Readiness tracks integration level, not quality, so it is not scored."""
    ready = _third_party(id="ready-one", name="Alpha", readiness="ready")
    unready = _third_party(id="unready-one", name="Alpha", readiness="setup-required")
    result = build_shortlist("alpha", records=[unready, ready], limit=2)
    assert {entry.score for entry in result.entries} == {result.entries[0].score}


def test_ecosystem_watch_entries_are_excluded():
    result = build_shortlist(
        "anything",
        records=[_third_party(id="runnable"), _third_party(id="watch", readiness="not-supported")],
        limit=5,
    )
    assert [entry.id for entry in result.entries] == ["runnable"]
    assert result.third_party_considered == 1


def test_output_always_points_at_measurement():
    text = render_shortlist(build_shortlist("anything", records=[_third_party()], limit=1))
    assert "not measurements" in text
    assert "HarnessBench" in text
    assert "not a chat model" in text
    assert "SUPERQODE_API_KEY" in text
    assert "superqode.dev" in text


def test_rendered_text_carries_no_catalogue_counts():
    """Counts go stale as the catalogue changes, so prose must not quote them.

    The structured payload still reports them, because a programmatic caller
    reads live values rather than a sentence written once.
    """
    result = build_shortlist(
        "anything", records=[_third_party(), _third_party(id="second"), _own()], limit=2
    )
    text = render_shortlist(result)
    assert not any(character.isdigit() for character in text.splitlines()[0])
    closing = [line for line in text.splitlines() if "Disclosure" in line]
    assert closing and not any(character.isdigit() for character in closing[0])
    assert "evaluate and optimise" in text
    assert result.to_dict()["thirdPartyConsidered"] == 2


def test_shortlist_reads_the_real_hub_by_default():
    result = build_shortlist("python coding agent", limit=3)
    assert result.third_party_considered > 10
    assert result.own_considered > 0
    assert result.hub_schema_version
    assert all(entry.superqode_supplied is False for entry in result.entries)
