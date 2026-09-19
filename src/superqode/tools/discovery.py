"""Configurable progressive discovery contracts.

The harness owns candidate normalization and lifecycle, not the retrieval
algorithm.  Built-in lexical and BM25 implementations are dependency-free;
projects can provide an async or sync callable without replacing activation,
permission, execution, or tracing.
"""

from __future__ import annotations

import importlib
import inspect
import math
import os
import re
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence
from uuid import uuid4


_WORD_RE = re.compile(r"[a-z0-9]+")
_FALSE = {"0", "false", "off", "no", "disabled"}
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


def tokenize(text: str) -> tuple[str, ...]:
    return tuple(
        token for token in _WORD_RE.findall((text or "").lower()) if token not in _STOP_WORDS
    )


def normalize_identifier(text: str) -> str:
    return "".join(tokenize(text))


@dataclass(frozen=True)
class ToolDescriptor:
    """Provider-neutral description of a searchable capability."""

    id: str
    exposed_name: str
    original_name: str
    source: str
    description: str
    input_schema: Mapping[str, Any] = field(default_factory=dict)
    namespace: str = ""
    read_only: bool = False
    catalog_version: str = ""
    payload: Any = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class ToolCandidate:
    """One normalized retrieval result with explainable component scores."""

    descriptor: ToolDescriptor
    score: float
    rank: int = 0
    signals: Mapping[str, float] = field(default_factory=dict)
    retrieved_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiscoverySettings:
    enabled: bool = False
    mode: str = "legacy"
    trace_dir: str = ""
    search_backend: str = "bm25"
    search_handler: str = ""
    search_limit: int = 20
    rank_backend: str = "score"
    rank_handler: str = ""
    candidate_limit: int = 8
    activation_limit: int = 3
    on_error: str = "fallback"
    fallback_backends: tuple[str, ...] = ("bm25", "lexical")
    exact_name_boost: float = 4.0
    judge_backend: str = "none"
    judge_mode: str = "off"
    mcp_mode: str = "meta_tools"


class ToolSearcher(Protocol):
    async def search(
        self, query: str, catalogue: Sequence[ToolDescriptor], *, limit: int
    ) -> Sequence[ToolCandidate]: ...


class ToolRanker(Protocol):
    async def rank(
        self, query: str, candidates: Sequence[ToolCandidate], *, limit: int
    ) -> Sequence[ToolCandidate]: ...


