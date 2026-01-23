"""
Edit Strategies - Fallback matching for edit operations.

When exact string match fails, these strategies are tried in order to find
a suitable match (e.g., whitespace differences, indentation, line trimming).
"""

from __future__ import annotations

from typing import Generator, Tuple
import re

# Similarity thresholds for block anchor fallback matching
SINGLE_CANDIDATE_SIMILARITY_THRESHOLD = 0.0
MULTIPLE_CANDIDATES_SIMILARITY_THRESHOLD = 0.3


def _levenshtein(a: str, b: str) -> int:
    """Levenshtein distance between two strings."""
    if not a or not b:
        return max(len(a), len(b))
    # Build matrix
    matrix = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        matrix[i][0] = i
    for j in range(len(b) + 1):
        matrix[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            matrix[i][j] = min(
                matrix[i - 1][j] + 1,
                matrix[i][j - 1] + 1,
                matrix[i - 1][j - 1] + cost,
            )
    return matrix[len(a)][len(b)]


def _simple_replacer(content: str, find: str) -> Generator[str, None, None]:
    """Exact match only."""
    if find in content:
        yield find


def _line_trimmed_replacer(content: str, find: str) -> Generator[str, None, None]:
    """Match when each line matches after trimming whitespace."""
    original_lines = content.split("\n")
    search_lines = find.split("\n")
    if search_lines and search_lines[-1] == "":
        search_lines.pop()
    for i in range(len(original_lines) - len(search_lines) + 1):
        matches = True
        for j in range(len(search_lines)):
            if original_lines[i + j].strip() != search_lines[j].strip():
                matches = False
                break
        if matches:
            match_start = sum(len(original_lines[k]) + 1 for k in range(i))
            match_end = match_start
            for k in range(len(search_lines)):
                match_end += len(original_lines[i + k])
                if k < len(search_lines) - 1:
                    match_end += 1
            yield content[match_start:match_end]


def _block_anchor_replacer(content: str, find: str) -> Generator[str, None, None]:
    """Match by first/last line anchors with Levenshtein similarity for middle lines."""
    original_lines = content.split("\n")
    search_lines = find.split("\n")
    if len(search_lines) < 3:
        return
    if search_lines and search_lines[-1] == "":
        search_lines.pop()
    first_line_search = search_lines[0].strip()
    last_line_search = search_lines[-1].strip()
    search_block_size = len(search_lines)
    candidates = []
    for i in range(len(original_lines)):
        if original_lines[i].strip() != first_line_search:
            continue
        for j in range(i + 2, len(original_lines)):
            if original_lines[j].strip() == last_line_search:
                candidates.append((i, j))
                break
    if not candidates:
        return
    if len(candidates) == 1:
        start_line, end_line = candidates[0]
        actual_block_size = end_line - start_line + 1
        lines_to_check = min(search_block_size - 2, actual_block_size - 2)
        similarity = 0.0
        if lines_to_check > 0:
            for j in range(1, min(search_block_size - 1, actual_block_size - 1)):
                orig = original_lines[start_line + j].strip()
                search = search_lines[j].strip()
                max_len = max(len(orig), len(search))
                if max_len == 0:
                    continue
                dist = _levenshtein(orig, search)
                similarity += (1 - dist / max_len) / lines_to_check
        else:
            similarity = 1.0
        if similarity >= SINGLE_CANDIDATE_SIMILARITY_THRESHOLD:
            match_start = sum(len(original_lines[k]) + 1 for k in range(start_line))
            match_end = match_start
            for k in range(start_line, end_line + 1):
                match_end += len(original_lines[k])
                if k < end_line:
                    match_end += 1
            yield content[match_start:match_end]
        return
    best_match = None
    max_similarity = -1.0
    for start_line, end_line in candidates:
        actual_block_size = end_line - start_line + 1
        lines_to_check = min(search_block_size - 2, actual_block_size - 2)
        similarity = 0.0
        if lines_to_check > 0:
            for j in range(1, min(search_block_size - 1, actual_block_size - 1)):
                orig = original_lines[start_line + j].strip()
                search = search_lines[j].strip()
                max_len = max(len(orig), len(search))
                if max_len == 0:
                    continue
                dist = _levenshtein(orig, search)
                similarity += 1 - dist / max_len
            similarity /= lines_to_check
        else:
            similarity = 1.0
        if similarity > max_similarity:
            max_similarity = similarity
            best_match = (start_line, end_line)
    if max_similarity >= MULTIPLE_CANDIDATES_SIMILARITY_THRESHOLD and best_match:
        start_line, end_line = best_match
        match_start = sum(len(original_lines[k]) + 1 for k in range(start_line))
        match_end = match_start
        for k in range(start_line, end_line + 1):
            match_end += len(original_lines[k])
            if k < end_line:
                match_end += 1
        yield content[match_start:match_end]


def _whitespace_normalized_replacer(content: str, find: str) -> Generator[str, None, None]:
    """Normalize all whitespace to single spaces for matching."""

    def normalize(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip()

    normalized_find = normalize(find)
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if normalize(line) == normalized_find:
            yield line
        else:
            if normalized_find in normalize(line):
                words = find.strip().split()
                if words:
                    pattern = re.escape(words[0])
                    for w in words[1:]:
                        pattern += r"\s+" + re.escape(w)
                    m = re.search(pattern, line)
                    if m:
                        yield m.group(0)
    find_lines = find.split("\n")
    if len(find_lines) > 1:
        for i in range(len(lines) - len(find_lines) + 1):
            block = "\n".join(lines[i : i + len(find_lines)])
            if normalize(block) == normalized_find:
                yield block


def _indentation_flexible_replacer(content: str, find: str) -> Generator[str, None, None]:
    """Ignore indentation differences by removing minimum indent."""

    def remove_indentation(text: str) -> str:
        lines = text.split("\n")
        non_empty = [line for line in lines if line.strip()]
        if not non_empty:
            return text
        min_indent = min(
            len(m.group(1)) if (m := re.match(r"^(\s*)", line)) else 0 for line in non_empty
        )
        return "\n".join(line if not line.strip() else line[min_indent:] for line in lines)

    normalized_find = remove_indentation(find)
    content_lines = content.split("\n")
    find_lines = find.split("\n")
    for i in range(len(content_lines) - len(find_lines) + 1):
        block = "\n".join(content_lines[i : i + len(find_lines)])
        if remove_indentation(block) == normalized_find:
            yield block


def _escape_normalized_replacer(content: str, find: str) -> Generator[str, None, None]:
    """Unescape \\n, \\t, etc. in the find string for matching."""

    def unescape(s: str) -> str:
        return re.sub(
            r"\\(n|t|r|'|\"|`|\\|\n|\$)",
            lambda m: {
                "n": "\n",
                "t": "\t",
                "r": "\r",
                "'": "'",
                '"': '"',
                "`": "`",
                "\\": "\\",
                "\n": "\n",
                "$": "$",
            }.get(m.group(1), m.group(0)),
            s,
        )

    unescaped = unescape(find)
    if unescaped in content:
        yield unescaped
    lines = content.split("\n")
    find_lines = unescape(find).split("\n")
    for i in range(len(lines) - len(find_lines) + 1):
        block = "\n".join(lines[i : i + len(find_lines)])
        if unescape(block) == unescaped:
            yield block


def _trimmed_boundary_replacer(content: str, find: str) -> Generator[str, None, None]:
    """Try matching with trimmed find (leading/trailing whitespace removed)."""
    trimmed = find.strip()
    if trimmed == find:
        return
    if trimmed in content:
        yield trimmed
    lines = content.split("\n")
    find_lines = find.split("\n")
    for i in range(len(lines) - len(find_lines) + 1):
        block = "\n".join(lines[i : i + len(find_lines)])
        if block.strip() == trimmed:
            yield block


def _context_aware_replacer(content: str, find: str) -> Generator[str, None, None]:
    """Match by first/last line anchors; require ~50% of middle lines to match."""
    find_lines = find.split("\n")
    if len(find_lines) < 3:
        return
    if find_lines and find_lines[-1] == "":
        find_lines.pop()
    first_line = find_lines[0].strip()
    last_line = find_lines[-1].strip()
    content_lines = content.split("\n")
    for i in range(len(content_lines)):
        if content_lines[i].strip() != first_line:
            continue
        for j in range(i + 2, len(content_lines)):
            if content_lines[j].strip() == last_line:
                block_lines = content_lines[i : j + 1]
                block = "\n".join(block_lines)
                if len(block_lines) == len(find_lines):
                    matching = 0
                    total = 0
                    for k in range(1, len(block_lines) - 1):
                        bl = block_lines[k].strip()
                        fl = find_lines[k].strip()
                        if bl or fl:
                            total += 1
                            if bl == fl:
                                matching += 1
                    if total == 0 or matching / total >= 0.5:
                        yield block
                        return
                break


def _multi_occurrence_replacer(content: str, find: str) -> Generator[str, None, None]:
    """Yield each exact occurrence (for replace_all handling)."""
    start = 0
    while True:
        idx = content.find(find, start)
        if idx == -1:
            break
        yield find
        start = idx + len(find)


REPLACERS = [
    _simple_replacer,
    _line_trimmed_replacer,
    _block_anchor_replacer,
    _whitespace_normalized_replacer,
    _indentation_flexible_replacer,
    _escape_normalized_replacer,
    _trimmed_boundary_replacer,
    _context_aware_replacer,
    _multi_occurrence_replacer,
]


def replace_with_strategies(
    content: str, old_string: str, new_string: str, replace_all: bool = False
) -> Tuple[str, int]:
    """
    Replace old_string with new_string in content, trying multiple matching
    strategies when exact match fails.

    Returns:
        Tuple of (new_content, replaced_count).

    Raises:
        ValueError: if old_string == new_string
        ValueError: if old_string not found with any strategy
        ValueError: if multiple matches and not replace_all
    """
    if old_string == new_string:
        raise ValueError("old_string and new_string must be different")
    for replacer in REPLACERS:
        for search in replacer(content, old_string):
            idx = content.find(search)
            if idx == -1:
                continue
            if replace_all:
                count = content.count(search)
                new_content = content.replace(search, new_string)
                return (new_content, count)
            last_idx = content.rfind(search)
            if idx != last_idx:
                count = content.count(search)
                raise ValueError(
                    f"Found {count} occurrences of old_string. Provide more surrounding "
                    "lines in old_string to identify the correct match, or use replace_all=true."
                )
            new_content = content[:idx] + new_string + content[idx + len(search) :]
            return (new_content, 1)
    raise ValueError("old_string not found in content")
