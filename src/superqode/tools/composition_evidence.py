"""Bounded, expiring local evidence for composed calls."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from uuid import uuid4


def redact_output(text: str) -> str:
    for key, value in os.environ.items():
        if len(value) >= 8 and any(
            word in key.lower() for word in ("token", "secret", "password", "api_key")
        ):
            text = text.replace(value, "[redacted]")
    text = re.sub(r"(?i)(bearer\s+)[^\s\"']+", r"\1[redacted]", text)
    text = re.sub(
        r"""(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\s*["']?\s*[:=]\s*["']?)[^\s,}"']+""",
        r"\1[redacted]",
        text,
    )
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,})\b", "[redacted]", text)
    return text


class CompositionEvidence:
    MAX_TOTAL_BYTES = 1024 * 1024
    MAX_RESULT_BYTES = 64_000
    RETENTION_SECONDS = 24 * 60 * 60

    def __init__(self, root: Path) -> None:
        self.root = root
        self.written = 0
        self._refs: dict[str, Path] = {}

    def retain(self, invocation_id: str, output: str, *, sensitive: bool = False) -> dict:
        if sensitive:
            return {"evidence_available": False, "evidence_reason": "sensitive result"}
        redacted = redact_output(output)
        data = redacted.encode()[: self.MAX_RESULT_BYTES].decode(errors="ignore")
        now = time.time()
        payload = {
            "id": invocation_id,
            "created_at": now,
            "expires_at": now + self.RETENTION_SECONDS,
            "output": data,
            "source_bytes": len(output.encode()),
            "retained_bytes": len(data.encode()),
            "truncated": len(redacted.encode()) > self.MAX_RESULT_BYTES,
            "redacted": redacted != output,
        }
        encoded = json.dumps(payload).encode()
        if self.written + len(encoded) > self.MAX_TOTAL_BYTES:
            return {"evidence_available": False, "evidence_reason": "invocation retention limit"}
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        # A configured workspace must not redirect evidence through a symlink.
        if self.root.resolve() != self.root.absolute():
            return {
                "evidence_available": False,
                "evidence_reason": "evidence directory is redirected",
            }
        files = list(self.root.glob("*.json"))
        for path in files[:1024]:
            try:
                if path.stat().st_mtime < now - self.RETENTION_SECONDS:
                    path.unlink()
            except OSError:
                pass
        if len(files) >= 1024:
            return {"evidence_available": False, "evidence_reason": "retained file limit"}
        name = (
            hashlib.sha256(invocation_id.encode()).hexdigest()[:24]
            + "-"
            + uuid4().hex[:8]
            + ".json"
        )
        path = self.root / name
        fd = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
        self.written += len(encoded)
        self._refs[invocation_id] = path
        return {
            "evidence_available": True,
            "evidence_ref": str(path),
            "evidence_expires_at": payload["expires_at"],
            "evidence_redacted": payload["redacted"],
            "evidence_truncated": payload["truncated"],
        }

    def read(self, invocation_id: str) -> dict:
        path = self._refs.get(invocation_id)
        if path is None or not path.is_file():
            return {"available": False, "reason": "evidence unavailable"}
        payload = json.loads(path.read_bytes())
        if payload["expires_at"] <= time.time():
            path.unlink(missing_ok=True)
            return {"available": False, "reason": "evidence expired"}
        return {"available": True, **payload}
