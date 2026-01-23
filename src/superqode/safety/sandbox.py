"""
Sandbox environment detection for SuperQode.

Detects whether QE sessions are being run in isolated, safe environments
and provides recommendations for safe execution.
"""

import os
import subprocess
import platform
from pathlib import Path
from enum import Enum
from typing import List, Dict, Any, Optional

from rich.console import Console

_console = Console()


class SandboxStatus(Enum):
    """Status of sandbox environment detection."""

    SAFE = "safe"
    WARNING = "warning"
    DANGEROUS = "dangerous"
    UNKNOWN = "unknown"


class SandboxDetector:
    """Detects sandbox environment characteristics."""

    def __init__(self, target_path: Optional[Path] = None):
        self.target_path = target_path or Path.cwd()
        self.detections = {}

    def detect_all(self) -> Dict[str, Any]:
        """Run all sandbox detection checks."""
        self.detections = {
            "git_status": self._check_git_status(),
            "container": self._check_container_environment(),
            "virtual_env": self._check_virtual_environment(),
            "filesystem": self._check_filesystem_safety(),
            "system_load": self._check_system_load(),
        }

        return self.detections

    def get_overall_status(self) -> SandboxStatus:
        """Get overall sandbox safety status."""
        if not self.detections:
            self.detect_all()

        # Critical indicators of danger
        if self.detections.get("git_status", {}).get("has_uncommitted_changes"):
            return SandboxStatus.DANGEROUS

        if self.detections.get("filesystem", {}).get("is_production_like"):
            return SandboxStatus.DANGEROUS

        # Warning indicators
        if not self.detections.get("container", {}).get("is_container"):
            return SandboxStatus.WARNING

        if not self.detections.get("virtual_env", {}).get("is_venv"):
            return SandboxStatus.WARNING

        # Safe indicators
        if self.detections.get("container", {}).get("is_container") and not self.detections.get(
            "git_status", {}
        ).get("has_uncommitted_changes"):
            return SandboxStatus.SAFE

        return SandboxStatus.UNKNOWN

    def _check_git_status(self) -> Dict[str, Any]:
        """Check git repository status."""
        try:
            # Check if we're in a git repository
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=self.target_path,
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode != 0:
                return {"is_git_repo": False, "has_uncommitted_changes": False, "is_clean": False}

            # Check for uncommitted changes
            status_result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.target_path,
                capture_output=True,
                text=True,
                timeout=5,
            )

            has_changes = bool(status_result.stdout.strip())

            return {
                "is_git_repo": True,
                "has_uncommitted_changes": has_changes,
                "is_clean": not has_changes,
                "changes_count": len(status_result.stdout.strip().split("\n"))
                if has_changes
                else 0,
            }

        except (subprocess.TimeoutExpired, subprocess.SubprocessError, FileNotFoundError):
            return {
                "is_git_repo": False,
                "has_uncommitted_changes": False,
                "is_clean": False,
                "error": "git not available",
            }

    def _check_container_environment(self) -> Dict[str, Any]:
        """Check if running in a container environment."""
        indicators = {
            "docker": self._check_docker_container(),
            "podman": self._check_podman_container(),
            "kubernetes": self._check_kubernetes_pod(),
            "wsl": self._check_wsl_environment(),
        }

        is_container = any(indicators.values())

        return {"is_container": is_container, "indicators": indicators}

    def _check_docker_container(self) -> bool:
        """Check if running in Docker container."""
        try:
            # Check for Docker-specific files
            if Path("/.dockerenv").exists():
                return True

            # Check cgroup for docker
            if Path("/proc/1/cgroup").exists():
                with open("/proc/1/cgroup", "r") as f:
                    content = f.read()
                    if "docker" in content.lower():
                        return True

            return False

        except (OSError, IOError):
            return False

    def _check_podman_container(self) -> bool:
        """Check if running in Podman container."""
        try:
            if Path("/run/.containerenv").exists():
                return True

            if Path("/proc/1/cgroup").exists():
                with open("/proc/1/cgroup", "r") as f:
                    content = f.read()
                    if "podman" in content.lower():
                        return True

            return False

        except (OSError, IOError):
            return False

    def _check_kubernetes_pod(self) -> bool:
        """Check if running in Kubernetes pod."""
        try:
            # Check for Kubernetes service account token
            if Path("/var/run/secrets/kubernetes.io/serviceaccount/token").exists():
                return True

            # Check environment variables
            if os.environ.get("KUBERNETES_SERVICE_HOST"):
                return True

            return False

        except OSError:
            return False

    def _check_wsl_environment(self) -> bool:
        """Check if running in WSL environment."""
        try:
            # Check for WSL-specific files
            if Path("/proc/version").exists():
                with open("/proc/version", "r") as f:
                    content = f.read()
                    if "microsoft" in content.lower() or "wsl" in content.lower():
                        return True

            # Check uname
            result = subprocess.run(["uname", "-r"], capture_output=True, text=True, timeout=2)

            if "microsoft" in result.stdout.lower() or "wsl" in result.stdout.lower():
                return True

            return False

        except (OSError, IOError, subprocess.SubprocessError):
            return False

    def _check_virtual_environment(self) -> Dict[str, Any]:
        """Check if running in a virtual environment."""
        is_venv = os.environ.get("VIRTUAL_ENV") is not None
        is_conda = os.environ.get("CONDA_DEFAULT_ENV") is not None
        is_poetry = os.environ.get("POETRY_ACTIVE") is not None

        return {
            "is_venv": is_venv,
            "is_conda": is_conda,
            "is_poetry": is_poetry,
            "has_any_venv": is_venv or is_conda or is_poetry,
            "venv_path": os.environ.get("VIRTUAL_ENV"),
            "conda_env": os.environ.get("CONDA_DEFAULT_ENV"),
        }

    def _check_filesystem_safety(self) -> Dict[str, Any]:
        """Check filesystem safety indicators."""
        path = self.target_path

        # Check for production-like indicators
        production_indicators = [
            "production" in str(path).lower(),
            "prod" in str(path).lower(),
            "live" in str(path).lower(),
            "main" in str(path).lower() and "master" in str(path).lower(),
            path == Path.home(),  # Running in home directory
            Path(path / "node_modules").exists(),  # Large npm project
            Path(path / ".git").exists()
            and any(
                f.suffix in [".py", ".js", ".ts", ".java", ".cpp", ".c"]
                for f in path.glob("*")
                if f.is_file()
            ),  # Looks like active development
        ]

        is_production_like = any(production_indicators)

        # Check write permissions
        try:
            test_file = path / ".superqode_safety_test"
            test_file.write_text("test")
            test_file.unlink()
            has_write_permission = True
        except (OSError, IOError):
            has_write_permission = False

        return {
            "is_production_like": is_production_like,
            "production_indicators": production_indicators,
            "has_write_permission": has_write_permission,
            "target_path": str(path),
        }

    def _check_system_load(self) -> Dict[str, Any]:
        """Check system load and resources."""
        try:
            # Get system info
            system = platform.system().lower()

            if system == "linux":
                # Check load average
                with open("/proc/loadavg", "r") as f:
                    loadavg = f.read().strip().split()
                    load_1min = float(loadavg[0])
                    load_5min = float(loadavg[1])
                    load_15min = float(loadavg[2])

                # Get CPU count
                cpu_count = os.cpu_count() or 1
                high_load = load_1min > cpu_count * 0.8

                return {
                    "system": system,
                    "load_1min": load_1min,
                    "load_5min": load_5min,
                    "load_15min": load_15min,
                    "cpu_count": cpu_count,
                    "high_load": high_load,
                }

            else:
                return {"system": system, "load_info": "not available"}

        except (OSError, IOError, ValueError):
            return {"system": platform.system().lower(), "load_info": "error reading system info"}


