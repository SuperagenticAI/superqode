"""Git diff computation and per-entry diff review/approve."""

from __future__ import annotations
import os
import subprocess
from pathlib import Path
from typing import Any
from superqode.sidebar import (
    get_file_diff,
)


class HelperDiffReviewMixin:
    """Git diff computation and per-entry diff review/approve."""

    def _compute_file_diffs(self, files_modified: list) -> dict:
        """Compute diff data for modified files.

        Returns dict mapping file_path -> {"additions": int, "deletions": int, "diff_text": str}
        """
        file_diffs = {}
        root_path = Path(os.getcwd())

        for file_path in files_modified:
            try:
                # Use git diff to get the actual changes
                diff_text = get_file_diff(root_path, file_path, staged=False)
                if diff_text:
                    # Parse diff to get additions/deletions
                    additions = sum(
                        1
                        for line in diff_text.split("\n")
                        if line.startswith("+") and not line.startswith("+++")
                    )
                    deletions = sum(
                        1
                        for line in diff_text.split("\n")
                        if line.startswith("-") and not line.startswith("---")
                    )
                    file_diffs[file_path] = {
                        "additions": additions,
                        "deletions": deletions,
                        "diff_text": diff_text,
                    }
                else:
                    # File might be new or untracked, try to detect
                    file_path_obj = Path(file_path)
                    if file_path_obj.exists():
                        # New file - count lines as additions
                        try:
                            with open(file_path_obj, "r", encoding="utf-8", errors="ignore") as f:
                                line_count = len(f.readlines())
                            file_diffs[file_path] = {
                                "additions": line_count,
                                "deletions": 0,
                                "diff_text": "",
                            }
                        except Exception:
                            file_diffs[file_path] = {
                                "additions": 0,
                                "deletions": 0,
                                "diff_text": "",
                            }
                    else:
                        # File doesn't exist - might be deleted
                        file_diffs[file_path] = {
                            "additions": 0,
                            "deletions": 0,
                            "diff_text": "",
                        }
            except Exception:
                # If we can't compute diff, just mark as modified
                file_diffs[file_path] = {
                    "additions": 0,
                    "deletions": 0,
                    "diff_text": "",
                }

        return file_diffs

    def _looks_like_diff(self, text: str) -> bool:
        """Detect unified-diff-shaped text produced by acp/render.py.

        We pre-format diffs in the ACP layer rather than letting
        ``_format_tool_output`` JSON-parse them, so it needs a cheap
        check to skip the JSON path. Accept standard unified-diff
        markers (``diff``, ``index``, ``---``/``+++``, ``@@``) plus
        ACP's compact hunk body lines.
        """
        if not text:
            return False
        head = text.lstrip().splitlines()
        saw_old = False
        saw_new = False
        for line in head[:12]:
            stripped = line.strip()
            if stripped.startswith(("diff ", "index ", "@@")):
                return True
            if stripped.startswith("--- "):
                saw_old = True
            elif stripped.startswith("+++ "):
                saw_new = True
            if saw_old and saw_new:
                return True
            if stripped.startswith(("+ ", "- ", "+\t", "-\t")):
                return True
        return False

    def _current_git_diff_text(self) -> str:
        """Return a review-grade current diff document.

        Kept for tests and compatibility; ``:diff`` uses the same formatter.
        """
        return self._format_diff_review(self._current_git_diff_sections())

    def _current_git_diff_sections(self) -> list[tuple[str, str]]:
        """Return the current working-tree diff, including staged and untracked files."""
        chunks: list[tuple[str, str]] = []
        commands = (
            ("Working tree", ["git", "diff", "--no-ext-diff", "--"]),
            ("Staged", ["git", "diff", "--cached", "--no-ext-diff", "--"]),
        )
        for label, command in commands:
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=10)
            except Exception:
                continue
            if result.returncode == 0 and result.stdout.strip():
                chunks.append((label, result.stdout.rstrip()))

        try:
            result = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            result = None
        if result is not None and result.returncode == 0:
            untracked_chunks: list[str] = []
            for raw_path in result.stdout.splitlines():
                path = raw_path.strip()
                if not path:
                    continue
                file_path = Path(path)
                if not file_path.is_file():
                    continue
                try:
                    data = file_path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                if len(data) > 200_000:
                    untracked_chunks.append(
                        f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
                        f"--- /dev/null\n+++ b/{path}\n@@\n"
                        f"# file is too large to preview inline ({len(data):,} bytes)"
                    )
                    continue
                added = "\n".join(f"+{line}" for line in data.splitlines())
                untracked_chunks.append(
                    f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
                    f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(data.splitlines())} @@\n"
                    f"{added}"
                )
            if untracked_chunks:
                chunks.append(("Untracked", "\n\n".join(untracked_chunks)))
        return chunks

    def _diff_review_entries(self, sections: list[tuple[str, str]]) -> list[dict[str, Any]]:
        """Return file-level diff entries for review/navigation."""
        entries: list[dict[str, Any]] = []
        for label, text in sections:
            for path, chunk in self._split_unified_diff_by_file(text):
                stats = self._diff_file_stats(chunk)
                stat = stats[0] if stats else {"path": path, "additions": 0, "deletions": 0}
                entry = {
                    "section": label,
                    "path": stat.get("path") or path,
                    "additions": int(stat.get("additions") or 0),
                    "deletions": int(stat.get("deletions") or 0),
                    "patch": chunk,
                }
                approval_id = self._diff_chunk_approval_id(chunk)
                if approval_id:
                    entry["approval_id"] = approval_id
                entries.append(entry)
        return entries

    def _diff_chunk_approval_id(self, chunk: str) -> str:
        """Extract the pending approval id marker from a synthetic pending diff."""
        for line in chunk.splitlines()[:3]:
            marker = "approval:"
            if marker in line:
                return line.split(marker, 1)[1].strip().split()[0]
        return ""

    def _approve_diff_entry(self, entry: dict[str, Any], *, always: bool = False) -> str:
        """Approve a pending approval diff entry and apply its file change."""
        approval_id = str(entry.get("approval_id") or "")
        manager = getattr(self, "_approval_manager", None)
        if not approval_id or manager is None:
            return "This diff entry is not pending approval."
        request = next((req for req in manager.requests if req.id == approval_id), None)
        if request is None:
            return "Approval request is no longer pending."
        ok = manager.approve(approval_id, always=always)
        if not ok:
            return "Approval request is no longer pending."
        if request.new_content and request.file_path:
            try:
                self._file_manager.write(request.file_path, request.new_content)
            except Exception as exc:
                return f"Approved, but failed to write {request.file_path}: {exc}"
        suffix = " (always)" if always else ""
        return f"Approved: {request.title}{suffix}"

    def _reject_diff_entry(self, entry: dict[str, Any], *, always: bool = False) -> str:
        """Reject a pending approval diff entry."""
        approval_id = str(entry.get("approval_id") or "")
        manager = getattr(self, "_approval_manager", None)
        if not approval_id or manager is None:
            return "This diff entry is not pending approval."
        request = next((req for req in manager.requests if req.id == approval_id), None)
        if request is None:
            return "Approval request is no longer pending."
        ok = manager.reject(approval_id, always=always)
        if not ok:
            return "Approval request is no longer pending."
        suffix = " (never allow)" if always else ""
        return f"Rejected: {request.title}{suffix}"

    def _filter_diff_sections(
        self,
        sections: list[tuple[str, str]],
        query: str,
    ) -> list[tuple[str, str]]:
        """Filter diff sections to hunks whose file path matches query."""
        query = query.strip().lower()
        if not query:
            return sections
        out: list[tuple[str, str]] = []
        for label, text in sections:
            chunks = self._split_unified_diff_by_file(text)
            matches = [
                chunk
                for path, chunk in chunks
                if query in path.lower() or path.lower().endswith(query)
            ]
            if matches:
                out.append((label, "\n\n".join(matches)))
        return out

    def _split_unified_diff_by_file(self, diff_text: str) -> list[tuple[str, str]]:
        """Split unified diff text into ``(path, chunk)`` file entries."""
        entries: list[tuple[str, str]] = []
        current_lines: list[str] = []
        current_path = ""

        def finish() -> None:
            nonlocal current_lines, current_path
            if current_lines:
                entries.append((current_path or "(unknown)", "\n".join(current_lines).rstrip()))
            current_lines = []
            current_path = ""

        for line in diff_text.splitlines():
            if line.startswith("diff --git "):
                finish()
                parts = line.split()
                if len(parts) >= 4:
                    current_path = parts[3][2:] if parts[3].startswith("b/") else parts[3]
                current_lines.append(line)
                continue
            if line.startswith("# ") and " +" in line and " -" in line:
                finish()
                current_path = line[2:].split("  ", 1)[0]
                current_lines.append(line)
                continue
            if not current_lines:
                continue
            current_lines.append(line)
            if line.startswith("+++ b/") and not current_path:
                current_path = line.removeprefix("+++ b/")
        finish()
        return entries

    def _diff_file_stats(self, diff_text: str) -> list[dict[str, Any]]:
        """Extract per-file path/add/delete counts from unified diff text."""
        stats: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        def finish() -> None:
            nonlocal current
            if current is not None:
                stats.append(current)
            current = None

        for line in diff_text.splitlines():
            if line.startswith("diff --git "):
                finish()
                parts = line.split()
                path = ""
                if len(parts) >= 4:
                    path = parts[3]
                    if path.startswith("b/"):
                        path = path[2:]
                current = {"path": path, "additions": 0, "deletions": 0}
                continue
            if current is None:
                if line.startswith("# ") and " +" in line and " -" in line:
                    current = {"path": line[2:].split("  ", 1)[0], "additions": 0, "deletions": 0}
                else:
                    continue
            if line.startswith("+") and not line.startswith("+++"):
                current["additions"] = int(current.get("additions") or 0) + 1
            elif line.startswith("-") and not line.startswith("---"):
                current["deletions"] = int(current.get("deletions") or 0) + 1
        finish()
        return stats
