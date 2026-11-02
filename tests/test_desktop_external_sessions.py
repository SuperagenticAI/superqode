"""External discovery is opt-in, bounded and read-only, without live agent calls."""

import json
import os
from pathlib import Path
import uuid

import pytest

from test_desktop_service import desktop  # noqa: F401
from superqode.desktop_service import external_sessions as external
from superqode.desktop_service.service import DesktopService


def session(path, cwd, *, identity=None, text="A recorded request", messages=None):
    identity = identity or str(uuid.uuid4())
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "type": "session_meta",
            "payload": {
                "id": identity,
                "cwd": str(cwd),
                "cli_version": "fixture",
                "base_instructions": "PRIVATE BASE INSTRUCTIONS",
                "git": {"branch": "feature/recorded"},
            },
        },
        {"type": "response_item", "payload": {"type": "reasoning", "summary": "PRIVATE REASONING"}},
        {
            "type": "response_item",
            "payload": {"type": "function_call_output", "output": "PRIVATE TOOL RESULT"},
        },
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "PRIVATE DEVELOPER INSTRUCTIONS"}],
            },
        },
    ]
    for role, content in messages or [("user", text), ("assistant", "Recorded answer")]:
        rows.append(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": role,
                    "content": [
                        {
                            "type": "input_text" if role == "user" else "output_text",
                            "text": content,
                        },
                        {"type": "input_image", "image_url": "PRIVATE IMAGE"},
                    ],
                },
            }
        )
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return identity


def connect(service, folder):
    row = service.dispatch("external.sources.add", {"path": str(folder), "provider": "codex"})
    service.dispatch("external.sources.scan", row)
    return row["id"]


def test_discovery_requires_explicit_source_and_never_indexes_messages(desktop, tmp_path):
    service, project, root = desktop
    folder = tmp_path / "sessions"
    path = folder / "2026/11/01/record.jsonl"
    session(path, root, text="PRIVATE USER MESSAGE")
    before = path.read_bytes()
    assert service.dispatch("external.sources.list", {}) == []
    assert service.dispatch("external.sessions.list", {})["count"] == 0
    source = connect(service, folder)
    rows = service.dispatch("external.sessions.list", {"project": project["id"]})["items"]
    assert len(rows) == 1
    assert rows[0]["status"] == "recorded"
    assert rows[0]["branch"] == "feature/recorded"
    assert rows[0]["source"] == source
    assert "PRIVATE" not in json.dumps(rows)
    assert "PRIVATE" not in json.dumps(service._all("SELECT * FROM external_sessions"))
    assert not service.dispatch("jobs.list", {})
    assert path.read_bytes() == before


def test_context_excludes_tools_reasoning_images_and_instructions_and_binds_review(
    desktop, tmp_path
):
    service, _, root = desktop
    path = tmp_path / "sessions/one.jsonl"
    session(path, root)
    connect(service, path.parent)
    row = service.dispatch("external.sessions.list", {})["items"][0]
    preview = service.dispatch("external.sessions.preview", {"id": row["id"]})
    assert "A recorded request" in preview["text"] and "Recorded answer" in preview["text"]
    assert "PRIVATE" not in preview["text"]
    assert preview["included_messages"] == 2
    checked = service.dispatch(
        "external.sessions.preview", {"id": row["id"], "expected_digest": preview["digest"]}
    )
    assert checked == preview
    with path.open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "New answer"}],
                    },
                }
            )
            + "\n"
        )
    with pytest.raises(ValueError, match="changed since review"):
        service.dispatch(
            "external.sessions.preview", {"id": row["id"], "expected_digest": preview["digest"]}
        )
    assert not service.dispatch("jobs.list", {})


def test_missing_replaced_and_symlinked_paths_cannot_be_read(desktop, tmp_path):
    service, _, root = desktop
    folder = tmp_path / "sessions"
    path = folder / "year/one.jsonl"
    session(path, root)
    outside = tmp_path / "outside"
    session(outside / "outside.jsonl", root)
    (folder / "linked-folder").symlink_to(outside, target_is_directory=True)
    (folder / "linked-file.jsonl").symlink_to(outside / "outside.jsonl")
    connect(service, folder)
    rows = service.dispatch("external.sessions.list", {})["items"]
    assert len(rows) == 1
    row = rows[0]
    path.unlink()
    path.symlink_to(outside / "outside.jsonl")
    for method in ["external.sessions.preview", "external.sessions.reveal"]:
        with pytest.raises(ValueError, match="unavailable|changed"):
            service.dispatch(method, {"id": row["id"]})
    path.unlink()
    path.parent.rmdir()
    path.parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="unavailable|changed"):
        service.dispatch("external.sessions.preview", {"id": row["id"]})


def test_source_replacement_is_not_silently_trusted(desktop, tmp_path):
    service, _, root = desktop
    folder = tmp_path / "sessions"
    session(folder / "one.jsonl", root)
    source = connect(service, folder)
    folder.rename(tmp_path / "old-sessions")
    folder.mkdir()
    session(folder / "two.jsonl", root)
    with pytest.raises(ValueError, match="folder changed"):
        service.dispatch("external.sources.scan", {"id": source})
    with pytest.raises(ValueError, match="folder changed"):
        service.dispatch("external.sources.add", {"path": str(folder)})


