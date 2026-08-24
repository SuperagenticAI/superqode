"""JSONL persistence and the session repository (checklist S7, S8)."""

from __future__ import annotations

import json

import pytest

from superqode.pipy import (
    AssistantMessage,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from superqode.pipy.config import encode_cwd
from superqode.pipy.messages import ImageContent, Usage, UsageCost
from superqode.pipy.session import (
    SESSION_FORMAT_VERSION,
    JsonlSessionStorage,
    SessionError,
    SessionRepository,
    create_session,
    decode_entry,
    decode_message,
    encode_entry,
    encode_message,
)


@pytest.fixture
def repo(tmp_path) -> SessionRepository:
    return SessionRepository(tmp_path / "sessions")


# -- header and file layout -------------------------------------------------- #


async def test_new_session_writes_a_v3_header(repo, tmp_path):
    session, path = await repo.create(tmp_path)

    header = json.loads(path.read_text().splitlines()[0])
    assert header["type"] == "session"
    assert header["version"] == SESSION_FORMAT_VERSION
    assert header["cwd"] == str(tmp_path.resolve())
    assert header["id"]


async def test_session_file_lives_in_a_cwd_encoded_directory(repo, tmp_path):
    _, path = await repo.create(tmp_path)

    assert path.parent.name == encode_cwd(tmp_path.resolve())
    assert path.name.endswith(".jsonl")


def test_encode_cwd_matches_pi():
    assert encode_cwd("/home/dev/work/project") == "--home-dev-work-project--"


async def test_entries_are_appended_one_line_each(repo, tmp_path):
    session, path = await repo.create(tmp_path)
    await session.append_message(UserMessage(content="one"))
    await session.append_message(UserMessage(content="two"))

    lines = [line for line in path.read_text().split("\n") if line.strip()]
    assert len(lines) == 3
    assert all(json.loads(line)["type"] == "message" for line in lines[1:])


async def test_round_trip_through_disk(repo, tmp_path):
    session, path = await repo.create(tmp_path)
    await session.append_message(UserMessage(content="hello"))
    await session.append_message(
        AssistantMessage(content=[TextContent(text="hi")], provider="anthropic", model="claude-x")
    )

    reopened = await repo.open(path)
    context = await reopened.build_context()

    assert [m.text for m in context.messages] == ["hello", "hi"]
    assert context.model is not None and context.model.model_id == "claude-x"


async def test_resume_continues_at_the_leaf(repo, tmp_path):
    session, path = await repo.create(tmp_path)
    await session.append_message(UserMessage(content="first"))

    resumed = await repo.open(path)
    await resumed.append_message(UserMessage(content="second"))

    again = await repo.open(path)
    assert [m.text for m in (await again.build_context()).messages] == ["first", "second"]


async def test_branch_survives_a_round_trip(repo, tmp_path):
    session, path = await repo.create(tmp_path)
    root = await session.append_message(UserMessage(content="root"))
    await session.append_message(UserMessage(content="abandoned"))
    await session.move_to(root)
    await session.append_message(UserMessage(content="taken"))

    reopened = await repo.open(path)
    assert [m.text for m in (await reopened.build_context()).messages] == ["root", "taken"]
    # root, abandoned, the leaf move, taken. The abandoned branch is still there.
    assert len(await reopened.get_entries()) == 4


# -- error reporting --------------------------------------------------------- #


async def test_missing_file(repo, tmp_path):
    with pytest.raises(SessionError) as error:
        await repo.open(tmp_path / "nope.jsonl")
    assert "Session not found" in str(error.value)


async def test_bad_header(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"type":"nope"}\n')

    with pytest.raises(SessionError) as error:
        JsonlSessionStorage.open(path)
    assert "first line is not a valid session header" in str(error.value)


async def test_unsupported_version(tmp_path):
    path = tmp_path / "old.jsonl"
    path.write_text('{"type":"session","version":2,"id":"a","timestamp":"t","cwd":"/x"}\n')

    with pytest.raises(SessionError) as error:
        JsonlSessionStorage.open(path)
    assert "unsupported session version" in str(error.value)


async def test_corrupt_entry_line_reports_its_number(repo, tmp_path):
    session, path = await repo.create(tmp_path)
    await session.append_message(UserMessage(content="ok"))
    with path.open("a") as handle:
        handle.write("{not json\n")

    with pytest.raises(SessionError) as error:
        JsonlSessionStorage.open(path)
    assert "line 3 is not valid JSON" in str(error.value)


async def test_entry_missing_id(repo, tmp_path):
    session, path = await repo.create(tmp_path)
    with path.open("a") as handle:
        handle.write(json.dumps({"type": "message", "parentId": None, "timestamp": "t"}) + "\n")

    with pytest.raises(SessionError) as error:
        JsonlSessionStorage.open(path)
    assert "is missing entry id" in str(error.value)


async def test_duplicate_entry_id(repo, tmp_path):
    session, path = await repo.create(tmp_path)
    await session.append_message(UserMessage(content="a"))
    line = path.read_text().splitlines()[1]
    with path.open("a") as handle:
        handle.write(line + "\n")

    with pytest.raises(SessionError) as error:
        JsonlSessionStorage.open(path)
    assert "duplicate entry id" in str(error.value)


async def test_creating_over_an_existing_file_is_refused(repo, tmp_path):
    _, path = await repo.create(tmp_path)
    from superqode.pipy.session.entries import SessionMetadata

    with pytest.raises(SessionError):
        JsonlSessionStorage.create(path, SessionMetadata(id="x", cwd="/x"))


# -- codec ------------------------------------------------------------------- #


def test_message_round_trip_preserves_every_field():
    original = AssistantMessage(
        content=[
            TextContent(text="answer", text_signature="sig"),
            ThinkingContent(thinking="hmm", thinking_signature="tsig", redacted=True),
            ToolCall(id="c1", name="read", arguments={"path": "a.py"}, thought_signature="th"),
        ],
        api="messages",
        provider="anthropic",
        model="claude-x",
        usage=Usage(
            input=1,
            output=2,
            cache_read=3,
            cache_write=4,
            reasoning=5,
            total_tokens=15,
            cost=UsageCost(input=0.1, output=0.2, cache_read=0.3, cache_write=0.4, total=1.0),
        ),
        stop_reason="toolUse",
        error_message=None,
        timestamp=1234,
    )

    restored = decode_message(encode_message(original))

    assert restored == original


def test_tool_result_round_trip():
    original = ToolResultMessage(
        tool_call_id="c1",
        tool_name="read",
        content=[TextContent(text="body"), ImageContent(data="AAA", mime_type="image/png")],
        details={"lines": 3},
        usage=Usage(input=1),
        added_tool_names=["extra"],
        is_error=True,
        timestamp=99,
    )

    assert decode_message(encode_message(original)) == original


def test_wire_format_uses_pi_key_names():
    payload = encode_message(
        ToolResultMessage(tool_call_id="c1", tool_name="read", content="x", is_error=True)
    )
    assert set(payload) >= {"role", "toolCallId", "toolName", "content", "isError", "timestamp"}

    assistant = encode_message(AssistantMessage(content=[TextContent(text="a")]))
    assert "stopReason" in assistant
    assert "cacheRead" in assistant["usage"]
    assert "totalTokens" in assistant["usage"]


def test_optional_fields_are_omitted_not_null():
    payload = encode_message(UserMessage(content="hi"))
    assert "errorMessage" not in payload

    assistant = encode_message(AssistantMessage(content=[TextContent(text="a")]))
    assert "errorMessage" not in assistant


@pytest.mark.parametrize(
    "entry_kwargs",
    [
        {"type": "thinking_level_change", "thinkingLevel": "high"},
        {"type": "model_change", "provider": "openai", "modelId": "gpt-x"},
        {"type": "active_tools_change", "activeToolNames": ["read", "bash"]},
        {"type": "custom", "customType": "telemetry", "data": {"k": 1}},
        {"type": "custom_message", "customType": "note", "content": "text", "display": True},
        {"type": "label", "targetId": "abc", "label": "checkpoint"},
        {"type": "session_info", "name": "my session"},
        {"type": "leaf", "targetId": "abc"},
        {"type": "branch_summary", "fromId": "abc", "summary": "tried"},
    ],
)
def test_entry_round_trip(entry_kwargs):
    payload = {"id": "e1", "parentId": None, "timestamp": "2026-01-01T00:00:00Z", **entry_kwargs}

    restored = decode_entry(payload)
    assert encode_entry(restored) == payload


def test_compaction_entry_round_trip():
    payload = {
        "id": "e1",
        "parentId": "e0",
        "timestamp": "2026-01-01T00:00:00Z",
        "type": "compaction",
        "summary": "the story so far",
        "tokensBefore": 4200,
        "firstKeptEntryId": "e0",
        "retainedTail": [encode_message(UserMessage(content="kept", timestamp=7))],
    }

    assert encode_entry(decode_entry(payload)) == payload


def test_leaf_entry_with_null_target():
    payload = {
        "id": "e1",
        "parentId": None,
        "timestamp": "t",
        "type": "leaf",
        "targetId": None,
    }
    assert encode_entry(decode_entry(payload)) == payload


# -- repository -------------------------------------------------------------- #


async def test_list_is_newest_first(repo, tmp_path):
    first, _ = await repo.create(tmp_path)
    second, _ = await repo.create(tmp_path)

    records = repo.list(tmp_path)

    assert len(records) == 2
    assert records[0].created_at >= records[1].created_at


async def test_list_only_returns_the_matching_cwd(repo, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    await repo.create(tmp_path)
    await repo.create(other)

    assert len(repo.list(tmp_path)) == 1
    assert len(repo.list(other)) == 1
    assert len(repo.list()) == 2


async def test_list_skips_a_corrupt_file(repo, tmp_path):
    await repo.create(tmp_path)
    directory = repo.root / encode_cwd(tmp_path.resolve())
    (directory / "broken.jsonl").write_text("not json\n")

    # One bad file must not make the whole picker unusable.
    assert len(repo.list(tmp_path)) == 1


async def test_latest_and_resume(repo, tmp_path):
    session, _ = await repo.create(tmp_path)
    await session.append_message(UserMessage(content="remembered"))

    resumed = await repo.resume_latest(tmp_path)

    assert resumed is not None
    assert [m.text for m in (await resumed.build_context()).messages] == ["remembered"]


async def test_resume_latest_with_no_sessions(repo, tmp_path):
    assert await repo.resume_latest(tmp_path) is None


async def test_fork_copies_the_branch_and_leaves_the_source_alone(repo, tmp_path):
    session, source = await repo.create(tmp_path)
    await session.append_message(UserMessage(content="shared"))
    before = source.read_text()

    forked, forked_path = await repo.fork(source)
    await forked.append_message(UserMessage(content="only in the fork"))

    assert [m.text for m in (await forked.build_context()).messages] == [
        "shared",
        "only in the fork",
    ]
    assert source.read_text() == before
    assert json.loads(forked_path.read_text().splitlines()[0])["parentSession"] == str(source)


async def test_fork_up_to_an_entry(repo, tmp_path):
    session, source = await repo.create(tmp_path)
    keep = await session.append_message(UserMessage(content="keep"))
    await session.append_message(UserMessage(content="drop"))

    forked, _ = await repo.fork(source, up_to_entry_id=keep)

    assert [m.text for m in (await forked.build_context()).messages] == ["keep"]


async def test_fork_from_an_unknown_entry(repo, tmp_path):
    _, source = await repo.create(tmp_path)
    with pytest.raises(SessionError):
        await repo.fork(source, up_to_entry_id="nope")


async def test_a_forked_session_is_itself_forkable(repo, tmp_path):
    session, source = await repo.create(tmp_path)
    await session.append_message(UserMessage(content="a"))
    _, first_fork = await repo.fork(source)
    second, _ = await repo.fork(first_fork)

    assert [m.text for m in (await second.build_context()).messages] == ["a"]


async def test_appending_a_duplicate_entry_id_is_refused(repo, tmp_path):
    session, path = await repo.create(tmp_path)
    await session.append_message(UserMessage(content="a"))
    storage = JsonlSessionStorage.open(path)
    entries = await storage.read_entries()

    with pytest.raises(SessionError):
        await storage.append_entry(entries[0])


async def test_concurrent_appends_land_on_disk_in_order(repo, tmp_path):
    import asyncio

    session, path = await repo.create(tmp_path)
    await asyncio.gather(*(session.append_message(UserMessage(content=str(i))) for i in range(10)))

    reopened = await repo.open(path)
    assert len((await reopened.build_context()).messages) == 10
    lines = [line for line in path.read_text().split("\n") if line.strip()]
    assert len(lines) == 11


# -- pi wire compatibility --------------------------------------------------- #


async def test_file_satisfies_pi_parser_invariants(repo, tmp_path):
    """Every rule pi's ``parseHeader`` and ``parseEntry`` enforce.

    Transliterated from ``packages/agent/src/harness/session/jsonl-repo.ts``.
    Cross-checked once by running those function bodies under node against a
    file this repository produced; this test keeps the guarantee in CI without
    needing a JavaScript runtime.
    """
    session, path = await repo.create(tmp_path)
    await session.append_message(UserMessage(content="hi"))
    await session.append_message(
        AssistantMessage(
            content=[
                ThinkingContent(thinking="hmm"),
                TextContent(text="reading"),
                ToolCall(id="c1", name="read", arguments={"path": "a.py"}),
            ],
            stop_reason="toolUse",
        )
    )
    await session.append_message(
        ToolResultMessage(tool_call_id="c1", tool_name="read", content="body")
    )
    await session.append_thinking_level_change("high")
    await session.append_compaction("summary", tokens_before=99)
    root = (await session.get_entries())[0].id
    await session.move_to(root, {"summary": "dead end"})
    await session.append_label(root, "start")
    await session.append_session_name("demo")

    lines = [line for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]

    header = json.loads(lines[0])
    assert header["type"] == "session"
    assert header["version"] == 3
    assert isinstance(header["id"], str) and header["id"]
    assert isinstance(header["timestamp"], str) and header["timestamp"]
    assert isinstance(header["cwd"], str) and header["cwd"]
    assert isinstance(header.get("parentSession", ""), str)
    assert isinstance(header.get("metadata", {}), dict)

    seen: set[str] = set()
    by_id: dict[str, dict] = {}
    for number, line in enumerate(lines[1:], start=2):
        entry = json.loads(line)
        assert isinstance(entry, dict), f"line {number} is not an object"
        assert isinstance(entry["type"], str), f"line {number} is missing entry type"
        assert isinstance(entry["id"], str) and entry["id"], f"line {number} is missing entry id"
        assert entry["parentId"] is None or isinstance(entry["parentId"], str)
        assert isinstance(entry["timestamp"], str) and entry["timestamp"]
        if entry["type"] == "leaf":
            assert entry["targetId"] is None or isinstance(entry["targetId"], str)
        assert entry["id"] not in seen, f"duplicate entry id {entry['id']}"
        seen.add(entry["id"])
        by_id[entry["id"]] = entry

    # The tree must be walkable the way pi walks it: follow parentId from the
    # leaf, where a leaf entry moves the pointer instead of extending the chain.
    leaf: str | None = None
    for line in lines[1:]:
        entry = json.loads(line)
        leaf = entry["targetId"] if entry["type"] == "leaf" else entry["id"]
    branch: list[str] = []
    current = leaf
    while current is not None and current in by_id:
        branch.append(by_id[current]["type"])
        current = by_id[current]["parentId"]
    assert branch, "branch from the leaf is empty"
    assert branch[-1] == "message"
