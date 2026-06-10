"""Tests for the codex-grammar apply_patch tool."""

import pytest

from superqode.tools.apply_patch import (
    ApplyPatchTool,
    apply_hunks,
    extract_heredoc_patch,
    parse_patch,
)
from superqode.tools.base import ToolContext
from superqode.tools.shell_tools import BashTool


def _ctx(tmp_path) -> ToolContext:
    return ToolContext(session_id="t", working_directory=tmp_path)


# ---------------------------------------------------------------- parser


def test_parse_add_update_delete_sections():
    ops = parse_patch(
        "*** Begin Patch\n"
        "*** Add File: new.txt\n"
        "+hello\n"
        "+world\n"
        "*** Update File: src/app.py\n"
        "@@ def main():\n"
        " line1\n"
        "-old\n"
        "+new\n"
        "*** Delete File: junk.txt\n"
        "*** End Patch"
    )
    assert [op.kind for op in ops] == ["add", "update", "delete"]
    assert ops[0].content_lines == ["hello", "world"]
    assert ops[1].hunks[0].locators == ["def main():"]
    assert ops[1].hunks[0].lines == [(" ", "line1"), ("-", "old"), ("+", "new")]
    assert ops[2].path == "junk.txt"


def test_parse_move_to_and_eof_marker():
    ops = parse_patch(
        "*** Begin Patch\n"
        "*** Update File: old_name.py\n"
        "*** Move to: new_name.py\n"
        " tail line\n"
        "+appended\n"
        "*** End of File\n"
        "*** End Patch"
    )
    assert ops[0].move_to == "new_name.py"
    assert ops[0].hunks[0].anchored_at_eof is True


def test_parse_strips_fences_and_prose():
    ops = parse_patch(
        "Here is the patch:\n```\n*** Begin Patch\n*** Add File: a.txt\n+x\n*** End Patch\n```"
    )
    assert ops[0].kind == "add"


def test_parse_rejects_missing_envelope_and_bad_lines():
    with pytest.raises(ValueError, match="must start"):
        parse_patch("*** Update File: a.py\n-x\n+y")
    with pytest.raises(ValueError, match="Unknown patch directive"):
        parse_patch("*** Begin Patch\n*** Bogus: a\n*** End Patch")
    with pytest.raises(ValueError, match="no change hunks"):
        parse_patch("*** Begin Patch\n*** Update File: a.py\n*** End Patch")


def test_extract_heredoc_patch():
    cmd = "apply_patch <<'EOF'\n*** Begin Patch\n*** Add File: x.txt\n+hi\n*** End Patch\nEOF"
    body = extract_heredoc_patch(cmd)
    assert body is not None and body.startswith("*** Begin Patch")
    assert extract_heredoc_patch("echo hello") is None
    assert extract_heredoc_patch("apply_patch <<'EOF'\nnot a patch\nEOF") is None


# ---------------------------------------------------------------- applier


FILE = "def add(a, b):\n    return a + b\n\nprint(add(1, 2))"


def test_apply_simple_hunk():
    ops = parse_patch(
        "*** Begin Patch\n"
        "*** Update File: f.py\n"
        " def add(a, b):\n"
        "-    return a + b\n"
        "+    return a * b\n"
        "*** End Patch"
    )
    out = apply_hunks(FILE, ops[0].hunks, "f.py")
    assert "a * b" in out and "a + b" not in out
    assert out.startswith("def add(a, b):")


def test_apply_with_locator():
    content = "class A:\n    def f(self):\n        return 1\n\nclass B:\n    def f(self):\n        return 1"
    ops = parse_patch(
        "*** Begin Patch\n"
        "*** Update File: f.py\n"
        "@@ class B:\n"
        "     def f(self):\n"
        "-        return 1\n"
        "+        return 2\n"
        "*** End Patch"
    )
    out = apply_hunks(content, ops[0].hunks, "f.py")
    # Only class B's method changed.
    assert out.count("return 1") == 1
    assert out.index("return 2") > out.index("class B")


def test_apply_fuzzy_trailing_whitespace():
    content = "line one   \nline two"
    ops = parse_patch(
        "*** Begin Patch\n*** Update File: f.txt\n-line one\n+line ONE\n*** End Patch"
    )
    out = apply_hunks(content, ops[0].hunks, "f.txt")
    assert out.splitlines()[0] == "line ONE"


