"""
Tests for the minimal tool system.
"""

import pytest
import tempfile
from pathlib import Path

from superqode.tools.base import ToolRegistry, ToolContext
from superqode.tools.file_tools import ReadFileTool, WriteFileTool, ListDirectoryTool
from superqode.tools.edit_tools import EditFileTool
from superqode.tools.search_tools import GlobTool


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
        assert "list_directory" in tool_names
        assert "edit_file" in tool_names
        assert "bash" in tool_names
        assert "grep" in tool_names
        assert "glob" in tool_names

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
        assert result.output == "Hello, World!"

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
        assert result.output == "line2\nline3\nline4"


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

    @pytest.mark.asyncio
    async def test_write_creates_directories(self, temp_dir, tool_context):
        """Test that write creates parent directories."""
        tool = WriteFileTool()
        result = await tool.execute(
            {"path": "subdir/nested/file.txt", "content": "Nested content"}, tool_context
        )

        assert result.success
        assert (temp_dir / "subdir/nested/file.txt").read_text() == "Nested content"


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
