"""
BM25 Search implementation for MCP tools.

Provides relevance-based ranking for MCP tool discovery using
the BM25 ranking algorithm (same as PyFlue).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, List, Optional


@dataclass
class MCPToolMatch:
    """A matched MCP tool with search metadata."""

    server: str
    name: str
    description: str
    input_schema: dict[str, Any]
    original_name: str
    score: float = 0.0


class BM25Search:
    """BM25 ranking algorithm implementation for MCP tool search."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        """
        Initialize BM25 search with ranking parameters.

        Args:
            k1: Term frequency saturation parameter (default 1.5)
            b: Document length normalization parameter (default 0.75)
        """
        self.k1 = k1
        self.b = b
        self.doc_freqs: dict[str, int] = {}
        self.avgdl: float = 0
        self.doc_lengths: List[int] = []
        self.doc_term_freqs: List[dict[str, int]] = []
        self._tools: List[MCPToolMatch] = []

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into lowercase terms."""
        if not text:
            return []
        text = text.lower()
        text = text.replace("_", " ").replace("-", " ")
        return [w for w in text.split() if w.strip()]

    def index(self, tools: List[MCPToolMatch]) -> "BM25Search":
        """
        Index a list of tool matches for BM25 search.

        Args:
            tools: List of MCPToolMatch objects to index

        Returns:
            Self for method chaining
        """
        self._tools = tools
        self.doc_term_freqs = []
        self.doc_lengths = []
        self.doc_freqs = {}

        for tool in tools:
            text = f"{tool.name} {tool.description} {tool.server}"
            tokens = self._tokenize(text)
            tf = {}
            for token in tokens:
                tf[token] = tf.get(token, 0) + 1

            self.doc_term_freqs.append(tf)
            self.doc_lengths.append(len(tokens))

            for token in tf:
                self.doc_freqs[token] = self.doc_freqs.get(token, 0) + 1

        if self.doc_lengths:
            self.avgdl = sum(self.doc_lengths) / len(self.doc_lengths)
        else:
            self.avgdl = 0

        return self

    def score(self, query: str, doc_idx: int) -> float:
        """
        Calculate BM25 score for a query against a document.

        Args:
            query: Search query string
            doc_idx: Document index to score against

        Returns:
            BM25 relevance score
        """
        query_terms = self._tokenize(query)
        if not query_terms:
            return 0.0

        tf = self.doc_term_freqs[doc_idx]
        doc_len = self.doc_lengths[doc_idx]
        N = len(self.doc_term_freqs)

        score = 0.0
        for term in query_terms:
            df = self.doc_freqs.get(term, 0)
            if df == 0:
                continue

            tf_term = tf.get(term, 0)
            idf = math.log((N - df + 0.5) / (df + 0.5) + 1)

            numerator = tf_term * (self.k1 + 1)
            denominator = tf_term + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)

            score += idf * numerator / denominator

        return score

    @staticmethod
    def search(
        tools: List[MCPToolMatch],
        query: str,
        limit: int = 10,
    ) -> List[MCPToolMatch]:
        """
        Search tools using BM25 ranking.

        Args:
            tools: List of tools to search
            query: Search query string
            limit: Maximum number of results to return

        Returns:
            List of tools sorted by relevance score (descending)
        """
        if not tools or not query.strip():
            return []

        searcher = BM25Search().index(tools)

        scored_tools = []
        for idx, tool in enumerate(tools):
            score = searcher.score(query, idx)
            if score > 0:
                tool.score = score
                scored_tools.append(tool)

        scored_tools.sort(key=lambda t: (t.score, t.server, t.name), reverse=True)
        return scored_tools[:limit]


def keyword_search(
    tools: List[MCPToolMatch],
    query: str,
    limit: int = 10,
) -> List[MCPToolMatch]:
    """
    Simple keyword-based search (fallback when BM25 unavailable).

    Args:
        tools: List of tools to search
        query: Search query string
        limit: Maximum number of results

    Returns:
        List of tools with relevance scores
    """
    if not tools or not query.strip():
        return []

    query_lower = query.lower()
    query_terms = set(query_lower.split())

    scored_tools = []
    for tool in tools:
        score = 0.0

        if query_lower in tool.name.lower():
            score += 3.0

        if query_lower in tool.description.lower():
            score += 2.0

        if query_lower in tool.server.lower():
            score += 1.0

        tool_text = f"{tool.name} {tool.description}".lower()
        matches = sum(1 for term in query_terms if term in tool_text)
        if matches:
            score += matches * 0.5

        if score > 0:
            tool.score = score
            scored_tools.append(tool)

    scored_tools.sort(key=lambda t: (t.score, t.server, t.name), reverse=True)
    return scored_tools[:limit]