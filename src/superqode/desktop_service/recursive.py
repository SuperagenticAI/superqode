"""Advanced Recursive agents page.

Reads an RLM session that is already on disk. Queues a command only when that
worker is already running. Nothing here starts a worker, a model call, or a
local-model harness row.
"""

from __future__ import annotations

import importlib.util
import json
import threading
import uuid
from pathlib import Path

_BOUNDARIES = ("rlm", "rlm-docker", "rlm-monty")
_COMMANDS = {"goal", "autonomous", "send", "steer", "cancel"}
_install_lock = threading.Lock()
_installs: dict[str, dict] = {}


def overview() -> dict:
    """Concept cards for the Advanced page. No project and no model call."""
    from superqode.rlm.sandbox import docker_available

    available, detail = docker_available(timeout=1.0)
    return {
        "cards": _templates(),
        "monty_installed": _monty_importable(),
        "docker_available": available,
        "docker_detail": detail,
    }


def _templates() -> list[dict]:
    from superqode.harness.templates import get_harness_template

    cards = []
    for name in _BOUNDARIES:
        spec = get_harness_template(name)
        config = dict(spec.runtime.config)
        cards.append(
            {
                "id": name,
                "sandbox": str(config.get("sandbox") or "host"),
                "read_only": bool(spec.metadata.get("read_only")),
                "max_depth": int(config.get("max_depth") or 0),
                "max_children": int(config.get("max_children") or 0),
                "max_parallel": int(config.get("max_parallel") or 0),
                "a2a": bool((config.get("a2a") or {}).get("enabled")),
                "warning": str(spec.metadata.get("selection_warning") or ""),
            }
        )
    return cards


def monty_install(service) -> dict:
    """Install the Monty extra into the app's private package folder."""
    if _monty_importable():
        return {"status": "completed"}
    with _install_lock:
        current = _installs.get("monty")
        if isinstance(current, dict) and current.get("status") == "running":
            return {"id": current["id"], "status": "running"}
        job_id = uuid.uuid4().hex
        row = {
            "id": job_id,
            "status": "running",
            "progress": "Installing Monty and checking that it loads…",
            "error": "",
        }
        # Status polls use the job id. A second click looks up "monty".
        _installs[job_id] = row
        _installs["monty"] = row
    threading.Thread(target=_run_monty_install, args=(service, job_id), daemon=True).start()
    return {"id": job_id, "status": "running"}


def monty_status(params) -> dict:
    job_id = str(params.get("id") or "")
    with _install_lock:
        row = _installs.get(job_id)
        if row is None:
            raise ValueError("That install is no longer running")
        return dict(row)


def inspect(service, params) -> dict:
    """Boundary, limits, and retained child agents. Does not start a worker."""
    root = service.project(params["project"])
    harness = str(params.get("harness") or "")
    card = _card(harness)
    status = _latest_status(root)
    children = _children(status.session_path if status is not None else "")
    return {
        "harness": harness,
        "sandbox": card["sandbox"] if card else "",
        "read_only": bool(card and card["read_only"]),
        "warning": card["warning"] if card else "",
        "max_depth": card["max_depth"] if card else 0,
        "max_children": card["max_children"] if card else 0,
        "max_parallel": card["max_parallel"] if card else 0,
        "a2a": bool(card and card["a2a"]),
        "worker": status.state if status is not None else "stopped",
        "worker_running": bool(status is not None and status.alive),
        "children": children,
        "usage": _usage(children),
    }


def command(service, params) -> dict:
    """Queue one TUI admin command on a worker that is already running."""
    root = service.project(params["project"])
    harness = str(params.get("harness") or "")
    name = str(params.get("command") or "")
    if name not in _COMMANDS:
        raise ValueError("That RLM control is not available here")
    card = _card(harness)
    if card is None:
        raise ValueError("Choose an RLM boundary first")
    if card["read_only"]:
        raise ValueError(
            "Monty is read-only. It cannot follow up, steer, cancel, or change the goal."
        )
    argument = _argument(name, params)
    client = _live_client(root)
    if client is None:
        raise ValueError("The RLM worker is not running. These controls do not start one.")
    command_id = client.submit_if_running("admin", {"command": name, "argument": argument})
    return {"queued": True, "id": command_id}


def _card(harness: str) -> dict | None:
    if harness not in _BOUNDARIES:
        return None
    return next(row for row in _templates() if row["id"] == harness)