def detect_sandbox_environment(target_path: Optional[Path] = None) -> Dict[str, Any]:
    """Convenience function to detect sandbox environment."""
    detector = SandboxDetector(target_path)
    return detector.detect_all()


def get_sandbox_recommendations(detections: Dict[str, Any]) -> List[str]:
    """Get recommendations based on sandbox detection results."""
    recommendations = []

    # Git status recommendations
    git_status = detections.get("git_status", {})
    if git_status.get("has_uncommitted_changes"):
        recommendations.append(
            "⚠️  Git repository has uncommitted changes. Consider committing or stashing before QE."
        )

    if not git_status.get("is_git_repo"):
        recommendations.append(
            "💡 Consider initializing a git repository for better change tracking during QE."
        )

    # Container recommendations
    container = detections.get("container", {})
    if not container.get("is_container"):
        recommendations.append("🐳 Consider running QE in a Docker container for better isolation.")

    # Virtual environment recommendations
    venv = detections.get("virtual_env", {})
    if not venv.get("has_any_venv"):
        recommendations.append(
            "📦 Consider using a virtual environment (venv, conda) for dependency isolation."
        )

    # Filesystem recommendations
    fs = detections.get("filesystem", {})
    if fs.get("is_production_like"):
        recommendations.append(
            "🚨 Production-like environment detected. Use sandbox environments for QE testing."
        )

    # System load recommendations
    sys_load = detections.get("system_load", {})
    if sys_load.get("high_load"):
        recommendations.append("⚡ System load is high. QE sessions may impact system performance.")

    # Always include general recommendations
    if not recommendations:
        recommendations.extend(
            [
                "✅ Environment looks suitable for QE testing.",
                "💡 For maximum safety, consider using git worktrees or Docker containers.",
            ]
        )

    return recommendations


