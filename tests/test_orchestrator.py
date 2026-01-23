"""
Tests for SuperQode QE Orchestrator.

Tests the high-level QE session orchestration functionality.
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from superqode.superqe.orchestrator import (
    QEOrchestrator,
    SuggestionMode,
)
from superqode.superqe.verifier import (
    VerificationResult,
    VerificationStatus,
    FixVerifierConfig,
)
from superqode.execution.modes import QEMode


class TestSuggestionMode:
    """Tests for SuggestionMode."""

    def test_initialization(self, tmp_path):
        """Test SuggestionMode initialization."""
        suggestion_mode = SuggestionMode(project_root=tmp_path)

        assert suggestion_mode.project_root == tmp_path
        assert suggestion_mode.verified_fixes == []

    def test_initialization_with_config(self, tmp_path):
        """Test SuggestionMode with custom verifier config."""
        config = FixVerifierConfig(
            timeout_seconds=60,
        )
        suggestion_mode = SuggestionMode(
            project_root=tmp_path,
            verifier_config=config,
        )

        assert suggestion_mode.project_root == tmp_path

    def test_get_summary_empty(self, tmp_path):
        """Test summary with no verified fixes."""
        suggestion_mode = SuggestionMode(project_root=tmp_path)
        summary = suggestion_mode.get_summary()

        assert summary["total"] == 0
        assert summary["verified"] == 0
        assert summary["improvements"] == 0
        assert summary["failed"] == 0

    def test_verify_finding_without_fix(self, tmp_path):
        """Test verifying a finding without suggested fix."""
        suggestion_mode = SuggestionMode(project_root=tmp_path)

        finding = {
            "id": "test-finding-1",
            "description": "Test bug",
            # No suggested_fix
        }

        result = suggestion_mode.verify_finding_fix(finding)
        assert result is None

    def test_verify_finding_with_fix(self, tmp_path):
        """Test verifying a finding with suggested fix."""
        suggestion_mode = SuggestionMode(project_root=tmp_path)

        finding = {
            "id": "test-finding-1",
            "description": "Test bug",
            "file_path": "test.py",
            "suggested_fix": "--- a/test.py\n+++ b/test.py\n@@ -1 +1 @@\n-bug\n+fix",
        }

        # Mock the verifier
        with patch.object(suggestion_mode.verifier, "verify_fix") as mock_verify:
            mock_verify.return_value = VerificationResult(
                finding_id="test-finding-1",
                status=VerificationStatus.SKIPPED,
            )

            result = suggestion_mode.verify_finding_fix(finding)

            assert result is not None
            assert result.finding_id == "test-finding-1"
            assert result.status == VerificationStatus.SKIPPED


class TestQEOrchestrator:
    """Tests for QEOrchestrator."""

    def test_initialization(self, tmp_path):
        """Test QEOrchestrator initialization."""
        orchestrator = QEOrchestrator(project_root=tmp_path)

        assert orchestrator.project_root == tmp_path

    def test_initialization_with_options(self, tmp_path):
        """Test QEOrchestrator with various options."""
        orchestrator = QEOrchestrator(
            project_root=tmp_path,
            verbose=True,
            output_format="plain",
        )

        assert orchestrator.project_root == tmp_path
        assert orchestrator.verbose is True
        assert orchestrator.output_format == "plain"


class TestQEModes:
    """Tests for QE execution modes."""

    def test_qe_mode_quick_scan(self):
        """Test quick scan mode configuration."""
        mode = QEMode.QUICK_SCAN
        assert mode.value == "quick_scan"

    def test_qe_mode_deep(self):
        """Test deep QE mode configuration."""
        mode = QEMode.DEEP_QE
        assert mode.value == "deep_qe"


class TestVerificationStatus:
    """Tests for verification status enum."""

    def test_skipped_status(self):
        """Test SKIPPED status."""
        assert VerificationStatus.SKIPPED.value == "skipped"


class TestVerificationResult:
    """Tests for VerificationResult dataclass."""

    def test_create_result(self):
        """Test creating a verification result."""
        result = VerificationResult(
            finding_id="test-1",
            status=VerificationStatus.SKIPPED,
        )

        assert result.finding_id == "test-1"
        assert result.status == VerificationStatus.SKIPPED


# Integration tests
@pytest.mark.integration
class TestQEOrchestratorIntegration:
    """Integration tests for QE orchestrator.

    These tests require a full project setup.
    Run with: pytest -m integration
    """

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full project setup")
    async def test_quick_scan_execution(self, tmp_path):
        """Test executing a quick scan."""
        orchestrator = QEOrchestrator(project_root=tmp_path)
        result = await orchestrator.quick_scan()

        assert result is not None
        assert "findings" in result

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires full project setup")
    async def test_deep_qe_execution(self, tmp_path):
        """Test executing a deep QE session."""
        orchestrator = QEOrchestrator(project_root=tmp_path)
        result = await orchestrator.deep_qe()

        assert result is not None