def _monty_importable() -> bool:
    return importlib.util.find_spec("pydantic_monty") is not None


def _run_monty_install(service, job_id: str) -> None:
    try:
        from .app_setup import install_extra

        install_extra(service.root, "monty")
    except Exception as exc:
        message = str(exc).strip() or "Monty did not finish installing."
        _finish(job_id, "failed", message[-500:])
        return
    _finish(job_id, "completed", "")


def _finish(job_id: str, status: str, error: str) -> None:
    with _install_lock:
        row = _installs.get(job_id)
        if row is None:
            return
        row["status"] = status
        row["error"] = error
        row["progress"] = "" if status != "running" else row["progress"]


def _argument(name: str, params: dict) -> str:
    if name == "autonomous":
        value = str(params.get("argument") or "")
        if value not in {"on", "off"}:
            raise ValueError("Autonomous gates are on or off")
        return value
    if name == "goal":
        text = str(params.get("argument") or "").strip()
        if not text:
            return "off"
        if len(text) > 2000:
            raise ValueError("Use a goal of at most 2,000 characters")
        return text
    if name == "cancel":
        return _agent_id(params.get("agent"))
    if name in {"send", "steer"}:
        message = str(params.get("message") or "").strip()
        if not message or len(message) > 2000:
            raise ValueError("Write a follow-up of at most 2,000 characters")
        return _agent_id(params.get("agent")) + " " + message
    raise ValueError("That RLM control is not available here")


def _agent_id(value) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 80 or any(not (ch.isalnum() or ch in "_.-:") for ch in text):
        raise ValueError("Choose a child agent")
    return text


def _latest_status(root: Path):
    client = _matching_client(root, alive_only=False)
    if client is None:
        return None
    return client.status()


def _live_client(root: Path):
    return _matching_client(root, alive_only=True)


def _matching_client(root: Path, *, alive_only: bool):
    from superqode.rlm.config import agent_dir
    from superqode.rlm.root_runtime import RootRuntimeClient

    directory = agent_dir() / "runtime"
    if not directory.is_dir():
        return None
    wanted = root.resolve()
    best = None
    best_heartbeat = -1.0
    for path in directory.iterdir():
        manifest_path = path / "manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(manifest, dict):
            continue
        recorded = Path(str(manifest.get("working_directory") or "")).expanduser()
        try:
            if recorded.resolve() != wanted:
                continue
        except OSError:
            continue
        session_id = str(manifest.get("session_id") or "")
        if not session_id:
            continue
        client = RootRuntimeClient(session_id, manifest)
        if client.directory.resolve() != path.resolve():
            continue
        status = client.status()
        if alive_only and not status.alive:
            continue
        if status.heartbeat >= best_heartbeat:
            best = client
            best_heartbeat = status.heartbeat
    return best


def _children(session_path: str) -> list[dict]:
    if not session_path:
        return []
    journal = Path(session_path).expanduser().with_suffix(".agents.jsonl")
    if not journal.is_file():
        return []
    latest: dict[str, dict] = {}
    deleted: set[str] = set()
    try:
        lines = journal.read_text(encoding="utf-8").splitlines()[-5000:]
    except OSError:
        return []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        agent = event.get("agent")
        if not isinstance(agent, dict) or not agent.get("id"):
            continue
        agent_id = str(agent["id"])
        if event.get("type") == "agent.deleted":
            deleted.add(agent_id)
            latest.pop(agent_id, None)
            continue
        if agent_id not in deleted:
            latest[agent_id] = agent
    rows = []
    for agent_id, agent in latest.items():
        usage = agent.get("usage") if isinstance(agent.get("usage"), dict) else {}
        rows.append(
            {
                "id": agent_id,
                "status": str(agent.get("status") or ""),
                "parent_id": str(agent.get("parent_id") or ""),
                "prompt": str(agent.get("prompt") or "")[:240],
                "error": str(agent.get("error") or "")[:240],
                "total_tokens": _number(usage.get("total_tokens")),
                "cost_usd": _number(usage.get("cost_usd")),
            }
        )
    return rows


def _usage(children: list[dict]) -> dict:
    return {
        "children": len(children),
        "total_tokens": sum(item["total_tokens"] for item in children),
        "cost_usd": sum(item["cost_usd"] for item in children),
    }


def _number(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return float(value)