def test_duplicates_paging_search_scope_and_stale_cursors(desktop, tmp_path):
    service, project, root = desktop
    folder = tmp_path / "sessions"
    duplicate = session(folder / "one.jsonl", root)
    session(folder / "copy.jsonl", root, identity=duplicate)
    for index in range(52):
        session(folder / f"{index}.jsonl", root)
    session(folder / "other.jsonl", tmp_path / "elsewhere")
    source = connect(service, folder)
    first = service.dispatch("external.sessions.list", {"project": project["id"]})
    assert first["count"] == 53 and len(first["items"]) == 50
    second = service.dispatch(
        "external.sessions.list", {"project": project["id"], "cursor": first["next_cursor"]}
    )
    assert len(second["items"]) == 3
    assert not {row["id"] for row in first["items"]} & {row["id"] for row in second["items"]}
    assert service.dispatch("external.sessions.list", {"query": duplicate})["count"] == 1
    assert service.dispatch("external.sessions.list", {"query": "feature/recorded"})["count"] == 54
    assert (
        service.dispatch("external.sessions.list", {"query": "not indexed prompt text"})["count"]
        == 0
    )
    with pytest.raises(ValueError, match="Refresh external"):
        service.dispatch("external.sessions.list", {"cursor": first["next_cursor"]})
    service.dispatch("external.sources.scan", {"id": source})
    with pytest.raises(ValueError, match="Refresh external"):
        service.dispatch(
            "external.sessions.list", {"project": project["id"], "cursor": first["next_cursor"]}
        )


def test_source_registration_is_idempotent_and_rejects_overlaps(desktop, tmp_path):
    service, _, root = desktop
    path = tmp_path / "sessions/year/one.jsonl"
    session(path, root)
    folder = path.parent.parent
    source = connect(service, folder)
    assert service.dispatch("external.sources.add", {"path": str(folder)})["id"] == source
    for overlapping in [path.parent, tmp_path]:
        with pytest.raises(ValueError, match="overlaps"):
            service.dispatch("external.sources.add", {"path": str(overlapping)})


def test_index_survives_restart_and_disconnect_preserves_source_files(desktop, tmp_path):
    service, _, root = desktop
    path = tmp_path / "sessions/one.jsonl"
    session(path, root)
    source = connect(service, path.parent)
    row = service.dispatch("external.sessions.list", {})["items"][0]
    state = service.root
    service.close()
    recovered = DesktopService(state)
    try:
        assert recovered.dispatch("external.sessions.list", {})["count"] == 1
        recovered.dispatch("external.sources.remove", {"id": source})
        assert not recovered.dispatch("external.sources.list", {})
        assert recovered.dispatch("external.sessions.list", {})["count"] == 0
        with pytest.raises(ValueError, match="no longer indexed"):
            recovered.dispatch("external.sessions.preview", {"id": row["id"]})
        assert path.is_file()
        assert not recovered.dispatch("jobs.list", {})
    finally:
        recovered.close()


def test_partial_scan_is_disclosed_and_does_not_erase_previous_index(
    desktop, tmp_path, monkeypatch
):
    service, _, root = desktop
    folder = tmp_path / "sessions"
    for index in range(3):
        session(folder / f"{index}.jsonl", root)
    source = connect(service, folder)
    monkeypatch.setattr(external, "SCAN_FILES", 1)
    report = service.dispatch("external.sources.scan", {"id": source})
    assert report["partial"] and report["files"] == 1
    assert service.dispatch("external.sessions.list", {})["count"] == 3
    assert service.dispatch("external.sources.list", {})[0]["report"]["partial"]


def test_full_scan_removes_deleted_and_unsupported_files(desktop, tmp_path):
    service, _, root = desktop
    folder = tmp_path / "sessions"
    first = folder / "one.jsonl"
    session(first, root)
    second = folder / "two.jsonl"
    session(second, root)
    source = connect(service, folder)
    first.unlink()
    second.write_text('{"type":"unrelated"}\nnot json\n')
    report = service.dispatch("external.sources.scan", {"id": source})
    assert report["ignored"] == 1
    assert service.dispatch("external.sessions.list", {})["count"] == 0


def test_context_tail_is_bounded_and_discloses_omissions(desktop, tmp_path, monkeypatch):
    service, _, root = desktop
    path = tmp_path / "sessions/one.jsonl"
    session(
        path, root, messages=[("user", f"message-{index}:" + "x" * 2000) for index in range(25)]
    )
    connect(service, path.parent)
    row = service.dispatch("external.sessions.list", {})["items"][0]
    monkeypatch.setattr(external, "TRANSCRIPT_BYTES", 30000)
    preview = service.dispatch("external.sessions.preview", {"id": row["id"]})
    assert preview["partial_file"] and preview["omitted_messages"] > 0
    assert len(preview["text"]) <= external.CONTEXT_CHARS
    assert "Earlier file content was not inspected" in preview["text"]
    assert "message-24:" in preview["text"] and "message-0:" not in preview["text"]


