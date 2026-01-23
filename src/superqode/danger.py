"""
SuperQode Danger Detection - Command Safety Analysis

Analyzes shell commands to detect potentially dangerous operations.
Uses a unique visual style with gradient warnings.
"""

from enum import IntEnum
from functools import lru_cache
from pathlib import Path
from typing import Iterable, NamedTuple, Sequence, Tuple

# Commands that are generally safe (read-only operations)
SAFE_COMMANDS = {
    # Display & Output
    "echo",
    "cat",
    "less",
    "more",
    "head",
    "tail",
    "tac",
    "nl",
    "bat",
    # File & Directory Information
    "ls",
    "tree",
    "pwd",
    "file",
    "stat",
    "du",
    "df",
    "exa",
    "lsd",
    # Search & Find
    "find",
    "locate",
    "which",
    "whereis",
    "type",
    "grep",
    "egrep",
    "fgrep",
    "rg",
    "ag",
    "fd",
    "fzf",
    # Text Processing (read-only)
    "wc",
    "sort",
    "uniq",
    "cut",
    "paste",
    "column",
    "tr",
    "diff",
    "cmp",
    "comm",
    # System Information
    "whoami",
    "who",
    "w",
    "id",
    "hostname",
    "uname",
    "uptime",
    "date",
    "cal",
    "env",
    "printenv",
    # Process Information
    "ps",
    "top",
    "htop",
    "pgrep",
    "jobs",
    "pstree",
    # Network (read-only)
    "ping",
    "traceroute",
    "nslookup",
    "dig",
    "host",
    "netstat",
    "ss",
    "ifconfig",
    "ip",
    # View compressed files
    "zcat",
    "zless",
    # History & Help
    "history",
    "man",
    "help",
    "info",
    "apropos",
    "whatis",
    # Checksums
    "md5sum",
    "sha256sum",
    "sha1sum",
    "cksum",
    "sum",
    "md5",
    "shasum",
    # Other Safe
    "bc",
    "expr",
    "test",
    "sleep",
    "true",
    "false",
    "yes",
    "seq",
    "basename",
    "dirname",
    "realpath",
    "readlink",
    # Dev tools (read-only)
    "git status",
    "git log",
    "git diff",
    "git show",
    "git branch",
    "npm list",
    "pip list",
    "cargo tree",
}

# Commands that can modify the filesystem
UNSAFE_COMMANDS = {
    # File/Directory Creation
    "mkdir",
    "touch",
    "mktemp",
    "mkfifo",
    "mknod",
    # File/Directory Deletion
    "rm",
    "rmdir",
    "shred",
    # File/Directory Moving/Copying
    "mv",
    "cp",
    "rsync",
    "scp",
    "install",
    # File Modification
    "sed",
    "awk",
    "tee",
    "nano",
    "vim",
    "vi",
    "emacs",
    "code",
    # Permissions/Ownership
    "chmod",
    "chown",
    "chgrp",
    "chattr",
    "setfacl",
    # Linking
    "ln",
    "link",
    "unlink",
    # Archive/Compression
    "tar",
    "zip",
    "unzip",
    "gzip",
    "gunzip",
    "bzip2",
    "bunzip2",
    "xz",
    "unxz",
    "7z",
    "rar",
    "unrar",
    # Download Tools
    "wget",
    "curl",
    "fetch",
    "aria2c",
    # Low-level Disk
    "dd",
    "truncate",
    "fallocate",
    # File Splitting
    "split",
    "csplit",
    # Sync
    "sync",
    # System Administration
    "useradd",
    "userdel",
    "usermod",
    "groupadd",
    "groupdel",
    "passwd",
    "mount",
    "umount",
    "mkfs",
    "fdisk",
    "parted",
    "swapon",
    "swapoff",
    # Package managers (can install/remove)
    "npm install",
    "pip install",
    "cargo install",
    "brew install",
    "apt",
    "yum",
    "dnf",
    "pacman",
    # Other Dangerous
    "patch",
    "git checkout",
    "git reset",
    "git clean",
}


class DangerLevel(IntEnum):
    """The danger level of a command."""

    SAFE = 0  # Command is known to be generally safe
    UNKNOWN = 1  # We don't know about this command
    DANGEROUS = 2  # Command can modify filesystem
    DESTRUCTIVE = 3  # Command modifies files outside project