def resolve_discovery_settings(
    spec: Any = None, environ: Mapping[str, str] | None = None
) -> DiscoverySettings:
    """Resolve typed discovery settings. Environment overrides the spec."""

    env = environ if environ is not None else os.environ
    declared = getattr(spec, "tool_discovery", None)
    enabled = bool(getattr(declared, "enabled", False))
    mode = str(getattr(declared, "mode", "legacy") or "legacy").lower()
    search = dict(getattr(declared, "search", {}) or {})
    rank = dict(getattr(declared, "rank", {}) or {})
    judge = dict(getattr(declared, "judge", {}) or {})
    activation = dict(getattr(declared, "activation", {}) or {})
    mcp = dict(getattr(declared, "mcp", {}) or {})

    raw_enabled = env.get("SUPERQODE_TOOL_DISCOVERY")
    if raw_enabled is not None:
        enabled = raw_enabled.strip().lower() not in _FALSE
        if raw_enabled.strip().lower() in {"legacy", "shadow", "unified"}:
            mode = raw_enabled.strip().lower()
    mode = str(env.get("SUPERQODE_TOOL_DISCOVERY_MODE") or mode).strip().lower()
    if mode not in {"legacy", "shadow", "unified"}:
        raise ValueError("Tool discovery mode must be legacy, shadow, or unified")

    backend = (
        str(env.get("SUPERQODE_TOOL_SEARCH_BACKEND") or search.get("backend") or "bm25")
        .strip()
        .lower()
    )
    on_error = str(search.get("on_error") or "fallback").strip().lower()
    if on_error not in {"fallback", "empty", "fail"}:
        raise ValueError("tool_discovery.search.on_error must be fallback, empty, or fail")
    fallbacks = search.get("fallback_chain", ("bm25", "lexical"))
    if isinstance(fallbacks, str):
        fallbacks = [item.strip() for item in fallbacks.split(",") if item.strip()]
    judge_backend = str(judge.get("backend") or "none").strip().lower()
    judge_mode = str(judge.get("mode") or "off").strip().lower()
    if judge_backend not in {"none", "jev"}:
        raise ValueError("tool_discovery.judge.backend must be none or jev")
    if judge_mode not in {"off", "shadow", "rerank"}:
        raise ValueError("tool_discovery.judge.mode must be off, shadow, or rerank")
    mcp_mode = str(mcp.get("mode") or "meta_tools").strip().lower()
    if mcp_mode not in {"disabled", "meta_tools", "deferred_tools"}:
        raise ValueError("tool_discovery.mcp.mode must be disabled, meta_tools, or deferred_tools")

    return DiscoverySettings(
        enabled=enabled,
        mode=mode,
        trace_dir=str(
            env.get("SUPERQODE_TOOL_DISCOVERY_TRACE_DIR")
            or getattr(declared, "trace_dir", "")
            or ""
        ),
        search_backend=backend,
        search_handler=str(search.get("handler") or ""),
        search_limit=max(1, int(search.get("limit", 20) or 20)),
        rank_backend=str(rank.get("backend") or "score").strip().lower(),
        rank_handler=str(rank.get("handler") or ""),
        candidate_limit=max(1, int(rank.get("candidate_limit", 8) or 8)),
        activation_limit=max(1, int(activation.get("limit", 3) or 3)),
        on_error=on_error,
        fallback_backends=tuple(
            str(item).strip().lower() for item in fallbacks if str(item).strip()
        ),
        exact_name_boost=float(rank.get("exact_name_boost", 4.0) or 0.0),
        judge_backend=judge_backend,
        judge_mode=judge_mode,
        mcp_mode=mcp_mode,
    )


class LexicalSearcher:
    """Small-catalogue compatibility search with identifier boosting."""

    def __init__(self, *, exact_name_boost: float = 4.0):
        self.exact_name_boost = exact_name_boost

    async def search(
        self, query: str, catalogue: Sequence[ToolDescriptor], *, limit: int
    ) -> Sequence[ToolCandidate]:
        query_tokens = tokenize(query)
        normalized_query = normalize_identifier(query)
        found: list[ToolCandidate] = []
        for descriptor in catalogue:
            name_tokens = set(tokenize(descriptor.original_name)) | set(
                tokenize(descriptor.exposed_name)
            )
            description = Counter(tokenize(descriptor.description))
            lexical = 0.0
            for term in query_tokens:
                lexical += 3.0 if term in name_tokens else 0.0
                lexical += min(description.get(term, 0), 3)
                lexical += (
                    1.0
                    if any(
                        token.startswith(term) or term.startswith(token) for token in name_tokens
                    )
                    else 0.0
                )
            exact = (
                self.exact_name_boost
                if normalized_query
                in {
                    normalize_identifier(descriptor.original_name),
                    normalize_identifier(descriptor.exposed_name),
                    normalize_identifier(descriptor.id),
                }
                else 0.0
            )
            score = lexical + exact
            if score > 0:
                found.append(
                    ToolCandidate(
                        descriptor=descriptor,
                        score=score,
                        signals={"lexical": lexical, "exact_name": exact},
                        retrieved_by=("lexical",),
                    )
                )
        return _rank(found, limit)


