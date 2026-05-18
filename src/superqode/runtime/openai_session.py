"""JSONL-backed session adapter for the openai-agents SDK.

Implements the SDK's ``SessionABC`` against a per-session ``.openai.jsonl`` file
under the standard SuperQode session directory. Items are stored verbatim
(they are already JSON-serializable mappings from OpenAI's response schema),
so we don't try to translate between SuperQode's ``SessionMessage`` and
``TResponseInputItem`` — different runtimes own different files under the
same ``session_id``.

This module imports the SDK lazily so importing ``superqode.runtime`` is
cheap without the optional extra.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any, List, Optional

from .errors import RuntimeNotInstalledError


def _require_sdk():
    try:
        from agents.memory.session import SessionABC  # noqa: F401
    except ImportError as exc:
        raise RuntimeNotInstalledError(
            "openai-agents is required. Install with: pip install superqode[openai-agents]"
        ) from exc


def make_session_class():
    """Return a ``SuperQodeSession`` class bound to the live SessionABC.

    Defined inside a function so importing this module never imports
    ``agents``. The class is cached per process.
    """
    _require_sdk()
    from agents.memory.session import SessionABC

    class SuperQodeSession(SessionABC):
        """SessionABC stored in ``{storage_dir}/{session_id}.openai.jsonl``.

        Concurrency: serialized with a per-instance lock; writes are
        append-only line-delimited JSON, safe across the single-process TUI/CLI
        and headless paths used by SuperQode.
        """

        def __init__(
            self,
            session_id: str,
            storage_dir: str | Path = ".superqode/sessions",
        ):
            self.session_id = session_id
            self.session_settings = None
            self._storage_dir = Path(storage_dir)
            self._storage_dir.mkdir(parents=True, exist_ok=True)
            self._path = self._storage_dir / f"{session_id}.openai.jsonl"
            self._lock = threading.Lock()

        # ----- SessionABC --------------------------------------------------

        async def get_items(self, limit: Optional[int] = None) -> List[Any]:
            return await asyncio.to_thread(self._read_items, limit)

        async def add_items(self, items: List[Any]) -> None:
            await asyncio.to_thread(self._append_items, items)

        async def pop_item(self) -> Optional[Any]:
            return await asyncio.to_thread(self._pop_item)

        async def clear_session(self) -> None:
            await asyncio.to_thread(self._clear)

        # ----- sync helpers ------------------------------------------------

        def _read_items(self, limit: Optional[int]) -> List[Any]:
            if not self._path.exists():
                return []
            with self._lock:
                lines = self._path.read_text(encoding="utf-8").splitlines()
            items: List[Any] = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # tolerate partial writes / hand-edits
            if limit is not None and limit >= 0:
                items = items[-limit:]
            return items

        def _append_items(self, items: List[Any]) -> None:
            if not items:
                return
            payload = "\n".join(json.dumps(item, default=str) for item in items) + "\n"
            with self._lock:
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(payload)

        def _pop_item(self) -> Optional[Any]:
            with self._lock:
                if not self._path.exists():
                    return None
                lines = [ln for ln in self._path.read_text(encoding="utf-8").splitlines() if ln.strip()]
                if not lines:
                    return None
                last, remaining = lines[-1], lines[:-1]
                self._path.write_text(
                    "\n".join(remaining) + ("\n" if remaining else ""),
                    encoding="utf-8",
                )
            try:
                return json.loads(last)
            except json.JSONDecodeError:
                return None

        def _clear(self) -> None:
            with self._lock:
                if self._path.exists():
                    self._path.unlink()

    return SuperQodeSession
