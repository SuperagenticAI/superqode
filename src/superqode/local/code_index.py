"""Persistent local code-search index.

The first index backend is intentionally boring: SQLite + FTS5 from the Python
stdlib. It is local, offline, embeddable, and good enough to sit behind
``local_code_search`` while leaving room for Tantivy/OpenSearch adapters later.
"""

from __future__ import annotations

import fnmatch
import re
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

INDEX_FILENAME = "code-search.sqlite3"
SCHEMA_VERSION = 1
MAX_FILE_BYTES = 1_000_000

CODE_EXTENSIONS = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
}

TEXT_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".css",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".json",
    ".kt",
    ".lua",
    ".md",
    ".php",
    ".rb",
    ".scss",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
    *CODE_EXTENSIONS.keys(),
}

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
    "venv",
}

SYMBOL_PATTERNS = {
    "python": {
        "function": r"^(\s*)def\s+(\w+)\s*\([^)]*\)",
        "class": r"^(\s*)class\s+(\w+)\s*[:\(]",
        "method": r"^(\s+)def\s+(\w+)\s*\(self[^)]*\)",
    },
    "javascript": {
        "function": r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(",
        "class": r"^(?:export\s+)?class\s+(\w+)",
        "const": r"^(?:export\s+)?const\s+(\w+)\s*=",
    },
    "typescript": {
        "function": r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)",
        "class": r"^(?:export\s+)?(?:abstract\s+)?class\s+(\w+)",
        "interface": r"^(?:export\s+)?interface\s+(\w+)",
        "type": r"^(?:export\s+)?type\s+(\w+)\s*=",
        "const": r"^(?:export\s+)?const\s+(\w+)\s*[=:]",
    },
    "go": {
        "function": r"^func\s+(\w+)\s*\(",
        "method": r"^func\s+\([^)]+\)\s+(\w+)\s*\(",
        "type": r"^type\s+(\w+)\s+",
    },
    "rust": {
        "function": r"^(?:pub\s+)?(?:async\s+)?fn\s+(\w+)",
        "struct": r"^(?:pub\s+)?struct\s+(\w+)",
        "enum": r"^(?:pub\s+)?enum\s+(\w+)",
        "trait": r"^(?:pub\s+)?trait\s+(\w+)",
    },
}


@dataclass
class CodeIndexBuildReport:
    index_path: str
    roots: list[str]
    files_indexed: int = 0
    symbols_indexed: int = 0
    bytes_indexed: int = 0
    elapsed_s: float = 0.0
    ok: bool = True
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CodeIndexMatch:
    root_path: str
    rel_path: str
    line: Optional[int] = None
    kind: str = ""
    name: str = ""
    preview: str = ""
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CodeIndexSearchReport:
    index_path: str
    query: str
    roots: list[str]
    covered: bool
    files: list[CodeIndexMatch] = field(default_factory=list)
    content: list[CodeIndexMatch] = field(default_factory=list)
    symbols: list[CodeIndexMatch] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index_path": self.index_path,
            "query": self.query,
            "roots": self.roots,
            "covered": self.covered,
            "files": [item.to_dict() for item in self.files],
            "content": [item.to_dict() for item in self.content],
            "symbols": [item.to_dict() for item in self.symbols],
            "error": self.error,
        }


def default_code_index_path(workspace_root: str | Path) -> Path:
    return Path(workspace_root).expanduser().resolve() / ".superqode" / INDEX_FILENAME