class BM25Searcher:
    """Dependency-free BM25 over tool identity, namespace, and description."""

    def __init__(self, *, exact_name_boost: float = 4.0, k1: float = 1.5, b: float = 0.75):
        self.exact_name_boost = exact_name_boost
        self.k1 = k1
        self.b = b

    async def search(
        self, query: str, catalogue: Sequence[ToolDescriptor], *, limit: int
    ) -> Sequence[ToolCandidate]:
        query_terms = tokenize(query)
        if not query_terms or not catalogue:
            return ()
        documents = [
            tokenize(
                f"{item.original_name} {item.exposed_name} {item.namespace} {item.description}"
            )
            for item in catalogue
        ]
        frequencies = [Counter(document) for document in documents]
        doc_frequency = Counter(term for counts in frequencies for term in counts)
        average_length = sum(map(len, documents)) / len(documents) or 1.0
        normalized_query = normalize_identifier(query)
        found: list[ToolCandidate] = []
        for descriptor, document, counts in zip(catalogue, documents, frequencies):
            bm25 = 0.0
            for term in query_terms:
                tf = counts.get(term, 0)
                if not tf:
                    continue
                df = doc_frequency[term]
                inverse = math.log((len(documents) - df + 0.5) / (df + 0.5) + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * len(document) / average_length)
                bm25 += inverse * tf * (self.k1 + 1) / denominator
            exact = (
                self.exact_name_boost
                if normalized_query
                in {
                    normalize_identifier(descriptor.original_name),
                    normalize_identifier(descriptor.exposed_name),
                    normalize_identifier(descriptor.id),
                }
                else 0.0
            )
            score = bm25 + exact
            if score > 0:
                found.append(
                    ToolCandidate(
                        descriptor=descriptor,
                        score=score,
                        signals={"bm25": bm25, "exact_name": exact},
                        retrieved_by=("bm25",),
                    )
                )
        return _rank(found, limit)


class CallableSearcher:
    """Adapter for a user-owned ``(query, catalogue, limit)`` callable."""

    def __init__(self, handler: str):
        self.handler_path = handler
        self.handler = _load_handler(handler)

    async def search(
        self, query: str, catalogue: Sequence[ToolDescriptor], *, limit: int
    ) -> Sequence[ToolCandidate]:
        result = self.handler(query, catalogue, limit=limit)
        if inspect.isawaitable(result):
            result = await result
        by_id = {item.id: item for item in catalogue}
        candidates: list[ToolCandidate] = []
        for item in result or ():
            if isinstance(item, ToolCandidate):
                candidates.append(item)
                continue
            if isinstance(item, str):
                descriptor, score, signals = by_id.get(item), 1.0, {}
            elif isinstance(item, Mapping):
                descriptor = by_id.get(str(item.get("id") or item.get("tool_id") or ""))
                score = float(item.get("score", 1.0))
                signals = dict(item.get("signals") or {})
            else:
                raise TypeError(
                    "Custom tool search results must be ids, mappings, or ToolCandidate"
                )
            if descriptor is not None:
                candidates.append(
                    ToolCandidate(
                        descriptor=descriptor,
                        score=score,
                        signals=signals,
                        retrieved_by=(self.handler_path,),
                    )
                )
        return _rank(candidates, limit)


class CallableRanker:
    """Adapter for a user-owned ``(query, candidates, limit)`` ranker."""

    def __init__(self, handler: str):
        self.handler_path = handler
        self.handler = _load_handler(handler)

    async def rank(
        self, query: str, candidates: Sequence[ToolCandidate], *, limit: int
    ) -> Sequence[ToolCandidate]:
        result = self.handler(query, candidates, limit=limit)
        if inspect.isawaitable(result):
            result = await result
        by_id = {item.descriptor.id: item for item in candidates}
        ranked: list[ToolCandidate] = []
        for item in result or ():
            if isinstance(item, ToolCandidate):
                ranked.append(item)
                continue
            tool_id = (
                str(item.get("id") or item.get("tool_id") or "")
                if isinstance(item, Mapping)
                else str(item)
            )
            original = by_id.get(tool_id)
            if original is None:
                continue
            score = (
                float(item.get("score", original.score))
                if isinstance(item, Mapping)
                else original.score
            )
            signals = (
                {**dict(original.signals), **dict(item.get("signals") or {})}
                if isinstance(item, Mapping)
                else original.signals
            )
            ranked.append(
                ToolCandidate(
                    descriptor=original.descriptor,
                    score=score,
                    signals=signals,
                    retrieved_by=(*original.retrieved_by, self.handler_path),
                )
            )
        return _rank_in_order(ranked, limit)


