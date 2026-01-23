"""Fuzzy search utilities with LRU caching for fast completion."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import NamedTuple


class FuzzyMatch(NamedTuple):
    """A fuzzy match result with score and match positions."""

    text: str
    score: float
    positions: list[int]  # Character positions that matched


class FuzzySearch:
    """
    Fast fuzzy search with LRU caching.

    Inspired by fzf/fuzzysort algorithms with:
    - Bonus for matches at word boundaries
    - Bonus for contiguous matches
    - Case-insensitive matching with case-match bonus
    """

    def __init__(self, max_cache_size: int = 1024):
        """Initialize with cache size."""
        self._cache_size = max_cache_size
        # Create cached version of core search
        self._cached_score = lru_cache(maxsize=max_cache_size)(self._compute_score)

    def _compute_score(self, query: str, text: str) -> tuple[float, tuple[int, ...]]:
        """
        Compute fuzzy match score between query and text.

        Returns (score, positions) where higher score = better match.
        """
        if not query:
            return (0.0, ())

        query_lower = query.lower()
        text_lower = text.lower()

        # Quick rejection: all query chars must be in text
        for char in query_lower:
            if char not in text_lower:
                return (-1.0, ())

        # Find best match using greedy algorithm
        positions: list[int] = []
        score = 0.0
        query_idx = 0
        prev_match_idx = -2  # For contiguity bonus

        # Word boundary detection
        word_boundaries = {0}  # Start is always a boundary
        for i, char in enumerate(text):
            if i > 0:
                prev_char = text[i - 1]
                # Boundary after: space, underscore, hyphen, slash, dot
                # Or transition from lowercase to uppercase (camelCase)
                if prev_char in " _-/." or (prev_char.islower() and char.isupper()):
                    word_boundaries.add(i)

        for text_idx, char in enumerate(text_lower):
            if query_idx >= len(query_lower):
                break

            if char == query_lower[query_idx]:
                positions.append(text_idx)

                # Base score for match
                match_score = 1.0

                # Bonus for word boundary match
                if text_idx in word_boundaries:
                    match_score += 2.0

                # Bonus for exact case match
                if text[text_idx] == query[query_idx]:
                    match_score += 0.5

                # Bonus for contiguous matches
                if text_idx == prev_match_idx + 1:
                    match_score += 1.5

                # Bonus for matching at start
                if text_idx == 0:
                    match_score += 3.0

                score += match_score
                prev_match_idx = text_idx
                query_idx += 1

        # All query characters must be matched
        if query_idx < len(query_lower):
            return (-1.0, ())

        # Normalize score by query length and penalize by text length
        # Shorter texts with same matches are preferred
        normalized_score = score / len(query) - (len(text) * 0.01)

        return (normalized_score, tuple(positions))

    def search(
        self,
        query: str,
        items: list[str],
        max_results: int = 10,
        threshold: float = 0.0,
    ) -> list[FuzzyMatch]:
        """
        Search items for fuzzy matches to query.

        Args:
            query: The search query
            items: List of strings to search
            max_results: Maximum number of results to return
            threshold: Minimum score threshold (default 0 = any match)

        Returns:
            List of FuzzyMatch objects sorted by score (best first)
        """
        if not query:
            # Return first max_results items with score 0
            return [FuzzyMatch(text=item, score=0.0, positions=[]) for item in items[:max_results]]

        results: list[FuzzyMatch] = []

        for item in items:
            score, positions = self._cached_score(query, item)
            if score >= threshold:
                results.append(FuzzyMatch(text=item, score=score, positions=list(positions)))

        # Sort by score descending
        results.sort(key=lambda x: x.score, reverse=True)

        return results[:max_results]

    def search_with_data(
        self,
        query: str,
        items: list[tuple[str, any]],
        max_results: int = 10,
        threshold: float = 0.0,
    ) -> list[tuple[FuzzyMatch, any]]:
        """
        Search items with associated data.

        Args:
            query: The search query
            items: List of (searchable_text, data) tuples
            max_results: Maximum number of results
            threshold: Minimum score threshold

        Returns:
            List of (FuzzyMatch, data) tuples sorted by score
        """
        if not query:
            return [
                (FuzzyMatch(text=text, score=0.0, positions=[]), data)
                for text, data in items[:max_results]
            ]

        results: list[tuple[FuzzyMatch, any]] = []

        for text, data in items:
            score, positions = self._cached_score(query, text)
            if score >= threshold:
                results.append(
                    (FuzzyMatch(text=text, score=score, positions=list(positions)), data)
                )

        results.sort(key=lambda x: x[0].score, reverse=True)

        return results[:max_results]

    def highlight_match(
        self,
        text: str,
        positions: list[int],
        highlight_start: str = "[bold cyan]",
        highlight_end: str = "[/bold cyan]",
    ) -> str:
        """
        Apply Rich markup to highlight matched positions.

        Args:
            text: Original text
            positions: List of matched character positions
            highlight_start: Rich markup to start highlight
            highlight_end: Rich markup to end highlight

        Returns:
            Text with Rich markup applied to matched characters
        """
        if not positions:
            return text

        result = []
        pos_set = set(positions)
        in_highlight = False

        for i, char in enumerate(text):
            if i in pos_set:
                if not in_highlight:
                    result.append(highlight_start)
                    in_highlight = True
                result.append(char)
            else:
                if in_highlight:
                    result.append(highlight_end)
                    in_highlight = False
                result.append(char)

        if in_highlight:
            result.append(highlight_end)

        return "".join(result)

    def clear_cache(self) -> None:
        """Clear the search cache."""
        self._cached_score.cache_clear()


class PathFuzzySearch(FuzzySearch):
    """
    Specialized fuzzy search for file paths.

    Gives extra weight to:
    - Filename matches (last segment)
    - Matches after path separators
    """

    def _compute_score(self, query: str, text: str) -> tuple[float, tuple[int, ...]]:
        """Compute path-aware fuzzy match score."""
        base_score, positions = super()._compute_score(query, text)

        if base_score < 0:
            return (base_score, positions)

        # Bonus for matches in filename (after last /)
        last_sep = text.rfind("/")
        if last_sep >= 0:
            filename_positions = [p for p in positions if p > last_sep]
            if filename_positions:
                # Significant bonus for filename matches
                base_score += len(filename_positions) * 2.0

        return (base_score, positions)


# Global instances for convenience
fuzzy_search = FuzzySearch()
path_fuzzy_search = PathFuzzySearch()