def test_apply_eof_anchor_appends():
    ops = parse_patch(
        "*** Begin Patch\n*** Update File: f.txt\n+appended\n*** End of File\n*** End Patch"
    )
    out = apply_hunks("a\nb", ops[0].hunks, "f.txt")
    assert out == "a\nb\nappended"


def test_apply_context_not_found_errors():
    ops = parse_patch(
        "*** Begin Patch\n*** Update File: f.txt\n-nonexistent\n+x\n*** End Patch"
    )
    with pytest.raises(ValueError, match="Could not locate hunk context"):
        apply_hunks("real content", ops[0].hunks, "f.txt")


# ---------------------------------------------------------------- tool


@pytest.mark.asyncio
async def test_tool_add_update_delete_roundtrip(tmp_path):
    (tmp_path / "mod.py").write_text("def f():\n    return 1\n")
    (tmp_path / "junk.txt").write_text("bye")
    tool = ApplyPatchTool()
    result = await tool.execute(
        {
            "input": (
                "*** Begin Patch\n"
                "*** Add File: pkg/new.txt\n"
                "+hello\n"
                "*** Update File: mod.py\n"
                " def f():\n"
                "-    return 1\n"
                "+    return 2\n"
                "*** Delete File: junk.txt\n"
                "*** End Patch"
            )
        },
        _ctx(tmp_path),
    )
    assert result.success, result.error
    assert (tmp_path / "pkg/new.txt").read_text() == "hello\n"
    assert "return 2" in (tmp_path / "mod.py").read_text()
    assert not (tmp_path / "junk.txt").exists()
    assert "A pkg/new.txt" in result.output
    assert "M mod.py" in result.output
    assert "D junk.txt" in result.output


@pytest.mark.asyncio
async def test_tool_move_file(tmp_path):
    (tmp_path / "old.py").write_text("x = 1\n")
    result = await ApplyPatchTool().execute(
        {
            "input": (
                "*** Begin Patch\n"
                "*** Update File: old.py\n"
                "*** Move to: new.py\n"
                "-x = 1\n"
                "+x = 2\n"
                "*** End Patch"
            )
        },
        _ctx(tmp_path),
    )
    assert result.success, result.error
    assert not (tmp_path / "old.py").exists()
    assert (tmp_path / "new.py").read_text() == "x = 2\n"


@pytest.mark.asyncio
async def test_tool_atomic_failure_leaves_files_untouched(tmp_path):
    (tmp_path / "a.py").write_text("alpha\n")
    (tmp_path / "b.py").write_text("beta\n")
    result = await ApplyPatchTool().execute(
        {
            "input": (
                "*** Begin Patch\n"
                "*** Update File: a.py\n"
                "-alpha\n"
                "+ALPHA\n"
                "*** Update File: b.py\n"
                "-does not exist\n"
                "+x\n"
                "*** End Patch"
            )
        },
        _ctx(tmp_path),
    )
    assert result.success is False
    # Phase-1 validation failed on b.py, so a.py must be untouched.
    assert (tmp_path / "a.py").read_text() == "alpha\n"


@pytest.mark.asyncio
async def test_tool_rejects_path_escape(tmp_path):
    result = await ApplyPatchTool().execute(
        {"input": "*** Begin Patch\n*** Add File: ../evil.txt\n+x\n*** End Patch"},
        _ctx(tmp_path),
    )
    assert result.success is False


@pytest.mark.asyncio
async def test_tool_add_existing_file_errors(tmp_path):
    (tmp_path / "a.txt").write_text("here")
    result = await ApplyPatchTool().execute(
        {"input": "*** Begin Patch\n*** Add File: a.txt\n+x\n*** End Patch"},
        _ctx(tmp_path),
    )
    assert result.success is False
    assert "already exists" in (result.error or "")


@pytest.mark.asyncio
async def test_bash_heredoc_routes_to_apply_patch(tmp_path):
    cmd = (
        "apply_patch <<'EOF'\n"
        "*** Begin Patch\n"
        "*** Add File: from_heredoc.txt\n"
        "+via bash\n"
        "*** End Patch\n"
        "EOF"
    )
    result = await BashTool(git_guard_enabled=False).execute({"command": cmd}, _ctx(tmp_path))
    assert result.success, result.error
    assert (tmp_path / "from_heredoc.txt").read_text() == "via bash\n"
