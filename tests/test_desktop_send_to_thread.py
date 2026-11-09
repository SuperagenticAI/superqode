"""Read-only previews for explicitly reviewed cross-thread drafts."""

import hashlib

import pytest

from test_desktop_service import desktop  # noqa: F401
from test_desktop_thread_share import add_turn
from superqode.desktop_service import conversations, turn_changes


def preview(service, project, identity="second", **extra):
    return service.dispatch(
        "threads.send.preview", {"project": project["id"], "id": identity, **extra}
    )


def test_visible_read_only_preview_and_digest(desktop):
    service, project, _ = desktop
    add_turn(service, project["id"], "first", prompt="Original goal")
    add_turn(service, project["id"], "second", "first")
    before = service._all("SELECT * FROM jobs")
    result = preview(service, project)
    assert result["turns"] == 2
    assert result["source_thread"] == "first"
    assert result["source_title"] == "first"
    assert result["source_harness"] == "core"
    assert 'Context from thread "first" (core)' in result["text"]
    assert "Original goal" in result["text"]
    assert "visible answer second" in result["text"]
    assert result["omitted_messages"] == 0
    assert result["digest"] == hashlib.sha256(result["text"].encode()).hexdigest()
    for private in ["PRIVATE_REASONING", "private-image", "private-session"]:
        assert private not in result["text"]
    assert service._all("SELECT * FROM jobs") == before
    assert not service.processes


def test_budget_counts_utf8_and_omitted_complete_messages(desktop):
    service, project, _ = desktop
    add_turn(service, project["id"], "first", prompt="Original goal")
    add_turn(service, project["id"], "huge", "first", prompt="界" * 25_000)
    add_turn(service, project["id"], "second", "huge", prompt="Latest request")
    result = preview(service, project)
    assert len(result["text"].encode("utf-8")) <= conversations.HANDOFF_BYTES
    assert result["omitted_messages"] == 1
    assert "Original goal" in result["text"] and "Latest request" in result["text"]
    assert "界" not in result["text"]
    assert "1 messages omitted" in result["text"]


def test_recent_messages_take_priority_after_goal(desktop, monkeypatch):
    service, project, _ = desktop
    monkeypatch.setattr(conversations, "HANDOFF_BYTES", 1400)
    add_turn(service, project["id"], "first", prompt="Goal")
    add_turn(service, project["id"], "older", "first", prompt="O" * 600)
    add_turn(service, project["id"], "second", "older", prompt="N" * 600)
    result = preview(service, project)
    assert "Goal" in result["text"]
    assert "N" * 600 in result["text"]
    assert "O" * 600 not in result["text"]
    assert len(result["text"].encode()) <= 1400


def test_from_turn_keeps_original_goal_and_selected_tail(desktop):
    service, project, _ = desktop
    add_turn(service, project["id"], "first", prompt="Original goal")
    add_turn(service, project["id"], "middle", "first", prompt="Excluded middle request")
    add_turn(service, project["id"], "second", "middle", prompt="Selected tail")
    result = preview(service, project, from_turn="second")
    assert result["turns"] == 1
    assert "Original goal" in result["text"]
    assert "Selected tail" in result["text"]
    assert "Excluded middle request" not in result["text"]
    assert len(result["available_turns"]) == 3
    with pytest.raises(ValueError, match="outside this thread"):
        preview(service, project, from_turn="unrelated")


def test_changed_file_names_are_filtered_and_optional(desktop, monkeypatch):
    service, project, _ = desktop
    add_turn(service, project["id"], "second")
    names = [
        "src/safe.py",
        ".env",
        "nested/.env.production",
        ".git/config",
        "a/.ssh/key",
        ".aws/credentials",
        ".gnupg/key",
        ".superqode/state",
        ".superqode-private/state",
        "../outside",
        "/absolute",
    ]
    calls = []

    def summary(*args):
        calls.append(args[-1])
        return {"files": [{"path": name} for name in names]}

    monkeypatch.setattr(turn_changes, "summary", summary)
    assert "Changed files" not in preview(service, project)["text"]
    assert not calls
    result = preview(service, project, include_changes=True)
    assert "- src/safe.py" in result["text"]
    for name in names[1:]:
        assert name not in result["text"]
    assert calls == ["second"]


def test_file_names_share_the_total_budget(desktop, monkeypatch):
    service, project, _ = desktop
    add_turn(service, project["id"], "second")
    monkeypatch.setattr(
        turn_changes,
        "summary",
        lambda *args: {"files": [{"path": f"src/{i}/" + "x" * 500} for i in range(200)]},
    )
    result = preview(service, project, include_changes=True)
    assert len(result["text"].encode()) <= conversations.HANDOFF_BYTES
    assert "Some changed file names were omitted" in result["text"]


def test_unknown_thread_and_active_source_errors(desktop):
    service, project, _ = desktop
    with pytest.raises(ValueError, match="missing a run"):
        preview(service, project, "unknown")
    add_turn(service, project["id"], "busy", status="running")
    with pytest.raises(ValueError, match="Finish or stop"):
        preview(service, project, "busy")


def test_project_scope_and_stable_root_resolution(desktop):
    service, project, root = desktop
    add_turn(service, project["id"], "first")
    add_turn(service, project["id"], "second", "first")
    assert preview(service, project, "first")["turns"] == 2
    other = root.parent / "other-send-project"
    other.mkdir()
    other_project = service.open_project(str(other))
    with pytest.raises(ValueError, match="selected project"):
        preview(service, other_project)


def test_renamed_source_title(desktop):
    service, project, _ = desktop
    add_turn(service, project["id"], "second")
    service.dispatch(
        "threads.update", {"project": project["id"], "id": "second", "title": "Reviewed title"}
    )
    assert preview(service, project)["source_title"] == "Reviewed title"
