"""Repository outcomes from reviewed checks, independent of the agent's answer."""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import signal

from .eval_workspace import changed_files, file_manifest

DEFAULT_PROTECTED = [
    "tests",
    "test",
    "test_*.py",
    "*_test.py",
    "conftest.py",
    "pytest.ini",
    "tox.ini",
    "pyproject.toml",
    "package.json",
    "Makefile",
    "setup.cfg",
    "jest.config.*",
    "vitest.config.*",
]


def relative_path(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise ValueError("Repository grader paths must be relative fixture paths")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(p in {".", "..", ".git"} for p in value.split("/"))
        or ":" in value
    ):
        raise ValueError("Repository grader paths must stay inside the fixture")
    return value


def validate(config):
    unknown = set(config) - {"type", "commands", "files", "protected_paths", "require_changes"}
    if unknown:
        raise ValueError("Unknown repository grader fields: " + ", ".join(sorted(unknown)))
    commands, files = config.get("commands", []), config.get("files", [])
    if (
        not isinstance(commands, list)
        or len(commands) > 8
        or not isinstance(files, list)
        or len(files) > 64
        or not (commands or files)
    ):
        raise ValueError("Repository grader requires up to 8 command checks or 64 file assertions")
    for command in commands:
        if not isinstance(command, dict):
            raise ValueError("Repository commands require argv and an optional timeout_seconds")
        if set(command) - {"argv", "timeout_seconds", "name"}:
            raise ValueError("Unknown repository command field; use argv and timeout_seconds")
        argv = command.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or len(argv) > 128
            or not all(
                isinstance(p, str) and p and "\x00" not in p and len(p) <= 16000 for p in argv
            )
        ):
            raise ValueError("Repository commands require a non-empty argv list; no implicit shell")
        timeout = command.get("timeout_seconds", 30)
        if type(timeout) not in {int, float} or not 0.1 <= timeout <= 300:
            raise ValueError("Repository command timeout must be between 0.1 and 300 seconds")
    if type(config.get("require_changes", False)) is not bool:
        raise ValueError("require_changes must be a boolean")
    protected = config.get("protected_paths", DEFAULT_PROTECTED)
    if not isinstance(protected, list) or len(protected) > 128:
        raise ValueError("protected_paths must be a list of fixture paths or glob patterns")
    for path in protected:
        relative_path(path)
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("Repository file assertions require a path")
        if set(item) - {"path", "exists", "contains", "sha256"}:
            raise ValueError(
                "Unknown repository file assertion; use path, exists, contains or sha256"
            )
        relative_path(item.get("path"))
        if "exists" in item and type(item["exists"]) is not bool:
            raise ValueError("File exists assertions must be booleans")
        if "contains" in item and (not isinstance(item["contains"], str) or not item["contains"]):
            raise ValueError("File contains assertions require non-empty text")
        if "sha256" in item and (
            not isinstance(item["sha256"], str)
            or len(item["sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in item["sha256"])
        ):
            raise ValueError("File sha256 assertions require a lowercase SHA256 digest")


def protected_changes(changes, patterns):
    return [
        name
        for name in changes
        if any(
            name == p
            or name.startswith(p.rstrip("/") + "/")
            or fnmatch.fnmatchcase(name, p)
            or ("/" not in p and fnmatch.fnmatchcase(name.rsplit("/", 1)[-1], p))
            for p in patterns
        )
    ]


async def _command(config, root):
    environment = dict(os.environ)
    for name in (
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTEST_ADDOPTS",
        "PYTEST_PLUGINS",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
    ):
        environment.pop(name, None)
    argv = config["argv"]
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=root,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=os.name != "nt",
    )
    captured = bytearray()
    truncated = False

    async def read():
        nonlocal truncated
        while chunk := await process.stdout.read(8192):
            room = max(0, 16000 - len(captured))
            captured.extend(chunk[:room])
            truncated |= len(chunk) > room
        await process.wait()

    async def stop():
        try:
            if os.name != "nt":
                # A parent may exit while its descendants still hold stdout.
                os.killpg(process.pid, signal.SIGKILL)
            elif process.returncode is None:
                process.kill()
        except ProcessLookupError:
            pass
        if process.returncode is None:
            await process.wait()

    timed_out = False
    try:
        await asyncio.wait_for(read(), timeout=config.get("timeout_seconds", 30))
    except asyncio.TimeoutError:
        timed_out = True
        await stop()
    except BaseException:
        await stop()
        raise
    finally:
        await stop()
    return {
        "argv": argv,
        "returncode": process.returncode,
        "timed_out": timed_out,
        "passed": not timed_out and process.returncode == 0,
        "output": captured.decode(errors="replace"),
        "output_truncated": truncated,
    }


async def evaluate(config, root: Path, before: dict, snapshot_digest: str):
    """Execute only the grader configuration loaded before the agent ran."""
    from .evaluators import EvaluationResult

    validate(config)
    changes = changed_files(before, file_manifest(root))
    protected = protected_changes(changes, config.get("protected_paths", DEFAULT_PROTECTED))
    evidence = {
        "smoke_only": False,
        "snapshot_sha256": snapshot_digest,
        "grader_sha256": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
        "changed_files": changes[:1000],
        "protected_changes": protected[:1000],
        "commands": [],
        "files": [],
    }
    if protected:
        return EvaluationResult(
            evaluator="repository",
            status="failed",
            reason="Protected grader/test files changed",
            evidence=evidence,
        )
    if config.get("require_changes") and not changes:
        return EvaluationResult(
            evaluator="repository",
            status="failed",
            reason="No repository change was produced",
            evidence=evidence,
        )
    for item in config.get("files", []):
        path = root / item["path"]
        if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
            return EvaluationResult(
                evaluator="repository",
                status="error",
                reason="File assertion leaves the fixture or uses a symbolic link",
                evidence=evidence,
            )
        exists = path.is_file()
        passed = exists == item.get("exists", True)
        if "contains" in item or "sha256" in item:
            content = (
                path.read_bytes() if exists and path.stat().st_size <= 2 * 1024 * 1024 else b""
            )
            passed &= exists and path.stat().st_size <= 2 * 1024 * 1024
            if "contains" in item:
                passed &= item["contains"] in content.decode(errors="replace")
            if "sha256" in item:
                passed &= hashlib.sha256(content).hexdigest() == item["sha256"]
        evidence["files"].append({"path": item["path"], "passed": bool(passed)})
    for command in config.get("commands", []):
        evidence["commands"].append(await _command(command, root))
    passed = all(
        row["passed"] for group in (evidence["files"], evidence["commands"]) for row in group
    )
    return EvaluationResult(
        evaluator="repository",
        status="passed" if passed else "failed",
        reason="Independent repository checks passed"
        if passed
        else "Independent repository checks failed",
        evidence=evidence,
    )
