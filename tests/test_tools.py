"""
Tests for the minimal tool system.
"""

import pytest
import tempfile
from pathlib import Path

from superqode.tools.base import ToolRegistry, ToolContext
from superqode.tools.file_tools import (
    ReadFileTool,
    WriteFileTool,
    CreateFileTool,
    ListDirectoryTool,
)
from superqode.tools.edit_tools import EditFileTool, InsertTextTool, MultiEditTool, PatchTool
from superqode.tools.search_tools import GlobTool, LocalCodeSearchTool, RepoSearchTool
from superqode.tools.shell_tools import BashTool


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def tool_context(temp_dir):
    """Create a tool context for tests."""
    return ToolContext(
        session_id="test-session",
        working_directory=temp_dir,
    )


class TestToolRegistry:
    """Test the tool registry."""

    def test_default_registry(self):
        """Test that default registry has all expected tools."""
        registry = ToolRegistry.default()
        tools = registry.list()

        tool_names = [t.name for t in tools]

        assert "read_file" in tool_names
        assert "write_file" in tool_names
        assert "create_file" in tool_names
        assert "list_directory" in tool_names
        assert "edit_file" in tool_names
        assert "bash" in tool_names
        assert "grep" in tool_names
        assert "glob" in tool_names
        assert "local_code_search" in tool_names

    def test_openai_format(self):
        """Test conversion to OpenAI format."""
        registry = ToolRegistry.default()
        tools = registry.to_openai_format()

        assert len(tools) > 0

        for tool in tools:
            assert tool["type"] == "function"
            assert "function" in tool
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]

    def test_coding_profile_is_lean_and_local_first(self):
        """Coding profile keeps routine agent turns focused and smaller than full."""
        coding = ToolRegistry.coding()
        full = ToolRegistry.full()

        coding_names = {tool.name for tool in coding.list()}

        assert "read_file" in coding_names
        assert "create_file" in coding_names
        assert "patch" in coding_names
        assert "ask_user" in coding_names
        assert "web_fetch" in coding_names
        assert "web_search" in coding_names
        assert "agent" not in coding_names
        assert "lsp" not in coding_names
        assert len(coding.to_openai_format()) < len(full.to_openai_format())

    def test_tool_profile_selector_defaults_to_coding(self):
        registry = ToolRegistry.for_profile("")

        names = {tool.name for tool in registry.list()}

        assert "patch" in names
        assert "web_fetch" in names

    def test_ds4_profile_is_smaller_and_avoids_parallel_meta_tools(self):
        registry = ToolRegistry.for_profile("ds4")
        names = {tool.name for tool in registry.list()}

        assert "read_file" in names
        assert "create_file" in names
        assert "patch" in names
        assert "bash" in names
        assert "repo_search" in names
        assert "local_code_search" in names
        # Local models lean on local search in place of web access.
        assert "code_search" in names
        assert "web_search" not in names
        assert "ask_user" in names
        assert "batch" not in names
        assert "multi_edit" not in names
        assert "compact" not in names
        assert len(registry.to_openai_format()) < len(ToolRegistry.coding().to_openai_format())

    def test_no_tool_profile_is_empty(self):
        registry = ToolRegistry.for_profile("no-tool")

        assert registry.list() == []
        assert registry.to_openai_format() == []


@pytest.mark.asyncio
async def test_bash_timeout_result_includes_failure_metadata(tool_context):
    result = await BashTool().execute(
        {"command": "python3 -c 'import time; time.sleep(2)'", "timeout": 0.01},
        tool_context,
    )

    assert result.success is False
    assert result.metadata["timed_out"] is True
    assert result.metadata["timeout"] == 0.01
    assert "python3" in result.metadata["command"]


class TestReadFileTool:
    """Test the read file tool."""

    @pytest.mark.asyncio
    async def test_read_existing_file(self, temp_dir, tool_context):
        """Test reading an existing file."""
        # Create a test file
        test_file = temp_dir / "test.txt"
        test_file.write_text("Hello, World!")

        tool = ReadFileTool()
        result = await tool.execute({"path": "test.txt"}, tool_context)

        assert result.success
        # Output is line-numbered ('N: content') for unambiguous follow-ups.
        assert result.output == "1: Hello, World!"

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, temp_dir, tool_context):
        """Test reading a file that doesn't exist."""
        tool = ReadFileTool()
        result = await tool.execute({"path": "nonexistent.txt"}, tool_context)

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_with_line_range(self, temp_dir, tool_context):
        """Test reading specific lines."""
        test_file = temp_dir / "lines.txt"
        test_file.write_text("line1\nline2\nline3\nline4\nline5")

        tool = ReadFileTool()
        result = await tool.execute(
            {"path": "lines.txt", "start_line": 2, "end_line": 4}, tool_context
        )

        assert result.success
        # Numbered range, plus a continuation note since the file has more lines.
        assert result.output.splitlines()[:3] == ["2: line2", "3: line3", "4: line4"]
        assert "start_line=5" in result.output


