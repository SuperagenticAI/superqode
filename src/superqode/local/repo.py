"""Repository sizing for local coding harness recommendations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

SKIP_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".superqode",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
    "vendor",
}

CODE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".lua",
    ".m",
    ".mm",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".scala",
    ".sh",
    ".sql",
    ".swift",
    ".ts",
    ".tsx",
    ".vue",
}

CONFIG_EXTENSIONS = {
    ".cfg",
    ".ini",
    ".json",
    ".md",
    ".toml",
    ".yaml",
    ".yml",
}

LANGUAGE_BY_EXTENSION = {
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cs": "C#",
    ".css": "CSS",
    ".go": "Go",
    ".h": "C/C++",
    ".hpp": "C++",
    ".html": "HTML",
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".kt": "Kotlin",
    ".lua": "Lua",
    ".m": "Objective-C",
    ".mm": "Objective-C++",
    ".php": "PHP",
    ".py": "Python",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".scala": "Scala",
    ".sh": "Shell",
    ".sql": "SQL",
    ".swift": "Swift",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".vue": "Vue",
}


@dataclass(frozen=True)
class RepoFileSummary:
    path: str
    size_bytes: int


@dataclass(frozen=True)
class RepoProfile:
    root: str
    file_count: int = 0
    code_file_count: int = 0
    config_file_count: int = 0
    total_bytes: int = 0
    code_bytes: int = 0
    estimated_tokens: int = 0
    recommended_context_tokens: int = 8192
    recommended_model_size: str = "small"
    workflow_shape: str = "single"
    languages: dict[str, int] = field(default_factory=dict)
    largest_files: tuple[RepoFileSummary, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "file_count": self.file_count,
            "code_file_count": self.code_file_count,
            "config_file_count": self.config_file_count,
            "total_bytes": self.total_bytes,
            "code_bytes": self.code_bytes,
            "estimated_tokens": self.estimated_tokens,
            "recommended_context_tokens": self.recommended_context_tokens,
            "recommended_model_size": self.recommended_model_size,
            "workflow_shape": self.workflow_shape,
            "languages": dict(self.languages),
            "largest_files": [
                {"path": item.path, "size_bytes": item.size_bytes} for item in self.largest_files
            ],
            "notes": list(self.notes),
        }


def analyze_repository(root: str | Path = ".") -> RepoProfile:
    """Summarize a repository for local model and harness sizing."""
    base = Path(root).resolve()
    file_count = 0
    code_file_count = 0
    config_file_count = 0
    total_bytes = 0
    code_bytes = 0
    languages: dict[str, int] = {}
    largest: list[RepoFileSummary] = []

    for path in _iter_repo_files(base):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        suffix = path.suffix.lower()
        relative = str(path.relative_to(base))
        file_count += 1
        total_bytes += size
        if suffix in CODE_EXTENSIONS:
            code_file_count += 1
            code_bytes += size
            language = LANGUAGE_BY_EXTENSION.get(suffix, suffix.lstrip(".").upper())
            languages[language] = languages.get(language, 0) + 1
        elif suffix in CONFIG_EXTENSIONS:
            config_file_count += 1
        largest.append(RepoFileSummary(path=relative, size_bytes=size))

    largest.sort(key=lambda item: item.size_bytes, reverse=True)
    estimated_tokens = max(1, int(code_bytes / 4)) if code_bytes else 0
    context = _recommended_context_tokens(estimated_tokens, code_file_count)
    model_size = _recommended_model_size(estimated_tokens, code_file_count)
    workflow = _workflow_shape(estimated_tokens, code_file_count)
    notes = _notes(
        estimated_tokens=estimated_tokens,
        code_file_count=code_file_count,
        languages=languages,
        context=context,
        workflow=workflow,
    )
    return RepoProfile(
        root=str(base),
        file_count=file_count,
        code_file_count=code_file_count,
        config_file_count=config_file_count,
        total_bytes=total_bytes,
        code_bytes=code_bytes,
        estimated_tokens=estimated_tokens,
        recommended_context_tokens=context,
        recommended_model_size=model_size,
        workflow_shape=workflow,
        languages=dict(sorted(languages.items(), key=lambda item: item[1], reverse=True)),
        largest_files=tuple(largest[:8]),
        notes=notes,
    )


def render_repo_profile(profile: RepoProfile) -> str:
    lines = ["Repository profile", "-" * 60]
    lines.append(f"Root       {profile.root}")
    lines.append(
        f"Files      {profile.file_count} total, {profile.code_file_count} code, "
        f"{profile.config_file_count} docs/config"
    )
    lines.append(
        f"Code size  {_human_bytes(profile.code_bytes)} (~{profile.estimated_tokens:,} tokens)"
    )
    lines.append(
        f"Advice     {profile.recommended_model_size} model, "
        f"{profile.recommended_context_tokens:,} token context, "
        f"{profile.workflow_shape} workflow"
    )
    if profile.languages:
        top = ", ".join(f"{name} {count}" for name, count in list(profile.languages.items())[:5])
        lines.append(f"Languages  {top}")
    if profile.largest_files:
        lines.append("Largest")
        for item in profile.largest_files[:5]:
            lines.append(f"  - {item.path} ({_human_bytes(item.size_bytes)})")
    if profile.notes:
        lines.append("Notes")
        for note in profile.notes:
            lines.append(f"  - {note}")
    return "\n".join(lines)


def _iter_repo_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                if child.name in SKIP_DIRS or child.name.startswith(".cache"):
                    continue
                stack.append(child)
            elif child.is_file() and _looks_relevant(child):
                yield child


def _looks_relevant(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix not in CODE_EXTENSIONS and suffix not in CONFIG_EXTENSIONS:
        return False
    try:
        return path.stat().st_size <= 2_000_000
    except OSError:
        return False


def _recommended_context_tokens(estimated_tokens: int, code_files: int) -> int:
    if estimated_tokens > 300_000 or code_files > 1500:
        return 131072
    if estimated_tokens > 120_000 or code_files > 600:
        return 65536
    if estimated_tokens > 35_000 or code_files > 180:
        return 32768
    return 16384


def _recommended_model_size(estimated_tokens: int, code_files: int) -> str:
    if estimated_tokens > 300_000 or code_files > 1500:
        return "large"
    if estimated_tokens > 120_000 or code_files > 600:
        return "medium-large"
    if estimated_tokens > 35_000 or code_files > 180:
        return "medium"
    return "small"


def _workflow_shape(estimated_tokens: int, code_files: int) -> str:
    if estimated_tokens > 120_000 or code_files > 600:
        return "plan-implement-review"
    if estimated_tokens > 35_000 or code_files > 180:
        return "fix-and-verify"
    return "single"


def _notes(
    *,
    estimated_tokens: int,
    code_file_count: int,
    languages: dict[str, int],
    context: int,
    workflow: str,
) -> tuple[str, ...]:
    notes: list[str] = []
    if estimated_tokens > context:
        notes.append(
            "Full-repository context will not fit; rely on search, summaries, and focused reads."
        )
    if code_file_count > 600:
        notes.append(
            "Use a planner/reviewer split so the main model does not carry every decision."
        )
    if languages:
        top_language = next(iter(languages))
        notes.append(
            f"Primary language appears to be {top_language}; prefer a coder-tuned local model."
        )
    if workflow != "single":
        notes.append(f"Recommended harness workflow: {workflow}.")
    return tuple(notes)


def _human_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024
    return f"{value:.1f}GB"


__all__ = ["RepoFileSummary", "RepoProfile", "analyze_repository", "render_repo_profile"]
