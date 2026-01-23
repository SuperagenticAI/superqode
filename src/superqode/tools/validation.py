"""
Path Validation Utilities.

Provides functions to validate that file paths stay within the working directory,
preventing directory traversal attacks and unauthorized file access.
"""

from pathlib import Path
import os
from typing import Optional


def validate_path_in_working_directory(path: str, working_directory: Path) -> Path:
    """Validate that a path stays within working_directory.

    This function prevents directory traversal attacks by ensuring that:
    - Relative paths with `../` cannot escape the working directory
    - Absolute paths outside the working directory are rejected
    - All paths are resolved and normalized before validation

    Args:
        path: Path to validate (can be relative or absolute)
        working_directory: The allowed working directory (must be absolute)

    Returns:
        Resolved absolute path within working_directory

    Raises:
        ValueError: If path escapes working_directory or working_directory is not absolute
    """
    # Ensure working_directory is absolute without resolving symlinks.
    working_dir = Path(working_directory).absolute()
    working_dir_real = Path(os.path.realpath(working_dir))

    # Resolve the input path without collapsing symlinks so /var stays /var on macOS.
    input_path = Path(path)
    if input_path.is_absolute():
        resolved = Path(os.path.abspath(input_path))
    else:
        resolved = Path(os.path.abspath(working_dir / input_path))

    resolved_real = Path(os.path.realpath(resolved))

    try:
        resolved.relative_to(working_dir)
        return resolved
    except ValueError:
        pass

    try:
        resolved_real.relative_to(working_dir_real)
    except ValueError:
        raise ValueError(
            f"Path '{path}' resolves to '{resolved_real}' which is outside "
            f"working directory '{working_dir_real}'. Access denied for security."
        )

    # Rebase to the non-symlink working directory for consistent relative paths.
    return working_dir / resolved_real.relative_to(working_dir_real)


def validate_working_dir_parameter(working_dir: Optional[str], ctx_working_directory: Path) -> Path:
    """Validate a working_dir parameter for shell commands.

    Ensures that the working_dir parameter stays within the context's working directory.

    Args:
        working_dir: Optional working directory parameter from tool call
        ctx_working_directory: The context's working directory (base for validation)

    Returns:
        Validated absolute path within ctx_working_directory

    Raises:
        ValueError: If working_dir escapes ctx_working_directory
    """
    if working_dir is None:
        return ctx_working_directory.resolve()

    return validate_path_in_working_directory(working_dir, ctx_working_directory)
