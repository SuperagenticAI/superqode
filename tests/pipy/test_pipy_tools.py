"""The seven pi coding tools (checklist T1 to T12)."""

from __future__ import annotations

import asyncio
import json

import pytest

from superqode.pipy import AbortController, TextContent
from superqode.pipy.tools import (
    ALL_TOOL_NAMES,
    CODING_TOOL_NAMES,
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_LINES,
    GREP_MAX_LINE_LENGTH,
    EditError,
    create_all_tools,
    create_tool,
    format_size,
    truncate_head,
    truncate_line,
    truncate_tail,
)
from superqode.pipy.tools.edit_diff import apply_edits, normalize_for_fuzzy_match
from superqode.pipy.tools.files import detect_image_mime_type


async def run(tool, **args):
    return await tool.execute("call-1", args)


def text_of(result) -> str:
    return "".join(b.text for b in result.content if isinstance(b, TextContent))


# -- truncation -------------------------------------------------------------- #


def test_limits_match_pi():
    assert DEFAULT_MAX_LINES == 2000
    assert DEFAULT_MAX_BYTES == 50 * 1024
    assert GREP_MAX_LINE_LENGTH == 500


@pytest.mark.parametrize(
    ("size", "expected"),
    [(0, "0B"), (512, "512B"), (1024, "1.0KB"), (51200, "50.0KB"), (1048576, "1.0MB")],
)
def test_format_size_matches_pi(size, expected):
    assert format_size(size) == expected


def test_truncate_head_keeps_the_beginning():
    result = truncate_head("\n".join(str(i) for i in range(10)), max_lines=3)
    assert result.content == "0\n1\n2"
    assert result.truncated is True
    assert result.truncated_by == "lines"
    assert (result.total_lines, result.output_lines) == (10, 3)


def test_truncate_tail_keeps_the_end():
    result = truncate_tail("\n".join(str(i) for i in range(10)), max_lines=3)
    assert result.content == "7\n8\n9"
    assert result.truncated_by == "lines"


def test_truncate_head_never_returns_a_partial_line():
    result = truncate_head("x" * 100, max_bytes=10)
    assert result.content == ""
    assert result.first_line_exceeds_limit is True


def test_truncate_tail_keeps_the_end_of_an_oversized_line():
    result = truncate_tail("abcdefghij", max_bytes=4)
    assert result.last_line_partial is True
    assert result.content == "ghij"


def test_truncate_line():
    assert truncate_line("short") == ("short", False)
    text, cut = truncate_line("y" * 600)
    assert cut is True and len(text) == GREP_MAX_LINE_LENGTH


def test_untruncated_content_is_returned_verbatim():
    result = truncate_head("a\nb\nc")
    assert result.content == "a\nb\nc"
    assert result.truncated is False
    assert result.truncated_by is None


# -- read -------------------------------------------------------------------- #


async def test_read_returns_file_contents(tmp_path):
    (tmp_path / "a.txt").write_text("line one\nline two\n")
    tool = create_tool("read", tmp_path)

    assert text_of(await run(tool, path="a.txt")) == "line one\nline two\n"


async def test_read_offset_and_limit(tmp_path):
    (tmp_path / "a.txt").write_text("\n".join(f"line {i}" for i in range(1, 11)))
    tool = create_tool("read", tmp_path)

    result = await run(tool, path="a.txt", offset=3, limit=2)

    text = text_of(result)
    assert text.startswith("line 3\nline 4")
    assert "[6 more lines in file. Use offset=5 to continue.]" in text


async def test_read_offset_beyond_end(tmp_path):
    (tmp_path / "a.txt").write_text("only\n")
    tool = create_tool("read", tmp_path)

    with pytest.raises(ValueError, match="beyond end of file"):
        await run(tool, path="a.txt", offset=99)


async def test_read_truncates_with_a_continuation_hint(tmp_path):
    (tmp_path / "big.txt").write_text("\n".join(str(i) for i in range(5000)))
    tool = create_tool("read", tmp_path)

    text = text_of(await run(tool, path="big.txt"))

    assert f"of 5000. Use offset={DEFAULT_MAX_LINES + 1} to continue.]" in text


async def test_read_points_at_bash_for_an_oversized_line(tmp_path):
    (tmp_path / "one.txt").write_text("z" * (DEFAULT_MAX_BYTES + 10))
    tool = create_tool("read", tmp_path)

    text = text_of(await run(tool, path="one.txt"))

    assert text.startswith("[Line 1 is ")
    assert "Use bash: sed -n '1p'" in text


