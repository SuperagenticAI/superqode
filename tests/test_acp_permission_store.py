"""Tests for the ACP permission store (A4 from the fast-agent gap audit).

Two layers:
1. The store itself — load/save/round-trip, parsing tolerance, removal.
2. The ACPClient integration — stored decisions short-circuit the user
   callback, fresh ``always`` decisions are persisted, scope/tool keys
   come from the tool_call.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import pytest

from superqode.acp.client import ACPClient
from superqode.acp.permission_store import (
    ACPPermissionStore,
    PermissionDecision,
    default_permissions_path,
)


# ---------------------------------------------------------------------------
# Store unit tests
# ---------------------------------------------------------------------------


def test_default_path_honors_superqode_home(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPERQODE_HOME", str(tmp_path))
    assert default_permissions_path() == tmp_path / "permissions.md"


def test_default_path_falls_back_to_dot_superqode(monkeypatch):
    monkeypatch.delenv("SUPERQODE_HOME", raising=False)
    assert default_permissions_path() == Path.home() / ".superqode" / "permissions.md"


def test_decision_from_option_kind_only_persists_always():
    """``once`` variants must map to ``None`` so they're never written.
    If we persisted ``allow_once``, the next session would silently
    auto-allow — exactly the opposite of what ``once`` means."""
    assert PermissionDecision.from_option_kind("allow_always") is PermissionDecision.ALLOW_ALWAYS
    assert PermissionDecision.from_option_kind("reject_always") is PermissionDecision.REJECT_ALWAYS
    assert PermissionDecision.from_option_kind("allow_once") is None
    assert PermissionDecision.from_option_kind("reject_once") is None
    assert PermissionDecision.from_option_kind(None) is None
    assert PermissionDecision.from_option_kind("bogus") is None


def test_allowed_property():
    assert PermissionDecision.ALLOW_ALWAYS.allowed is True
    assert PermissionDecision.REJECT_ALWAYS.allowed is False


@pytest.mark.asyncio
async def test_round_trip_set_get(tmp_path):
    store = ACPPermissionStore(path=tmp_path / "permissions.md")
    assert await store.get("opencode.ai", "bash") is None

    await store.set("opencode.ai", "bash", PermissionDecision.ALLOW_ALWAYS)
    assert await store.get("opencode.ai", "bash") is PermissionDecision.ALLOW_ALWAYS

    # Second store instance pointed at the same file must see it.
    fresh = ACPPermissionStore(path=tmp_path / "permissions.md")
    assert await fresh.get("opencode.ai", "bash") is PermissionDecision.ALLOW_ALWAYS


@pytest.mark.asyncio
async def test_file_only_created_on_first_always_decision(tmp_path):
    """No noisy empty file on startup. fast-agent matches this — the
    file is only meaningful when there's at least one row."""
    path = tmp_path / "permissions.md"
    store = ACPPermissionStore(path=path)
    await store.get("x", "y")  # lazy load with nothing on disk
    assert not path.exists()
    await store.set("x", "y", PermissionDecision.ALLOW_ALWAYS)
    assert path.exists()


@pytest.mark.asyncio
async def test_remove_deletes_file_when_last_row_gone(tmp_path):
    """An empty cache + leftover file would parse back to empty next
    session, but the user might think permissions are still active.
    Delete the file when it'd serialize to a header-only document."""
    path = tmp_path / "permissions.md"
    store = ACPPermissionStore(path=path)
    await store.set("a", "b", PermissionDecision.ALLOW_ALWAYS)
    assert path.exists()
    await store.remove("a", "b")
    assert not path.exists()


@pytest.mark.asyncio
async def test_remove_returns_false_for_unknown(tmp_path):
    store = ACPPermissionStore(path=tmp_path / "permissions.md")
    assert await store.remove("never", "set") is False


@pytest.mark.asyncio
async def test_clear_removes_file(tmp_path):
    path = tmp_path / "permissions.md"
    store = ACPPermissionStore(path=path)
    await store.set("a", "b", PermissionDecision.ALLOW_ALWAYS)
    await store.set("c", "d", PermissionDecision.REJECT_ALWAYS)
    await store.clear()
    assert not path.exists()
    assert await store.list_all() == {}


@pytest.mark.asyncio
async def test_parser_tolerates_extra_blank_lines_and_comments(tmp_path):
    """Users will edit this file by hand. Make sure a stray comment or
    blank line doesn't wipe their stored permissions on next load."""
    path = tmp_path / "permissions.md"
    path.write_text(
        "# Some comment\n"
        "\n"
        "| Scope | Tool | Permission |\n"
        "|-------|------|------------|\n"
        "| opencode.ai | bash | allow_always |\n"
        "\n"
        "| claude.com | edit_file | reject_always |\n",
        encoding="utf-8",
    )
    store = ACPPermissionStore(path=path)
    snapshot = await store.list_all()
    assert snapshot == {
        "opencode.ai/bash": PermissionDecision.ALLOW_ALWAYS,
        "claude.com/edit_file": PermissionDecision.REJECT_ALWAYS,
    }


@pytest.mark.asyncio
async def test_parser_skips_unknown_decision_values(tmp_path):
    """An old version of this file with a decision we no longer
    recognize must be skipped, not crash the whole load."""
    path = tmp_path / "permissions.md"
    path.write_text(
        "| Scope | Tool | Permission |\n"
        "|-------|------|------------|\n"
        "| a | b | allow_always |\n"
        "| c | d | something_old_we_dropped |\n",
        encoding="utf-8",
    )
    store = ACPPermissionStore(path=path)
    snapshot = await store.list_all()
    assert snapshot == {"a/b": PermissionDecision.ALLOW_ALWAYS}