class TestWriteFileTool:
    """Test the write file tool."""

    @pytest.mark.asyncio
    async def test_write_new_file(self, temp_dir, tool_context):
        """Test writing a new file."""
        tool = WriteFileTool()
        result = await tool.execute(
            {"path": "new_file.txt", "content": "New content"}, tool_context
        )

        assert result.success
        assert (temp_dir / "new_file.txt").read_text() == "New content"
        assert result.metadata["additions"] == 1
        assert result.metadata["deletions"] == 0
        assert "+++ b/new_file.txt" in result.metadata["diff_text"]
        assert "+New content" in result.metadata["diff_text"]

    @pytest.mark.asyncio
    async def test_write_creates_directories(self, temp_dir, tool_context):
        """Test that write creates parent directories."""
        tool = WriteFileTool()
        result = await tool.execute(
            {"path": "subdir/nested/file.txt", "content": "Nested content"}, tool_context
        )

        assert result.success
        assert (temp_dir / "subdir/nested/file.txt").read_text() == "Nested content"


class TestCreateFileTool:
    """Test the create file tool."""

    @pytest.mark.asyncio
    async def test_create_new_file(self, temp_dir, tool_context):
        """Test creating a new file without overwriting anything."""
        tool = CreateFileTool()
        result = await tool.execute({"path": "new.txt", "content": "created"}, tool_context)

        assert result.success
        assert (temp_dir / "new.txt").read_text() == "created"
        assert result.metadata["additions"] == 1
        assert result.metadata["deletions"] == 0
        assert "+created" in result.metadata["diff_text"]

    @pytest.mark.asyncio
    async def test_create_existing_file_fails(self, temp_dir, tool_context):
        """Test create_file refuses to overwrite existing content."""
        (temp_dir / "exists.txt").write_text("old")

        tool = CreateFileTool()
        result = await tool.execute({"path": "exists.txt", "content": "new"}, tool_context)

        assert not result.success
        assert "already exists" in (result.error or "")


class TestEditFileTool:
    """Test the edit file tool."""

    @pytest.mark.asyncio
    async def test_edit_simple_replacement(self, temp_dir, tool_context):
        """Test simple text replacement."""
        test_file = temp_dir / "edit_test.txt"
        test_file.write_text("Hello, World!")

        tool = EditFileTool()
        result = await tool.execute(
            {"path": "edit_test.txt", "old_text": "World", "new_text": "Universe"}, tool_context
        )

        assert result.success
        assert test_file.read_text() == "Hello, Universe!"
        assert result.metadata["additions"] == 1
        assert result.metadata["deletions"] == 1
        assert "-Hello, World!" in result.metadata["diff_text"]
        assert "+Hello, Universe!" in result.metadata["diff_text"]

    @pytest.mark.asyncio
    async def test_edit_text_not_found(self, temp_dir, tool_context):
        """Test editing when text is not found."""
        test_file = temp_dir / "edit_test.txt"
        test_file.write_text("Hello, World!")

        tool = EditFileTool()
        result = await tool.execute(
            {"path": "edit_test.txt", "old_text": "Goodbye", "new_text": "Hi"}, tool_context
        )

        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_edit_multiple_occurrences_error(self, temp_dir, tool_context):
        """Test that multiple occurrences without replace_all fails."""
        test_file = temp_dir / "edit_test.txt"
        test_file.write_text("foo bar foo baz foo")

        tool = EditFileTool()
        result = await tool.execute(
            {"path": "edit_test.txt", "old_text": "foo", "new_text": "qux"}, tool_context
        )

        assert not result.success
        assert "3 occurrences" in result.error

    @pytest.mark.asyncio
    async def test_edit_replace_all(self, temp_dir, tool_context):
        """Test replace_all option."""
        test_file = temp_dir / "edit_test.txt"
        test_file.write_text("foo bar foo baz foo")

        tool = EditFileTool()
        result = await tool.execute(
            {"path": "edit_test.txt", "old_text": "foo", "new_text": "qux", "replace_all": True},
            tool_context,
        )

        assert result.success
        assert test_file.read_text() == "qux bar qux baz qux"

    @pytest.mark.asyncio
    async def test_insert_returns_diff_metadata(self, temp_dir, tool_context):
        """Test insert_text returns unified diff metadata."""
        test_file = temp_dir / "insert_test.txt"
        test_file.write_text("one\nthree")

        tool = InsertTextTool()
        result = await tool.execute(
            {"path": "insert_test.txt", "line": 2, "text": "two"}, tool_context
        )

        assert result.success
        assert test_file.read_text() == "one\ntwo\nthree"
        assert result.metadata["additions"] == 1
        assert "+two" in result.metadata["diff_text"]

    @pytest.mark.asyncio
    async def test_multi_edit_returns_diff_metadata(self, temp_dir, tool_context):
        """Test multi_edit returns unified diff metadata."""
        test_file = temp_dir / "multi_test.txt"
        test_file.write_text("alpha\nbeta\ngamma")

        tool = MultiEditTool()
        result = await tool.execute(
            {
                "path": "multi_test.txt",
                "edits": [
                    {"old_text": "alpha", "new_text": "ALPHA"},
                    {"old_text": "gamma", "new_text": "GAMMA"},
                ],
            },
            tool_context,
        )

        assert result.success
        assert test_file.read_text() == "ALPHA\nbeta\nGAMMA"
        assert result.metadata["additions"] == 2
        assert result.metadata["deletions"] == 2
        assert "+ALPHA" in result.metadata["diff_text"]
        assert "-gamma" in result.metadata["diff_text"]

    @pytest.mark.asyncio
    async def test_patch_returns_file_diff_metadata(self, temp_dir, tool_context):
        """Test patch returns per-file unified diff metadata."""
        test_file = temp_dir / "patch_test.txt"
        test_file.write_text("one\ntwo\nthree")

        tool = PatchTool()
        result = await tool.execute(
            {
                "patch": "\n".join(
                    [
                        "--- a/patch_test.txt",
                        "+++ b/patch_test.txt",
                        "@@ -1,3 +1,3 @@",
                        " one",
                        "-two",
                        "+TWO",
                        " three",
                    ]
                )
            },
            tool_context,
        )

        assert result.success
        assert test_file.read_text() == "one\nTWO\nthree"
        file_diff = result.metadata["file_diffs"]["patch_test.txt"]
        assert file_diff["additions"] == 1
        assert file_diff["deletions"] == 1
        assert "+TWO" in file_diff["diff_text"]