def test_incomplete_oversized_and_malformed_records_are_omitted(desktop, tmp_path, monkeypatch):
    service, _, root = desktop
    path = tmp_path / "sessions/one.jsonl"
    session(path, root)
    with path.open("a") as stream:
        stream.write("not-json\n" + "x" * 10000 + '\n{"type":')
    connect(service, path.parent)
    row = service.dispatch("external.sessions.list", {})["items"][0]
    monkeypatch.setattr(external, "LINE_BYTES", 4000)
    preview = service.dispatch("external.sessions.preview", {"id": row["id"]})
    assert preview["malformed_records"] == 3 and preview["included_messages"] == 2
    assert "Omitted 3" in preview["text"]


def test_replaced_session_id_requires_reindexing(desktop, tmp_path):
    service, _, root = desktop
    path = tmp_path / "sessions/one.jsonl"
    session(path, root)
    connect(service, path.parent)
    row = service.dispatch("external.sessions.list", {})["items"][0]
    session(path, root)
    with pytest.raises(ValueError, match="identity changed"):
        service.dispatch("external.sessions.preview", {"id": row["id"]})


def test_remove_during_scan_does_not_resurrect_source(desktop, tmp_path, monkeypatch):
    service, _, root = desktop
    path = tmp_path / "sessions/one.jsonl"
    session(path, root)
    source = connect(service, path.parent)
    original = external._metadata

    def remove(stream):
        service.dispatch("external.sources.remove", {"id": source})
        return original(stream)

    monkeypatch.setattr(external, "_metadata", remove)
    with pytest.raises(ValueError, match="source was removed"):
        service.dispatch("external.sources.scan", {"id": source})
    assert not service._all("SELECT * FROM external_sessions")


def test_scan_excludes_special_files_and_rejects_parallel_refresh(desktop, tmp_path):
    service, _, root = desktop
    path = tmp_path / "sessions/one.jsonl"
    session(path, root)
    os.mkfifo(path.parent / "pipe.jsonl")
    source = connect(service, path.parent)
    assert service.dispatch("external.sessions.list", {})["count"] == 1
    with service._external_scan_lock:
        with pytest.raises(ValueError, match="already refreshing"):
            service.dispatch("external.sources.scan", {"id": source})


def test_duplicate_sources_keep_independent_provenance_and_disconnect_fallback(desktop, tmp_path):
    service, _, root = desktop
    first = tmp_path / "sessions/one.jsonl"
    second = tmp_path / "archived_sessions/one.jsonl"
    identity = session(first, root, text="First copy")
    session(second, root, identity=identity, text="Second copy")
    source1 = connect(service, first.parent)
    source2 = connect(service, second.parent)
    all_rows = service.dispatch("external.sessions.list", {})
    assert all_rows["count"] == 1
    row = service.dispatch("external.sessions.list", {"source": source1})["items"][0]
    preview = service.dispatch("external.sessions.preview", {"id": row["id"], "source": source1})
    assert "First copy" in preview["text"] and "Second copy" not in preview["text"]
    service.dispatch("external.sources.remove", {"id": source2})
    assert service.dispatch("external.sessions.list", {})["count"] == 1
    assert first.is_file() and second.is_file()


def test_structurally_invalid_message_records_do_not_break_a_handoff(desktop, tmp_path):
    service, _, root = desktop
    path = tmp_path / "sessions/one.jsonl"
    session(path, root)
    with path.open("a") as stream:
        for payload in [
            {"type": "message", "role": [], "content": []},
            {"type": "message", "role": "user", "content": [{"type": [], "text": "invalid"}]},
        ]:
            stream.write(json.dumps({"type": "response_item", "payload": payload}) + "\n")
    connect(service, path.parent)
    row = service.dispatch("external.sessions.list", {})["items"][0]
    assert (
        service.dispatch("external.sessions.preview", {"id": row["id"]})["included_messages"] == 2
    )


def test_invalid_unicode_cannot_poison_native_json_frames(desktop, tmp_path):
    service, _, root = desktop
    folder = tmp_path / "sessions"
    valid = folder / "valid.jsonl"
    session(valid, root, messages=[("user", "Valid request"), ("assistant", "Invalid \ud800 text")])
    session(folder / "invalid-meta.jsonl", "/invalid/\ud800")
    connect(service, folder)
    listed = service.dispatch("external.sessions.list", {})
    assert listed["count"] == 1
    preview = service.dispatch("external.sessions.preview", {"id": listed["items"][0]["id"]})
    assert preview["included_messages"] == 1 and preview["malformed_records"] == 1
    json.dumps(preview, ensure_ascii=False).encode("utf-8")
    assert service.dispatch("external.sources.list", {})[0]["report"]["ignored"] == 1