@pytest.mark.asyncio
async def test_set_overwrites_prior_decision(tmp_path):
    """User changes their mind: reject_always -> allow_always.
    Must not produce two rows for the same scope/tool."""
    store = ACPPermissionStore(path=tmp_path / "permissions.md")
    await store.set("a", "b", PermissionDecision.REJECT_ALWAYS)
    await store.set("a", "b", PermissionDecision.ALLOW_ALWAYS)
    snapshot = await store.list_all()
    assert snapshot == {"a/b": PermissionDecision.ALLOW_ALWAYS}


@pytest.mark.asyncio
async def test_scope_isolates_per_agent(tmp_path):
    """Same tool name from different agents must not collide — user
    may trust ``bash`` in opencode but not in some-other-agent."""
    store = ACPPermissionStore(path=tmp_path / "permissions.md")
    await store.set("opencode.ai", "bash", PermissionDecision.ALLOW_ALWAYS)
    await store.set("other.com", "bash", PermissionDecision.REJECT_ALWAYS)
    assert (await store.get("opencode.ai", "bash")).allowed is True
    assert (await store.get("other.com", "bash")).allowed is False


# ---------------------------------------------------------------------------
# ACPClient integration
# ---------------------------------------------------------------------------


def _client(tmp_path, scope: str = "opencode.ai") -> ACPClient:
    return ACPClient(
        project_root=Path.cwd(),
        command="(unused)",
        permission_store=ACPPermissionStore(path=tmp_path / "permissions.md"),
        permission_scope=scope,
    )


def _options() -> List[dict]:
    """The four standard ACP permission options the agent normally offers."""
    return [
        {"kind": "allow_once", "optionId": "ao", "name": "Allow once"},
        {"kind": "allow_always", "optionId": "aa", "name": "Allow always"},
        {"kind": "reject_once", "optionId": "ro", "name": "Reject once"},
        {"kind": "reject_always", "optionId": "ra", "name": "Reject always"},
    ]


@pytest.mark.asyncio
async def test_stored_allow_always_short_circuits_user_prompt(tmp_path):
    """The whole point of the store: once the user has said "allow
    always" for a tool, never bother them again about it."""
    client = _client(tmp_path)
    await client.permission_store.set("opencode.ai", "bash", PermissionDecision.ALLOW_ALWAYS)

    asked = False

    async def on_perm(options, tool_call):
        nonlocal asked
        asked = True
        return "ao"

    client.on_permission_request = on_perm

    result = await client._handle_permission_request(
        {
            "options": _options(),
            "toolCall": {"toolCallId": "1", "title": "bash"},
        }
    )

    assert asked is False, "user callback must not be invoked when decision is stored"
    assert result == {"outcome": {"outcome": "selected", "optionId": "aa"}}


@pytest.mark.asyncio
async def test_stored_reject_always_short_circuits(tmp_path):
    client = _client(tmp_path)
    await client.permission_store.set(
        "opencode.ai", "delete_file", PermissionDecision.REJECT_ALWAYS
    )

    result = await client._handle_permission_request(
        {
            "options": _options(),
            "toolCall": {"toolCallId": "1", "title": "delete_file"},
        }
    )
    assert result["outcome"]["optionId"] == "ra"


@pytest.mark.asyncio
async def test_fresh_allow_always_is_persisted(tmp_path):
    """User picks ``allow_always`` for the first time — next session
    must remember it without prompting."""
    client = _client(tmp_path)

    async def on_perm(options, tool_call):
        # User picks "Allow always".
        return "aa"

    client.on_permission_request = on_perm

    await client._handle_permission_request(
        {
            "options": _options(),
            "toolCall": {"toolCallId": "1", "title": "bash"},
        }
    )

    decision = await client.permission_store.get("opencode.ai", "bash")
    assert decision is PermissionDecision.ALLOW_ALWAYS


@pytest.mark.asyncio
async def test_fresh_allow_once_is_not_persisted(tmp_path):
    """``once`` decisions stay ephemeral. Persisting them would silently
    auto-allow next time — defeating the user's intent."""
    client = _client(tmp_path)

    async def on_perm(options, tool_call):
        return "ao"  # allow_once

    client.on_permission_request = on_perm

    await client._handle_permission_request(
        {
            "options": _options(),
            "toolCall": {"toolCallId": "1", "title": "bash"},
        }
    )

    assert await client.permission_store.get("opencode.ai", "bash") is None


@pytest.mark.asyncio
async def test_no_store_configured_preserves_legacy_behavior(tmp_path):
    """Without ``permission_store`` set, behavior must match what we had
    before A4 landed — always invoke the callback, never persist."""
    client = ACPClient(project_root=Path.cwd(), command="(unused)")
    seen: List[dict] = []

    async def on_perm(options, tool_call):
        seen.append(tool_call)
        return "ao"

    client.on_permission_request = on_perm

    result = await client._handle_permission_request(
        {"options": _options(), "toolCall": {"toolCallId": "1", "title": "bash"}}
    )
    assert seen and result["outcome"]["optionId"] == "ao"


@pytest.mark.asyncio
async def test_stored_decision_falls_back_to_once_when_always_option_missing(tmp_path):
    """Some agents only offer once-variants for sensitive tools. If the
    user previously stored ``allow_always`` for it, we should still
    respect their intent for the current call by picking ``allow_once``."""
    client = _client(tmp_path)
    await client.permission_store.set("opencode.ai", "bash", PermissionDecision.ALLOW_ALWAYS)

    once_only = [
        {"kind": "allow_once", "optionId": "ao", "name": "Allow once"},
        {"kind": "reject_once", "optionId": "ro", "name": "Reject once"},
    ]

    result = await client._handle_permission_request(
        {"options": once_only, "toolCall": {"toolCallId": "1", "title": "bash"}}
    )
    assert result["outcome"]["optionId"] == "ao"
