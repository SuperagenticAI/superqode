"""
Apply Patch Tool for Open Responses.

Implements the apply_patch built-in tool for applying unified diff patches
to files in the workspace. Critical for QIR (Quality Issue Resolution) fixes.

Features:
- Dry-run mode by default for safety
- Git-based patch application
- Validation before application
- Detailed error reporting

Usage:
    tool = ApplyPatchTool(workspace_root="/path/to/project")

    # Validate without applying
    result = await tool.execute(patch_content, dry_run=True)

    # Apply the patch
    result = await tool.execute(patch_content, dry_run=False)
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class PatchResult:
    """Result of a patch operation."""

    success: bool
    message: str
    files_modified: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    dry_run: bool = True


@dataclass
class PatchOperation:
    """A single file operation from a patch."""

    operation: str  # "create", "update", "delete"
    path: str
    old_path: Optional[str] = None  # For renames


class ApplyPatchTool:
    """
    Apply patch tool for Open Responses.

    Applies unified diff patches to files in the workspace.
    Uses git apply for robust patch handling.

    Args:
        workspace_root: Root directory for file operations
        dry_run: If True (default), validate without applying
        allow_outside_workspace: If True, allow patches to files outside workspace
    """

    def __init__(
        self,
        workspace_root: str,
        dry_run: bool = True,
        allow_outside_workspace: bool = False,
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.dry_run = dry_run
        self.allow_outside_workspace = allow_outside_workspace

    async def execute(
        self,
        patch: str,
        dry_run: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Execute the patch operation.

        Args:
            patch: The patch content in unified diff format
            dry_run: Override the default dry_run setting

        Returns:
            Dict with success status, message, and details
        """
        use_dry_run = dry_run if dry_run is not None else self.dry_run

        # Parse patch to extract operations
        operations = self._parse_patch(patch)

        if not operations:
            return {
                "success": False,
                "message": "No valid patch operations found",
                "dry_run": use_dry_run,
            }

        # Validate paths
        validation_errors = self._validate_paths(operations)
        if validation_errors:
            return {
                "success": False,
                "message": "Path validation failed",
                "errors": validation_errors,
                "dry_run": use_dry_run,
            }

        # Apply or validate the patch
        if use_dry_run:
            result = await self._validate_patch(patch)
        else:
            result = await self._apply_patch(patch)

        return {
            "success": result.success,
            "message": result.message,
            "files_modified": result.files_modified,
            "errors": result.errors,
            "dry_run": use_dry_run,
        }

    def _parse_patch(self, patch: str) -> List[PatchOperation]:
        """Parse a patch to extract file operations."""
        operations = []
        lines = patch.split("\n")
        current_file = None
        is_new_file = False
        is_delete = False

        for line in lines:
            if line.startswith("diff --git"):
                # New file in patch
                parts = line.split()
                if len(parts) >= 4:
                    # Extract paths: diff --git a/path b/path
                    a_path = parts[2][2:] if parts[2].startswith("a/") else parts[2]
                    b_path = parts[3][2:] if parts[3].startswith("b/") else parts[3]
                    current_file = b_path if b_path != "/dev/null" else a_path
                    is_new_file = False
                    is_delete = False

            elif line.startswith("new file mode"):
                is_new_file = True

            elif line.startswith("deleted file mode"):
                is_delete = True

            elif line.startswith("--- ") and current_file:
                old_path = line[4:].strip()
                if old_path.startswith("a/"):
                    old_path = old_path[2:]
                elif old_path == "/dev/null":
                    is_new_file = True

            elif line.startswith("+++ ") and current_file:
                new_path = line[4:].strip()
                if new_path.startswith("b/"):
                    new_path = new_path[2:]
                elif new_path == "/dev/null":
                    is_delete = True

                # Determine operation type
                if is_delete:
                    op_type = "delete"
                elif is_new_file:
                    op_type = "create"
                else:
                    op_type = "update"

                operations.append(
                    PatchOperation(
                        operation=op_type,
                        path=current_file,
                    )
                )
                current_file = None

        return operations

    def _validate_paths(self, operations: List[PatchOperation]) -> List[str]:
        """Validate that all paths are within the workspace."""
        errors = []

        if self.allow_outside_workspace:
            return errors

        for op in operations:
            try:
                full_path = (self.workspace_root / op.path).resolve()
                if not str(full_path).startswith(str(self.workspace_root)):
                    errors.append(f"Path '{op.path}' is outside workspace")
            except Exception as e:
                errors.append(f"Invalid path '{op.path}': {e}")

        return errors

    async def _validate_patch(self, patch: str) -> PatchResult:
        """Validate a patch without applying it."""
        # Write patch to temporary file
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".patch",
            delete=False,
        ) as f:
            f.write(patch)
            patch_file = f.name

        try:
            # Run git apply --check
            proc = await asyncio.create_subprocess_exec(
                "git",
                "apply",
                "--check",
                patch_file,
                cwd=str(self.workspace_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                # Parse operations for file list
                operations = self._parse_patch(patch)
                return PatchResult(
                    success=True,
                    message="Patch validation successful",
                    files_modified=[op.path for op in operations],
                    dry_run=True,
                )
            else:
                error_msg = stderr.decode("utf-8").strip()
                return PatchResult(
                    success=False,
                    message="Patch validation failed",
                    errors=[error_msg] if error_msg else ["Patch does not apply cleanly"],
                    dry_run=True,
                )

        except FileNotFoundError:
            # Git not available, try manual validation
            return await self._validate_patch_manual(patch)
        finally:
            # Clean up temp file
            try:
                os.unlink(patch_file)
            except Exception:
                pass

    async def _validate_patch_manual(self, patch: str) -> PatchResult:
        """Manually validate a patch without git."""
        operations = self._parse_patch(patch)
        errors = []

        for op in operations:
            full_path = self.workspace_root / op.path

            if op.operation == "update":
                if not full_path.exists():
                    errors.append(f"File does not exist: {op.path}")

            elif op.operation == "create":
                if full_path.exists():
                    errors.append(f"File already exists: {op.path}")

            elif op.operation == "delete":
                if not full_path.exists():
                    errors.append(f"File does not exist: {op.path}")

        if errors:
            return PatchResult(
                success=False,
                message="Patch validation failed",
                errors=errors,
                dry_run=True,
            )

        return PatchResult(
            success=True,
            message="Patch validation successful (manual check)",
            files_modified=[op.path for op in operations],
            dry_run=True,
        )

    async def _apply_patch(self, patch: str) -> PatchResult:
        """Apply a patch to the workspace."""
        # Write patch to temporary file
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".patch",
            delete=False,
        ) as f:
            f.write(patch)
            patch_file = f.name

        try:
            # Run git apply
            proc = await asyncio.create_subprocess_exec(
                "git",
                "apply",
                patch_file,
                cwd=str(self.workspace_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                operations = self._parse_patch(patch)
                return PatchResult(
                    success=True,
                    message="Patch applied successfully",
                    files_modified=[op.path for op in operations],
                    dry_run=False,
                )
            else:
                error_msg = stderr.decode("utf-8").strip()
                return PatchResult(
                    success=False,
                    message="Failed to apply patch",
                    errors=[error_msg] if error_msg else ["Patch application failed"],
                    dry_run=False,
                )

        except FileNotFoundError:
            # Git not available, try manual application
            return await self._apply_patch_manual(patch)
        finally:
            # Clean up temp file
            try:
                os.unlink(patch_file)
            except Exception:
                pass

    async def _apply_patch_manual(self, patch: str) -> PatchResult:
        """Manually apply a patch without git (limited support)."""
        return PatchResult(
            success=False,
            message="Manual patch application not supported. Please install git.",
            errors=["Git is required for patch application"],
            dry_run=False,
        )

    def get_tool_definition(self) -> Dict[str, Any]:
        """Get the Open Responses tool definition for apply_patch."""
        return {
            "type": "apply_patch",
        }