async def test_read_returns_an_image_as_an_attachment(tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    (tmp_path / "i.png").write_bytes(png)
    tool = create_tool("read", tmp_path)

    result = await run(tool, path="i.png")

    assert text_of(result) == "Read image file [image/png]"
    assert any(getattr(b, "type", "") == "image" for b in result.content)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"\xff\xd8\xff\x00", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"GIF89a", "image/gif"),
        (b"BM..", "image/bmp"),
        (b"RIFF0000WEBP", "image/webp"),
        (b"just text", None),
    ],
)
def test_image_sniffing(data, expected):
    assert detect_image_mime_type(data) == expected


# -- write ------------------------------------------------------------------- #


async def test_write_creates_the_file_and_parents(tmp_path):
    tool = create_tool("write", tmp_path)

    result = await run(tool, path="nested/deep/a.txt", content="hello")

    assert (tmp_path / "nested/deep/a.txt").read_text() == "hello"
    assert text_of(result) == "Successfully wrote 5 bytes to nested/deep/a.txt"


async def test_write_overwrites(tmp_path):
    (tmp_path / "a.txt").write_text("old")
    tool = create_tool("write", tmp_path)

    await run(tool, path="a.txt", content="new")

    assert (tmp_path / "a.txt").read_text() == "new"


# -- edit -------------------------------------------------------------------- #


async def test_edit_applies_one_replacement(tmp_path):
    (tmp_path / "a.py").write_text("def old():\n    pass\n")
    tool = create_tool("edit", tmp_path)

    result = await run(
        tool, path="a.py", edits=[{"oldText": "def old():", "newText": "def new():"}]
    )

    assert (tmp_path / "a.py").read_text() == "def new():\n    pass\n"
    assert text_of(result) == "Successfully applied 1 edit to a.py"


async def test_edit_applies_multiple_disjoint_replacements(tmp_path):
    (tmp_path / "a.py").write_text("alpha\nbeta\ngamma\n")
    tool = create_tool("edit", tmp_path)

    result = await run(
        tool,
        path="a.py",
        edits=[
            {"oldText": "alpha", "newText": "ALPHA"},
            {"oldText": "gamma", "newText": "GAMMA"},
        ],
    )

    assert (tmp_path / "a.py").read_text() == "ALPHA\nbeta\nGAMMA\n"
    assert text_of(result) == "Successfully applied 2 edits to a.py"


async def test_edit_matches_against_the_original_not_incrementally(tmp_path):
    (tmp_path / "a.py").write_text("one\ntwo\n")
    tool = create_tool("edit", tmp_path)

    await run(
        tool,
        path="a.py",
        edits=[{"oldText": "one", "newText": "two"}, {"oldText": "two", "newText": "three"}],
    )

    assert (tmp_path / "a.py").read_text() == "two\nthree\n"


async def test_edit_preserves_crlf(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"alpha\r\nbeta\r\n")
    tool = create_tool("edit", tmp_path)

    await run(tool, path="a.txt", edits=[{"oldText": "alpha", "newText": "ALPHA"}])

    assert (tmp_path / "a.txt").read_bytes() == b"ALPHA\r\nbeta\r\n"


async def test_edit_accepts_the_legacy_single_edit_shape(tmp_path):
    (tmp_path / "a.txt").write_text("alpha\n")
    tool = create_tool("edit", tmp_path)

    prepared = tool.prepare_arguments({"path": "a.txt", "oldText": "alpha", "newText": "beta"})
    await run(tool, **prepared)

    assert (tmp_path / "a.txt").read_text() == "beta\n"


async def test_edit_runs_sequentially():
    tool = create_tool("edit", ".")
    assert tool.execution_mode == "sequential"


@pytest.mark.parametrize(
    ("edits", "fragment"),
    [
        ([{"oldText": "missing", "newText": "x"}], "Could not find the exact text in a.py"),
        ([{"oldText": "dup", "newText": "x"}], "Found 2 occurrences of the text in a.py"),
        ([{"oldText": "", "newText": "x"}], "oldText must not be empty in a.py."),
        ([{"oldText": "keep", "newText": "keep"}], "No changes made to a.py"),
    ],
)
async def test_edit_error_strings_match_pi(tmp_path, edits, fragment):
    (tmp_path / "a.py").write_text("dup\ndup\nkeep\n")
    tool = create_tool("edit", tmp_path)

    with pytest.raises(EditError) as error:
        await run(tool, path="a.py", edits=edits)
    assert fragment in str(error.value)


