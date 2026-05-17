"""Persistent ACP tool-permission store (A4 from the fast-agent gap audit).

What this is for
----------------
When an ACP agent asks the user "may I run this tool?", the user picks
one of four standard ACP permission options:

- ``allow_once``    — let it run, ask again next time
- ``allow_always``  — let it run, and remember
- ``reject_once``   — block, ask again next time
- ``reject_always`` — block, and remember

Without persistence, every session is a clean slate — the user has to
re-approve common-but-noisy tools (bash, read_file, web_fetch) on every
startup. fast-agent solves this with a human-readable markdown file at
``~/.fast-agent/auths.md``. We do the same at ``~/.superqode/permissions.md``.

Design choices
--------------
- **Markdown table**, not JSON: the file is meant to be edited by hand
  to revoke or audit permissions. JSON is harder to scan and easy to
  break with a misplaced comma.
- **Only ``always`` variants are persisted**: a once-decision is, by
  definition, scoped to one call. Persisting it would make
  ``allow_once`` and ``allow_always`` indistinguishable on next run.
- **Scoped by ``<scope>/<tool>``**: a tool title alone isn't unique
  across agents — both Claude and OpenCode might call their shell tool
  ``bash`` but the user may want to trust one and not the other. The
  caller passes a scope string (typically the agent identity).
- **Lazy load + asyncio.Lock**: file isn't created until the first
  ``always`` decision, and a single in-process lock prevents two
  concurrent writes from corrupting the table.
- **Soft-fail on I/O errors**: if the file can't be read or written
  (permissions, disk full, etc.) we keep the in-memory cache and log
  through the existing thinking callback. Never crash a session over
  a permission-cache failure.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Awaitable, Callable, Dict, Optional


# Standard ACP permission kinds — these strings come straight from the
# spec, so we mirror them rather than inventing our own enum.
ALLOW_ONCE = "allow_once"
ALLOW_ALWAYS = "allow_always"
REJECT_ONCE = "reject_once"
REJECT_ALWAYS = "reject_always"


class PermissionDecision(str, Enum):
    """Persisted permission decision. ``once`` variants are not stored."""

    ALLOW_ALWAYS = ALLOW_ALWAYS
    REJECT_ALWAYS = REJECT_ALWAYS

    @classmethod
    def from_option_kind(cls, kind: Optional[str]) -> Optional["PermissionDecision"]:
        """Map an ACP ``PermissionOption.kind`` to a stored decision.

        Returns ``None`` for ``allow_once`` / ``reject_once`` so callers
        know not to persist them.
        """
        if kind == ALLOW_ALWAYS:
            return cls.ALLOW_ALWAYS
        if kind == REJECT_ALWAYS:
            return cls.REJECT_ALWAYS
        return None

    @property
    def allowed(self) -> bool:
        return self is PermissionDecision.ALLOW_ALWAYS


def default_permissions_path() -> Path:
    """Resolve the default permissions file path.

    Honors ``SUPERQODE_HOME`` so tests and per-project setups can
    redirect without touching the global file.
    """
    home = os.environ.get("SUPERQODE_HOME")
    if home:
        return Path(home).expanduser() / "permissions.md"
    return Path.home() / ".superqode" / "permissions.md"


@dataclass(frozen=True)
class StoredPermission:
    """Snapshot of a single persisted permission."""

    scope: str
    tool: str
    decision: PermissionDecision


class ACPPermissionStore:
    """Persistent store for ``allow_always`` / ``reject_always`` decisions.

    Usage::

        store = ACPPermissionStore()
        decision = await store.get(scope="opencode.ai", tool="bash")
        if decision is None:
            # Ask the user; on their answer, optionally:
            await store.set(scope="opencode.ai", tool="bash",
                            decision=PermissionDecision.ALLOW_ALWAYS)
    """

    # Markdown table format — kept stable so users can hand-edit:
    #   | Scope | Tool | Permission |
    #   |-------|------|------------|
    #   | opencode.ai | bash | allow_always |
    _HEADER_LINES = (
        "# SuperQode Tool Permissions",
        "",
        "This file stores persistent tool execution permissions for ACP agents.",
        "You can edit this file manually to add or revoke permissions.",
        "Only `allow_always` and `reject_always` decisions are persisted —",
        "`allow_once` and `reject_once` are per-call and never written here.",
        "",
        "| Scope | Tool | Permission |",
        "|-------|------|------------|",
    )

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        on_warn: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> None:
        self._path: Path = path or default_permissions_path()
        self._cache: Dict[str, PermissionDecision] = {}
        self._loaded = False
        self._lock = asyncio.Lock()
        self._on_warn = on_warn

    @property
    def path(self) -> Path:
        """Where the markdown file lives."""
        return self._path

    @staticmethod
    def _key(scope: str, tool: str) -> str:
        return f"{scope}/{tool}"

    async def _warn(self, msg: str) -> None:
        if self._on_warn is not None:
            try:
                await self._on_warn(msg)
            except Exception:
                # A warning callback failing must not break a session.
                pass

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self._path.exists():
            try:
                text = await asyncio.to_thread(self._path.read_text, encoding="utf-8")
                self._parse(text)
            except Exception as e:
                await self._warn(f"[permission_store] failed to load {self._path}: {e}")
        self._loaded = True

    def _parse(self, content: str) -> None:
        """Parse the markdown table into ``self._cache``.

        Tolerant: lines that don't match the table shape are skipped
        rather than rejected, so a hand-edit that adds blank rows or
        comments doesn't blow away the cache.
        """
        in_table = False
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("# "):
                continue
            if stripped.startswith("| Scope") or stripped.startswith("|Scope"):
                continue
            if stripped.startswith("|--") or stripped.startswith("| --"):
                in_table = True
                continue
            if in_table and stripped.startswith("|") and stripped.endswith("|"):
                parts = [p.strip() for p in stripped.split("|")[1:-1]]
                if len(parts) < 3:
                    continue
                scope, tool, raw = parts[0], parts[1], parts[2]
                if not scope or not tool:
                    continue
                try:
                    self._cache[self._key(scope, tool)] = PermissionDecision(raw)
                except ValueError:
                    # Unknown decision string — skip, don't crash.
                    continue

    async def _save(self) -> None:
        if not self._cache:
            # Don't materialize an empty file. fast-agent matches this:
            # the file is meaningful only when there's at least one row.
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            rows = [
                f"| {key.split('/', 1)[0]} | {key.split('/', 1)[1]} | {dec.value} |"
                for key, dec in sorted(self._cache.items())
            ]
            content = "\n".join(self._HEADER_LINES + tuple(rows) + ("",))
            await asyncio.to_thread(self._path.write_text, content, encoding="utf-8")
        except Exception as e:
            # In-memory cache stays correct; just log.
            await self._warn(f"[permission_store] failed to save {self._path}: {e}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get(self, scope: str, tool: str) -> Optional[PermissionDecision]:
        """Return the persisted decision for ``scope/tool``, or ``None``."""
        async with self._lock:
            await self._ensure_loaded()
            return self._cache.get(self._key(scope, tool))

    async def set(self, scope: str, tool: str, decision: PermissionDecision) -> None:
        """Persist a decision. Overwrites any prior entry for the same pair."""
        async with self._lock:
            await self._ensure_loaded()
            self._cache[self._key(scope, tool)] = decision
            await self._save()

    async def remove(self, scope: str, tool: str) -> bool:
        """Forget a stored decision. Returns ``True`` if one was removed."""
        async with self._lock:
            await self._ensure_loaded()
            key = self._key(scope, tool)
            if key not in self._cache:
                return False
            del self._cache[key]
            if self._cache:
                await self._save()
            else:
                # Last entry just left — remove the file so a re-run
                # starts genuinely fresh, not with an empty table.
                try:
                    if self._path.exists():
                        await asyncio.to_thread(self._path.unlink)
                except Exception as e:
                    await self._warn(f"[permission_store] failed to delete {self._path}: {e}")
            return True

    async def clear(self) -> None:
        """Drop all decisions and remove the file."""
        async with self._lock:
            self._cache.clear()
            try:
                if self._path.exists():
                    await asyncio.to_thread(self._path.unlink)
            except Exception as e:
                await self._warn(f"[permission_store] failed to delete {self._path}: {e}")

    async def list_all(self) -> Dict[str, PermissionDecision]:
        """Snapshot of every stored decision keyed by ``scope/tool``."""
        async with self._lock:
            await self._ensure_loaded()
            return dict(self._cache)
