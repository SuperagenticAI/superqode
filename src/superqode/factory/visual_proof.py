"""Safe Visual Proof collection and PR/handoff Markdown formatting for Factory runs."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .definition import project_path

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}
_ALLOWED_EXTENSIONS = _IMAGE_EXTENSIONS | _VIDEO_EXTENSIONS
_MAX_ITEMS = 12
_MAX_BYTES = 25 * 1024 * 1024

_VISUAL_PROOF_HEADING = re.compile(
    r"(?:^|\n)##+\s+Visual\s+proof\s*\n(.*?)(?=\n##+\s+|\Z)",
    re.IGNORECASE | re.DOTALL,
)


def _extract_visual_proof_notes(order: Any) -> str:
    notes: list[str] = []
    for artifact in reversed(getattr(order, "artifacts", ()) or ()):
        content = getattr(artifact, "content", "") or ""
        if not content:
            continue
        match = _VISUAL_PROOF_HEADING.search(content)
        if match:
            body = match.group(1).strip()
            if body and body not in notes:
                notes.append(body[:3000])
    return "\n\n".join(notes)


def collect_visual_proof(root: str | Path, order: Any) -> dict[str, Any]:
    """Collect bounded visual proof files from ``.superqode/factory-proof`` safely."""
    root_path = Path(root).resolve()
    work_order_id = str(getattr(order, "work_order_id", "") or "")
    search_dirs: list[Path] = []
    for rel in (
        f".superqode/factory-proof/{work_order_id}" if work_order_id else "",
        ".superqode/factory-proof",
    ):
        if not rel:
            continue
        try:
            candidate_dir = project_path(root_path, rel)
        except ValueError:
            continue
        if candidate_dir.exists() and candidate_dir.is_dir() and not candidate_dir.is_symlink():
            search_dirs.append(candidate_dir)

    items: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for folder in search_dirs:
        for entry in sorted(folder.iterdir(), key=lambda p: p.name.casefold()):
            if len(items) >= _MAX_ITEMS:
                break
            if entry.is_symlink() or not entry.is_file():
                continue
            ext = entry.suffix.lower()
            if ext not in _ALLOWED_EXTENSIONS:
                continue
            try:
                resolved = entry.resolve(strict=True)
                rel_posix = resolved.relative_to(root_path).as_posix()
                size = resolved.stat().st_size
            except (OSError, ValueError):
                continue
            if size <= 0 or size > _MAX_BYTES or rel_posix in seen_paths:
                continue
            seen_paths.add(rel_posix)
            items.append(
                {
                    "name": entry.name,
                    "path": str(resolved),
                    "relative_path": rel_posix,
                    "kind": "video" if ext in _VIDEO_EXTENSIONS else "image",
                    "size_bytes": size,
                }
            )

    summary = _extract_visual_proof_notes(order)
    return {
        "directory": ".superqode/factory-proof",
        "summary": summary,
        "items": items,
    }


def build_handoff_markdown(
    *,
    goal: str,
    status: str,
    supergauge_verdict: str,
    merge_risk: dict[str, Any],
    visual_proof: dict[str, Any],
) -> str:
    """Render a clean PR/handoff Markdown summary combining verdict, risk, and visual proof."""
    parts = [
        f"# Factory Handoff: {goal or 'Trial Run'}",
        "",
        f"- **Run status:** `{status or 'unknown'}`",
        f"- **SuperGauge verdict:** `{(supergauge_verdict or 'pending').upper()}`",
        f"- **Merge risk (advisory):** `{str(merge_risk.get('overall') or 'low').upper()}`",
        "",
        str(merge_risk.get("markdown") or "").strip(),
    ]
    proof_summary = str(visual_proof.get("summary") or "").strip()
    proof_items = visual_proof.get("items") or []
    if proof_summary or proof_items:
        parts.extend(["", "## Visual proof"])
        if proof_summary:
            parts.extend(["", proof_summary])
        if proof_items:
            parts.append("")
            for item in proof_items:
                parts.append(f"- `{item['relative_path']}` ({item['kind']})")
    return "\n".join(parts).strip() + "\n"