async def test_edit_multi_error_strings_name_the_index(tmp_path):
    (tmp_path / "a.py").write_text("alpha\nbeta\n")
    tool = create_tool("edit", tmp_path)

    with pytest.raises(EditError) as error:
        await run(
            tool,
            path="a.py",
            edits=[
                {"oldText": "alpha", "newText": "A"},
                {"oldText": "missing", "newText": "B"},
            ],
        )
    assert "Could not find edits[1] in a.py" in str(error.value)


async def test_edit_rejects_a_missing_file(tmp_path):
    tool = create_tool("edit", tmp_path)

    with pytest.raises(EditError, match="Could not edit file"):
        await run(tool, path="nope.py", edits=[{"oldText": "a", "newText": "b"}])


async def test_edit_rejects_overlapping_edits(tmp_path):
    (tmp_path / "a.txt").write_text("abcdef\n")
    tool = create_tool("edit", tmp_path)

    with pytest.raises(EditError, match="overlap"):
        await run(
            tool,
            path="a.txt",
            edits=[{"oldText": "abcd", "newText": "X"}, {"oldText": "cdef", "newText": "Y"}],
        )


def test_fuzzy_normalisation_folds_typography():
    assert normalize_for_fuzzy_match("“quoted” — text ") == '"quoted" - text'
    assert normalize_for_fuzzy_match("it’s") == "it's"


def test_edit_matches_through_smart_quotes():
    original = "print(“hello”)\n"
    updated = apply_edits("a.py", original, [{"oldText": 'print("hello")', "newText": "pass"}])
    assert updated == "pass\n"


def test_edit_diff_details_are_produced():
    from superqode.pipy.tools.edit_diff import first_changed_line, generate_unified_patch

    patch = generate_unified_patch("a.py", "one\ntwo\n", "one\nTWO\n")
    assert "-two" in patch and "+TWO" in patch
    assert first_changed_line("one\ntwo\n", "one\nTWO\n") == 2


# -- bash -------------------------------------------------------------------- #


async def test_bash_returns_stdout(tmp_path):
    tool = create_tool("bash", tmp_path)

    assert text_of(await run(tool, command="echo hello")).strip() == "hello"


async def test_bash_merges_stderr(tmp_path):
    tool = create_tool("bash", tmp_path)

    assert "oops" in text_of(await run(tool, command="echo oops >&2"))


async def test_bash_runs_in_the_working_directory(tmp_path):
    (tmp_path / "marker.txt").write_text("x")
    tool = create_tool("bash", tmp_path)

    assert "marker.txt" in text_of(await run(tool, command="ls"))


async def test_bash_reports_no_output(tmp_path):
    tool = create_tool("bash", tmp_path)

    assert text_of(await run(tool, command="true")) == "(no output)"


async def test_bash_raises_on_a_non_zero_exit(tmp_path):
    tool = create_tool("bash", tmp_path)

    with pytest.raises(RuntimeError) as error:
        await run(tool, command="echo failing; exit 3")
    assert "Command exited with code 3" in str(error.value)
    # The output is preserved so the model can read what went wrong.
    assert "failing" in str(error.value)


async def test_bash_times_out(tmp_path):
    tool = create_tool("bash", tmp_path)

    with pytest.raises(RuntimeError, match="Command timed out after 1 seconds"):
        await run(tool, command="sleep 5", timeout=1)


async def test_bash_streams_updates(tmp_path):
    tool = create_tool("bash", tmp_path)
    updates: list[str] = []

    await tool.execute(
        "c1",
        {"command": "echo one; sleep 0.2; echo two"},
        None,
        lambda partial: updates.append(partial.text),
    )

    # The first update is the empty priming one pi sends.
    assert updates and updates[0] == ""
    assert len(updates) > 1


async def test_bash_spills_large_output_to_a_temp_file(tmp_path):
    tool = create_tool("bash", tmp_path)

    result = await run(tool, command="seq 1 5000")

    text = text_of(result)
    assert "Full output:" in text
    spill = result.details["full_output_path"]
    assert "5000" in open(spill).read()


async def test_bash_aborts(tmp_path):
    tool = create_tool("bash", tmp_path)
    controller = AbortController()

    async def cancel_soon():
        await asyncio.sleep(0.1)
        controller.abort()

    task = asyncio.ensure_future(cancel_soon())
    with pytest.raises(RuntimeError, match="Command aborted"):
        await tool.execute("c1", {"command": "sleep 5"}, controller.signal, None)
    await task