def normalize_roots(roots: Iterable[str | Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        path = Path(root).expanduser().resolve()
        if not path.exists():
            continue
        key = str(path)
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def build_code_index(
    *,
    workspace_root: str | Path,
    roots: Iterable[str | Path],
    index_path: str | Path | None = None,
) -> CodeIndexBuildReport:
    started = time.perf_counter()
    root_paths = normalize_roots(roots)
    db_path = Path(index_path).expanduser().resolve() if index_path else default_code_index_path(workspace_root)
    report = CodeIndexBuildReport(index_path=str(db_path), roots=[str(root) for root in root_paths])
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            _create_schema(conn)
            _clear_index(conn)
            conn.execute("INSERT INTO meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
            indexed_at = time.time()
            for root in root_paths:
                root_files = 0
                root_bytes = 0
                for file_path in _iter_indexable_files(root):
                    try:
                        data = file_path.read_bytes()
                    except OSError:
                        continue
                    if not _looks_text(data):
                        continue
                    text = data.decode("utf-8", errors="replace")
                    rel_path = str(file_path.relative_to(root))
                    lang = CODE_EXTENSIONS.get(file_path.suffix.lower(), "")
                    symbols = _extract_symbols(file_path, text, lang)
                    cursor = conn.execute(
                        """
                        INSERT INTO docs(root_path, rel_path, abs_path, language, mtime_ns, size, content)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(root),
                            rel_path,
                            str(file_path),
                            lang,
                            file_path.stat().st_mtime_ns,
                            len(data),
                            text,
                        ),
                    )
                    doc_id = int(cursor.lastrowid)
                    symbol_text = " ".join(symbol.name for symbol in symbols)
                    conn.execute(
                        """
                        INSERT INTO docs_fts(doc_id, root_path, rel_path, content, symbols)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (str(doc_id), str(root), rel_path, text, symbol_text),
                    )
                    for symbol in symbols:
                        conn.execute(
                            """
                            INSERT INTO symbols(doc_id, root_path, rel_path, name, kind, line, signature)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                doc_id,
                                str(root),
                                rel_path,
                                symbol.name,
                                symbol.kind,
                                symbol.line,
                                symbol.signature,
                            ),
                        )
                    report.symbols_indexed += len(symbols)
                    root_files += 1
                    root_bytes += len(data)
                conn.execute(
                    """
                    INSERT INTO roots(root_path, indexed_at, file_count, content_bytes)
                    VALUES (?, ?, ?, ?)
                    """,
                    (str(root), indexed_at, root_files, root_bytes),
                )
                report.files_indexed += root_files
                report.bytes_indexed += root_bytes
    except sqlite3.Error as exc:
        report.ok = False
        report.error = str(exc)
    finally:
        report.elapsed_s = round(time.perf_counter() - started, 3)
    return report


def index_covers_roots(index_path: str | Path, roots: Iterable[str | Path]) -> bool:
    db_path = Path(index_path).expanduser().resolve()
    if not db_path.exists():
        return False
    wanted = {str(root) for root in normalize_roots(roots)}
    if not wanted:
        return False
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("SELECT root_path FROM roots").fetchall()
    except sqlite3.Error:
        return False
    indexed = {str(Path(row[0]).resolve()) for row in rows}
    return wanted <= indexed


def search_code_index(
    *,
    workspace_root: str | Path,
    roots: Iterable[str | Path],
    query: str,
    mode: str = "all",
    include: str | None = None,
    language: str | None = None,
    limit: int = 20,
    index_path: str | Path | None = None,
) -> CodeIndexSearchReport:
    root_paths = normalize_roots(roots)
    db_path = Path(index_path).expanduser().resolve() if index_path else default_code_index_path(workspace_root)
    report = CodeIndexSearchReport(
        index_path=str(db_path),
        query=query,
        roots=[str(root) for root in root_paths],
        covered=False,
    )
    if not db_path.exists():
        report.error = "index does not exist"
        return report
    if not index_covers_roots(db_path, root_paths):
        report.error = "index does not cover requested roots"
        return report
    report.covered = True
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            root_values = [str(root) for root in root_paths]
            if mode in {"all", "path"}:
                report.files = _search_paths(conn, query, root_values, include, limit)
            if mode in {"all", "content"}:
                report.content = _search_content(conn, query, root_values, include, language, limit)
            if mode in {"all", "symbol"}:
                report.symbols = _search_symbols(conn, query, root_values, include, language, limit)
    except sqlite3.Error as exc:
        report.covered = False
        report.error = str(exc)
    return report


@dataclass
class _Symbol:
    name: str
    kind: str
    line: int
    signature: str


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS roots(
            root_path TEXT PRIMARY KEY,
            indexed_at REAL NOT NULL,
            file_count INTEGER NOT NULL,
            content_bytes INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS docs(
            id INTEGER PRIMARY KEY,
            root_path TEXT NOT NULL,
            rel_path TEXT NOT NULL,
            abs_path TEXT NOT NULL UNIQUE,
            language TEXT NOT NULL,
            mtime_ns INTEGER NOT NULL,
            size INTEGER NOT NULL,
            content TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_docs_root_path ON docs(root_path, rel_path);
        CREATE TABLE IF NOT EXISTS symbols(
            id INTEGER PRIMARY KEY,
            doc_id INTEGER NOT NULL,
            root_path TEXT NOT NULL,
            rel_path TEXT NOT NULL,
            name TEXT NOT NULL,
            kind TEXT NOT NULL,
            line INTEGER NOT NULL,
            signature TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name COLLATE NOCASE);
        CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
            doc_id UNINDEXED,
            root_path UNINDEXED,
            rel_path,
            content,
            symbols,
            tokenize = 'unicode61 tokenchars ''_./-'''
        );
        """
    )


def _clear_index(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM meta")
    conn.execute("DELETE FROM roots")
    conn.execute("DELETE FROM docs")
    conn.execute("DELETE FROM symbols")
    conn.execute("DELETE FROM docs_fts")


def _iter_indexable_files(root: Path) -> Iterable[Path]:
    if root.is_file():
        if root.suffix.lower() in TEXT_EXTENSIONS and _size_ok(root):
            yield root
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel_parts = path.relative_to(root).parts
        except ValueError:
            rel_parts = path.parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        if not _size_ok(path):
            continue
        yield path


def _size_ok(path: Path) -> bool:
    try:
        return path.stat().st_size <= MAX_FILE_BYTES
    except OSError:
        return False


def _looks_text(data: bytes) -> bool:
    return b"\0" not in data[:4096]


def _extract_symbols(file_path: Path, text: str, language: str) -> list[_Symbol]:
    if not language:
        return []
    patterns = SYMBOL_PATTERNS.get(language, {})
    out: list[_Symbol] = []
    for line_num, line in enumerate(text.splitlines(), 1):
        for kind, pattern in patterns.items():
            match = re.match(pattern, line)
            if not match:
                continue
            groups = match.groups()
            raw = groups[-1] if groups else ""
            names = [name.strip() for name in raw.split(",")] if "," in raw else [raw]
            for name in names:
                if name:
                    out.append(_Symbol(name=name, kind=kind, line=line_num, signature=line.strip()[:160]))
    return out


def _fts_query(text: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_./-]+", text)
    if not tokens:
        return '""'
    return " OR ".join(f'"{token.replace("\"", "\"\"")}"' for token in tokens[:8])


def _roots_clause(roots: list[str]) -> tuple[str, list[str]]:
    placeholders = ",".join("?" for _ in roots)
    return f"root_path IN ({placeholders})", roots


def _include_ok(rel_path: str, include: str | None) -> bool:
    if not include:
        return True
    return fnmatch.fnmatch(rel_path, include) or Path(rel_path).match(include)


def _language_ok(language: str, wanted: str | None) -> bool:
    return not wanted or language == wanted


def _path_score(query: str, rel_path: str) -> int:
    query_lower = query.lower()
    path_lower = rel_path.lower()
    basename = Path(path_lower).name
    if query_lower in basename:
        return 100 + len(query_lower)
    if query_lower in path_lower:
        return 50 + len(query_lower)
    cursor = 0
    score = 0
    for char in query_lower:
        found = path_lower.find(char, cursor)
        if found == -1:
            return 0
        score += 1
        cursor = found + 1
    return score


def _search_paths(
    conn: sqlite3.Connection, query: str, roots: list[str], include: str | None, limit: int
) -> list[CodeIndexMatch]:
    clause, params = _roots_clause(roots)
    rows = conn.execute(
        f"SELECT root_path, rel_path FROM docs WHERE {clause}",
        params,
    ).fetchall()
    ranked: list[CodeIndexMatch] = []
    for row in rows:
        rel_path = str(row["rel_path"])
        if not _include_ok(rel_path, include):
            continue
        score = _path_score(query, rel_path)
        if score > 0:
            ranked.append(
                CodeIndexMatch(
                    root_path=str(row["root_path"]),
                    rel_path=rel_path,
                    preview=f"score {score}",
                    score=float(score),
                )
            )
    ranked.sort(key=lambda item: (-item.score, item.rel_path))
    return ranked[:limit]


def _search_content(
    conn: sqlite3.Connection,
    query: str,
    roots: list[str],
    include: str | None,
    language: str | None,
    limit: int,
) -> list[CodeIndexMatch]:
    fts = _fts_query(query)
    clause, params = _roots_clause(roots)
    rows = conn.execute(
        f"""
        SELECT f.doc_id, f.root_path, f.rel_path, d.language, d.content
        FROM docs_fts f
        JOIN docs d ON d.id = CAST(f.doc_id AS INTEGER)
        WHERE docs_fts MATCH ? AND f.{clause}
        LIMIT ?
        """,
        [fts, *params, limit * 4],
    ).fetchall()
    out: list[CodeIndexMatch] = []
    for row in rows:
        rel_path = str(row["rel_path"])
        if not _include_ok(rel_path, include) or not _language_ok(str(row["language"]), language):
            continue
        line_num, preview = _first_matching_line(str(row["content"]), query)
        out.append(
            CodeIndexMatch(
                root_path=str(row["root_path"]),
                rel_path=rel_path,
                line=line_num,
                preview=preview,
            )
        )
        if len(out) >= limit:
            return out
    return out


def _search_symbols(
    conn: sqlite3.Connection,
    query: str,
    roots: list[str],
    include: str | None,
    language: str | None,
    limit: int,
) -> list[CodeIndexMatch]:
    clause, params = _roots_clause(roots)
    needle = f"%{query.lower()}%"
    rows = conn.execute(
        f"""
        SELECT s.root_path, s.rel_path, s.name, s.kind, s.line, s.signature, d.language
        FROM symbols s
        JOIN docs d ON d.id = s.doc_id
        WHERE lower(s.name) LIKE ? AND s.{clause}
        ORDER BY s.rel_path, s.line
        LIMIT ?
        """,
        [needle, *params, limit * 4],
    ).fetchall()
    out: list[CodeIndexMatch] = []
    for row in rows:
        rel_path = str(row["rel_path"])
        if not _include_ok(rel_path, include) or not _language_ok(str(row["language"]), language):
            continue
        out.append(
            CodeIndexMatch(
                root_path=str(row["root_path"]),
                rel_path=rel_path,
                line=int(row["line"]),
                kind=str(row["kind"]),
                name=str(row["name"]),
                preview=str(row["signature"]),
            )
        )
        if len(out) >= limit:
            return out
    return out


def _first_matching_line(content: str, query: str) -> tuple[Optional[int], str]:
    tokens = [token.lower() for token in re.findall(r"[A-Za-z0-9_./-]+", query)]
    if not tokens:
        return None, ""
    for line_num, line in enumerate(content.splitlines(), 1):
        low = line.lower()
        if any(token in low for token in tokens):
            return line_num, line.strip()[:200]
    return None, ""


__all__ = [
    "CodeIndexBuildReport",
    "CodeIndexMatch",
    "CodeIndexSearchReport",
    "build_code_index",
    "default_code_index_path",
    "index_covers_roots",
    "normalize_roots",
    "search_code_index",
]