class TestGlobTool:
    """Test the glob tool."""

    @pytest.mark.asyncio
    async def test_glob_find_files(self, temp_dir, tool_context):
        """Test finding files with glob pattern."""
        # Create test files
        (temp_dir / "file1.py").write_text("")
        (temp_dir / "file2.py").write_text("")
        (temp_dir / "file3.txt").write_text("")

        tool = GlobTool()
        result = await tool.execute({"pattern": "*.py"}, tool_context)

        assert result.success
        assert "file1.py" in result.output
        assert "file2.py" in result.output
        assert "file3.txt" not in result.output


class TestRepoSearchTool:
    """Test the high-level repository search tool."""

    @pytest.mark.asyncio
    async def test_repo_search_returns_files_content_and_symbols(self, temp_dir, tool_context):
        """Test combined file/content/symbol search."""
        src = temp_dir / "src"
        src.mkdir()
        (src / "provider_manager.py").write_text(
            "class ProviderManager:\n    def list_models(self):\n        return ['model']\n",
            encoding="utf-8",
        )

        tool = RepoSearchTool()
        result = await tool.execute({"query": "ProviderManager"}, tool_context)

        assert result.success
        assert "Files:" in result.output
        assert "Content:" in result.output
        assert "Symbols:" in result.output
        assert "src/provider_manager.py" in result.output


@pytest.mark.asyncio
class TestLocalCodeSearchTool:
    """Test the offline local code-search broker."""

    async def test_local_code_search_returns_files_content_and_symbols(self, temp_dir, tool_context):
        src = temp_dir / "src"
        src.mkdir()
        (src / "provider_manager.py").write_text(
            "class ProviderManager:\n    def list_models(self):\n        return ['model']\n",
            encoding="utf-8",
        )

        result = await LocalCodeSearchTool().execute({"query": "ProviderManager"}, tool_context)

        assert result.success
        assert "Local code search results" in result.output
        assert "Files:" in result.output
        assert "Content:" in result.output
        assert "Symbols:" in result.output
        assert "src/provider_manager.py" in result.output
        assert result.metadata["backend"] in {"ripgrep+regex-symbols", "python-fallback"}

    async def test_local_code_search_mode_filters(self, temp_dir, tool_context):
        (temp_dir / "alpha.py").write_text("def alpha_symbol():\n    return 1\n", encoding="utf-8")

        result = await LocalCodeSearchTool().execute(
            {"query": "alpha_symbol", "mode": "symbol"},
            tool_context,
        )

        assert result.success
        assert "Symbols:" in result.output
        assert "Content:" not in result.output


class TestListDirectoryTool:
    """Test the list directory tool."""

    @pytest.mark.asyncio
    async def test_list_directory(self, temp_dir, tool_context):
        """Test listing directory contents."""
        # Create test files and dirs
        (temp_dir / "file.txt").write_text("")
        (temp_dir / "subdir").mkdir()

        tool = ListDirectoryTool()
        result = await tool.execute({"path": "."}, tool_context)

        assert result.success
        assert "file.txt" in result.output
        assert "subdir" in result.output