async def retrieve(
    query: str, catalogue: Sequence[ToolDescriptor], settings: DiscoverySettings
) -> tuple[list[ToolCandidate], dict[str, Any]]:
    """Run configured retrieval with explicit, observable fallback semantics."""

    backends = [settings.search_backend]
    if settings.on_error == "fallback":
        backends.extend(item for item in settings.fallback_backends if item not in backends)
    errors: list[dict[str, str]] = []
    for backend in backends:
        try:
            searcher = _searcher(backend, settings)
            searched = list(await searcher.search(query, catalogue, limit=settings.search_limit))
            candidates = await _apply_ranker(query, searched, settings)
            return list(candidates), {
                "backend": backend,
                "ranker": settings.rank_backend,
                "errors": errors,
            }
        except Exception as exc:
            errors.append({"backend": backend, "error": type(exc).__name__})
            if settings.on_error == "fail":
                raise
            if settings.on_error == "empty":
                return [], {"backend": backend, "errors": errors}
    return [], {"backend": "none", "errors": errors}


async def evaluate_retrieval(
    labels: Sequence[Mapping[str, Any]],
    catalogue: Sequence[ToolDescriptor],
    settings: DiscoverySettings,
) -> dict[str, Any]:
    """Evaluate retrieval separately from judging and execution.

    Each row requires ``query`` and accepts either ``expected`` (one id),
    ``acceptable`` (several ids), or an empty/``none`` label for abstention.
    """

    evidence: list[dict[str, Any]] = []
    reciprocal_rank = 0.0
    hits = {1: 0, 5: 0, 8: 0}
    positives = 0
    none_cases = 0
    correct_none = 0
    for index, row in enumerate(labels):
        query = str(row.get("query") or "").strip()
        raw_acceptable = row.get("acceptable")
        if isinstance(raw_acceptable, str):
            acceptable = {raw_acceptable}
        elif isinstance(raw_acceptable, Sequence):
            acceptable = {str(item) for item in raw_acceptable}
        else:
            expected = row.get("expected")
            acceptable = {str(expected)} if expected not in (None, "", "none") else set()
        candidates, retrieval_trace = await retrieve(query, catalogue, settings)
        ids = [candidate.descriptor.id for candidate in candidates]
        matched_rank = next(
            (rank for rank, tool_id in enumerate(ids, start=1) if tool_id in acceptable), None
        )
        if acceptable:
            positives += 1
            if matched_rank is not None:
                reciprocal_rank += 1.0 / matched_rank
                for cutoff in hits:
                    hits[cutoff] += int(matched_rank <= cutoff)
        else:
            none_cases += 1
            correct_none += int(not ids)
        evidence.append(
            {
                "id": str(row.get("id") or index + 1),
                "query": query,
                "acceptable": sorted(acceptable),
                "candidates": ids,
                "matchedRank": matched_rank,
                "retrieval": retrieval_trace,
            }
        )
    return {
        "total": len(labels),
        "positive": positives,
        "none": none_cases,
        "recallAt1": hits[1] / positives if positives else None,
        "recallAt5": hits[5] / positives if positives else None,
        "recallAt8": hits[8] / positives if positives else None,
        "mrr": reciprocal_rank / positives if positives else None,
        "noneAccuracy": correct_none / none_cases if none_cases else None,
        "evidence": evidence,
    }


def record_discovery_trace(settings: DiscoverySettings, event: Mapping[str, Any]) -> dict[str, Any]:
    """Add stable identity/time and optionally persist a sanitized JSON trace."""

    payload = {
        "schemaVersion": "superqode.tool-discovery.v1",
        "discoveryId": uuid4().hex,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **dict(event),
    }
    try:
        from ..systemone.state import prepare_decision_state

        payload = prepare_decision_state(payload)
    except (ImportError, TypeError, ValueError):
        pass
    if not settings.trace_dir:
        return payload
    directory = Path(settings.trace_dir).expanduser() / "tool-discovery"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{payload['discoveryId']}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False)
    return payload


def descriptors_from_tools(tools: Sequence[Any]) -> list[ToolDescriptor]:
    return [
        ToolDescriptor(
            id=f"native:{tool.name}",
            exposed_name=tool.name,
            original_name=tool.name,
            source="native",
            description=tool.description,
            input_schema=tool.parameters,
            read_only=bool(getattr(tool, "read_only", False)),
            payload=tool,
        )
        for tool in tools
    ]


