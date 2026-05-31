"""
Path Validation Utilities.

Provides functions to validate that file paths stay within the working directory,
preventing directory traversal attacks and unauthorized file access.
"""

from pathlib import Path
import os
from typing import List, Optional, Sequence


SEARCH_ROOTS_ENV = "SUPERQODE_SEARCH_ROOTS"


def get_configured_search_roots() -> List[Path]:
    """Extra read-only roots that search/read tools may access.

    Sourced from the ``SUPERQODE_SEARCH_ROOTS`` env var, ``os.pathsep``
    separated (``:`` on POSIX, ``;`` on Windows). Lets a local model search a
    repo downloaded outside the current project without weakening the default
    working-directory sandbox (writes still stay in the cwd). ``~`` is expanded;
    only existing directories are returned, de-duplicated, order preserved.
    """
    raw = os.environ.get(SEARCH_ROOTS_ENV, "").strip()
    if not raw:
        return []
    roots: List[Path] = []
    seen: set[str] = set()
    for part in raw.split(os.pathsep):
        part = part.strip()
        if not part:
            continue
        resolved = Path(os.path.abspath(os.path.expanduser(part)))
        key = str(resolved)
        if key in seen:
            continue
        if resolved.is_dir():
            seen.add(key)
            roots.append(resolved)
    return roots


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


def validate_path_in_search_scope(
    path: str,
    working_directory: Path,
    search_roots: Optional[Sequence[Path]] = None,
) -> Path:
    """Validate a path for read-only search/read tools.

    Accepts paths inside ``working_directory`` (same rule as
    :func:`validate_path_in_working_directory`) OR inside any configured
    read-only search root. This is the relaxed validator used by search and
    read tools so a local model can explore a downloaded/cloned repo that
    lives outside the project. Writers must keep using the strict
    working-directory validator.

    Args:
        path: Path to validate (relative paths resolve against the cwd).
        working_directory: The primary allowed directory (absolute).
        search_roots: Extra allowed roots. ``None`` falls back to
            :func:`get_configured_search_roots` (the env var).

    Returns:
        Resolved absolute path within the cwd or one of the roots.

    Raises:
        ValueError: If the path escapes both the cwd and every search root.
    """
    # Inside the working directory? Keep the existing behavior verbatim.
    try:
        return validate_path_in_working_directory(path, working_directory)
    except ValueError:
        pass

    roots = list(search_roots) if search_roots is not None else get_configured_search_roots()
    if not roots:
        # No extra roots configured — re-raise the original, clearer error.
        return validate_path_in_working_directory(path, working_directory)

    input_path = Path(path)
    # Search roots are addressed by absolute path (search tools emit absolute
    # paths for out-of-tree matches). Relative paths still resolve against cwd
    # and were already handled above, so only absolute paths reach here.
    if input_path.is_absolute():
        resolved = Path(os.path.abspath(input_path))
        resolved_real = Path(os.path.realpath(resolved))
        for root in roots:
            root_real = Path(os.path.realpath(root))
            try:
                resolved_real.relative_to(root_real)
                return resolved
            except ValueError:
                continue

    root_list = ", ".join(str(r) for r in roots)
    raise ValueError(
        f"Path '{path}' is outside the working directory '{Path(working_directory).absolute()}' "
        f"and all configured search roots ({root_list}). Access denied for security."
    )


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
