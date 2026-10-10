"""State and bounded project-context checks for a guided first task."""

from dataclasses import dataclass
from pathlib import Path

FIRST_TASK = (
    "Using the attached project context, explain this project's purpose and how to run "
    "its tests. Read files only; do not edit files or run shell commands."
)


@dataclass
class DeveloperTrial:
    checked_route: tuple | None = None
    route_ready: bool = False
    check_message: str = "Choose a connection, then validate its setup."
    context: str = ""
    task: str = FIRST_TASK
    submitted_route: tuple | None = None
    pending: bool = False
    task_id: str = ""
    completed: bool = False
    result: str = "No guided task has run yet."
    reviewed: bool = False
    outcome: object | None = None
    awaiting_connection: bool = False


def project_context(value: str, root: Path) -> Path:
    root = root.resolve()
    path = Path(value).expanduser()
    path = (root / path if not path.is_absolute() else path).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Choose a text file inside the current project.")
    if not path.is_file():
        raise ValueError("Choose an existing project file, such as README.md.")
    if path.name.lower().startswith(".env") or path.suffix.lower() in {
        ".pem",
        ".key",
        ".p12",
        ".pfx",
    }:
        raise ValueError("Choose project documentation, rather than a credential file.")
    # Bound both the read and the attachment. The file may have changed since stat.
    with path.open("rb") as handle:
        data = handle.read(262145)
    if len(data) > 262144:
        raise ValueError("Choose a project text file smaller than 256 KiB.")
    if b"\0" in data:
        raise ValueError("Choose a text file; this file appears to be binary.")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("Choose a UTF-8 project text file.") from None
    if "PRIVATE KEY-----" in text:
        raise ValueError("This file contains a private key. Choose project documentation.")
    return path


def default_context(root: Path) -> str:
    for name in ("README.md", "README", "readme.md", "pyproject.toml", "package.json"):
        if (root / name).is_file():
            return name
    return ""