async def descriptors_from_mcp(mcp_manager_getter=None) -> list[ToolDescriptor]:
    """Load connected MCP capabilities as deferred, executable descriptors."""

    from .mcp_tools import MCPProxyTool, _resolve_mcp_manager

    manager = await _resolve_mcp_manager(mcp_manager_getter)
    if manager is None:
        return []
    tools = manager.list_all_tools()
    descriptors: list[ToolDescriptor] = []
    used_names: set[str] = set()
    for tool in tools:
        server_slug = _tool_name_slug(tool.server_id)
        tool_slug = _tool_name_slug(tool.name)
        base_name = f"mcp__{server_slug}__{tool_slug}"
        exposed_name = base_name
        suffix = 2
        while exposed_name in used_names:
            exposed_name = f"{base_name}_{suffix}"
            suffix += 1
        used_names.add(exposed_name)
        proxy = MCPProxyTool(
            exposed_name=exposed_name,
            server=tool.server_id,
            original_name=tool.name,
            description=tool.description,
            input_schema=tool.input_schema,
            read_only=bool(tool.annotations and tool.annotations.read_only_hint),
            mcp_manager_getter=mcp_manager_getter,
        )
        descriptors.append(
            ToolDescriptor(
                id=f"mcp:{tool.server_id}:{tool.name}",
                exposed_name=exposed_name,
                original_name=tool.name,
                source="mcp",
                namespace=tool.server_id,
                description=tool.description,
                input_schema=tool.input_schema,
                read_only=bool(tool.annotations and tool.annotations.read_only_hint),
                payload=proxy,
            )
        )
    return descriptors


def _searcher(backend: str, settings: DiscoverySettings) -> ToolSearcher:
    if backend == "lexical":
        return LexicalSearcher(exact_name_boost=settings.exact_name_boost)
    if backend == "bm25":
        return BM25Searcher(exact_name_boost=settings.exact_name_boost)
    if backend == "custom" or settings.search_handler:
        if not settings.search_handler:
            raise ValueError("Custom tool search requires tool_discovery.search.handler")
        return CallableSearcher(settings.search_handler)
    raise ValueError(f"Tool search backend is not installed: {backend}")


async def _apply_ranker(
    query: str, candidates: Sequence[ToolCandidate], settings: DiscoverySettings
) -> Sequence[ToolCandidate]:
    if settings.rank_backend in {"score", "search", "none"}:
        return _rank(candidates, settings.candidate_limit)
    if settings.rank_handler:
        return await CallableRanker(settings.rank_handler).rank(
            query, candidates, limit=settings.candidate_limit
        )
    raise ValueError(f"Tool rank backend is not installed: {settings.rank_backend}")


def _rank(candidates: Sequence[ToolCandidate], limit: int) -> list[ToolCandidate]:
    ordered = sorted(candidates, key=lambda item: (-item.score, item.descriptor.id))[:limit]
    return _rank_in_order(ordered, limit)


def _rank_in_order(candidates: Sequence[ToolCandidate], limit: int) -> list[ToolCandidate]:
    ordered = list(candidates)[:limit]
    return [
        ToolCandidate(
            descriptor=item.descriptor,
            score=item.score,
            rank=index,
            signals=item.signals,
            retrieved_by=item.retrieved_by,
        )
        for index, item in enumerate(ordered, start=1)
    ]


def _load_handler(path: str) -> Callable[..., Any]:
    module_name, separator, attribute = path.partition(":")
    if not separator:
        module_name, separator, attribute = path.rpartition(".")
    if not module_name or not attribute:
        raise ValueError("Custom search handler must be module:function or module.function")
    handler = getattr(importlib.import_module(module_name), attribute)
    if not callable(handler):
        raise TypeError(f"Custom search handler is not callable: {path}")
    return handler


def _tool_name_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", value or "").strip("_")
    return slug or "tool"


__all__ = [
    "BM25Searcher",
    "CallableSearcher",
    "CallableRanker",
    "DiscoverySettings",
    "LexicalSearcher",
    "ToolCandidate",
    "ToolDescriptor",
    "ToolSearcher",
    "ToolRanker",
    "descriptors_from_tools",
    "descriptors_from_mcp",
    "evaluate_retrieval",
    "normalize_identifier",
    "resolve_discovery_settings",
    "record_discovery_trace",
    "retrieve",
]
