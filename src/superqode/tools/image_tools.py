"""view_image: attach a local image to the conversation.

Vision-capable models — including local multimodal ones like Gemma 4 —
can inspect screenshots, UI mockups, diagrams, or rendered output. The tool
loads a local image file and returns a data URL in its metadata; the agent
loop injects it into the next model request as a multimodal content part
(OpenAI ``image_url`` format, which LiteLLM translates per provider).

The tool itself never errors a non-vision run: if the active model cannot
consume images the provider simply rejects or ignores the part, and the
text note still tells the model what was attached.
"""

from __future__ import annotations

import base64
from typing import Any, Dict

from .base import Tool, ToolContext, ToolResult
from .validation import validate_path_in_search_scope

# Keep attachments bounded: a data URL lives in the context for the rest of
# the session, and local vision models have small windows.
MAX_IMAGE_BYTES = 4 * 1024 * 1024

_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


class ViewImageTool(Tool):
    """Load a local image file into the model's visual context."""

    read_only = True

    @property
    def name(self) -> str:
        return "view_image"

    @property
    def description(self) -> str:
        return (
            "Attach a local image file (png, jpg, gif, webp) to the "
            "conversation so it can be inspected visually. Use only when the "
            "active model supports vision and visual inspection is needed "
            "(screenshots, diagrams, rendered UI)."
        )

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Local filesystem path to an image file.",
                },
            },
            "required": ["path"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        path = args.get("path") or args.get("file_path") or ""
        try:
            file_path = validate_path_in_search_scope(
                path, ctx.working_directory, getattr(ctx, "search_roots", None)
            )
        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e))

        if not file_path.exists() or not file_path.is_file():
            return ToolResult(success=False, output="", error=f"Image not found: {path}")

        mime = _MIME_BY_SUFFIX.get(file_path.suffix.lower())
        if mime is None:
            supported = ", ".join(sorted(_MIME_BY_SUFFIX))
            return ToolResult(
                success=False,
                output="",
                error=f"Unsupported image type '{file_path.suffix}'. Supported: {supported}",
            )

        size = file_path.stat().st_size
        if size > MAX_IMAGE_BYTES:
            return ToolResult(
                success=False,
                output="",
                error=(
                    f"Image is {size / 1024 / 1024:.1f} MB; limit is "
                    f"{MAX_IMAGE_BYTES // 1024 // 1024} MB. Resize or crop it first "
                    "(e.g. with `sips -Z 1600` on macOS or ImageMagick `convert -resize`)."
                ),
            )

        data = file_path.read_bytes()
        data_url = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        return ToolResult(
            success=True,
            output=f"Attached image {path} ({mime}, {size:,} bytes). It is included in the next message.",
            metadata={
                "image_path": str(file_path),
                "image_mime": mime,
                "image_bytes": size,
                "image_data_url": data_url,
            },
        )


__all__ = ["MAX_IMAGE_BYTES", "ViewImageTool"]
