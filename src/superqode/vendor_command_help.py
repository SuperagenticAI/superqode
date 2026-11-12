"""Read command trees from the three installed vendor CLIs."""

from __future__ import annotations

import re
import shlex

FAMILIES = {"antigravity": "agy", "codex": "codex", "grok": "grok"}
ANTIGRAVITY_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CODEX_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
GROK_EFFORTS = ("low", "medium", "high", "xhigh")
_STARTUP_EFFORTS = {
    "antigravity": ANTIGRAVITY_EFFORTS,
    "codex": CODEX_EFFORTS,
    "grok": GROK_EFFORTS,
}
_COMMAND = re.compile(r"[a-z][a-z0-9-]{0,63}")
_ROW = re.compile(r"^( {2,4})([a-z][a-z0-9-]*)(?: +(?:\[[^\]]+\]|<[^>]+>))*(?: {2,}(.+))?\s*$")
_FLAG = re.compile(r"^ *(?:-\w, )?(--[a-z][a-z0-9-]+)(?=\s|=|$)")


def command_rows(text: str) -> list[dict[str, str]]:
    """Read Clap and agy command sections while skipping flags and continuations."""
    rows = {}
    inside = False
    indentation = None
    for line in text.splitlines():
        if line.strip().lower() in {"commands:", "available subcommands:", "subcommands:"}:
            inside, indentation = True, None
        elif line.strip() and not line[0].isspace():
            inside = False
        elif inside and (match := _ROW.fullmatch(line)):
            indent, name, summary = match.groups()
            indentation = indentation or indent
            if indent == indentation and _COMMAND.fullmatch(name):
                rows[name] = {"id": name, "name": name, "description": (summary or "").strip()}
    return list(rows.values())


def command_path(value) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > 6
        or any(not isinstance(part, str) or not _COMMAND.fullmatch(part) for part in value)
    ):
        raise ValueError("Choose a command from the vendor catalog.")
    return value


def cli_arguments(value: str) -> list[str]:
    if not isinstance(value, str) or len(value) > 16_384 or any(ord(c) < 32 for c in value):
        raise ValueError("Enter one line of vendor CLI arguments.")
    try:
        return shlex.split(value)
    except ValueError as exc:
        raise ValueError("Check the quotes in the CLI arguments.") from exc


def help_arguments(family: str, path: list[str]) -> list[str]:
    if family == "antigravity" and not path:
        return ["--help"]
    return ["help", *path]


def command_flags(text: str) -> list[str]:
    return list(
        dict.fromkeys(match[1] for line in text.splitlines() if (match := _FLAG.match(line)))
    )


def startup_arguments(family: str, model: str, effort: str) -> list[str]:
    """Translate a model and effort selection into structured startup arguments."""
    if not isinstance(model, str) or len(model) > 512 or any(ord(c) < 32 for c in model):
        raise ValueError("Enter a valid model ID.")
    if effort and effort not in _STARTUP_EFFORTS[family]:
        raise ValueError("Unsupported CLI reasoning effort.")
    if family == "antigravity":
        model = antigravity_model_for_effort(model, effort)
    args = [f"--model={model}"] if model else []
    if effort:
        args.extend(
            {
                "antigravity": ["--effort", effort],
                "codex": ["-c", f'model_reasoning_effort="{effort}"'],
                "grok": ["--reasoning-effort", effort],
            }[family]
        )
    return args


def antigravity_model_for_effort(model: str, effort: str | None) -> str:
    """agy rejects a variant slug paired with a different effort."""
    base, _, variant = model.rpartition("-")
    if base and effort and variant in ANTIGRAVITY_EFFORTS and variant != effort:
        return base
    return model


def antigravity_efforts(help_text: str) -> list[str]:
    line = next(
        (line for line in help_text.splitlines() if line.lstrip().startswith("--effort ")), ""
    )
    return [level for level in ANTIGRAVITY_EFFORTS if re.search(rf"\b{level}\b", line)]