# -- grep, find, ls ---------------------------------------------------------- #


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("def alpha():\n    return 1\n")
    (tmp_path / "src/b.py").write_text("def beta():\n    return 2\n")
    (tmp_path / "notes.md").write_text("alpha is documented here\n")
    (tmp_path / ".gitignore").write_text("ignored/\n")
    (tmp_path / "ignored").mkdir()
    (tmp_path / "ignored/secret.py").write_text("def alpha(): pass\n")
    return tmp_path


async def test_grep_finds_matches(workspace):
    tool = create_tool("grep", workspace)

    text = text_of(await run(tool, pattern="def alpha"))

    assert "a.py" in text
    assert ":1:" in text


async def test_grep_reports_no_matches(workspace):
    tool = create_tool("grep", workspace)

    assert text_of(await run(tool, pattern="zzzz-not-here")) == "No matches found"


async def test_grep_respects_case_and_literal_flags(workspace):
    tool = create_tool("grep", workspace)

    assert "a.py" in text_of(await run(tool, pattern="DEF ALPHA", ignoreCase=True))
    assert text_of(await run(tool, pattern="def alpha(", literal=True)) != "No matches found"


async def test_grep_limit_notice(workspace):
    tool = create_tool("grep", workspace)

    text = text_of(await run(tool, pattern="def", limit=1))

    assert "1 matches limit reached" in text


async def test_grep_truncates_long_lines(tmp_path):
    (tmp_path / "long.txt").write_text("match " + "x" * 900 + "\n")
    tool = create_tool("grep", tmp_path)

    text = text_of(await run(tool, pattern="match"))

    assert f"Some lines truncated to {GREP_MAX_LINE_LENGTH} chars" in text


async def test_find_matches_a_glob(workspace):
    tool = create_tool("find", workspace)

    text = text_of(await run(tool, pattern="*.py"))

    assert "src/a.py" in text and "src/b.py" in text


async def test_find_reports_nothing_found(workspace):
    tool = create_tool("find", workspace)

    assert text_of(await run(tool, pattern="*.rs")) == "No files found matching pattern"


async def test_ls_lists_with_directory_suffixes(workspace):
    tool = create_tool("ls", workspace)

    rows = text_of(await run(tool)).split("\n")

    assert "src/" in rows
    assert "notes.md" in rows


async def test_ls_sorts_case_insensitively(tmp_path):
    for name in ("Zeta", "alpha", "Beta"):
        (tmp_path / name).write_text("")
    tool = create_tool("ls", tmp_path)

    assert text_of(await run(tool)).split("\n") == ["alpha", "Beta", "Zeta"]


async def test_ls_limit_notice(tmp_path):
    for index in range(5):
        (tmp_path / f"f{index}.txt").write_text("")
    tool = create_tool("ls", tmp_path)

    text = text_of(await run(tool, limit=2))

    assert "2 entries limit reached. Use limit=4 for more" in text


async def test_ls_rejects_a_file(workspace):
    tool = create_tool("ls", workspace)

    with pytest.raises(NotADirectoryError):
        await run(tool, path="notes.md")


# -- registry and schemas ---------------------------------------------------- #


def test_tool_set_names_match_pi():
    assert ALL_TOOL_NAMES == ("read", "bash", "edit", "write", "grep", "find", "ls")
    assert CODING_TOOL_NAMES == ("read", "bash", "edit", "write")


def test_unknown_tool_name():
    with pytest.raises(ValueError, match="Unknown tool name"):
        create_tool("nope", ".")


def test_every_tool_declares_a_usable_schema():
    import jsonschema

    for tool in create_all_tools("."):
        jsonschema.validators.validator_for(tool.parameters).check_schema(tool.parameters)
        assert tool.parameters["type"] == "object"
        assert tool.description
        # A tool only appears in the system prompt's tool list when it has a
        # snippet, so every shipped tool needs one.
        assert tool.prompt_snippet


def test_tool_schemas_are_json_serialisable():
    for tool in create_all_tools("."):
        json.dumps(tool.parameters)


def test_no_pipy_module_imports_superqode_policy():
    """Nothing in superqode.pipy may reach for the approval or sandbox stack.

    Checked against real imports rather than the file text, so a docstring
    explaining the policy does not trip the guard.
    """
    import ast
    import pathlib

    root = pathlib.Path(__import__("superqode.pipy", fromlist=["x"]).__file__).parent
    forbidden_roots = {
        "superqode.approval",
        "superqode.permissions",
        "superqode.sandbox",
        "superqode.tools",
        "superqode.agent",
        "textual",
    }

    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                if any(name == bad or name.startswith(f"{bad}.") for bad in forbidden_roots):
                    offenders.append(f"{path.relative_to(root)} imports {name}")

    assert offenders == []