class CommandInfo(NamedTuple):
    """Information about a command's danger level."""

    command: str
    level: DangerLevel
    target_path: Path | None
    reason: str


# Visual styles for each danger level
DANGER_STYLES = {
    DangerLevel.SAFE: {
        "icon": "✅",
        "color": "#22c55e",
        "bg": "#22c55e20",
        "label": "Safe",
        "border": "green",
    },
    DangerLevel.UNKNOWN: {
        "icon": "❓",
        "color": "#f59e0b",
        "bg": "#f59e0b20",
        "label": "Unknown",
        "border": "yellow",
    },
    DangerLevel.DANGEROUS: {
        "icon": "⚠️",
        "color": "#f97316",
        "bg": "#f9731620",
        "label": "Dangerous",
        "border": "orange1",
    },
    DangerLevel.DESTRUCTIVE: {
        "icon": "🚨",
        "color": "#ef4444",
        "bg": "#ef444420",
        "label": "DESTRUCTIVE",
        "border": "red",
    },
}


@lru_cache(maxsize=512)
def analyze_command(
    project_dir: str,
    working_dir: str,
    command: str,
) -> Tuple[DangerLevel, str, Path | None]:
    """
    Analyze a shell command for potential dangers.

    Args:
        project_dir: The project root directory
        working_dir: Current working directory
        command: The shell command to analyze

    Returns:
        Tuple of (danger_level, reason, target_path)
    """
    if not command or not command.strip():
        return DangerLevel.SAFE, "Empty command", None

    command = command.strip()
    parts = command.split()
    if not parts:
        return DangerLevel.SAFE, "Empty command", None

    base_cmd = parts[0]
    project_path = Path(project_dir).resolve()
    current_path = Path(working_dir).resolve()

    # Check for safe commands first
    if base_cmd in SAFE_COMMANDS:
        return DangerLevel.SAFE, f"'{base_cmd}' is a read-only command", None

    # Check for known unsafe commands
    is_unsafe = base_cmd in UNSAFE_COMMANDS

    # Look for file paths in arguments
    target_path = None
    for arg in parts[1:]:
        if arg.startswith("-"):
            continue
        try:
            # Try to resolve the path
            if arg.startswith("/"):
                target_path = Path(arg).resolve()
            elif arg.startswith("~"):
                target_path = Path(arg).expanduser().resolve()
            else:
                target_path = (current_path / arg).resolve()
            break
        except (OSError, ValueError):
            continue

    # Determine danger level
    if is_unsafe:
        if target_path:
            try:
                # Check if path is outside project
                target_path.relative_to(project_path)
                return DangerLevel.DANGEROUS, f"'{base_cmd}' can modify files", target_path
            except ValueError:
                return (
                    DangerLevel.DESTRUCTIVE,
                    f"'{base_cmd}' targets files outside project!",
                    target_path,
                )
        return DangerLevel.DANGEROUS, f"'{base_cmd}' can modify the filesystem", None

    # Unknown command
    return DangerLevel.UNKNOWN, f"Unknown command '{base_cmd}'", target_path


def get_danger_display(level: DangerLevel) -> dict:
    """Get display properties for a danger level."""
    return DANGER_STYLES.get(level, DANGER_STYLES[DangerLevel.UNKNOWN])


def format_danger_message(
    command: str,
    level: DangerLevel,
    reason: str,
    target_path: Path | None = None,
) -> str:
    """Format a danger warning message."""
    style = DANGER_STYLES[level]
    icon = style["icon"]
    label = style["label"]

    msg = f"{icon} [{label}] {reason}"
    if target_path:
        msg += f"\n   📁 Target: {target_path}"
    return msg


# Quick check functions
def is_safe(command: str, project_dir: str = ".", working_dir: str = ".") -> bool:
    """Check if a command is safe to run."""
    level, _, _ = analyze_command(project_dir, working_dir, command)
    return level == DangerLevel.SAFE


def is_destructive(command: str, project_dir: str = ".", working_dir: str = ".") -> bool:
    """Check if a command is destructive (modifies files outside project)."""
    level, _, _ = analyze_command(project_dir, working_dir, command)
    return level == DangerLevel.DESTRUCTIVE


def requires_approval(command: str, project_dir: str = ".", working_dir: str = ".") -> bool:
    """Check if a command requires user approval."""
    level, _, _ = analyze_command(project_dir, working_dir, command)
    return level >= DangerLevel.DANGEROUS