def display_sandbox_status(detections: Dict[str, Any], console: Optional[Console] = None) -> None:
    """Display sandbox detection results."""
    if console is None:
        console = _console

    from rich.table import Table
    from rich.panel import Panel

    # Create status table
    table = Table(title="Sandbox Environment Detection")
    table.add_column("Check", style="cyan", no_wrap=True)
    table.add_column("Status", style="green")
    table.add_column("Details", style="white")

    # Git status
    git = detections.get("git_status", {})
    git_status = (
        "✅ Clean"
        if git.get("is_clean")
        else "⚠️  Has Changes"
        if git.get("has_uncommitted_changes")
        else "❓ Not a Git Repo"
    )
    git_details = (
        f"Repository: {git.get('is_git_repo', False)}, Changes: {git.get('changes_count', 0)}"
    )
    table.add_row("Git Status", git_status, git_details)

    # Container
    container = detections.get("container", {})
    container_status = "✅ Container" if container.get("is_container") else "⚠️  Host System"
    container_details = ", ".join([k for k, v in container.get("indicators", {}).items() if v])
    if not container_details:
        container_details = "Not detected"
    table.add_row("Container", container_status, container_details)

    # Virtual Environment
    venv = detections.get("virtual_env", {})
    venv_status = "✅ Virtual Env" if venv.get("has_any_venv") else "⚠️  System Python"
    venv_details = []
    if venv.get("is_venv"):
        venv_details.append("venv")
    if venv.get("is_conda"):
        venv_details.append("conda")
    if venv.get("is_poetry"):
        venv_details.append("poetry")
    venv_details = ", ".join(venv_details) if venv_details else "None detected"
    table.add_row("Virtual Env", venv_status, venv_details)

    # Filesystem
    fs = detections.get("filesystem", {})
    fs_status = "🚨 Production Risk" if fs.get("is_production_like") else "✅ Development Safe"
    fs_details = f"Path: {fs.get('target_path', 'unknown')}"
    table.add_row("Filesystem", fs_status, fs_details)

    console.print(table)

    # Show recommendations
    recommendations = get_sandbox_recommendations(detections)
    if recommendations:
        rec_panel = Panel(
            "\n".join(recommendations), title="💡 Recommendations", border_style="blue"
        )
        console.print()
        console.print(rec_panel)
