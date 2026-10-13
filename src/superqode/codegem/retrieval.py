"""Optional local EmbeddingGemma retrieval inside CodeGem's existing search tool."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import math
import re
import sqlite3
import struct
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse

import httpx

EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".md",
    ".sh",
    ".yaml",
    ".toml",
}

_SENTENCE_TRANSFORMER_MODELS = {}
_SENTENCE_TRANSFORMER_LOCK = threading.Lock()


def _sentence_transformers_embed(model_name, texts, config):
    """Load Google's model once per process and run its official local encoder."""
    device = config.get("device", "auto")
    revision = config.get("revision") or None
    key = (model_name, revision, device)
    with _SENTENCE_TRANSFORMER_LOCK:
        model = _SENTENCE_TRANSFORMER_MODELS.get(key)
        if model is None:
            try:
                import torch
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "Install CodeGem's local semantic extra with "
                    "`pip install 'superqode[semantic-local]'` to use EmbeddingGemma directly"
                ) from exc
            if device == "auto":
                if torch.cuda.is_available():
                    device = "cuda"
                elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                    device = "mps"
                else:
                    device = "cpu"
                key = (model_name, revision, device)
                model = _SENTENCE_TRANSFORMER_MODELS.get(key)
            elif device == "mps" and not (
                hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
            ):
                raise RuntimeError(
                    "PyTorch cannot access the macOS Metal backend in this environment; "
                    "use device: auto or device: cpu"
                )
            elif device == "cuda" and not torch.cuda.is_available():
                raise RuntimeError(
                    "CUDA is unavailable; use device: auto or select an available device"
                )
            if model is None:
                kwargs = {"device": device}
                if revision:
                    kwargs["revision"] = revision
                if config.get("local_files_only"):
                    kwargs["local_files_only"] = True
                model = SentenceTransformer(model_name, **kwargs)
                _SENTENCE_TRANSFORMER_MODELS[key] = model
    return model.encode(texts, convert_to_numpy=True, show_progress_bar=False).tolist()


class EmbeddingClient:
    def __init__(self, config=None, *, transport=None):
        self.config = dict(config or {})
        self.provider = self.config.get("provider", "openai")
        default_model = (
            "google/embeddinggemma-2"
            if self.provider == "sentence-transformers"
            else "embeddinggemma-2"
        )
        self.model = self.config.get("model", default_model)
        if "embeddinggemma" not in self.model.lower():
            raise ValueError("CodeGem retrieval supports EmbeddingGemma models only")
        self.base = self.config.get("base_url", "http://127.0.0.1:8081/v1").rstrip("/")
        if urlparse(self.base).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError(
                "CodeGem embedding search requires a loopback endpoint; code stays local"
            )
        self.dimensions = int(self.config.get("dimensions", 256))
        if self.dimensions not in {128, 256, 512, 768}:
            raise ValueError("EmbeddingGemma dimensions must be 128, 256, 512, or 768")
        self.transport = transport
        self.identity = json.dumps(
            {
                "provider": self.config.get("provider", "openai"),
                "model": self.model,
                "dimensions": self.dimensions,
                "revision": self.config.get("revision", ""),
                "prefix": "code-v1",
            },
            sort_keys=True,
        )

    async def embed(self, texts):
        provider = self.provider
        if provider == "sentence-transformers":
            # Model loading and GPU/CPU inference can take seconds. Metal,
            # CUDA and CPU all run off the terminal's event loop.
            vectors = await asyncio.to_thread(
                _sentence_transformers_embed, self.model, texts, self.config
            )
        else:
            async with httpx.AsyncClient(transport=self.transport, timeout=60) as client:
                if provider == "ollama":
                    try:
                        response = await client.post(
                            self.base.removesuffix("/v1") + "/api/embed",
                            json={"model": self.model, "input": texts, "truncate": False},
                        )
                    except httpx.ConnectError as exc:
                        raise RuntimeError(
                            f"Cannot connect to the local Ollama embedding endpoint at {self.base}; "
                            "start Ollama and pull the selected EmbeddingGemma model"
                        ) from exc
                    if response.status_code >= 400:
                        detail = response.text[:500]
                        hint = (
                            " Update Ollama to a release that supports EmbeddingGemma 2, or use "
                            "provider: sentence-transformers with the semantic-local extra."
                            if "newer version" in detail.lower()
                            else " Check that the selected EmbeddingGemma model is installed."
                        )
                        raise RuntimeError(
                            f"Ollama embedding request failed ({response.status_code}): {detail}.{hint}"
                        )
                    vectors = response.json().get("embeddings", [])
                else:
                    response = await client.post(
                        self.base + "/embeddings", json={"model": self.model, "input": texts}
                    )
                    response.raise_for_status()
                    vectors = [
                        entry["embedding"]
                        for entry in sorted(response.json()["data"], key=lambda d: d["index"])
                    ]
        if len(vectors) != len(texts):
            raise ValueError("Embedding server returned the wrong batch size")
        normalized = []
        for vector in vectors:
            if len(vector) < self.dimensions:
                raise ValueError("Embedding vector is shorter than the selected dimension")
            vector = [float(v) for v in vector[: self.dimensions]]
            norm = math.sqrt(sum(v * v for v in vector))
            if not math.isfinite(norm) or norm == 0:
                raise ValueError("Embedding server returned an invalid vector")
            normalized.append([v / norm for v in vector])
        return normalized

    async def query(self, text):
        prefix = "task: code retrieval | query: "
        return (await self.embed([prefix + text]))[0]


