"""
Tests for SuperQode Ephemeral Workspace.

Tests the immutable repo guarantee:
- Changes are tracked and reverted
- Git operations are blocked
- Artifacts are preserved
"""

import pytest
from pathlib import Path
import tempfile
import shutil

from superqode.workspace import (
    WorkspaceManager,
    WorkspaceState,
    ArtifactManager,
    ArtifactType,
    GitGuard,
    GitOperationBlocked,
    SnapshotManager,
)
from superqode.workspace.manager import QESessionConfig, QEMode


class TestSnapshotManager:
    """Tests for SnapshotManager."""

    def test_start_session(self, tmp_path):
        """Test starting a session."""
        snapshot = SnapshotManager(tmp_path)
        session_id = snapshot.start_session()

        assert session_id is not None
        assert session_id.startswith("qe-")

    def test_capture_existing_file(self, tmp_path):
        """Test capturing an existing file."""
        # Create a file
        test_file = tmp_path / "test.txt"
        test_file.write_text("original content")

        snapshot = SnapshotManager(tmp_path)
        snapshot.start_session()

        file_snapshot = snapshot.capture_file(Path("test.txt"))

        assert file_snapshot.existed
        assert file_snapshot.original_content == b"original content"

    def test_capture_new_file(self, tmp_path):
        """Test capturing a non-existent file (will be created)."""
        snapshot = SnapshotManager(tmp_path)
        snapshot.start_session()

        file_snapshot = snapshot.capture_file(Path("new_file.txt"))

        assert not file_snapshot.existed
        assert file_snapshot.original_content is None

    def test_revert_modified_file(self, tmp_path):
        """Test reverting a modified file."""
        # Create original file
        test_file = tmp_path / "test.txt"
        test_file.write_text("original content")

        snapshot = SnapshotManager(tmp_path)
        snapshot.start_session()

        # Capture and modify
        snapshot.capture_file(Path("test.txt"))
        test_file.write_text("modified content")
        snapshot.record_modification(Path("test.txt"))

        # Revert
        result = snapshot.revert_all()

        # Verify restored
        assert test_file.read_text() == "original content"
        assert "test.txt" in result["files_restored"]

    def test_revert_created_file(self, tmp_path):
        """Test reverting a created file (should delete it)."""
        snapshot = SnapshotManager(tmp_path)
        snapshot.start_session()

        # Capture non-existent, then create
        snapshot.capture_file(Path("new_file.txt"))
        new_file = tmp_path / "new_file.txt"
        new_file.write_text("new content")
        snapshot.record_modification(Path("new_file.txt"))

        # Revert
        result = snapshot.revert_all()

        # File should be deleted
        assert not new_file.exists()
        assert "new_file.txt" in result["files_deleted"]

    def test_end_session_with_revert(self, tmp_path):
        """Test ending session with revert."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("original")

        snapshot = SnapshotManager(tmp_path)
        snapshot.start_session()
        snapshot.capture_file(Path("test.txt"))
        test_file.write_text("modified")

        result = snapshot.end_session(revert=True)

        assert test_file.read_text() == "original"
        assert "revert_result" in result


class TestGitGuard:
    """Tests for GitGuard."""

    def test_safe_commands_allowed(self):
        """Test that safe git commands are allowed."""
        guard = GitGuard()

        safe_commands = [
            "git status",
            "git log --oneline",
            "git diff HEAD",
            "git show abc123",
            "git branch -l",
            "git branch --list",
            "git remote -v",
        ]

        for cmd in safe_commands:
            assert not guard.is_blocked(cmd), f"Should allow: {cmd}"

    def test_write_commands_blocked(self):
        """Test that write git commands are blocked."""
        guard = GitGuard()

        blocked_commands = [
            "git commit -m 'test'",
            "git push origin main",
            "git merge feature",
            "git rebase main",
            "git checkout -b new-branch",
            "git reset --hard HEAD",
            "git add .",
        ]

        for cmd in blocked_commands:
            assert guard.is_blocked(cmd), f"Should block: {cmd}"

    def test_check_command_raises(self):
        """Test that check_command raises on blocked commands."""
        guard = GitGuard()

        with pytest.raises(GitOperationBlocked) as exc_info:
            guard.check_command("git commit -m 'test'")

        assert "commit" in str(exc_info.value).lower()

    def test_disabled_guard_allows_all(self):
        """Test that disabled guard allows all commands."""
        guard = GitGuard(enabled=False)

        assert not guard.is_blocked("git commit -m 'test'")
        assert not guard.is_blocked("git push origin main")

    def test_non_git_commands_allowed(self):
        """Test that non-git commands are allowed."""
        guard = GitGuard()

        assert not guard.is_blocked("ls -la")
        assert not guard.is_blocked("cat file.txt")
        assert not guard.is_blocked("python script.py")


class TestArtifactManager:
    """Tests for ArtifactManager."""

    def test_save_patch(self, tmp_path):
        """Test saving a patch artifact."""
        manager = ArtifactManager(tmp_path)
        manager.initialize("test-session")

        artifact = manager.save_patch(
            original_file="src/main.py",
            original_content="def main():\n    pass\n",
            modified_content="def main():\n    print('hello')\n",
            description="Fix main function",
        )

        assert artifact.id.startswith("patch-")
        assert artifact.type == ArtifactType.PATCH
        assert artifact.original_file == "src/main.py"

        # Verify file exists
        patch_path = tmp_path / ".superqode" / "qe-artifacts" / "patches" / artifact.name
        assert patch_path.exists()

        # Verify it's a valid unified diff
        content = patch_path.read_text()
        assert "---" in content
        assert "+++" in content

    def test_save_generated_test(self, tmp_path):
        """Test saving a generated test."""
        manager = ArtifactManager(tmp_path)
        manager.initialize("test-session")

        artifact = manager.save_generated_test(
            test_type=ArtifactType.TEST_UNIT,
            filename="test_main.py",
            content="def test_main():\n    assert True\n",
            description="Test for main function",
            target_file="src/main.py",
        )

        assert artifact.id.startswith("test-unit-")
        assert artifact.type == ArtifactType.TEST_UNIT

        # Verify file exists
        test_path = (
            tmp_path / ".superqode" / "qe-artifacts" / "generated-tests" / "unit" / "test_main.py"
        )
        assert test_path.exists()

    def test_save_qir(self, tmp_path):
        """Test saving a QR."""
        manager = ArtifactManager(tmp_path)
        manager.initialize("test-session")

        artifact = manager.save_qir(
            content="# QR\n\nTest report",
            session_id="test-session",
            metadata={"findings": 0},
        )

        assert artifact.id.startswith("qr-")
        assert artifact.type == ArtifactType.QR

        # Verify both MD and JSON exist
        qr_dir = tmp_path / ".superqode" / "qe-artifacts" / "qr"
        md_files = list(qr_dir.glob("*.md"))
        json_files = list(qr_dir.glob("*.json"))

        assert len(md_files) == 1
        assert len(json_files) == 1

    def test_manifest_persistence(self, tmp_path):
        """Test that manifest persists artifacts."""
        manager = ArtifactManager(tmp_path)
        manager.initialize("test-session")

        manager.save_generated_test(
            test_type=ArtifactType.TEST_UNIT,
            filename="test1.py",
            content="# test1",
        )

        # Create new manager (simulates restart)
        manager2 = ArtifactManager(tmp_path)
        manager2.initialize("test-session")

        artifacts = manager2.get_all_artifacts()
        assert len(artifacts) == 1


class TestWorkspaceManager:
    """Tests for WorkspaceManager."""

    def test_initialize(self, tmp_path):
        """Test workspace initialization."""
        workspace = WorkspaceManager(tmp_path)
        workspace.initialize()

        assert (tmp_path / ".superqode").exists()
        assert (tmp_path / ".superqode" / "qe-artifacts").exists()

    def test_session_lifecycle(self, tmp_path):
        """Test starting and ending a session."""
        workspace = WorkspaceManager(tmp_path)

        # Start
        session_id = workspace.start_session()
        assert workspace.is_active
        assert workspace.state == WorkspaceState.ACTIVE

        # End
        result = workspace.end_session()
        assert not workspace.is_active
        assert workspace.state == WorkspaceState.IDLE
        assert result.session_id == session_id

    def test_file_operations_tracked(self, tmp_path):
        """Test that file operations are tracked."""
        # Create initial file
        test_file = tmp_path / "test.txt"
        test_file.write_text("original")

        workspace = WorkspaceManager(tmp_path)
        workspace.start_session()

        # Modify file
        workspace.write_file("test.txt", "modified")
        assert test_file.read_text() == "modified"

        # End and revert
        result = workspace.end_session()

        # Should be reverted
        assert test_file.read_text() == "original"
        assert result.reverted

    def test_git_guard_integration(self, tmp_path):
        """Test that git guard is active during session."""
        workspace = WorkspaceManager(tmp_path)
        workspace.start_session()

        # Git write should be blocked
        with pytest.raises(GitOperationBlocked):
            workspace.check_command("git commit -m 'test'")

        # Git read should be allowed
        workspace.check_command("git status")  # Should not raise

    def test_finding_creates_patch(self, tmp_path):
        """Test that adding a finding with fix creates a patch."""
        test_file = tmp_path / "test.py"
        test_file.write_text("def main():\n    pass\n")

        workspace = WorkspaceManager(tmp_path)
        workspace.start_session()

        # Capture the file first
        workspace.snapshot.capture_file(Path("test.py"))

        # Add finding with suggested fix
        finding = workspace.add_finding(
            severity="critical",
            title="Empty function",
            description="Function does nothing",
            file_path="test.py",
            suggested_fix="def main():\n    print('hello')\n",
        )

        assert finding.patch_artifact_id is not None

        # Verify patch was created
        patches = workspace.artifacts.list_patches()
        assert len(patches) == 1


class TestQRGenerator:
    """Tests for QR generation."""

    def test_generate_markdown(self):
        """Test generating QR markdown."""
        from superqode.qr import QRGenerator
        from superqode.qr.generator import QRData, Finding
        from datetime import datetime

        data = QRData(
            session_id="test-123",
            mode="quick_scan",
            started_at=datetime.now(),
            ended_at=datetime.now(),
            target_description="Test project",
            findings=[
                Finding(
                    id="finding-001",
                    severity="critical",
                    category="security",
                    title="SQL Injection",
                    description="User input not sanitized",
                    file_path="src/db.py",
                    line_start=42,
                ),
            ],
        )

        generator = QRGenerator(data)
        markdown = generator.generate_markdown()

        assert "Quality Report (QR)" in markdown
        assert "test-123" in markdown
        assert "SQL Injection" in markdown
        assert "FAIL" in markdown  # Critical finding = fail

    def test_generate_json(self):
        """Test generating QR JSON."""
        from superqode.qr import QRGenerator
        from superqode.qr.generator import QRData
        from datetime import datetime

        data = QRData(
            session_id="test-456",
            mode="deep_qe",
            started_at=datetime.now(),
            ended_at=datetime.now(),
        )

        generator = QRGenerator(data)
        json_data = generator.generate_json()

        assert json_data["session_id"] == "test-456"
        assert json_data["mode"] == "deep_qe"
        assert json_data["verdict"] == "pass"  # No findings
        assert "summary" in json_data
