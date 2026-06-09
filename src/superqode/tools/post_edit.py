"""
Post-edit verification — the feedback loop that runs after the agent writes or
edits a file. It runs a *fast, single-file* check (syntax + lint) and, when
enabled, an auto-format, then returns concise findings that get appended to the
tool result so the model can self-correct immediately instead of shipping a
broken edit.

Design goals:
- Fast: per-file checkers only (ruff/py_compile, eslint, gofmt, json/yaml),
  short timeout, bounded output. Never a repo-wide scan.
- Quiet on success: clean files add nothing (keeps local-model context lean).
- Safe by default: diagnostics ON, auto-format OFF (formatting mutates files).

Env toggles:
- ``SUPERQODE_VERIFY_EDITS=0``     disable diagnostics entirely.
- ``SUPERQODE_FORMAT_ON_EDIT=1``   enable auto-format after edit.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import List

from .base import ToolResult

_MAX_FINDINGS = 15
_TIMEOUT_SECONDS = 12


def _diagnostics_enabled() -> bool:
    return os.environ.get("SUPERQODE_VERIFY_EDITS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _format_enabled() -> bool:
    return os.environ.get("SUPERQODE_FORMAT_ON_EDIT", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _arg(path: Path, cwd: Path) -> str:
    """Path to hand a checker — relative to cwd when possible for tidy output."""
    try:
        return os.path.relpath(str(path), str(cwd))
    except Exception:
        return str(path)


async def _run(args: List[str], cwd: Path) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd),
    )
    out, err = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT_SECONDS)
    return (
        proc.returncode if proc.returncode is not None else 1,
        out.decode("utf-8", errors="replace"),
        err.decode("utf-8", errors="replace"),
    )


# ── Per-language diagnostics ────────────────────────────────────────────────


async def _check_python(file_path: Path, cwd: Path) -> List[str]:
    """Prefer ruff (lint + syntax); fall back to py_compile (syntax only)."""
    if shutil.which("ruff"):
        try:
            _, out, _ = await _run(
                ["ruff", "check", _arg(file_path, cwd), "--output-format", "concise", "--quiet"],
                cwd,
            )
            lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
            # ruff concise lines look like: path:line:col: CODE message
            return [ln for ln in lines if ":" in ln][:_MAX_FINDINGS]
        except Exception:
            pass
    # Syntax-only fallback.
    try:
        code, _, err = await _run(["python", "-m", "py_compile", _arg(file_path, cwd)], cwd)
        if code != 0:
            msg = err.strip().splitlines()
            return [m for m in msg if m.strip()][:_MAX_FINDINGS]
    except Exception:
        pass
    return []


async def _check_js_ts(file_path: Path, cwd: Path) -> List[str]:
    """eslint on the single file when it's configured; otherwise stay silent."""
    if not shutil.which("eslint"):
        return []
    try:
        _, out, _ = await _run(["eslint", _arg(file_path, cwd), "--format", "compact"], cwd)
        lines = [ln.strip() for ln in out.splitlines() if ": line " in ln or "error" in ln.lower()]
        return lines[:_MAX_FINDINGS]
    except Exception:
        return []


async def _check_go(file_path: Path, cwd: Path) -> List[str]:
    """gofmt -e surfaces syntax errors without rewriting the file."""
    if not shutil.which("gofmt"):
        return []
    try:
        code, _, err = await _run(["gofmt", "-e", _arg(file_path, cwd)], cwd)
        if code != 0 and err.strip():
            return [ln.strip() for ln in err.splitlines() if ln.strip()][:_MAX_FINDINGS]
    except Exception:
        pass
    return []


async def _check_json(file_path: Path, cwd: Path) -> List[str]:
    try:
        json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{file_path.name}:{exc.lineno}:{exc.colno}: invalid JSON: {exc.msg}"]
    except Exception:
        pass
    return []


async def _check_yaml(file_path: Path, cwd: Path) -> List[str]:
    try:
        import yaml  # type: ignore
    except Exception:
        return []
    try:
        yaml.safe_load(file_path.read_text(encoding="utf-8"))
    except Exception as exc:  # yaml.YAMLError
        return [f"{file_path.name}: invalid YAML: {str(exc).splitlines()[0]}"]
    return []


_DIAGNOSTIC_CHECKERS = {
    ".py": _check_python,
    ".pyi": _check_python,
    ".js": _check_js_ts,
    ".jsx": _check_js_ts,
    ".ts": _check_js_ts,
    ".tsx": _check_js_ts,
    ".mjs": _check_js_ts,
    ".cjs": _check_js_ts,
    ".go": _check_go,
    ".json": _check_json,
    ".yaml": _check_yaml,
    ".yml": _check_yaml,
}


# ── Per-language formatters (opt-in) ────────────────────────────────────────


async def _format_file(file_path: Path, cwd: Path) -> bool:
    """Format the file in place if a formatter is available. Returns True if run."""
    suffix = file_path.suffix.lower()
    try:
        if suffix in (".py", ".pyi") and shutil.which("ruff"):
            await _run(["ruff", "format", str(file_path), "--quiet"], cwd)
            return True
        if suffix == ".go" and shutil.which("gofmt"):
            await _run(["gofmt", "-w", str(file_path)], cwd)
            return True
        if suffix in (".js", ".jsx", ".ts", ".tsx", ".json", ".css", ".md", ".yaml", ".yml"):
            if shutil.which("prettier"):
                await _run(["prettier", "--write", str(file_path)], cwd)
                return True
    except Exception:
        return False
    return False


async def _diagnose(file_path: Path, cwd: Path) -> List[str]:
    checker = _DIAGNOSTIC_CHECKERS.get(file_path.suffix.lower())
    if checker is None:
        return []
    try:
        return await checker(file_path, cwd)
    except asyncio.TimeoutError:
        return []
    except Exception:
        return []


async def verify_edit(result: ToolResult, file_path: Path, ctx) -> ToolResult:
    """Augment a successful edit/write result with format + diagnostics feedback.

    Returns the (possibly mutated) result. Failures and unsupported file types
    pass through untouched. Errors here never break the edit itself.
    """
    if not getattr(result, "success", False):
        return result
    if not _diagnostics_enabled() and not _format_enabled():
        return result

    try:
        cwd = Path(getattr(ctx, "working_directory", Path.cwd()))
        path = Path(file_path)
        if not path.is_absolute():
            path = cwd / path
        if not path.exists() or not path.is_file():
            return result

        formatted = False
        if _format_enabled():
            formatted = await _format_file(path, cwd)

        findings = await _diagnose(path, cwd) if _diagnostics_enabled() else []

        extra_parts: List[str] = []
        if formatted:
            extra_parts.append("🎨 Auto-formatted.")
        if findings:
            block = [f"⚠️  {len(findings)} issue(s) detected after your edit:"]
            block.extend(f"  {f}" for f in findings)
            block.append("If your change caused these, fix them before continuing.")
            extra_parts.append("\n".join(block))

        if extra_parts:
            result.output = (result.output or "") + "\n\n" + "\n\n".join(extra_parts)
            meta = dict(getattr(result, "metadata", None) or {})
            meta["post_edit_findings"] = len(findings)
            meta["post_edit_formatted"] = formatted
            result.metadata = meta
    except Exception:
        # Verification is best-effort; never fail the underlying edit.
        return result
    return result