class CodeGemIndex:
    def __init__(self, root: Path, config=None, *, client=None):
        self.root = root.resolve()
        config = dict(config or {})
        self.client = client or EmbeddingClient(config)
        scopes = config.get("scope", ".")
        if isinstance(scopes, (str, Path)):
            scopes = [scopes]
        self.scope_keys = []
        for scope in scopes:
            scope_path = Path(scope)
            resolved = (
                (self.root / scope_path).resolve()
                if not scope_path.is_absolute()
                else scope_path.resolve()
            )
            try:
                relative_scope = resolved.relative_to(self.root)
            except ValueError as exc:
                raise ValueError("CodeGem semantic scope must stay inside the project") from exc
            self.scope_keys.append(relative_scope.as_posix() or ".")
        self.scope_keys = sorted(set(self.scope_keys))
        self.scope_key = (
            self.scope_keys[0] if len(self.scope_keys) == 1 else json.dumps(self.scope_keys)
        )
        scope_identity = json.dumps(self.scope_keys)
        suffix = (
            ""
            if self.scope_keys == ["."]
            else "-" + hashlib.sha256(scope_identity.encode()).hexdigest()[:12]
        )
        self.path = self.root / ".superqode" / "codegem" / f"search{suffix}.sqlite3"

    @property
    def identity(self):
        return json.dumps(
            {"embedding": self.client.identity, "scope": self.scope_keys}, sort_keys=True
        )

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.execute(
            "CREATE TABLE IF NOT EXISTS chunks (key TEXT PRIMARY KEY, path TEXT, start INTEGER, end INTEGER, text TEXT, hash TEXT, vector BLOB)"
        )
        db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)")
        return db

    def chunks(self):
        # Respect .gitignore, including model weights, dependencies and private state.
        proc = subprocess.run(
            ["git", "ls-files", "-co", "--exclude-standard", "-z"],
            cwd=self.root,
            capture_output=True,
        )
        if proc.returncode:
            raise ValueError("Embedding indexing currently requires a Git working directory")
        paths = sorted(set(proc.stdout.decode().split("\0")) - {""})
        result = []
        for relative in paths:
            if not any(
                scope == "." or relative == scope or relative.startswith(scope.rstrip("/") + "/")
                for scope in self.scope_keys
            ):
                continue
            path = self.root / relative
            if (
                path.suffix not in EXTENSIONS
                or path.is_symlink()
                or not path.resolve().is_relative_to(self.root)
                or any(p.startswith(".") and p != ".github" for p in Path(relative).parts)
            ):
                continue
            if not path.is_file() or path.stat().st_size > 500_000:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            lines = text.splitlines()
            ranges = []
            if path.suffix == ".py":
                try:
                    ranges = [
                        (n.lineno - 1, n.end_lineno)
                        for n in ast.walk(ast.parse(text))
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    ]
                except SyntaxError:
                    pass
            if not ranges:
                ranges = [(i, min(i + 40, len(lines))) for i in range(0, len(lines), 32)]
            for start, end in ranges:
                for offset in range(start, end, 32):
                    stop = min(offset + 40, end)
                    content = "\n".join(lines[offset:stop])
                    # Keep even pathological long source lines within a small token budget.
                    content = content[:2000]
                    if content.strip():
                        digest = hashlib.sha256(content.encode()).hexdigest()
                        result.append(
                            (
                                f"{relative}:{offset + 1}",
                                relative,
                                offset + 1,
                                stop,
                                content,
                                digest,
                            )
                        )
        if len(result) > 10000:
            raise ValueError("Project exceeds CodeGem's 10,000-chunk local index budget")
        return result

    async def build(self, on_progress=None):
        chunks = self.chunks()
        db = self._connect()
        try:
            identity = db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
            reusable = (
                dict(db.execute("SELECT key, hash FROM chunks"))
                if identity and identity[0] == self.identity
                else {}
            )
            pending = [row for row in chunks if reusable.get(row[0]) != row[-1]]
            updates = []
            for offset in range(0, len(pending), 16):
                batch = pending[offset : offset + 16]
                vectors = await self.client.embed([f"title: {r[1]} | text: {r[4]}" for r in batch])
                updates.extend(
                    [(*r, struct.pack(f"<{len(v)}f", *v)) for r, v in zip(batch, vectors)]
                )
                if on_progress:
                    on_progress(min(offset + len(batch), len(pending)), len(pending))
            # Commit atomically only after all new embeddings succeed.
            with db:
                if not identity or identity[0] != self.identity:
                    db.execute("DELETE FROM chunks")
                db.executemany("INSERT OR REPLACE INTO chunks VALUES (?,?,?,?,?,?,?)", updates)
                valid = {r[0] for r in chunks}
                db.executemany(
                    "DELETE FROM chunks WHERE key=?",
                    [(k,) for (k,) in db.execute("SELECT key FROM chunks") if k not in valid],
                )
                db.execute(
                    "INSERT OR REPLACE INTO metadata VALUES ('identity',?)", (self.identity,)
                )
            return {
                "chunks": len(chunks),
                "embedded": len(pending),
                "reused": len(chunks) - len(pending),
                "index": str(self.path),
            }
        finally:
            db.close()

    async def search(self, query, *, limit=5, hybrid=True):
        if not self.path.exists():
            raise ValueError("Build the local CodeGem index before semantic search")
        db = self._connect()
        try:
            identity = db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
            if not identity or identity[0] != self.identity:
                raise ValueError("Embedding model or dimensions changed; rebuild the index")
            rows = db.execute("SELECT path,start,end,text,hash,vector FROM chunks").fetchall()
        finally:
            db.close()
        query_vector = await self.client.query(query)
        terms = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]+", query.lower()))
        semantic, lexical = [], []
        for i, row in enumerate(rows):
            vector = struct.unpack(f"<{len(row[-1]) // 4}f", row[-1])
            if len(vector) != len(query_vector):
                raise ValueError("Index vector dimensions are inconsistent")
            semantic.append((sum(a * b for a, b in zip(query_vector, vector)), i))
            words = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]+", (row[0] + " " + row[3]).lower()))
            lexical.append((len(terms & words), i))
        ordered = sorted(semantic, reverse=True)
        scores = {i: 1 / (60 + rank) for rank, (_, i) in enumerate(ordered, 1)}
        if hybrid:
            for rank, (overlap, i) in enumerate(sorted(lexical, reverse=True), 1):
                if overlap:
                    scores[i] += 1 / (60 + rank)
        matches = []
        seen_paths = set()
        result_limit = max(1, min(int(limit), 20))
        # Return the best chunk per source file so the small result window does
        # not get consumed by several adjacent chunks from one large module.
        for i in sorted(scores, key=scores.get, reverse=True):
            path, start, end, text, digest, _ = rows[i]
            if path in seen_paths:
                continue
            actual = self.root / path
            # Never present an old line reference as current code.
            if (
                not actual.is_file()
                or actual.is_symlink()
                or not actual.resolve().is_relative_to(self.root)
            ):
                continue
            try:
                current = "\n".join(
                    actual.read_text(encoding="utf-8").splitlines()[start - 1 : end]
                )[:2000]
            except (OSError, UnicodeError):
                continue
            if hashlib.sha256(current.encode()).hexdigest() != digest:
                continue
            seen_paths.add(path)
            matches.append(
                {"path": path, "line": start, "end": end, "score": scores[i], "text": text}
            )
            if len(matches) >= result_limit:
                break
        return matches
