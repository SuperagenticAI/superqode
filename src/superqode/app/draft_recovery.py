"""Bounded, private workspace drafts; image payloads are never persisted."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from threading import Lock

MAX_DRAFT_BYTES = 32 * 1024 * 1024


class DraftStore:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.path = self.workspace / ".superqode" / "draft.json"
        self._lock = Lock()
        self._last_revision = -1

    def load(self) -> dict:
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(MAX_DRAFT_BYTES + 1)
            if len(raw) > MAX_DRAFT_BYTES:
                return {}
            state = json.loads(raw)
            if not isinstance(state, dict) or state.get("version") != 1:
                return {}
            text = state.get("text")
            cursor = state.get("cursor")
            refs = state.get("refs")
            images = state.get("images")
            if not isinstance(text, str) or not isinstance(cursor, int):
                return {}
            if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
                return {}
            if not isinstance(images, dict) or not all(
                ref in refs and isinstance(path, str) for ref, path in images.items()
            ):
                return {}
            blocks = state.get("blocks", {})
            if not isinstance(blocks, dict) or len(blocks) > 100:
                return {}
            for key, block in blocks.items():
                if not isinstance(key, str) or not isinstance(block, dict):
                    return {}
                if not isinstance(block.get("text"), str) or not isinstance(
                    block.get("label"), str
                ):
                    return {}
                block["lines"] = block["text"].count("\n") + 1
            return {
                "blocks": blocks,
                "text": text,
                "cursor": max(0, min(cursor, len(text))),
                "refs": list(dict.fromkeys(refs))[:100],
                "images": images,
                "prefill": state.get("prefill") if isinstance(state.get("prefill"), str) else "",
            }
        except (OSError, ValueError, TypeError):
            return {}

    def save(self, state: dict, revision: int) -> None:
        """Serialize writes, refusing a stale background save after an exit flush."""
        with self._lock:
            if revision < self._last_revision:
                return
            self._last_revision = revision
            raw = json.dumps({"version": 1, **state}, ensure_ascii=False).encode("utf-8")
            if not state.get("text") and not state.get("refs") or len(raw) > MAX_DRAFT_BYTES:
                self.path.unlink(missing_ok=True)
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                descriptor, name = tempfile.mkstemp(prefix=".draft-", dir=self.path.parent)
                temporary = Path(name)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(raw)
                os.replace(temporary, self.path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
