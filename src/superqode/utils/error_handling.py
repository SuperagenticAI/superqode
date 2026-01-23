"""
Error handling utilities for SuperQode OSS

Provides robust error handling for common edge cases and failure modes.
"""

import os
import sys
import logging
from typing import Optional, Dict, Any, Callable
from pathlib import Path
from functools import wraps
import asyncio

logger = logging.getLogger(__name__)


class SuperQodeError(Exception):
    """Base exception for SuperQode errors."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(SuperQodeError):
    """Configuration-related errors."""

    pass


class DependencyError(SuperQodeError):
    """Missing dependency errors."""

    pass


class NetworkError(SuperQodeError):
    """Network connectivity errors."""

    pass


class TimeoutError(SuperQodeError):
    """Timeout-related errors."""

    pass


class ResourceError(SuperQodeError):
    """Resource exhaustion errors."""

    pass


def handle_errors(fallback_message: str = "An unexpected error occurred"):
    """Decorator to handle common errors gracefully."""

    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                return handle_error(e, fallback_message, func.__name__)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                return handle_error(e, fallback_message, func.__name__)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def handle_error(error: Exception, fallback_message: str, context: str = "") -> Optional[Any]:
    """Handle an error with appropriate logging and user-friendly messages."""

    error_type = type(error).__name__

    # Log the full error for debugging
    logger.error(f"Error in {context}: {error_type}: {error}", exc_info=True)

    # Handle specific error types with user-friendly messages
    if isinstance(error, (OSError, PermissionError)):
        if "permission denied" in str(error).lower():
            print(f"❌ Permission denied: {error}")
            print("💡 Try running with appropriate permissions or check file access.")
            return None
        elif "no space left on device" in str(error).lower():
            print(f"❌ Disk full: {error}")
            print("💡 Free up disk space and try again.")
            return None
        else:
            print(f"❌ System error: {error}")

    elif isinstance(error, ImportError):
        if "opencode" in str(error).lower():
            print("❌ OpenCode not found. Install with: npm i -g opencode-ai")
            print("💡 OpenCode is required for AI agent analysis.")
        else:
            print(f"❌ Missing dependency: {error}")
        return None

    elif isinstance(error, asyncio.TimeoutError):
        print(f"⏰ Operation timed out: {error}")
        print("💡 Try increasing timeout or checking network connectivity.")
        return None

    elif isinstance(error, ConnectionError):
        print(f"🌐 Network error: {error}")
        print("💡 Check your internet connection and try again.")
        return None

    elif isinstance(error, MemoryError):
        print(f"💾 Out of memory: {error}")
        print("💡 Try closing other applications or reducing workload.")
        return None

    elif isinstance(error, FileNotFoundError):
        if "opencode" in str(error).lower():
            print("❌ OpenCode command not found.")
            print("💡 Install OpenCode: npm i -g opencode-ai")
        else:
            print(f"❌ File not found: {error}")
        return None

    else:
        # Generic error handling
        print(f"❌ {fallback_message}: {error}")
        if context:
            print(f"   Context: {context}")

    return None


def check_dependencies():
    """Check for required dependencies and provide helpful error messages."""

    issues = []

    # Check for Python version
    if sys.version_info < (3, 8):
        issues.append("Python 3.8+ required (current: {}.{}.{})".format(*sys.version_info[:3]))

    # Check for Node.js and npm (for OpenCode)
    try:
        import subprocess

        result = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            issues.append("Node.js not found or not working")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        issues.append("Node.js not found - required for OpenCode")

    try:
        result = subprocess.run(["npm", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            issues.append("npm not found or not working")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        issues.append("npm not found - required for OpenCode")

    # Check for OpenCode
    if not os.path.exists("/usr/local/bin/opencode") and not os.path.exists("/usr/bin/opencode"):
        try:
            result = subprocess.run(
                ["which", "opencode"], capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                issues.append("OpenCode not installed - install with: npm i -g opencode-ai")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            issues.append("OpenCode not found - install with: npm i -g opencode-ai")

    if issues:
        print("⚠️  Dependency Issues Found:")
        for issue in issues:
            print(f"   • {issue}")
        print("\n🔧 Fix these issues before running SuperQode QE features.")

    return len(issues) == 0


def validate_project_structure(project_root: Path) -> Dict[str, Any]:
    """Validate project structure and return issues found."""

    issues = {"warnings": [], "errors": [], "missing_files": [], "large_files": []}

    # Check for common project files
    common_files = ["package.json", "requirements.txt", "pyproject.toml", "Pipfile", "yarn.lock"]
    has_project_file = any((project_root / f).exists() for f in common_files)

    if not has_project_file:
        issues["warnings"].append(
            "No standard project file found (package.json, requirements.txt, etc.)"
        )

    # Check for large files that might cause issues
    large_files = []
    total_size = 0

    try:
        for file_path in project_root.rglob("*"):
            if file_path.is_file() and not any(part.startswith(".") for part in file_path.parts):
                try:
                    size = file_path.stat().st_size
                    total_size += size

                    # Flag files over 50MB
                    if size > 50 * 1024 * 1024:
                        large_files.append(f"{file_path.name} ({size / (1024 * 1024):.1f}MB)")

                    # Flag files over 10MB as warnings
                    elif size > 10 * 1024 * 1024:
                        issues["warnings"].append(
                            f"Large file: {file_path.name} ({size / (1024 * 1024):.1f}MB)"
                        )

                except (OSError, PermissionError):
                    continue

        if large_files:
            issues["errors"].extend([f"File too large for analysis: {f}" for f in large_files])

        # Check total project size (warn over 500MB)
        if total_size > 500 * 1024 * 1024:
            issues["warnings"].append(".1f")

    except Exception as e:
        issues["warnings"].append(f"Could not analyze project structure: {e}")

    return issues


def create_fallback_result(operation: str, error: Exception) -> Dict[str, Any]:
    """Create a fallback result when an operation fails."""

    return {
        "success": False,
        "operation": operation,
        "error": str(error),
        "error_type": type(error).__name__,
        "fallback": True,
        "message": f"Operation '{operation}' failed, using fallback mode",
    }


def safe_file_operation(operation_name: str):
    """Decorator for safe file operations."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except (OSError, PermissionError) as e:
                logger.warning(f"File operation '{operation_name}' failed: {e}")
                return create_fallback_result(operation_name, e)
            except Exception as e:
                logger.error(f"Unexpected error in '{operation_name}': {e}")
                return create_fallback_result(operation_name, e)

        return wrapper

    return decorator


def safe_network_operation(operation_name: str, timeout: int = 30):
    """Decorator for safe network operations."""

    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(f"Network operation '{operation_name}' timed out")
                return create_fallback_result(
                    operation_name, asyncio.TimeoutError("Operation timed out")
                )
            except Exception as e:
                logger.error(f"Network operation '{operation_name}' failed: {e}")
                return create_fallback_result(operation_name, e)

        return async_wrapper

    return decorator


# Global error recovery strategies
def attempt_recovery(func: Callable, max_retries: int = 3, backoff_factor: float = 1.5):
    """Attempt to recover from transient failures."""

    import time

    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        last_error = None

        for attempt in range(max_retries):
            try:
                return await func(*args, **kwargs)
            except (ConnectionError, OSError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = backoff_factor**attempt
                    logger.info(f"Attempt {attempt + 1} failed, retrying in {delay:.1f}s: {e}")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"All {max_retries} attempts failed: {e}")
            except Exception as e:
                # Don't retry for non-transient errors
                raise e

        # If we get here, all retries failed
        raise last_error

    return async_wrapper
